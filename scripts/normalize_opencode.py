#!/usr/bin/env python3
"""Normalize OpenCode export JSONL into the common event model.

Usage:
    python scripts/export_opencode.py --session-id ses_123 --output session.jsonl
    python scripts/normalize_opencode.py --input session.jsonl --output normalized.jsonl
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse


def make_event(*, seq, source_line, source_path, session_id, ts, kind,
               turn_index, **extra):
    """Build a normalized event dict, omitting None values."""
    evt = {
        "seq": seq,
        "source_line": source_line,
        "source_path": str(source_path),
        "provider": "opencode",
        "session_id": session_id,
        "ts": ts,
        "kind": kind,
        "turn_index": turn_index,
    }
    for k, v in extra.items():
        if v is not None:
            evt[k] = v
    return evt


def epoch_ms_to_iso(value) -> str:
    """Convert milliseconds since epoch into an ISO8601 UTC timestamp."""
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


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


def make_synthetic_diff(before: str, after: str, file_path: str) -> str:
    """Create a synthetic unified diff from before/after text."""
    before = before or ""
    after = after or ""
    old_lines = before.splitlines(keepends=True)
    new_lines = after.splitlines(keepends=True)

    diff_lines = [
        f"--- a/{file_path}",
        f"+++ b/{file_path}",
        f"@@ -1,{len(old_lines)} +1,{len(new_lines)} @@",
    ]
    for line in old_lines:
        diff_lines.append("-" + line.rstrip("\n"))
    for line in new_lines:
        diff_lines.append("+" + line.rstrip("\n"))
    return "\n".join(diff_lines)


def nonempty_text_parts(parts: list[dict]) -> list[dict]:
    """Return visible text parts with non-empty content."""
    result = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("type") != "text":
            continue
        if part.get("ignored"):
            continue
        text = str(part.get("text", "")).strip()
        if text:
            result.append(part)
    return result


def build_model_string(message_info: dict) -> str:
    """Extract a provider/model string from a message info object."""
    if message_info.get("role") == "assistant":
        provider = message_info.get("providerID")
        model = message_info.get("modelID")
        if provider and model:
            return f"{provider}/{model}"
        return model or provider or ""

    model_info = message_info.get("model")
    if isinstance(model_info, dict):
        provider = model_info.get("providerID")
        model = model_info.get("modelID")
        if provider and model:
            return f"{provider}/{model}"
        return model or provider or ""
    return ""


def build_meta(session_info: dict, messages: list[dict]) -> dict:
    """Build the normalized meta payload."""
    meta = {}

    cwd = session_info.get("directory")
    if cwd:
        meta["cwd"] = cwd

    version = session_info.get("version")
    if version:
        meta["cli_version"] = version

    title = session_info.get("title")
    if title:
        meta["title"] = title

    parent_id = session_info.get("parentID")
    if parent_id:
        meta["parent_session_id"] = parent_id

    for message in messages:
        info = message.get("info", {})
        model = build_model_string(info)
        if model:
            meta["model"] = model
            break

    return meta


def extract_attachment_screenshot(attachment: dict, *, tool_name: str, context: str) -> dict | None:
    """Convert an image attachment into a normalized media payload."""
    mime = str(attachment.get("mime", "") or "")
    if not mime.startswith("image/"):
        return None

    media = {
        "mime_type": mime,
        "context": context,
        "tool_name": tool_name,
        "source": "session",
    }

    url = str(attachment.get("url", "") or "")
    if url.startswith("data:") and ";base64," in url:
        _, data_b64 = url.split(",", 1)
        if data_b64 and not data_b64.startswith("[BASE64:"):
            media["data_b64"] = data_b64
            return media

    if url.startswith("file://"):
        parsed = urlparse(url)
        media["file_path"] = unquote(parsed.path)
        media["source"] = "file"
        return media

    if url.startswith("/"):
        media["file_path"] = url
        media["source"] = "file"
        return media

    return None


def build_command_from_tool(part: dict) -> dict | None:
    """Extract a normalized command payload from an OpenCode bash tool part."""
    if str(part.get("tool", "")).lower() != "bash":
        return None

    state = part.get("state", {})
    if not isinstance(state, dict):
        return None

    tool_input = state.get("input", {})
    if not isinstance(tool_input, dict):
        return None

    cmd = tool_input.get("command") or tool_input.get("cmd")
    if not cmd:
        return None

    command = {"cmd": cmd}
    metadata = state.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    exit_code = coerce_int(metadata.get("exit"))
    if exit_code is not None:
        command["exit_code"] = exit_code
        command["status"] = "pass" if exit_code == 0 else "fail"
    elif state.get("status") == "completed":
        command["status"] = "pass"
    elif state.get("status") == "error":
        command["status"] = "fail"

    output_text = (
        state.get("output")
        if isinstance(state.get("output"), str)
        else state.get("error") if isinstance(state.get("error"), str)
        else metadata.get("output") if isinstance(metadata.get("output"), str)
        else ""
    )
    if output_text:
        command["output_preview"] = output_text[:500]
        command["output_lines"] = len(output_text.splitlines()) or 1

    return command


def diff_kind(diff: dict) -> str:
    """Map an OpenCode diff entry to create/modify/delete."""
    status = diff.get("status")
    if status == "added":
        return "create"
    if status == "deleted":
        return "delete"
    if status == "modified":
        return "modify"
    before = diff.get("before", "")
    after = diff.get("after", "")
    if before and not after:
        return "delete"
    if after and not before:
        return "create"
    return "modify"


def load_export(input_path: str) -> tuple[dict, list[dict]]:
    """Load the OpenCode JSONL intermediary."""
    session_info = {}
    messages = []

    with open(input_path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            rtype = record.get("type")
            if rtype == "session" and isinstance(record.get("info"), dict):
                session_info = record["info"]
            elif rtype == "message" and isinstance(record.get("info"), dict):
                messages.append({
                    "info": record["info"],
                    "parts": record.get("parts", []) if isinstance(record.get("parts"), list) else [],
                    "_source_line": line_no,
                })

    return session_info, messages


def normalize_opencode(input_path: str, output_path: str):
    """Normalize a single OpenCode export JSONL file."""
    session_info, messages = load_export(input_path)
    source_path = Path(input_path).resolve()

    session_id = session_info.get("id") or next(
        (m.get("info", {}).get("sessionID", "") for m in messages if m.get("info", {}).get("sessionID")),
        "",
    )

    pending_diffs: dict[str, dict] = {}
    events = []
    seq = 0
    turn_index = 0

    meta_ts = epoch_ms_to_iso(session_info.get("time", {}).get("created"))
    if not meta_ts:
        meta_ts = next(
            (
                ts
                for m in messages
                if (ts := epoch_ms_to_iso(m.get("info", {}).get("time", {}).get("created")))
            ),
            "",
        )
    seq += 1
    events.append(make_event(
        seq=seq,
        source_line=1,
        source_path=source_path,
        session_id=session_id,
        ts=meta_ts,
        kind="meta",
        turn_index=0,
        meta=build_meta(session_info, messages),
    ))

    for message in messages:
        info = message.get("info", {})
        parts = message.get("parts", [])
        source_line = message.get("_source_line", 0)
        role = info.get("role")

        message_ts = epoch_ms_to_iso(info.get("time", {}).get("created")) or meta_ts

        if role == "user":
            visible_parts = nonempty_text_parts(parts)
            if visible_parts:
                turn_index += 1

            summary = info.get("summary", {})
            if isinstance(summary, dict) and isinstance(summary.get("diffs"), list) and summary["diffs"]:
                pending_diffs[info.get("id", "")] = {
                    "diffs": summary["diffs"],
                    "ts": message_ts,
                    "turn_index": turn_index,
                    "source_line": source_line,
                }

            for part in visible_parts:
                part_ts = epoch_ms_to_iso(part.get("time", {}).get("start")) or message_ts
                seq += 1
                events.append(make_event(
                    seq=seq,
                    source_line=source_line,
                    source_path=source_path,
                    session_id=session_id,
                    ts=part_ts,
                    kind="user_message",
                    turn_index=turn_index,
                    text=part.get("text", ""),
                ))

            continue

        current_turn = turn_index
        parent_diffs = pending_diffs.pop(info.get("parentID", ""), None)
        use_patch_parts = parent_diffs is None

        for part in parts:
            if not isinstance(part, dict):
                continue

            part_type = part.get("type")

            if part_type == "text":
                if part.get("ignored"):
                    continue
                text = str(part.get("text", "")).strip()
                if not text:
                    continue
                part_ts = epoch_ms_to_iso(part.get("time", {}).get("start")) or message_ts
                seq += 1
                events.append(make_event(
                    seq=seq,
                    source_line=source_line,
                    source_path=source_path,
                    session_id=session_id,
                    ts=part_ts,
                    kind="assistant_message",
                    turn_index=current_turn,
                    text=part.get("text", ""),
                ))

            elif part_type == "reasoning":
                text = str(part.get("text", "")).strip()
                if not text:
                    continue
                part_ts = epoch_ms_to_iso(part.get("time", {}).get("start")) or message_ts
                seq += 1
                events.append(make_event(
                    seq=seq,
                    source_line=source_line,
                    source_path=source_path,
                    session_id=session_id,
                    ts=part_ts,
                    kind="reasoning",
                    turn_index=current_turn,
                    text=part.get("text", ""),
                ))

            elif part_type == "tool":
                state = part.get("state", {})
                if not isinstance(state, dict):
                    state = {}

                start_ts = epoch_ms_to_iso(state.get("time", {}).get("start")) or message_ts
                seq += 1
                events.append(make_event(
                    seq=seq,
                    source_line=source_line,
                    source_path=source_path,
                    session_id=session_id,
                    ts=start_ts,
                    kind="tool_use",
                    turn_index=current_turn,
                    tool={
                        "name": part.get("tool", ""),
                        "call_id": part.get("callID", ""),
                        "input": state.get("input", {}) if isinstance(state.get("input"), dict) else {},
                    },
                ))

                command = build_command_from_tool(part)
                if command:
                    seq += 1
                    events.append(make_event(
                        seq=seq,
                        source_line=source_line,
                        source_path=source_path,
                        session_id=session_id,
                        ts=epoch_ms_to_iso(state.get("time", {}).get("end")) or start_ts,
                        kind="command",
                        turn_index=current_turn,
                        command=command,
                    ))

                if state.get("status") == "completed":
                    end_ts = epoch_ms_to_iso(state.get("time", {}).get("end")) or start_ts
                    seq += 1
                    events.append(make_event(
                        seq=seq,
                        source_line=source_line,
                        source_path=source_path,
                        session_id=session_id,
                        ts=end_ts,
                        kind="tool_result",
                        turn_index=current_turn,
                        tool={
                            "call_id": part.get("callID", ""),
                            "output": state.get("output", ""),
                        },
                    ))

                    attachments = state.get("attachments", [])
                    if isinstance(attachments, list):
                        for attachment in attachments:
                            if not isinstance(attachment, dict):
                                continue
                            media = extract_attachment_screenshot(
                                attachment,
                                tool_name=part.get("tool", ""),
                                context=f"tool result for {part.get('callID', '')}",
                            )
                            if not media:
                                continue
                            seq += 1
                            events.append(make_event(
                                seq=seq,
                                source_line=source_line,
                                source_path=source_path,
                                session_id=session_id,
                                ts=end_ts,
                                kind="screenshot",
                                turn_index=current_turn,
                                media=media,
                            ))

                elif state.get("status") == "error":
                    end_ts = epoch_ms_to_iso(state.get("time", {}).get("end")) or start_ts
                    seq += 1
                    events.append(make_event(
                        seq=seq,
                        source_line=source_line,
                        source_path=source_path,
                        session_id=session_id,
                        ts=end_ts,
                        kind="tool_result",
                        turn_index=current_turn,
                        tool={
                            "call_id": part.get("callID", ""),
                            "output": state.get("error", ""),
                            "is_error": True,
                        },
                    ))

            elif part_type == "patch" and use_patch_parts:
                for file_path in part.get("files", []) or []:
                    seq += 1
                    events.append(make_event(
                        seq=seq,
                        source_line=source_line,
                        source_path=source_path,
                        session_id=session_id,
                        ts=message_ts,
                        kind="file_change",
                        turn_index=current_turn,
                        file_change={
                            "path": file_path,
                            "kind": "modify",
                        },
                    ))

            elif part_type == "compaction":
                text = "Context compacted"
                if part.get("auto"):
                    text += " automatically"
                if part.get("overflow"):
                    text += " after overflow"
                seq += 1
                events.append(make_event(
                    seq=seq,
                    source_line=source_line,
                    source_path=source_path,
                    session_id=session_id,
                    ts=message_ts,
                    kind="compaction",
                    turn_index=current_turn,
                    text=text,
                ))

            elif part_type == "retry":
                error = part.get("error", {})
                if isinstance(error, dict):
                    err_text = error.get("data", {}).get("message") or error.get("message") or ""
                else:
                    err_text = str(error)
                seq += 1
                events.append(make_event(
                    seq=seq,
                    source_line=source_line,
                    source_path=source_path,
                    session_id=session_id,
                    ts=epoch_ms_to_iso(part.get("time", {}).get("created")) or message_ts,
                    kind="system",
                    turn_index=current_turn,
                    text=f"Retry attempt {part.get('attempt', 0)}: {err_text}".strip(),
                ))

        error = info.get("error")
        if isinstance(error, dict):
            error_text = error.get("data", {}).get("message") or error.get("message") or ""
            if error_text:
                seq += 1
                events.append(make_event(
                    seq=seq,
                    source_line=source_line,
                    source_path=source_path,
                    session_id=session_id,
                    ts=epoch_ms_to_iso(info.get("time", {}).get("completed")) or message_ts,
                    kind="system",
                    turn_index=current_turn,
                    text=f"Assistant error: {error_text}",
                ))

        if parent_diffs:
            for diff in parent_diffs["diffs"]:
                if not isinstance(diff, dict):
                    continue
                file_path = diff.get("file")
                if not file_path:
                    continue
                before = diff.get("before", "")
                after = diff.get("after", "")
                seq += 1
                events.append(make_event(
                    seq=seq,
                    source_line=source_line,
                    source_path=source_path,
                    session_id=session_id,
                    ts=epoch_ms_to_iso(info.get("time", {}).get("completed")) or message_ts,
                    kind="file_change",
                    turn_index=current_turn,
                    file_change={
                        "path": file_path,
                        "kind": diff_kind(diff),
                        "diff": make_synthetic_diff(before, after, file_path),
                    },
                ))

    for pending in pending_diffs.values():
        for diff in pending["diffs"]:
            if not isinstance(diff, dict):
                continue
            file_path = diff.get("file")
            if not file_path:
                continue
            seq += 1
            events.append(make_event(
                seq=seq,
                source_line=pending["source_line"],
                source_path=source_path,
                session_id=session_id,
                ts=pending["ts"],
                kind="file_change",
                turn_index=pending["turn_index"],
                file_change={
                    "path": file_path,
                    "kind": diff_kind(diff),
                    "diff": make_synthetic_diff(diff.get("before", ""), diff.get("after", ""), file_path),
                },
            ))

    with open(output_path, "w", encoding="utf-8") as f:
        for evt in events:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Normalize OpenCode export JSONL into the common event model"
    )
    parser.add_argument("--input", required=True, help="Input OpenCode export JSONL")
    parser.add_argument("--output", required=True, help="Output normalized JSONL")
    args = parser.parse_args()

    normalize_opencode(args.input, args.output)


if __name__ == "__main__":
    main()
