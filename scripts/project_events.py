#!/usr/bin/env python3
"""Project normalized events to reduce noise for LLM summarization.

Sits between normalize and chunk. Reads normalized JSONL, outputs projected JSONL
with noise events dropped and verbose tool_result outputs compressed.

DROP entirely:
- file_snapshot — Codex file context dumps, zero reasoning value
- turn_context — Codex system metadata repeated per turn (~12KB each)
- compaction — context window compression markers

COMPRESS tool_result events (when is_error is falsy):
- Replace full output with byte/line counts and first meaningful line

KEEP full output for error tool_results (is_error: true)

KEEP at full fidelity: all other event kinds

Two-pass design:
  Pass 1: Build call_id → tool_name index from tool_use events
  Pass 2: Process each event (drop / compress / keep)

Usage:
    python3 scripts/project_events.py --input normalized.jsonl --output projected.jsonl
"""

import argparse
import copy
import json
import sys


DROP_KINDS = {"file_snapshot", "turn_context", "compaction"}


def build_call_index(lines: list[str]) -> dict[str, str]:
    """Pass 1: scan tool_use events to build call_id → tool_name mapping."""
    index: dict[str, str] = {}
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("kind") == "tool_use":
            tool = obj.get("tool", {})
            call_id = tool.get("call_id", "")
            name = tool.get("name", "")
            if call_id and name:
                index[call_id] = name
    return index


def first_meaningful_line(text: str) -> str:
    """Return the first non-empty line of text."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def compress_tool_result(obj: dict, call_index: dict[str, str]) -> dict:
    """Compress a non-error tool_result event."""
    tool = obj.get("tool", {})
    call_id = tool.get("call_id", "")
    output = tool.get("output", "")
    output_str = output if isinstance(output, str) else json.dumps(output)

    compressed = {
        "seq": obj.get("seq"),
        "kind": "tool_result",
        "turn_index": obj.get("turn_index"),
        "tool": {
            "call_id": call_id,
            "name": call_index.get(call_id, ""),
            "compressed": True,
            "success": True,
            "output_bytes": len(output_str.encode("utf-8")),
            "output_lines": output_str.count("\n") + (1 if output_str else 0),
            "output_head": first_meaningful_line(output_str)[:200],
            "error_text": None,
        },
    }

    # Preserve standard envelope fields
    for key in ("source_line", "source_path", "provider", "session_id", "ts",
                "agent_id", "parent_call_id", "root_turn_index"):
        if key in obj:
            compressed[key] = obj[key]

    return compressed


def project_events(
    input_path: str,
    output_path: str,
    keep_snapshots: bool = False,
    keep_turn_context: bool = False,
) -> None:
    """Read normalized JSONL, write projected JSONL."""
    with open(input_path) as f:
        lines = [line.strip() for line in f if line.strip()]

    # Pass 1: build call_id → tool_name index
    call_index = build_call_index(lines)

    # Pass 2: process events
    kept = 0
    dropped = 0
    compressed = 0
    input_bytes = 0
    output_bytes = 0
    output_lines: list[str] = []

    for line in lines:
        input_bytes += len(line.encode("utf-8"))
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        kind = obj.get("kind", "")

        # Check drop kinds (respecting escape hatches)
        if kind == "file_snapshot" and not keep_snapshots:
            dropped += 1
            continue
        if kind == "turn_context" and not keep_turn_context:
            dropped += 1
            continue
        if kind == "compaction":
            dropped += 1
            continue

        # Compress non-error tool_results
        if kind == "tool_result":
            tool = obj.get("tool", {})
            is_error = tool.get("is_error", False)
            if not is_error:
                projected = compress_tool_result(obj, call_index)
                out_line = json.dumps(projected, ensure_ascii=False)
                output_lines.append(out_line)
                output_bytes += len(out_line.encode("utf-8"))
                compressed += 1
                continue

        # Keep everything else at full fidelity
        if kind == "screenshot":
            media = obj.get("media", {})
            if isinstance(media, dict) and "data_b64" in media:
                projected = copy.deepcopy(obj)
                projected["media"].pop("data_b64", None)
                out_line = json.dumps(projected, ensure_ascii=False)
                output_lines.append(out_line)
                output_bytes += len(out_line.encode("utf-8"))
                kept += 1
                continue

        out_line = json.dumps(obj, ensure_ascii=False)
        output_lines.append(out_line)
        output_bytes += len(out_line.encode("utf-8"))
        kept += 1

    # Write output
    out = sys.stdout if output_path == "-" else open(output_path, "w")
    try:
        for line in output_lines:
            out.write(line + "\n")
    finally:
        if out is not sys.stdout:
            out.close()

    # Stats to stderr
    total = kept + dropped + compressed
    if input_bytes > 0:
        reduction = round((1 - output_bytes / input_bytes) * 100)
    else:
        reduction = 0
    print(
        f"Projected: {kept} kept, {dropped} dropped, {compressed} compressed "
        f"({reduction}% byte reduction)",
        file=sys.stderr,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Project normalized events to reduce noise for LLM summarization"
    )
    parser.add_argument("--input", required=True, help="Path to normalized JSONL")
    parser.add_argument("--output", required=True, help="Output projected JSONL (- for stdout)")
    parser.add_argument(
        "--keep-snapshots", action="store_true",
        help="Keep file_snapshot events (default: drop)",
    )
    parser.add_argument(
        "--keep-turn-context", action="store_true",
        help="Keep turn_context events (default: drop)",
    )
    args = parser.parse_args()

    project_events(
        args.input, args.output,
        keep_snapshots=args.keep_snapshots,
        keep_turn_context=args.keep_turn_context,
    )


if __name__ == "__main__":
    main()
