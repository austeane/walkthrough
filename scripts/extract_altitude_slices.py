#!/usr/bin/env python3
"""Extract altitude slices from a walkthrough.json for time-to-grok judging.

Produces two nested markdown views of the artifact, mirroring how far a reader
has descended the altitude ladder (see references/ttg-judging-rubric.md):

- skim.md: overview goal/summary (+ end-state framing) and step titles with
  takeaway lines only — what a ~30-second scan of the rendered page conveys.
- scan.md: skim plus the always-visible narrative band per step (intent,
  claims with confidence tags, decisions, gotchas) and overview key files.
  No collapsed evidence (diffs, commands, media) and no source refs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _as_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _text(value: object, *keys: str) -> str:
    """Best-effort text from a string or an object with one of the given keys."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in keys:
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return text
    return ""


def _overview_lines(data: dict) -> list[str]:
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    overview = data.get("overview") if isinstance(data.get("overview"), dict) else {}
    lines: list[str] = []

    scope = meta.get("scope")
    if isinstance(scope, str) and scope.strip():
        lines.append(f"Scope: {scope}")
    goal = overview.get("goal")
    if isinstance(goal, str) and goal.strip():
        lines.append(f"Goal: {goal}")
    for item in _as_list(overview.get("summary")):
        text = _text(item)
        if text:
            lines.append(f"- {text}")

    end_state = overview.get("end_state") if isinstance(overview.get("end_state"), dict) else {}
    if end_state:
        lines.append("")
        lines.append("## End state")
        es_goal = end_state.get("goal")
        if isinstance(es_goal, str) and es_goal.strip():
            lines.append(f"Goal: {es_goal}")
        for item in _as_list(end_state.get("summary")):
            text = _text(item)
            if text:
                lines.append(f"- {text}")
        architecture = [a for a in _as_list(end_state.get("architecture")) if isinstance(a, dict)]
        if architecture:
            lines.append("")
            lines.append("Architecture:")
            for entry in architecture:
                component = entry.get("component", "")
                summary = entry.get("summary", "")
                lines.append(f"- {component}: {summary}".rstrip(": "))
        constraints = [c for c in _as_list(end_state.get("constraints")) if isinstance(c, str)]
        if constraints:
            lines.append("")
            lines.append("Current constraints:")
            lines.extend(f"- {c}" for c in constraints)
    return lines


def _step_heading(index: int, step: dict) -> str:
    mode = step.get("mode")
    tag = f" [{mode}]" if isinstance(mode, str) and mode and mode != "both" else ""
    title = step.get("title") or step.get("id") or f"step {index}"
    return f"{index}. {title}{tag}"


def build_skim(data: dict) -> str:
    lines = ["# Skim slice", ""]
    lines.extend(_overview_lines(data))
    lines.append("")
    lines.append("## Steps (title — takeaway)")
    for index, step in enumerate(_as_list(data.get("steps")), start=1):
        if not isinstance(step, dict):
            continue
        lines.append(_step_heading(index, step))
        takeaway = step.get("takeaway")
        if isinstance(takeaway, str) and takeaway.strip():
            lines.append(f"   {takeaway}")
        else:
            lines.append("   (no takeaway)")
    return "\n".join(lines).rstrip() + "\n"


def build_scan(data: dict) -> str:
    lines = ["# Scan slice (narrative band, no evidence)", ""]
    lines.extend(_overview_lines(data))

    overview = data.get("overview") if isinstance(data.get("overview"), dict) else {}
    key_files = _as_list(overview.get("key_files"))
    if key_files:
        lines.append("")
        lines.append("## Key files")
        for entry in key_files:
            path = _text(entry, "path")
            reason = entry.get("reason", "") if isinstance(entry, dict) else ""
            lines.append(f"- {path}" + (f" — {reason}" if reason else ""))

    lines.append("")
    lines.append("## Steps")
    for index, step in enumerate(_as_list(data.get("steps")), start=1):
        if not isinstance(step, dict):
            continue
        lines.append("")
        lines.append(f"### {_step_heading(index, step)}")
        takeaway = step.get("takeaway")
        if isinstance(takeaway, str) and takeaway.strip():
            lines.append(f"Takeaway: {takeaway}")
        intent = step.get("intent")
        if isinstance(intent, str) and intent.strip():
            lines.append(f"Intent: {intent}")
        claims = [c for c in _as_list(step.get("claims")) if _text(c, "text")]
        if claims:
            lines.append("Claims:")
            for claim in claims:
                confidence = claim.get("confidence", "") if isinstance(claim, dict) else ""
                suffix = f" [{confidence}]" if confidence else ""
                lines.append(f"- {_text(claim, 'text')}{suffix}")
        decisions = [d for d in _as_list(step.get("decisions")) if _text(d, "decision")]
        if decisions:
            lines.append("Decisions:")
            for decision in decisions:
                text = _text(decision, "decision")
                rationale = decision.get("rationale", "") if isinstance(decision, dict) else ""
                lines.append(f"- {text}" + (f" — {rationale}" if rationale else ""))
        gotchas = [e for e in _as_list(step.get("errors_encountered")) if _text(e, "error")]
        if gotchas:
            lines.append("Gotchas:")
            for gotcha in gotchas:
                text = _text(gotcha, "error")
                resolution = gotcha.get("resolution", "") if isinstance(gotcha, dict) else ""
                lines.append(f"- {text}" + (f" — resolved: {resolution}" if resolution else ""))
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract skim/scan altitude slices for judging")
    parser.add_argument("--input", required=True, help="Path to walkthrough.json")
    parser.add_argument("--output-dir", required=True, help="Directory for skim.md and scan.md")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "skim.md").write_text(build_skim(data), encoding="utf-8")
    (out_dir / "scan.md").write_text(build_scan(data), encoding="utf-8")
    print(f"wrote {out_dir / 'skim.md'} and {out_dir / 'scan.md'}")


if __name__ == "__main__":
    main()
