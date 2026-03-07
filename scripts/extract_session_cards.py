#!/usr/bin/env python3
"""Extract a ~2KB session card from a normalized session JSONL file.

Produces a deterministic summary card per session — no LLM calls.
Intended for giving an LLM a quick overview of all sessions in one pass.

Usage:
    python3 scripts/extract_session_cards.py \
      --input session-0001-claude-normalized.jsonl \
      --output card.json
"""

import argparse
import json
import sys
from collections import defaultdict


def first_sentence(text: str) -> str:
    """Extract the first sentence from text."""
    text = text.strip()
    if not text:
        return ""
    for end in (".", "!", "?"):
        idx = text.find(end)
        if idx != -1:
            return text[: idx + 1]
    # No sentence-ending punctuation — return first 120 chars
    return text[:120] + ("..." if len(text) > 120 else "")


def extract_card(input_path: str) -> dict:
    """Single-pass scan of normalized JSONL to build a session card."""
    session_id = ""
    provider = ""
    model = ""
    ts_start = None
    ts_end = None
    event_count = 0
    subagents: set[str] = set()

    # file_path -> {kinds: set, turns: set}
    files: dict[str, dict] = defaultdict(lambda: {"kinds": set(), "turns": set()})
    commands: list[dict] = []
    errors: list[str] = []
    user_intents: list[str] = []
    saw_user_message = False

    # Track max turn_index seen
    max_turn = 0

    with open(input_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_count += 1
            kind = obj.get("kind", "")
            ts = obj.get("ts", "")
            turn_index = obj.get("turn_index", 0)

            # Track session metadata
            if not session_id:
                session_id = obj.get("session_id", "")
            if not provider:
                provider = obj.get("provider", "")

            # Track time range
            if ts:
                if ts_start is None or ts < ts_start:
                    ts_start = ts
                if ts_end is None or ts > ts_end:
                    ts_end = ts

            # Track max turn
            if turn_index > max_turn:
                max_turn = turn_index

            # Track subagents
            agent_id = obj.get("agent_id")
            if agent_id:
                subagents.add(agent_id)

            # Extract model from meta events
            if kind == "meta":
                meta = obj.get("meta", {})
                m = meta.get("model", "")
                if m and not model:
                    model = m

            # User intents = first sentence of each user_message
            elif kind == "user_message":
                saw_user_message = True
                text = obj.get("text", "")
                if text:
                    intent = first_sentence(text)
                    if intent and intent not in user_intents:
                        user_intents.append(intent)

            # Files touched from file_change events
            elif kind == "file_change":
                fc = obj.get("file_change", {})
                path = fc.get("path", "")
                change_kind = fc.get("kind", "modify")
                if path:
                    files[path]["kinds"].add(change_kind)
                    files[path]["turns"].add(turn_index)

            # Commands from command events
            elif kind == "command":
                cmd_info = obj.get("command", {})
                cmd = cmd_info.get("cmd", "")
                exit_code = cmd_info.get("exit_code")
                if cmd:
                    commands.append({
                        "cmd": cmd[:200],
                        "exit_code": exit_code,
                        "turn": turn_index,
                    })
                    # Collect errors from failed commands
                    if exit_code is not None and exit_code != 0:
                        errors.append(f"Command failed (exit {exit_code}): {cmd[:120]}")

            # Errors from error tool_results
            elif kind == "tool_result":
                tool = obj.get("tool", {})
                if tool.get("is_error"):
                    output = tool.get("output", "")
                    if output:
                        # First meaningful line of error
                        for err_line in output.splitlines():
                            err_line = err_line.strip()
                            if err_line:
                                errors.append(err_line[:200])
                                break

    # Build files_touched list
    files_touched = []
    for path, info in sorted(files.items()):
        files_touched.append({
            "path": path,
            "kinds": sorted(info["kinds"]),
            "turns": sorted(info["turns"]),
        })

    # Deduplicate and cap errors
    seen_errors: set[str] = set()
    unique_errors: list[str] = []
    for e in errors:
        if e not in seen_errors:
            seen_errors.add(e)
            unique_errors.append(e)
    errors = unique_errors[:20]

    turns = max_turn if max_turn > 0 else (1 if saw_user_message else 0)

    card = {
        "session_id": session_id,
        "provider": provider,
        "model": model,
        "ts_start": ts_start,
        "ts_end": ts_end,
        "turns": turns,
        "events": event_count,
        "subagents": sorted(subagents),
        "files_touched": files_touched[:50],
        "commands_run": commands[:30],
        "errors": errors,
        "user_intents": user_intents[:20],
        "source_path": input_path,
    }

    return card


def main():
    parser = argparse.ArgumentParser(
        description="Extract a session card from a normalized session JSONL file"
    )
    parser.add_argument("--input", required=True, help="Path to normalized session JSONL")
    parser.add_argument("--output", required=True, help="Output card JSON (- for stdout)")
    args = parser.parse_args()

    card = extract_card(args.input)

    out = sys.stdout if args.output == "-" else open(args.output, "w")
    try:
        json.dump(card, out, indent=2, ensure_ascii=False)
        out.write("\n")
    finally:
        if out is not sys.stdout:
            out.close()

    print(
        f"Card: {card['provider']}/{card['session_id'][:8]}... "
        f"{card['events']} events, {card['turns']} turns, "
        f"{len(card['files_touched'])} files, {len(card['commands_run'])} commands",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
