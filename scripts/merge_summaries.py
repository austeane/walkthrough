#!/usr/bin/env python3
"""Merge chunk summaries into a draft walkthrough.json.

Reads the chunk manifest and corresponding summary files, then produces
a 1:1 chunk-to-step draft that the orchestrator can editorially reshape.

Usage:
    python scripts/merge_summaries.py \
      --manifest out/chunks/manifest.json \
      --summaries-dir out/summaries \
      --repo-root "$(pwd)" \
      --output out/draft-walkthrough.json

    # Dry-run: check coverage without producing output
    python scripts/merge_summaries.py \
      --manifest out/chunks/manifest.json \
      --summaries-dir out/summaries \
      --output /dev/null --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone


SUMMARY_FILE_RE = re.compile(r"^chunk-\d+\..+\.json$")
COMMAND_STATUS_RE = re.compile(r"^(?P<cmd>.*?)(?:\s+\[(?P<status>pass|fail)\])?$", re.IGNORECASE)

EXPECTED_KEYS = {
    "chunk_id", "narrative", "claims", "files_changed", "commands",
    "decisions", "diff_hunks", "errors", "key_concepts", "screenshots",
}


def _normalize_command_entry(cmd: object) -> dict | None:
    if isinstance(cmd, str):
        match = COMMAND_STATUS_RE.match(cmd.strip())
        if not match:
            return {"cmd": cmd, "status": "pass", "summary": ""}
        status = (match.group("status") or "pass").lower()
        return {
            "cmd": match.group("cmd") or "",
            "status": status,
            "summary": "",
        }
    if isinstance(cmd, dict):
        cmd_text = cmd.get("cmd") or cmd.get("command") or ""
        if not cmd_text:
            return None
        status = str(cmd.get("status") or "pass").lower()
        if status not in {"pass", "fail"}:
            status = "pass"
        return {
            "cmd": cmd_text,
            "status": status,
            "summary": cmd.get("summary") or cmd.get("output_preview") or "",
        }
    return None


def _normalize_decision_entry(decision: object) -> dict | None:
    if isinstance(decision, str):
        return {"decision": decision, "rationale": ""}
    if isinstance(decision, dict):
        text = decision.get("decision") or decision.get("text") or ""
        if not text:
            return None
        return {
            "decision": text,
            "rationale": decision.get("rationale") or "",
            "alternatives_considered": decision.get("alternatives_considered", []),
        }
    return None


def _normalize_error_entry(err: object) -> dict | None:
    if isinstance(err, str):
        return {"error": err, "resolution": ""}
    if isinstance(err, dict):
        text = err.get("error") or err.get("text") or err.get("message") or ""
        if not text:
            return None
        out = {
            "error": text,
            "resolution": err.get("resolution") or "",
        }
        if err.get("evidence_ref"):
            out["evidence_ref"] = err["evidence_ref"]
        return out
    return None


def validate_summary(raw: dict) -> dict:
    """Normalize an incoming summary to the expected schema.

    Handles the variations agents produce: narrative as list, files_changed
    as plain strings, missing fields, invented extra keys, etc.
    """
    out = {}

    # chunk_id — pass through
    out["chunk_id"] = raw.get("chunk_id", "")

    # narrative — must be a string
    narrative = raw.get("narrative", "")
    if isinstance(narrative, list):
        narrative = " ".join(str(n) for n in narrative)
    elif not isinstance(narrative, str):
        narrative = str(narrative)
    out["narrative"] = narrative

    # claims — list of dicts, each with at least "text"
    claims = raw.get("claims", [])
    if not isinstance(claims, list):
        claims = []
    normalized_claims = []
    for c in claims:
        if isinstance(c, str):
            normalized_claims.append({"text": c, "confidence": "inferred", "source_refs": []})
        elif isinstance(c, dict) and c.get("text"):
            normalized_claims.append(c)
    out["claims"] = normalized_claims

    # files_changed — list of {"path", "kind", "summary"} dicts
    files = raw.get("files_changed", [])
    if not isinstance(files, list):
        files = []
    normalized_files = []
    for fc in files:
        if isinstance(fc, str):
            normalized_files.append({"path": fc, "kind": "unknown", "summary": ""})
        elif isinstance(fc, dict):
            normalized_files.append({
                "path": fc.get("path", ""),
                "kind": fc.get("kind", "unknown"),
                "summary": fc.get("summary", ""),
            })
    out["files_changed"] = normalized_files

    commands = raw.get("commands", [])
    if not isinstance(commands, list):
        commands = []
    out["commands"] = [entry for cmd in commands if (entry := _normalize_command_entry(cmd))]

    decisions = raw.get("decisions", [])
    if not isinstance(decisions, list):
        decisions = []
    out["decisions"] = [entry for d in decisions if (entry := _normalize_decision_entry(d))]

    diff_hunks = raw.get("diff_hunks", [])
    if not isinstance(diff_hunks, list):
        diff_hunks = []
    out["diff_hunks"] = [h for h in diff_hunks if isinstance(h, dict)]

    errors = raw.get("errors", [])
    if not isinstance(errors, list):
        errors = []
    out["errors"] = [entry for err in errors if (entry := _normalize_error_entry(err))]

    key_concepts = raw.get("key_concepts", [])
    out["key_concepts"] = key_concepts if isinstance(key_concepts, list) else []

    # screenshots — list of dicts with event_seq, context, relevance
    out["screenshots"] = raw.get("screenshots", [])
    if not isinstance(out["screenshots"], list):
        out["screenshots"] = []

    return out


def find_summary(summaries_dir: str, chunk_id: str, sha256: str) -> str | None:
    """Find the exact summary file matching chunk_id and sha256 prefix."""
    prefix = sha256[:8]
    candidate = os.path.join(summaries_dir, f"{chunk_id}.{prefix}.json")
    if os.path.isfile(candidate):
        return candidate
    return None


def first_sentence(text: str) -> str:
    """Extract the first sentence from a string."""
    for end in (".", "!", "?"):
        idx = text.find(end)
        if idx != -1:
            return text[: idx + 1]
    # No sentence-ending punctuation — return first 80 chars
    return text[:80] + ("..." if len(text) > 80 else "")


def build_deterministic_summary(chunk_path: str, chunk_id: str) -> dict:
    """Build a deterministic summary from a chunk JSONL file.

    Extracts factual information without LLM calls:
    - file_change paths with kinds
    - commands with pass/fail
    - error messages (first line)
    - first sentence of each user_message
    - event count breakdown by kind
    """
    kind_counts: Counter = Counter()
    files_changed: list[dict] = []
    seen_files: set[str] = set()
    commands: list[dict] = []
    errors: list[dict] = []
    user_intents: list[str] = []

    with open(chunk_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            kind = obj.get("kind", "")
            kind_counts[kind] += 1

            if kind == "user_message":
                text = obj.get("text", "")
                if text:
                    intent = first_sentence(text)
                    if intent and intent not in user_intents:
                        user_intents.append(intent)

            elif kind == "file_change":
                fc = obj.get("file_change", {})
                path = fc.get("path", "")
                change_kind = fc.get("kind", "modify")
                if path and path not in seen_files:
                    seen_files.add(path)
                    files_changed.append({"path": path, "kind": change_kind, "summary": ""})

            elif kind == "command":
                cmd_info = obj.get("command", {})
                cmd = cmd_info.get("cmd", "")
                exit_code = cmd_info.get("exit_code")
                if cmd:
                    status = "pass" if exit_code == 0 or exit_code is None else "fail"
                    commands.append({
                        "cmd": cmd[:80],
                        "status": status,
                        "summary": cmd_info.get("output_preview", ""),
                    })
                    if exit_code is not None and exit_code != 0:
                        errors.append({
                            "error": f"Command failed (exit {exit_code}): {cmd[:120]}",
                            "resolution": "",
                        })

            elif kind == "tool_result":
                tool = obj.get("tool", {})
                if tool.get("is_error"):
                    output = tool.get("output", "")
                    if output:
                        for err_line in output.splitlines():
                            err_line = err_line.strip()
                            if err_line:
                                errors.append({"error": err_line[:200], "resolution": ""})
                                break

    total_events = sum(kind_counts.values())
    kind_breakdown = ", ".join(f"{k}: {v}" for k, v in kind_counts.most_common(5))

    # Build narrative
    parts = [f"{chunk_id}: {total_events} events ({kind_breakdown})."]
    if user_intents:
        parts.append(f"User intents: {'; '.join(user_intents[:5])}.")
    if files_changed:
        file_names = [fc["path"].rsplit("/", 1)[-1] for fc in files_changed[:8]]
        parts.append(f"Files: {', '.join(file_names)}.")
    if commands:
        parts.append(f"{len(commands)} commands run.")
    if errors:
        parts.append(f"{len(errors)} error(s).")

    narrative = " ".join(parts)

    return {
        "chunk_id": chunk_id,
        "narrative": narrative,
        "claims": [],
        "files_changed": files_changed,
        "commands": commands[:10],
        "decisions": [],
        "diff_hunks": [],
        "errors": errors[:10],
        "key_concepts": [],
        "screenshots": [],
    }


def _clean_git_info(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {}
    git_info = {}
    branch = raw.get("branch") or raw.get("gitBranch")
    commit = raw.get("commit") or raw.get("commit_hash")
    dirty = raw.get("dirty")
    repository_url = raw.get("repository_url") or raw.get("repo") or raw.get("repository")
    if branch:
        git_info["branch"] = branch
    if commit:
        git_info["commit"] = commit
    if isinstance(dirty, bool):
        git_info["dirty"] = dirty
    if repository_url:
        git_info["repository_url"] = repository_url
    return git_info


def _merge_consistent_dicts(items: list[dict]) -> dict:
    merged = {}
    keys = {key for item in items for key in item.keys()}
    for key in keys:
        values = {item.get(key) for item in items if item.get(key) not in (None, "")}
        if len(values) == 1:
            merged[key] = values.pop()
    return merged


def collect_source_metadata(source_path: str) -> tuple[list[dict], dict]:
    """Collect sessions and best-effort repo metadata from a source stream."""
    if not source_path or not os.path.isfile(source_path):
        return [], {}

    by_key: dict[tuple[str, str], str] = {}
    repo_roots: list[str] = []
    git_infos: list[dict] = []

    with open(source_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            provider = obj.get("provider", "")
            session_path = obj.get("source_path", "")
            ts = obj.get("ts", "")
            if provider and session_path:
                key = (provider, session_path)
                existing_ts = by_key.get(key, "")
                if ts and (not existing_ts or ts < existing_ts):
                    by_key[key] = ts
                elif key not in by_key:
                    by_key[key] = ts

            if obj.get("kind") == "meta":
                meta = obj.get("meta", {})
                cwd = meta.get("cwd")
                if cwd:
                    repo_roots.append(cwd)
                git_info = _clean_git_info(meta.get("git"))
                if git_info:
                    git_infos.append(git_info)

    sessions = [
        {"provider": provider, "path": path, "timestamp": ts}
        for (provider, path), ts in by_key.items()
    ]
    sessions.sort(key=lambda s: (s.get("timestamp") or "9999-12-31T23:59:59Z", s.get("path", "")))

    meta = {}
    unique_roots = sorted({root for root in repo_roots if root})
    if len(unique_roots) == 1:
        meta["repo_root"] = unique_roots[0]

    merged_git = _merge_consistent_dicts(git_infos)
    if merged_git:
        meta["git"] = {k: v for k, v in merged_git.items() if k != "repository_url"}
        if merged_git.get("repository_url"):
            meta["repo"] = merged_git["repository_url"]

    return sessions, meta


def detect_provider_from_first_chunk(chunks_dir: str, chunks: list[dict]) -> str:
    """Best-effort provider detection from the first chunk event."""
    if not chunks:
        return "unknown"
    first_chunk_path = os.path.join(chunks_dir, chunks[0].get("path", ""))
    if not os.path.isfile(first_chunk_path):
        return "unknown"

    with open(first_chunk_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            provider = obj.get("provider")
            if provider:
                return provider
            break
    return "unknown"


def merge_summaries(
    manifest_path: str,
    summaries_dir: str,
    output_path: str,
    repo_root: str = "",
    dry_run: bool = False,
    allow_fallback: bool = False,
) -> None:
    with open(manifest_path) as f:
        manifest = json.load(f)

    chunks = manifest["chunks"]
    chunks_dir = os.path.dirname(manifest_path)
    summaries = []
    missing = []
    fallback_count = 0

    for chunk in chunks:
        chunk_id = chunk["chunk_id"]
        sha256 = chunk["sha256"]
        path = find_summary(summaries_dir, chunk_id, sha256)
        if path is None:
            missing.append(chunk_id)
        else:
            with open(path) as f:
                raw = json.load(f)
            summaries.append(validate_summary(raw))

    # Report coverage
    total = len(chunks)
    found = total - len(missing)
    print(f"Summary coverage: {found}/{total} chunks", file=sys.stderr)
    if missing:
        print(f"Missing: {', '.join(missing)}", file=sys.stderr)

    if dry_run:
        if missing:
            sys.exit(1)
        return

    if missing and not allow_fallback:
        print("ERROR: Cannot proceed with missing summaries.", file=sys.stderr)
        sys.exit(1)

    # With --allow-fallback, build deterministic summaries for missing chunks
    if missing and allow_fallback:
        # Rebuild summaries list in chunk order, inserting fallbacks for missing
        ordered_summaries = []
        for chunk in chunks:
            chunk_id = chunk["chunk_id"]
            sha256 = chunk["sha256"]
            path = find_summary(summaries_dir, chunk_id, sha256)
            if path is not None:
                with open(path) as f:
                    raw = json.load(f)
                ordered_summaries.append(validate_summary(raw))
            else:
                # Build deterministic fallback from chunk JSONL
                chunk_path = os.path.join(chunks_dir, chunk["path"])
                if os.path.isfile(chunk_path):
                    fb = build_deterministic_summary(chunk_path, chunk_id)
                    ordered_summaries.append(validate_summary(fb))
                    fallback_count += 1
                else:
                    # Minimal stub if chunk file is also missing
                    ordered_summaries.append(validate_summary({
                        "chunk_id": chunk_id,
                        "narrative": f"{chunk_id}: {chunk.get('event_count', 0)} events (chunk file not found).",
                    }))
                    fallback_count += 1
        summaries = ordered_summaries
        print(f"Fallback summaries generated: {fallback_count}", file=sys.stderr)

    # Collect all unique file paths
    all_files = []
    seen_files = set()
    for s in summaries:
        for fc in s["files_changed"]:
            p = fc["path"]
            if p and p not in seen_files:
                seen_files.add(p)
                all_files.append(p)

    # Build steps (1:1 from chunks)
    steps = []
    for i, s in enumerate(summaries):
        step = {
            "id": f"step-{i + 1}",
            "title": first_sentence(s["narrative"]),
            "intent": s["narrative"],
            "claims": s["claims"],
            "evidence": {
                "files_changed": [fc["path"] for fc in s["files_changed"]],
                "diff_hunks": s["diff_hunks"],
                "commands": s["commands"],
                "screenshots": s["screenshots"],
            },
            "decisions": s["decisions"],
            "errors_encountered": s["errors"],
        }
        steps.append(step)

    # Build overview
    narratives = [s["narrative"] for s in summaries]
    overview_goal = narratives[0] if narratives else ""

    # Collect sessions from the concatenated source stream.
    source = manifest.get("source", "")
    source_path = source
    if source_path and not os.path.isfile(source_path):
        candidate = os.path.join(chunks_dir, source_path)
        if os.path.isfile(candidate):
            source_path = candidate

    sessions, source_meta = collect_source_metadata(source_path)
    if not sessions and source:
        sessions.append({
            "provider": detect_provider_from_first_chunk(chunks_dir, chunks),
            "path": source,
            "timestamp": chunks[0]["time_range"]["start"] if chunks else "",
        })

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sessions": sessions,
        "scope": "draft — needs editorial reshaping",
    }
    meta.update(source_meta)
    if repo_root:
        meta["repo_root"] = repo_root

    walkthrough = {
        "version": "0.1.0",
        "meta": meta,
        "overview": {
            "goal": overview_goal,
            "summary": [first_sentence(n) for n in narratives[:7]],
            "key_files": all_files[:20],
        },
        "steps": steps,
    }

    out = sys.stdout if output_path == "-" else open(output_path, "w")
    try:
        json.dump(walkthrough, out, indent=2, ensure_ascii=False)
        out.write("\n")
    finally:
        if out is not sys.stdout:
            out.close()

    print(
        f"Merged {len(summaries)} summaries → {output_path}",
        file=sys.stderr,
    )
    if repo_root:
        print(f"  repo_root: {repo_root}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Merge chunk summaries into a draft walkthrough.json"
    )
    parser.add_argument("--manifest", required=True, help="Path to chunks/manifest.json")
    parser.add_argument("--summaries-dir", required=True, help="Directory containing chunk-*.json")
    parser.add_argument("--output", required=True, help="Path to output walkthrough.json (- for stdout)")
    parser.add_argument(
        "--repo-root", default="",
        help="Absolute path to project root (written to meta.repo_root for editor links)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Check summary coverage and exit non-zero if any are missing"
    )
    parser.add_argument(
        "--allow-fallback", action="store_true",
        help="Use deterministic fallback for missing summaries instead of erroring"
    )
    args = parser.parse_args()

    merge_summaries(
        args.manifest,
        args.summaries_dir,
        args.output,
        repo_root=args.repo_root,
        dry_run=args.dry_run,
        allow_fallback=args.allow_fallback,
    )


if __name__ == "__main__":
    main()
