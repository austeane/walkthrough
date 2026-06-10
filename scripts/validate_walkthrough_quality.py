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


def _iter_claim_refs(steps: list) -> list[tuple[int, dict, dict]]:
    """(step_number, claim, ref) for every claim source_ref across all steps."""
    out: list[tuple[int, dict, dict]] = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        claims = step.get("claims")
        if not isinstance(claims, list):
            continue
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            refs = claim.get("source_refs")
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if isinstance(ref, dict):
                    out.append((index, claim, ref))
    return out


def _resolve_ref_path(path: str, base_dir: str, repo_root: str) -> str | None:
    if not path:
        return None
    if os.path.isabs(path):
        return path if os.path.isfile(path) else None
    for root in (base_dir, repo_root, os.getcwd()):
        if root:
            candidate = os.path.join(root, path)
            if os.path.isfile(candidate):
                return candidate
    return None


def _examples(items: list[str], limit: int = 3) -> str:
    unique: list[str] = []
    for item in items:
        if item not in unique:
            unique.append(item)
    suffix = ", ..." if len(unique) > limit else ""
    return ", ".join(unique[:limit]) + suffix


MAX_REF_SPAN_LINES = 200
SHARED_RANGE_CLAIM_LIMIT = 3
MONOCULTURE_CLAIM_FLOOR = 20
GLOSSARY_MAX_ENTRIES = 50
GLOSSARY_MAX_DEFINITION_CHARS = 300

# Keys whose string values are never reader-facing prose (so glossary terms
# appearing only there would never be annotated by the viewer).
_NON_PROSE_KEYS = frozenset({
    "evidence", "source_refs", "files_changed", "key_files", "commands",
    "media", "screenshots", "diff", "code", "output", "session_path",
    "path", "file", "href", "url", "id", "step_ref", "step_refs", "mode",
    "confidence", "provider", "timestamp", "github_path", "github_ref",
    "diagram_mermaid", "diagram_image", "aliases",
})


def _collect_prose(value: object, out: list[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, list):
        for item in value:
            _collect_prose(item, out)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in _NON_PROSE_KEYS:
                _collect_prose(item, out)


def _normalize_glossary(raw: object) -> tuple[list[dict], int]:
    """Mirror the viewer's normalizeGlossary: accept an array of entry objects
    or a {term: definition-or-object} map. Returns (entries, malformed_count)
    where malformed counts items that are not objects at all."""
    entries: list[dict] = []
    malformed = 0
    if isinstance(raw, dict):
        for term, value in raw.items():
            if isinstance(value, str):
                entries.append({"term": term, "definition": value})
            elif isinstance(value, dict):
                entries.append({"term": term, **value})
            else:
                malformed += 1
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                entries.append(item)
            else:
                malformed += 1
    return entries, malformed


def _validate_glossary(data: dict, report: QualityReport, *, base_dir: str | None) -> None:
    """Glossary lint (warnings only — the feature is optional): malformed
    entries, duplicate terms, dead terms that never appear in annotated prose,
    file paths that do not resolve, oversized definitions or entry counts."""
    overview = data.get("overview") if isinstance(data.get("overview"), dict) else {}
    raw = data.get("glossary", overview.get("glossary"))
    if raw is None:
        return
    if not isinstance(raw, (list, dict)):
        report.add_warning("glossary must be an array of entries or a term->definition map")
        return

    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    repo_root = _as_text(meta.get("repo_root")).rstrip("/")
    entries, malformed = _normalize_glossary(raw)

    incomplete: list[str] = []
    seen_terms: set[str] = set()
    duplicates: list[str] = []
    long_definitions: list[str] = []
    missing_files: list[str] = []
    dead_terms: list[str] = []

    prose_parts: list[str] = []
    _collect_prose(overview, prose_parts)
    _collect_prose(data.get("steps"), prose_parts)
    prose = "\n".join(prose_parts)

    for entry in entries:
        term = _as_text(entry.get("term") or entry.get("label"))
        definition = _as_text(entry.get("definition") or entry.get("description"))
        expanded = _as_text(entry.get("expanded") or entry.get("expansion"))
        if not term or not (definition or expanded):
            incomplete.append(term or "(no term)")
            continue

        key = term.lower()
        if key in seen_terms:
            duplicates.append(term)
            continue
        seen_terms.add(key)

        if len(definition) > GLOSSARY_MAX_DEFINITION_CHARS:
            long_definitions.append(term)

        file_path = _as_text(entry.get("file") or entry.get("github_path"))
        if file_path and not _as_text(entry.get("href") or entry.get("url")):
            if _resolve_ref_path(file_path, base_dir or "", repo_root) is None:
                missing_files.append(f"{term}: {file_path}")

        aliases = entry.get("aliases") if isinstance(entry.get("aliases"), list) else []
        patterns = [p for p in [term, *(_as_text(a) for a in aliases)] if len(p) >= 2]
        found = any(
            re.search(
                r"(?:^|[^A-Za-z0-9_])" + re.escape(pattern) + r"(?=$|[^A-Za-z0-9_])",
                prose,
                re.IGNORECASE,
            )
            for pattern in patterns
        )
        if not found:
            dead_terms.append(term)

    if malformed:
        report.add_warning(f"{malformed} glossary entries are not objects (or map values are invalid)")
    if incomplete:
        report.add_warning(
            f"{len(incomplete)} glossary entries lack a term or any definition/expansion: "
            + _examples(incomplete)
        )
    if duplicates:
        report.add_warning(
            f"{len(duplicates)} glossary terms are duplicated (case-insensitive): " + _examples(duplicates)
        )
    if long_definitions:
        report.add_warning(
            f"{len(long_definitions)} glossary definitions exceed {GLOSSARY_MAX_DEFINITION_CHARS} chars "
            "(tooltips should be one or two short sentences): " + _examples(long_definitions)
        )
    if missing_files:
        report.add_warning(
            f"{len(missing_files)} glossary file paths do not resolve on disk: " + _examples(missing_files)
        )
    if dead_terms:
        report.add_warning(
            f"{len(dead_terms)} glossary terms never appear in reader-facing prose "
            "(the viewer will never annotate them): " + _examples(dead_terms)
        )
    if len(entries) > GLOSSARY_MAX_ENTRIES:
        report.add_warning(
            f"glossary has {len(entries)} entries (over {GLOSSARY_MAX_ENTRIES}) — "
            "tooltip overload dilutes the signal; keep the terms a new teammate actually needs"
        )


def _validate_source_refs(
    data: dict,
    report: QualityReport,
    *,
    base_dir: str | None,
    fs_refs: bool,
) -> None:
    """Source-ref integrity: cited files exist, line ranges are in bounds, paths
    are declared in meta.sessions, spans are selective, and ranges are not
    shared verbatim across many claims. Filesystem checks need base_dir (the
    directory of the walkthrough.json); without it only pure checks run."""
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    steps = data.get("steps") if isinstance(data.get("steps"), list) else []
    repo_root = _as_text(meta.get("repo_root")).rstrip("/")
    refs = _iter_claim_refs(steps)

    add_fs_issue = report.add_error if fs_refs else report.add_warning

    declared: set[str] = set()
    sessions = meta.get("sessions")
    if isinstance(sessions, list):
        for session in sessions:
            if isinstance(session, dict) and _as_text(session.get("path")):
                path = _as_text(session.get("path"))
                declared.add(path)
                declared.add(os.path.basename(path))

    line_counts: dict[str, int] = {}
    missing: list[str] = []
    out_of_bounds: list[str] = []
    undeclared: list[str] = []
    wide_spans = 0
    range_claims: dict[tuple[str, int, int], int] = {}

    for step_number, _claim, ref in refs:
        cited = _as_text(ref.get("session_path"))
        start = ref.get("line_start")
        end = ref.get("line_end")
        if isinstance(start, int) and isinstance(end, int):
            if end - start > MAX_REF_SPAN_LINES:
                wide_spans += 1
            key = (cited, start, end)
            range_claims[key] = range_claims.get(key, 0) + 1

        if base_dir is not None and cited:
            resolved = _resolve_ref_path(cited, base_dir, repo_root)
            if resolved is None:
                missing.append(f"step {step_number}: {cited}")
                continue
            if declared and cited not in declared and os.path.basename(cited) not in declared:
                undeclared.append(cited)
            if isinstance(start, int) and isinstance(end, int):
                if resolved not in line_counts:
                    try:
                        with open(resolved, "rb") as handle:
                            line_counts[resolved] = sum(1 for _ in handle)
                    except OSError:
                        line_counts[resolved] = -1
                count = line_counts[resolved]
                if count >= 0 and (start < 1 or end < start or end > count):
                    out_of_bounds.append(f"step {step_number}: {cited}:{start}-{end} (file has {count} lines)")

    if missing:
        add_fs_issue(
            f"{len(missing)} source_refs cite files that do not exist on disk: " + _examples(missing)
        )
    if out_of_bounds:
        add_fs_issue(
            f"{len(out_of_bounds)} source_refs have line ranges out of bounds: " + _examples(out_of_bounds)
        )
    if undeclared:
        report.add_warning(
            f"{len(undeclared)} source_refs cite paths not declared in meta.sessions: " + _examples(undeclared)
        )
    if wide_spans:
        report.add_warning(
            f"{wide_spans} source_refs span more than {MAX_REF_SPAN_LINES} lines — "
            "refs should select evidence, not partition the transcript"
        )
    shared = [key for key, uses in range_claims.items() if uses >= SHARED_RANGE_CLAIM_LIMIT]
    if shared:
        report.add_warning(
            f"{len(shared)} identical line ranges are cited by {SHARED_RANGE_CLAIM_LIMIT}+ claims each "
            "(e.g. " + _examples([f"{p}:{s}-{e}" for p, s, e in shared]) + ") — distinct assertions need distinct evidence"
        )

    confidences = [
        _as_text(claim.get("confidence")).lower()
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("claims"), list)
        for claim in step.get("claims")
        if isinstance(claim, dict) and _as_text(claim.get("confidence"))
    ]
    if len(confidences) >= MONOCULTURE_CLAIM_FLOOR and len(set(confidences)) == 1 and confidences[0] == "grounded":
        report.add_warning(
            f"all {len(confidences)} claims are labeled grounded — confidence looks rubber-stamped, "
            "not calibrated (inferred/speculative should appear where honest)"
        )


def validate_walkthrough(
    data: dict,
    *,
    max_steps: int = 12,
    base_dir: str | None = None,
    fs_refs: bool = True,
) -> QualityReport:
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

    end_state = overview.get("end_state")
    if not (isinstance(end_state, dict) and (_as_text(end_state.get("goal")) or end_state.get("summary"))):
        report.add_warning(
            "overview.end_state missing — the destination-first framing is the highest-scoring overview structure"
        )

    _validate_source_refs(data, report, base_dir=base_dir, fs_refs=fs_refs)
    _validate_glossary(data, report, base_dir=base_dir)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate finished walkthrough narrative quality")
    parser.add_argument("--input", required=True, help="Path to walkthrough.json")
    parser.add_argument("--max-steps", type=int, default=12, help="Maximum final step count before failing")
    parser.add_argument(
        "--no-fs-refs",
        action="store_true",
        help="Downgrade filesystem source-ref checks (existence, line bounds) to warnings, e.g. off the producing machine",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable report")
    args = parser.parse_args()

    input_path = Path(args.input)
    data = json.loads(input_path.read_text(encoding="utf-8"))
    report = validate_walkthrough(
        data,
        max_steps=args.max_steps,
        base_dir=str(input_path.resolve().parent),
        fs_refs=not args.no_fs_refs,
    )

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
