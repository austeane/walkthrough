#!/usr/bin/env python3
"""Inject Path B capture manifest screenshots into walkthrough step media."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
TOKEN_RE = re.compile(r"[a-z][a-z0-9]+")

ROUTE_STOPWORDS = {
    "http",
    "https",
    "localhost",
    "127",
    "0",
    "www",
}

TOKEN_SYNONYMS = {
    "login": {"auth", "signin", "sign", "in"},
    "signin": {"login", "auth"},
    "auth": {"login", "signin", "signup"},
    "register": {"registration", "signup", "wizard"},
    "registration": {"register", "signup", "wizard"},
    "signup": {"register", "registration"},
    "dashboard": {"home", "analytics"},
    "checkout": {"payment", "pay"},
    "payment": {"checkout", "pay"},
}


def _deep_copy(data: dict) -> dict:
    return json.loads(json.dumps(data))


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return cleaned or "root"


def _normalize_path(path_str: str, manifest_path: Path | None) -> str:
    p = Path(path_str)
    if p.is_absolute():
        return str(p)
    if manifest_path is not None:
        return str((manifest_path.parent / p).resolve())
    return str(p.resolve())


def _extract_text(step: dict) -> dict[str, str]:
    title = str(step.get("title", ""))
    intent = str(step.get("intent", ""))
    claims = " ".join(
        str(claim.get("text", ""))
        for claim in step.get("claims", [])
        if isinstance(claim, dict)
    )

    evidence = step.get("evidence", {}) if isinstance(step.get("evidence", {}), dict) else {}
    files_text = " ".join(str(f) for f in evidence.get("files_changed", []) if isinstance(f, str))

    command_chunks = []
    for cmd in evidence.get("commands", []):
        if isinstance(cmd, dict):
            command_chunks.append(str(cmd.get("cmd", "")))
            command_chunks.append(str(cmd.get("summary", "")))
        else:
            command_chunks.append(str(cmd))
    commands_text = " ".join(command_chunks)

    narrative = f"{title} {intent} {claims}".lower()
    files = files_text.lower()
    commands = commands_text.lower()
    all_text = f"{narrative} {files} {commands}"

    return {
        "narrative": narrative,
        "files": files,
        "commands": commands,
        "all": all_text,
    }


def _route_tokens(route: str) -> list[str]:
    base = route.strip().lower().split("?", 1)[0]
    pieces = re.split(r"[/:._-]+", base)
    tokens: list[str] = []
    for piece in pieces:
        if not piece:
            continue
        if piece.isdigit():
            continue
        if piece in ROUTE_STOPWORDS:
            continue
        if len(piece) < 3:
            continue
        tokens.append(piece)
    # Stable unique order
    out: list[str] = []
    seen = set()
    for token in tokens:
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _pick_step_index(steps: list[dict], route: str, commit_shorts: list[str]) -> int:
    if not steps:
        return 0

    corpora = [_extract_text(step) for step in steps]

    if route.strip() in {"", "/"}:
        return 0

    # Pass 1: route/token relevance scoring
    route_lc = route.lower()
    tokens = _route_tokens(route)
    best_idx = 0
    best_score = -1

    for idx, corpus in enumerate(corpora):
        score = 0
        if route_lc and route_lc in corpus["all"]:
            score += 5

        for token in tokens:
            if token in corpus["narrative"]:
                score += 3
            if token in corpus["files"]:
                score += 2
            if token in corpus["commands"]:
                score += 1

            for synonym in TOKEN_SYNONYMS.get(token, set()):
                if synonym in corpus["narrative"]:
                    score += 2
                if synonym in corpus["files"]:
                    score += 1
                if synonym in corpus["commands"]:
                    score += 1

        if score > best_score:
            best_score = score
            best_idx = idx

    if best_score > 0:
        return best_idx

    # Pass 2: direct commit mention fallback
    best_idx = -1
    best_score = 0
    for idx, corpus in enumerate(corpora):
        score = 0
        for sha in commit_shorts:
            if not sha:
                continue
            if sha.lower() in corpus["all"]:
                score += 10
        if score > best_score:
            best_score = score
            best_idx = idx
    if best_idx >= 0 and best_score > 0:
        return best_idx

    # Final fallback: send to the last step (usually "ship/finalize")
    return max(len(steps) - 1, 0)


def _group_captures_by_route(
    manifest: dict,
    manifest_path: Path | None,
) -> dict[str, list[dict]]:
    captures = manifest.get("captures", {})
    if not isinstance(captures, dict):
        return {}

    commit_order = manifest.get("commit_order")
    if not isinstance(commit_order, list) or not commit_order:
        commit_order = list(captures.keys())

    by_route: dict[str, list[dict]] = {}
    for commit_key in commit_order:
        shots = captures.get(commit_key, [])
        if not isinstance(shots, list):
            continue
        commit_short_default = str(commit_key).replace("commit-", "")[:8]

        for shot in shots:
            if not isinstance(shot, dict):
                continue

            route = str(shot.get("route") or "/")
            commit_short = str(shot.get("commit_short") or commit_short_default)
            commit_sha = str(shot.get("commit_sha") or commit_short)
            path_str = str(shot.get("path") or "")
            if not path_str:
                continue

            record = {
                "route": route,
                "commit_key": str(commit_key),
                "commit_short": commit_short,
                "commit_sha": commit_sha,
                "path": _normalize_path(path_str, manifest_path),
                "url": str(shot.get("url") or ""),
            }
            by_route.setdefault(route, []).append(record)

    return by_route


def attach_capture_media(
    walkthrough: dict,
    manifest: dict,
    *,
    manifest_path: Path | None = None,
    replace_managed: bool = True,
) -> tuple[dict, int]:
    """Attach capture manifest records to step evidence.media entries."""
    data = _deep_copy(walkthrough)
    steps = data.get("steps", [])
    if not isinstance(steps, list) or not steps:
        return data, 0

    if replace_managed:
        for step in steps:
            evidence = step.setdefault("evidence", {})
            media = evidence.get("media", [])
            if isinstance(media, list):
                evidence["media"] = [
                    item
                    for item in media
                    if not (isinstance(item, dict) and item.get("source") == "capture_manifest")
                ]
            else:
                evidence["media"] = []

    by_route = _group_captures_by_route(manifest, manifest_path)
    if not by_route:
        return data, 0

    injected = 0
    for route, route_shots in by_route.items():
        commit_shorts = [shot.get("commit_short", "") for shot in route_shots]
        step_idx = _pick_step_index(steps, route, commit_shorts)
        step = steps[step_idx]
        evidence = step.setdefault("evidence", {})
        media = evidence.setdefault("media", [])
        if not isinstance(media, list):
            media = []
            evidence["media"] = media

        existing_keys = set()
        existing_paths = set()
        for item in media:
            if not isinstance(item, dict):
                continue
            path_value = str(item.get("path", ""))
            if path_value:
                existing_paths.add(path_value)
            existing_keys.add(
                (
                    str(item.get("route", "")),
                    str(item.get("commit", "")),
                    path_value,
                )
            )

        route_group = f"capture-route-{_slug(route)}"
        last_idx = len(route_shots) - 1
        for idx, shot in enumerate(route_shots):
            role = "standalone"
            if len(route_shots) >= 2:
                if idx == 0:
                    role = "before"
                elif idx == last_idx:
                    role = "after"

            route_value = str(shot.get("route", route))
            commit_short = str(shot.get("commit_short", ""))
            path_value = str(shot.get("path", ""))
            dedupe_key = (route_value, commit_short, path_value)
            if dedupe_key in existing_keys or path_value in existing_paths:
                continue

            if role == "before":
                caption = f"{route_value} before ({commit_short})"
            elif role == "after":
                caption = f"{route_value} after ({commit_short})"
            else:
                caption = f"{route_value} ({commit_short})"

            media.append(
                {
                    "id": f"capture-{_slug(route_value)}-{commit_short}-{idx + 1}",
                    "type": "screenshot",
                    "caption": caption,
                    "path": path_value,
                    "group": route_group,
                    "group_role": role,
                    "source": "capture_manifest",
                    "route": route_value,
                    "commit": commit_short,
                    "commit_sha": str(shot.get("commit_sha", "")),
                    "source_ref": {
                        "manifest_path": str(manifest_path) if manifest_path else "",
                        "route": route_value,
                        "commit": commit_short,
                    },
                }
            )
            existing_keys.add(dedupe_key)
            existing_paths.add(path_value)
            injected += 1

    return data, injected


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inject captures/manifest.json screenshots into walkthrough evidence.media"
    )
    parser.add_argument("--walkthrough", type=Path, required=True, help="Path to walkthrough.json")
    parser.add_argument("--manifest", type=Path, required=True, help="Path to captures/manifest.json")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output walkthrough path (default: overwrite --walkthrough)",
    )
    parser.add_argument(
        "--no-replace-managed",
        action="store_true",
        help="Keep previously injected capture_manifest entries instead of replacing them",
    )
    args = parser.parse_args()

    if not args.walkthrough.exists():
        print(f"Error: walkthrough not found: {args.walkthrough}", file=sys.stderr)
        sys.exit(1)
    if not args.manifest.exists():
        print(f"Error: manifest not found: {args.manifest}", file=sys.stderr)
        sys.exit(1)

    with open(args.walkthrough, "r", encoding="utf-8") as f:
        walkthrough = json.load(f)
    with open(args.manifest, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    updated, injected = attach_capture_media(
        walkthrough,
        manifest,
        manifest_path=args.manifest.resolve(),
        replace_managed=not args.no_replace_managed,
    )

    output_path = args.output or args.walkthrough
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(updated, f, indent=2)

    print(
        f"Injected {injected} capture media item(s) into {output_path}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
