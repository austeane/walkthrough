#!/usr/bin/env python3
"""Normalize Codex CLI rollout JSONL into the common event model.

Usage:
    python scripts/normalize_codex.py --input rollout.jsonl --output normalized.jsonl
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path


def make_event(*, seq, source_line, source_path, session_id, ts, kind,
               turn_index, **extra):
    """Build a normalized event dict, omitting None/empty values."""
    evt = {
        "seq": seq,
        "source_line": source_line,
        "source_path": str(source_path),
        "provider": "codex",
        "session_id": session_id,
        "ts": ts,
        "kind": kind,
        "turn_index": turn_index,
    }
    for k, v in extra.items():
        if v is not None:
            evt[k] = v
    return evt


def extract_text_from_content(content):
    """Extract text from a Codex content array."""
    parts = []
    if not isinstance(content, list):
        return ""
    for item in content:
        if isinstance(item, dict):
            text = item.get("output_text") or item.get("input_text") or item.get("text", "")
            if isinstance(text, str) and text.strip():
                parts.append(text)
    return "\n".join(parts)


def parse_jsonish(value):
    """Parse JSON string values when possible, otherwise return input unchanged."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
    return value


def coerce_int(value):
    """Best-effort integer coercion for exit codes."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and (stripped.isdigit() or (stripped[0] in "+-" and stripped[1:].isdigit())):
            try:
                return int(stripped)
            except ValueError:
                return None
    return None


def _normalize_git_info(raw):
    """Normalize git metadata from session_meta payloads."""
    if not isinstance(raw, dict):
        return {}
    git_info = {}
    branch = raw.get("branch")
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


def _has_visible_user_payload(payload):
    """Return True when a payload should advance the conversation turn."""
    if not isinstance(payload, dict):
        return False
    ptype = payload.get("type", "")
    if ptype == "message" and payload.get("role") == "user":
        return bool(extract_text_from_content(payload.get("content", [])).strip())
    if ptype == "user_message":
        return bool(str(payload.get("message", "")).strip())
    return False


def process_response_item(payload, ts, seq, source_line, source_path,
                          session_id, turn_index):
    """Process a response_item record, returning a list of events."""
    events = []
    ptype = payload.get("type", "")
    role = payload.get("role", "")

    if ptype == "message":
        if role == "developer":
            # Skip system/developer prompts
            return events

        if role == "user":
            text = extract_text_from_content(payload.get("content", []))
            if text:
                events.append(make_event(
                    seq=seq, source_line=source_line,
                    source_path=source_path, session_id=session_id,
                    ts=ts, kind="user_message", turn_index=turn_index,
                    text=text,
                ))

        elif role == "assistant":
            text = extract_text_from_content(payload.get("content", []))
            if text:
                events.append(make_event(
                    seq=seq, source_line=source_line,
                    source_path=source_path, session_id=session_id,
                    ts=ts, kind="assistant_message", turn_index=turn_index,
                    text=text,
                ))

    elif ptype in ("function_call", "custom_tool_call"):
        name = payload.get("name", "")
        call_id = payload.get("call_id", "")
        arguments = payload.get("arguments") or payload.get("input", "")
        parsed_args = parse_jsonish(arguments)

        tool_info = {"name": name, "call_id": call_id, "input": parsed_args}
        events.append(make_event(
            seq=seq, source_line=source_line,
            source_path=source_path, session_id=session_id,
            ts=ts, kind="tool_use", turn_index=turn_index,
            tool=tool_info,
        ))

        if ptype == "custom_tool_call" and isinstance(parsed_args, dict):
            normalized_name = str(name).strip()
            normalized_name_lower = normalized_name.lower()

            if normalized_name == "fileChange" or normalized_name_lower == "filechange":
                path = parsed_args.get("path") or parsed_args.get("file_path")
                change_kind = parsed_args.get("kind") or "modify"
                diff = parsed_args.get("diff")
                if path:
                    file_change = {"path": path, "kind": change_kind}
                    if diff:
                        file_change["diff"] = diff
                    events.append(make_event(
                        seq=seq, source_line=source_line,
                        source_path=source_path, session_id=session_id,
                        ts=ts, kind="file_change", turn_index=turn_index,
                        file_change=file_change,
                    ))

            elif normalized_name == "commandExecution" or normalized_name_lower == "commandexecution":
                cmd = parsed_args.get("command") or parsed_args.get("cmd")
                exit_code = coerce_int(
                    parsed_args.get("exitCode", parsed_args.get("exit_code"))
                )
                status = parsed_args.get("status")
                output_preview = parsed_args.get("output")
                if cmd or exit_code is not None or status:
                    command = {}
                    if cmd:
                        command["cmd"] = cmd
                    if exit_code is not None:
                        command["exit_code"] = exit_code
                    if status:
                        command["status"] = status
                    if isinstance(output_preview, str) and output_preview:
                        command["output_preview"] = output_preview[:500]
                    events.append(make_event(
                        seq=seq, source_line=source_line,
                        source_path=source_path, session_id=session_id,
                        ts=ts, kind="command", turn_index=turn_index,
                        command=command,
                    ))

    elif ptype in ("function_call_output", "custom_tool_call_output"):
        call_id = payload.get("call_id", "")
        output = payload.get("output", "")
        tool_info = {"call_id": call_id, "output": output}
        events.append(make_event(
            seq=seq, source_line=source_line,
            source_path=source_path, session_id=session_id,
            ts=ts, kind="tool_result", turn_index=turn_index,
            tool=tool_info,
        ))

        if ptype == "custom_tool_call_output":
            parsed_output = parse_jsonish(output)
            if isinstance(parsed_output, dict):
                cmd = parsed_output.get("command") or parsed_output.get("cmd")
                exit_code = coerce_int(
                    parsed_output.get("exitCode", parsed_output.get("exit_code"))
                )
                status = parsed_output.get("status")
                output_preview = parsed_output.get("output")
                if cmd or exit_code is not None or status:
                    command = {}
                    if cmd:
                        command["cmd"] = cmd
                    if exit_code is not None:
                        command["exit_code"] = exit_code
                    if status:
                        command["status"] = status
                    if isinstance(output_preview, str) and output_preview:
                        command["output_preview"] = output_preview[:500]
                    events.append(make_event(
                        seq=seq, source_line=source_line,
                        source_path=source_path, session_id=session_id,
                        ts=ts, kind="command", turn_index=turn_index,
                        command=command,
                    ))

        # Check for screenshot file paths in output
        if isinstance(output, str):
            for match in re.finditer(r'(/\S+\.(?:png|jpg|jpeg|gif|webp))', output):
                file_path = match.group(1)
                media_info = {
                    "file_path": file_path,
                    "mime_type": "image/png",
                    "context": f"tool output for {call_id}",
                    "source": "file",
                }
                if os.path.isfile(file_path):
                    media_info["file_exists"] = True
                events.append(make_event(
                    seq=seq, source_line=source_line,
                    source_path=source_path, session_id=session_id,
                    ts=ts, kind="screenshot", turn_index=turn_index,
                    media=media_info,
                ))

    elif ptype == "reasoning":
        summary_parts = []
        for item in (payload.get("summary") or []):
            if isinstance(item, dict):
                t = item.get("text", "")
                if t:
                    summary_parts.append(t)
        # Skip if only encrypted content with no summary
        if summary_parts:
            events.append(make_event(
                seq=seq, source_line=source_line,
                source_path=source_path, session_id=session_id,
                ts=ts, kind="reasoning", turn_index=turn_index,
                text="\n".join(summary_parts),
            ))

    elif ptype == "ghost_snapshot":
        # Git snapshot info — skip for now (low signal for walkthrough)
        pass

    return events


def process_event_msg(payload, ts, seq, source_line, source_path,
                      session_id, turn_index):
    """Process an event_msg record."""
    events = []
    ptype = payload.get("type", "")

    if ptype == "user_message":
        text = payload.get("message", "")
        if text:
            events.append(make_event(
                seq=seq, source_line=source_line,
                source_path=source_path, session_id=session_id,
                ts=ts, kind="user_message", turn_index=turn_index,
                text=text,
            ))

    elif ptype == "agent_message":
        text = payload.get("message", "")
        if text:
            events.append(make_event(
                seq=seq, source_line=source_line,
                source_path=source_path, session_id=session_id,
                ts=ts, kind="assistant_message", turn_index=turn_index,
                text=text,
            ))

    elif ptype == "agent_reasoning":
        text = payload.get("text", "")
        if text:
            events.append(make_event(
                seq=seq, source_line=source_line,
                source_path=source_path, session_id=session_id,
                ts=ts, kind="reasoning", turn_index=turn_index,
                text=text,
            ))

    elif ptype == "agent_plan" or ptype == "turn/plan/updated":
        text = payload.get("plan") or payload.get("text") or payload.get("message", "")
        if isinstance(text, list):
            text = "\n".join(str(item) for item in text)
        elif isinstance(text, dict):
            text = json.dumps(text)
        if text:
            events.append(make_event(
                seq=seq, source_line=source_line,
                source_path=source_path, session_id=session_id,
                ts=ts, kind="plan_update", turn_index=turn_index,
                text=text,
            ))

    elif ptype == "turn/diff/updated":
        diff = payload.get("diff") or payload.get("text") or payload.get("message", "")
        if isinstance(diff, dict):
            diff = json.dumps(diff)
        if diff:
            events.append(make_event(
                seq=seq, source_line=source_line,
                source_path=source_path, session_id=session_id,
                ts=ts, kind="aggregate_diff", turn_index=turn_index,
                text=diff,
            ))

    # Skip: token_count, task_started, task_complete, turn_aborted
    return events


def normalize_codex(input_path, output_path):
    """Read a Codex rollout JSONL and write normalized events."""
    input_path = str(Path(input_path).expanduser())
    source_path = str(Path(input_path).resolve())
    session_id = ""
    turn_index = 0
    seq = 0
    events = []

    with open(input_path, "r") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = record.get("timestamp", "")
            rtype = record.get("type", "")
            payload = record.get("payload", {})

            if rtype == "session_meta":
                session_id = payload.get("id") or payload.get("session_id", "")
                meta_info = {
                    "cwd": payload.get("cwd"),
                    "model": payload.get("model_provider") or payload.get("model"),
                }
                cli_version = payload.get("cli_version")
                if cli_version:
                    meta_info["cli_version"] = cli_version
                source = payload.get("source")
                if source:
                    meta_info["source"] = source
                git_info = _normalize_git_info(payload.get("git"))
                if git_info:
                    meta_info["git"] = git_info

                seq += 1
                events.append(make_event(
                    seq=seq, source_line=line_no,
                    source_path=source_path, session_id=session_id,
                    ts=ts, kind="meta", turn_index=turn_index,
                    meta=meta_info,
                ))

            elif rtype == "response_item":
                if _has_visible_user_payload(payload):
                    turn_index += 1

                for evt in process_response_item(
                    payload, ts, seq + 1, line_no, source_path,
                    session_id, turn_index
                ):
                    seq += 1
                    evt["seq"] = seq
                    events.append(evt)

            elif rtype == "event_msg":
                if _has_visible_user_payload(payload):
                    turn_index += 1

                for evt in process_event_msg(
                    payload, ts, seq + 1, line_no, source_path,
                    session_id, turn_index
                ):
                    seq += 1
                    evt["seq"] = seq
                    events.append(evt)

            elif rtype == "turn_context":
                seq += 1
                extra = {}
                model = payload.get("model")
                if model:
                    extra["meta"] = {"model": model}
                cwd = payload.get("cwd")
                if cwd:
                    extra.setdefault("meta", {})["cwd"] = cwd
                events.append(make_event(
                    seq=seq, source_line=line_no,
                    source_path=source_path, session_id=session_id,
                    ts=ts, kind="turn_context", turn_index=turn_index,
                    **extra,
                ))

            elif rtype == "turn/diff/updated":
                diff = payload.get("diff") or payload.get("text", "")
                if isinstance(diff, dict):
                    diff = json.dumps(diff)
                if diff:
                    seq += 1
                    events.append(make_event(
                        seq=seq, source_line=line_no,
                        source_path=source_path, session_id=session_id,
                        ts=ts, kind="aggregate_diff", turn_index=turn_index,
                        text=diff,
                    ))

            elif rtype == "turn/plan/updated":
                plan = payload.get("plan") or payload.get("text", "")
                if isinstance(plan, list):
                    plan = "\n".join(str(item) for item in plan)
                elif isinstance(plan, dict):
                    plan = json.dumps(plan)
                if plan:
                    seq += 1
                    events.append(make_event(
                        seq=seq, source_line=line_no,
                        source_path=source_path, session_id=session_id,
                        ts=ts, kind="plan_update", turn_index=turn_index,
                        text=plan,
                    ))

            elif rtype == "compacted":
                replacement_history = payload.get("replacement_history")
                replacement_count = (
                    len(replacement_history)
                    if isinstance(replacement_history, list)
                    else 0
                )
                text = payload.get("message") or ""
                if not str(text).strip():
                    text = (
                        f"Context compacted; replacement_history items: {replacement_count}"
                        if replacement_count
                        else "Context compacted"
                    )
                seq += 1
                events.append(make_event(
                    seq=seq, source_line=line_no,
                    source_path=source_path, session_id=session_id,
                    ts=ts, kind="compaction", turn_index=turn_index,
                    text=text,
                ))

    # Write output
    out = sys.stdout if output_path == "-" else open(output_path, "w")
    try:
        for evt in events:
            out.write(json.dumps(evt, ensure_ascii=False) + "\n")
    finally:
        if out is not sys.stdout:
            out.close()

    print(f"Wrote {len(events)} events to {output_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Normalize Codex CLI rollout JSONL into common event model"
    )
    parser.add_argument("--input", required=True, help="Path to rollout JSONL file")
    parser.add_argument("--output", required=True, help="Output normalized JSONL (- for stdout)")
    args = parser.parse_args()

    normalize_codex(args.input, args.output)


if __name__ == "__main__":
    main()
