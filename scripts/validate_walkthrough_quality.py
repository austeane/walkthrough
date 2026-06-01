#!/usr/bin/env python3
"""Validate that walkthrough.json is editorially ready to render/share.

This complements pipeline validation. Pipeline validation proves the event data
is structurally sound; this gate catches draft-grade walkthroughs that are valid
JSON but poor reading artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


CHUNK_TITLE_RE = re.compile(r"^\s*chunk-\d+\b", re.IGNORECASE)
EVENT_COUNT_RE = re.compile(r"\b\d+\s+events\b", re.IGNORECASE)
RAW_INTENT_RE = re.compile(
    r"<(?:environment_context|local-command-caveat)>|#\s*AGENTS\b|continued from a previous conversation",
    re.IGNORECASE,
)
GENERIC_TAKEAWAY_RE = re.compile(r"^\s*(this chunk|chunk-\d+|n/a|none|todo)\b", re.IGNORECASE)


@dataclass
class QualityReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    @property
    def ok(self) -> bool:
        return not self.errors


def _as_text(value: object) -> str:
    return str(value or "").strip()


def _is_in_repo(path: str, repo_root: str) -> bool:
    if not path or not repo_root or not os.path.isabs(path):
        return True
    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(repo_root)]) == os.path.realpath(repo_root)
    except ValueError:
        return False


def _is_noisy_file(path: str, repo_root: str) -> bool:
    normalized = path.replace("\\", "/")
    basename = os.path.basename(normalized).lower()
    if not normalized:
        return True
    if normalized.startswith("/tmp/"):
        return True
    if "/.claude/" in normalized or "/.codex/" in normalized:
        return True
    if basename.startswith(".env"):
        return True
    if "worklog" in basename and basename.endswith(".md"):
        return True
    if repo_root and os.path.isabs(normalized) and not _is_in_repo(normalized, repo_root):
        return True
    return False


def _has_grounded_source_ref(claims: object) -> bool:
    if not isinstance(claims, list):
        return False
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        confidence = _as_text(claim.get("confidence")).lower()
        refs = claim.get("source_refs")
        if confidence == "grounded" and isinstance(refs, list) and refs:
            return True
    return False


def validate_walkthrough(data: dict, *, max_steps: int = 20) -> QualityReport:
    report = QualityReport()
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    overview = data.get("overview") if isinstance(data.get("overview"), dict) else {}
    steps = data.get("steps") if isinstance(data.get("steps"), list) else []
    repo_root = _as_text(meta.get("repo_root")).rstrip("/")

    goal = _as_text(overview.get("goal"))
    if not goal:
        report.add_error("overview.goal is required")
    elif CHUNK_TITLE_RE.search(goal) or EVENT_COUNT_RE.search(goal):
        report.add_error("overview.goal still looks like raw chunk metadata")

    summary = overview.get("summary")
    if not isinstance(summary, list) or len([item for item in summary if _as_text(item)]) < 3:
        report.add_warning("overview.summary should contain at least 3 useful bullets")
    elif isinstance(summary, list):
        for index, item in enumerate(summary, start=1):
            text = _as_text(item)
            if CHUNK_TITLE_RE.search(text) or EVENT_COUNT_RE.search(text) or RAW_INTENT_RE.search(text):
                report.add_error(f"overview.summary item {index} still looks like raw chunk/transcript text")

    key_files = overview.get("key_files") or []
    if not isinstance(key_files, list):
        report.add_error("overview.key_files must be a list when present")
    else:
        noisy = [_as_text(path) for path in key_files if _is_noisy_file(_as_text(path), repo_root)]
        if noisy:
            report.add_error(
                "overview.key_files contains non-reader-facing paths: "
                + ", ".join(noisy[:5])
            )

    if not steps:
        report.add_error("steps must contain at least one step")
        return report
    if len(steps) > max_steps:
        report.add_error(f"steps has {len(steps)} entries; max allowed before editorial compression is {max_steps}")

    takeaways: list[str] = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            report.add_error(f"step {index} is not an object")
            continue

        title = _as_text(step.get("title"))
        takeaway = _as_text(step.get("takeaway"))
        intent = _as_text(step.get("intent"))

        if not title:
            report.add_error(f"step {index} is missing title")
        if CHUNK_TITLE_RE.search(title) or EVENT_COUNT_RE.search(title):
            report.add_error(f"step {index} title still looks like raw chunk metadata")
        if RAW_INTENT_RE.search(title):
            report.add_error(f"step {index} title contains raw transcript/control text")

        if not takeaway:
            report.add_error(f"step {index} is missing takeaway")
        elif GENERIC_TAKEAWAY_RE.search(takeaway) or EVENT_COUNT_RE.search(takeaway):
            report.add_error(f"step {index} takeaway is not reader-facing")
        else:
            takeaways.append(takeaway)

        if title and takeaway and title.rstrip(".") == takeaway.rstrip("."):
            report.add_warning(f"step {index} takeaway duplicates the title")

        if CHUNK_TITLE_RE.search(intent) or EVENT_COUNT_RE.search(intent):
            report.add_error(f"step {index} intent still looks like raw chunk metadata")
        elif RAW_INTENT_RE.search(intent):
            report.add_error(f"step {index} intent contains raw transcript/control text")

        if not _has_grounded_source_ref(step.get("claims")):
            report.add_error(f"step {index} has no grounded claim with source_refs")

    if len(set(takeaways)) != len(takeaways):
        report.add_warning("duplicate takeaway lines weaken the skim path")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate finished walkthrough narrative quality")
    parser.add_argument("--input", required=True, help="Path to walkthrough.json")
    parser.add_argument("--max-steps", type=int, default=20, help="Maximum final step count before failing")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable report")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    report = validate_walkthrough(data, max_steps=args.max_steps)

    if args.json:
        print(json.dumps({"ok": report.ok, "errors": report.errors, "warnings": report.warnings}, indent=2))
    else:
        print(f"Quality gate: {'PASS' if report.ok else 'FAIL'}")
        for error in report.errors:
            print(f"ERROR: {error}")
        for warning in report.warnings:
            print(f"WARNING: {warning}")

    if not report.ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
