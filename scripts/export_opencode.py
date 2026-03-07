#!/usr/bin/env python3
"""Export an OpenCode session into a line-oriented JSONL intermediary.

Usage:
    python scripts/export_opencode.py --session-id ses_123 --output session.jsonl
"""

import argparse
import json
import os
import subprocess
import sys


def export_session(session_id: str, opencode_bin: str) -> dict:
    """Fetch a single OpenCode session export via the CLI."""
    result = subprocess.run(
        [opencode_bin, "export", session_id],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "unknown OpenCode export failure"
        raise RuntimeError(stderr)

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"failed to parse OpenCode export JSON: {exc}") from exc


def build_export_lines(export_data: dict) -> list[dict]:
    """Flatten nested export JSON into one line for session info and one per message."""
    info = export_data.get("info")
    messages = export_data.get("messages", [])

    if not isinstance(info, dict):
        raise RuntimeError("OpenCode export is missing top-level session info")
    if not isinstance(messages, list):
        raise RuntimeError("OpenCode export has invalid messages payload")

    lines = [{"type": "session", "info": info}]
    for message in messages:
        if not isinstance(message, dict):
            continue
        msg_info = message.get("info")
        parts = message.get("parts", [])
        if not isinstance(msg_info, dict):
            continue
        if not isinstance(parts, list):
            parts = []
        lines.append({
            "type": "message",
            "info": msg_info,
            "parts": parts,
        })
    return lines


def main():
    parser = argparse.ArgumentParser(description="Export an OpenCode session to JSONL")
    parser.add_argument("--session-id", required=True, help="OpenCode session ID")
    parser.add_argument("--output", required=True, help="Output JSONL path ('-' for stdout)")
    parser.add_argument(
        "--opencode-bin",
        default=os.environ.get("OPENCODE_BIN", "opencode"),
        help="OpenCode CLI binary (default: opencode)",
    )
    args = parser.parse_args()

    try:
        export_data = export_session(args.session_id, args.opencode_bin)
        lines = build_export_lines(export_data)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    out = sys.stdout if args.output == "-" else open(args.output, "w", encoding="utf-8")
    try:
        for obj in lines:
            out.write(json.dumps(obj, ensure_ascii=False) + "\n")
    finally:
        if out is not sys.stdout:
            out.close()


if __name__ == "__main__":
    main()
