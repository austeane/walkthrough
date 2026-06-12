#!/usr/bin/env python3
"""Normalize Claude Code session JSONL into the common event model.

Usage:
    python scripts/normalize_claude.py --input session.jsonl --output normalized.jsonl
    python scripts/normalize_claude.py --input session.jsonl --subagents path1.jsonl,path2.jsonl --output normalized.jsonl
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path


def make_event(*, seq, source_line, source_path, session_id, ts, kind,
               turn_index, **extra):
    """Build a normalized event dict, omitting None/empty values."""
    evt = {
        "seq": seq,
        "source_line": source_line,
        "source_path": str(source_path),
        "provider": "claude",
        "session_id": session_id,
        "ts": ts,
        "kind": kind,
        "turn_index": turn_index,
    }
    for k, v in extra.items():
        if v is not None:
            evt[k] = v
    return evt


def make_synthetic_diff(old_string, new_string, file_path):
    """Create a synthetic unified diff from old_string/new_string."""
    old_lines = old_string.splitlines(keepends=True)
    new_lines = new_string.splitlines(keepends=True)

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


def _extract_record_session_id(record: dict) -> str:
    return record.get("sessionId") or record.get("session_id") or ""


def _has_nonempty_user_text(content) -> bool:
    if isinstance(content, str):
        return bool(content.strip())
    if not isinstance(content, list):
        return False
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "text":
            continue
        if str(item.get("text", "")).strip():
            return True
    return False


def _meta_updates_from_record(record: dict, model: str = "") -> dict:
    meta = {}
    cwd = record.get("cwd")
    if cwd:
        meta["cwd"] = cwd
    version = record.get("version")
    if version:
        meta["cli_version"] = version
    if model:
        meta["model"] = model
    git_branch = record.get("gitBranch")
    if git_branch:
        meta.setdefault("git", {})["branch"] = git_branch
    return meta


def _attach_agent_metadata(events, agent_id=None, parent_call_id=None,
                           root_turn_index=None, parent_link_status=None,
                           parent_link_basis=None):
    if not agent_id:
        return
    for evt in events:
        evt["agent_id"] = agent_id
        if parent_call_id:
            evt["parent_call_id"] = parent_call_id
        if root_turn_index is not None:
            evt["root_turn_index"] = root_turn_index
        if parent_link_status:
            evt["parent_link_status"] = parent_link_status
        if parent_link_basis:
            evt["parent_link_basis"] = parent_link_basis


def _agent_id_from_path(path: str) -> str:
    """Extract the agent id from agent-{id}.jsonl without stripping inner substrings."""
    stem = Path(path).stem
    return stem[len("agent-"):] if stem.startswith("agent-") else stem


def _session_id_from_path(path: str) -> str:
    """Extract a session id from a session JSONL path when available."""
    stem = Path(path).stem
    return stem if stem and not stem.startswith("agent-") else ""


def process_user_record(record, source_path, session_id, turn_index, seq):
    """Process a Claude Code 'user' type record."""
    events = []
    ts = record.get("timestamp", "")
    line_no = record.get("_source_line", 0)
    message = record.get("message", {})
    content = message.get("content", [])

    # content can be a string (rare) or a list
    if isinstance(content, str):
        if content.strip():
            seq += 1
            events.append(make_event(
                seq=seq, source_line=line_no, source_path=source_path,
                session_id=session_id, ts=ts, kind="user_message",
                turn_index=turn_index, text=content,
            ))
        return events, seq

    for item in content:
        if not isinstance(item, dict):
            continue

        item_type = item.get("type", "")

        if item_type == "text":
            text = item.get("text", "")
            if str(text).strip():
                seq += 1
                events.append(make_event(
                    seq=seq, source_line=line_no, source_path=source_path,
                    session_id=session_id, ts=ts, kind="user_message",
                    turn_index=turn_index, text=text,
                ))

        elif item_type == "tool_result":
            tool_use_id = item.get("tool_use_id", "")
            # tool_result content can be a string or list of content blocks
            result_content = item.get("content", "")
            if isinstance(result_content, list):
                parts = []
                for rc in result_content:
                    if isinstance(rc, dict) and rc.get("type") == "image":
                        source_info = rc.get("source", {})
                        image_data = source_info.get("data", "")
                        if image_data and not image_data.startswith("[BASE64:"):
                            seq += 1
                            events.append(make_event(
                                seq=seq, source_line=line_no, source_path=source_path,
                                session_id=session_id, ts=ts, kind="screenshot",
                                turn_index=turn_index,
                                media={
                                    "data_b64": image_data,
                                    "mime_type": source_info.get("media_type", "image/png"),
                                    "context": f"tool_result for {tool_use_id}",
                                    "tool_name": "computer",
                                    "source": "session",
                                },
                            ))
                        continue  # Don't add image blocks to text parts
                    if isinstance(rc, dict):
                        parts.append(rc.get("text", ""))
                    elif isinstance(rc, str):
                        parts.append(rc)
                result_text = "\n".join(p for p in parts if p)
            else:
                result_text = str(result_content)

            is_error = item.get("is_error", False)
            seq += 1
            tool_info = {
                "call_id": tool_use_id,
                "output": result_text,
            }
            if is_error:
                tool_info["is_error"] = True
            events.append(make_event(
                seq=seq, source_line=line_no, source_path=source_path,
                session_id=session_id, ts=ts, kind="tool_result",
                turn_index=turn_index, tool=tool_info,
            ))

    return events, seq


def process_assistant_record(record, source_path, session_id, turn_index, seq):
    """Process a Claude Code 'assistant' type record."""
    events = []
    ts = record.get("timestamp", "")
    line_no = record.get("_source_line", 0)
    message = record.get("message", {})
    content = message.get("content", [])

    if not isinstance(content, list):
        return events, seq

    for item in content:
        if not isinstance(item, dict):
            continue

        item_type = item.get("type", "")

        if item_type == "text":
            text = item.get("text", "")
            if text.strip():
                seq += 1
                events.append(make_event(
                    seq=seq, source_line=line_no, source_path=source_path,
                    session_id=session_id, ts=ts, kind="assistant_message",
                    turn_index=turn_index, text=text,
                ))

        elif item_type == "tool_use":
            tool_id = item.get("id", "")
            tool_name = item.get("name", "")
            tool_input = item.get("input", {})

            seq += 1
            events.append(make_event(
                seq=seq, source_line=line_no, source_path=source_path,
                session_id=session_id, ts=ts, kind="tool_use",
                turn_index=turn_index,
                tool={"name": tool_name, "call_id": tool_id, "input": tool_input},
            ))

            # Emit synthetic file_change for Edit/Write tool calls
            if tool_name == "Edit" and isinstance(tool_input, dict):
                file_path = tool_input.get("file_path", "")
                old_string = tool_input.get("old_string", "")
                new_string = tool_input.get("new_string", "")
                if file_path and (old_string or new_string):
                    diff = make_synthetic_diff(old_string, new_string, file_path)
                    seq += 1
                    events.append(make_event(
                        seq=seq, source_line=line_no, source_path=source_path,
                        session_id=session_id, ts=ts, kind="file_change",
                        turn_index=turn_index,
                        file_change={"path": file_path, "kind": "modify", "diff": diff},
                    ))

            elif tool_name == "Write" and isinstance(tool_input, dict):
                file_path = tool_input.get("file_path", "")
                if file_path:
                    seq += 1
                    events.append(make_event(
                        seq=seq, source_line=line_no, source_path=source_path,
                        session_id=session_id, ts=ts, kind="file_change",
                        turn_index=turn_index,
                        file_change={"path": file_path, "kind": "create"},
                    ))

            elif tool_name == "Bash" and isinstance(tool_input, dict):
                cmd = tool_input.get("command", "")
                if cmd:
                    seq += 1
                    events.append(make_event(
                        seq=seq, source_line=line_no, source_path=source_path,
                        session_id=session_id, ts=ts, kind="command",
                        turn_index=turn_index,
                        command={"cmd": cmd},
                    ))

        elif item_type == "thinking":
            # Skip internal thinking/reasoning blocks
            pass

    return events, seq


def normalize_stream(input_path, session_id_override=None, agent_id=None,
                     parent_call_id=None, root_turn_index=None,
                     parent_link_status=None, parent_link_basis=None,
                     expected_session_id=None):
    """Normalize a single JSONL stream (main or subagent).

    Returns (events, session_id).
    """
    input_path = str(Path(input_path).expanduser())
    source_path = str(Path(input_path).resolve())
    session_id = session_id_override or ""
    turn_index = 0
    seq = 0
    events = []
    meta_event = None
    last_ts = ""
    first_ts = ""
    seen_expected_session = expected_session_id is None

    def ensure_meta(line_no, ts, meta_updates):
        nonlocal seq, meta_event
        if not meta_updates:
            return
        if meta_event is None:
            seq += 1
            meta_event = make_event(
                seq=seq,
                source_line=line_no,
                source_path=source_path,
                session_id=session_id,
                ts=ts,
                kind="meta",
                turn_index=0,
                meta={},
            )
            _attach_agent_metadata(
                [meta_event],
                agent_id=agent_id,
                parent_call_id=parent_call_id,
                root_turn_index=root_turn_index,
                parent_link_status=parent_link_status,
                parent_link_basis=parent_link_basis,
            )
            events.insert(0, meta_event)
        meta_event.setdefault("meta", {}).update(meta_updates)

    with open(input_path, "r") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            record["_source_line"] = line_no
            rtype = record.get("type", "")
            explicit_session_id = _extract_record_session_id(record)
            if expected_session_id:
                if explicit_session_id and explicit_session_id != expected_session_id:
                    continue
                if not seen_expected_session:
                    if explicit_session_id != expected_session_id:
                        continue
                    seen_expected_session = True

            raw_ts = record.get("timestamp", "")
            if raw_ts:
                last_ts = raw_ts
                if not first_ts:
                    first_ts = raw_ts
            ts = raw_ts or last_ts

            if not session_id:
                session_id = session_id_override or expected_session_id or explicit_session_id

            if rtype == "user":
                message = record.get("message", {})
                content = message.get("content", [])
                if _has_nonempty_user_text(content):
                    turn_index += 1

                ensure_meta(line_no, ts, _meta_updates_from_record(record))
                new_events, seq = process_user_record(
                    record, source_path, session_id, turn_index, seq
                )
                _attach_agent_metadata(
                    new_events,
                    agent_id=agent_id,
                    parent_call_id=parent_call_id,
                    root_turn_index=root_turn_index,
                    parent_link_status=parent_link_status,
                    parent_link_basis=parent_link_basis,
                )
                events.extend(new_events)

            elif rtype == "assistant":
                message = record.get("message", {})
                model = message.get("model", "")
                ensure_meta(line_no, ts, _meta_updates_from_record(record, model=model))
                new_events, seq = process_assistant_record(
                    record, source_path, session_id, turn_index, seq
                )
                _attach_agent_metadata(
                    new_events,
                    agent_id=agent_id,
                    parent_call_id=parent_call_id,
                    root_turn_index=root_turn_index,
                    parent_link_status=parent_link_status,
                    parent_link_basis=parent_link_basis,
                )
                events.extend(new_events)

            elif rtype == "file-history-snapshot":
                ensure_meta(line_no, ts, _meta_updates_from_record(record))
                seq += 1
                snapshot = record.get("snapshot", {})
                tracked = snapshot.get("trackedFileBackups", {})
                evt = make_event(
                    seq=seq, source_line=line_no,
                    source_path=source_path, session_id=session_id,
                    ts=ts, kind="file_snapshot", turn_index=turn_index,
                    text=json.dumps({"files": list(tracked.keys())}) if tracked else None,
                )
                _attach_agent_metadata(
                    [evt],
                    agent_id=agent_id,
                    parent_call_id=parent_call_id,
                    root_turn_index=root_turn_index,
                    parent_link_status=parent_link_status,
                    parent_link_basis=parent_link_basis,
                )
                events.append(evt)

            elif rtype == "system":
                ensure_meta(line_no, ts, _meta_updates_from_record(record))
                subtype = record.get("subtype", "")
                seq += 1
                evt = make_event(
                    seq=seq, source_line=line_no,
                    source_path=source_path, session_id=session_id,
                    ts=ts, kind="system", turn_index=turn_index,
                    text=subtype,
                )
                _attach_agent_metadata(
                    [evt],
                    agent_id=agent_id,
                    parent_call_id=parent_call_id,
                    root_turn_index=root_turn_index,
                    parent_link_status=parent_link_status,
                    parent_link_basis=parent_link_basis,
                )
                events.append(evt)

            # Skip: progress, queue-operation

    if session_id:
        for evt in events:
            if not evt.get("session_id"):
                evt["session_id"] = session_id
    if first_ts:
        for evt in events:
            if not evt.get("ts"):
                evt["ts"] = first_ts

    # Keep the stream in transcript order, but make meta the first event if present.
    for i, evt in enumerate(events, 1):
        evt["seq"] = i

    return events, session_id


def _build_agent_calls(main_events):
    agent_calls = []
    by_call_id = {}
    for evt in main_events:
        if evt.get("kind") != "tool_use":
            continue
        tool = evt.get("tool", {})
        if tool.get("name") != "Agent":
            continue
        info = {
            "call_id": tool.get("call_id"),
            "turn_index": evt.get("turn_index"),
            "ts": evt.get("ts", ""),
        }
        agent_calls.append(info)
        if info["call_id"]:
            by_call_id[info["call_id"]] = info
    return agent_calls, by_call_id


def _extract_explicit_subagent_links(main_session_path, agent_calls_by_id):
    links = {}
    with open(main_session_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            data = record.get("data")
            if not isinstance(data, dict):
                continue
            agent_id = data.get("agentId")
            parent_call_id = data.get("parentToolUseID") or data.get("parentToolUseId")
            if not agent_id or not parent_call_id:
                continue
            if parent_call_id not in agent_calls_by_id:
                continue
            parent = agent_calls_by_id[parent_call_id]
            links[agent_id] = {
                "parent_call_id": parent_call_id,
                "root_turn_index": parent.get("turn_index"),
                "parent_link_status": "matched",
                "parent_link_basis": "progress",
            }
    return links


def _first_timestamp(path: str) -> str:
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = record.get("timestamp", "")
            if ts:
                return ts
    return ""


def _resolve_subagent_links(main_session_path, main_events, subagent_paths):
    agent_calls, agent_calls_by_id = _build_agent_calls(main_events)
    resolved = _extract_explicit_subagent_links(main_session_path, agent_calls_by_id)
    used_call_ids = {
        info["parent_call_id"] for info in resolved.values() if info.get("parent_call_id")
    }

    unresolved = []
    for sa_path in subagent_paths:
        agent_id = _agent_id_from_path(sa_path)
        if agent_id in resolved:
            continue
        unresolved.append({
            "agent_id": agent_id,
            "path": sa_path,
            "first_ts": _first_timestamp(sa_path),
        })

    remaining_calls = [c for c in agent_calls if c.get("call_id") and c["call_id"] not in used_call_ids]

    if len(unresolved) == 1 and len(remaining_calls) == 1:
        candidate = remaining_calls[0]
        resolved[unresolved[0]["agent_id"]] = {
            "parent_call_id": candidate["call_id"],
            "root_turn_index": candidate.get("turn_index"),
            "parent_link_status": "matched",
            "parent_link_basis": "single",
        }
        return resolved

    if unresolved and remaining_calls and len(unresolved) == len(remaining_calls):
        sorted_unresolved = sorted(unresolved, key=lambda item: (item.get("first_ts") or "9999", item["agent_id"]))
        sorted_calls = sorted(remaining_calls, key=lambda item: (item.get("ts") or "9999", item["call_id"]))
        if all(
            (not sa.get("first_ts") or not call.get("ts") or sa["first_ts"] >= call["ts"])
            for sa, call in zip(sorted_unresolved, sorted_calls)
        ):
            for sa, call in zip(sorted_unresolved, sorted_calls):
                resolved[sa["agent_id"]] = {
                    "parent_call_id": call["call_id"],
                    "root_turn_index": call.get("turn_index"),
                    "parent_link_status": "matched",
                    "parent_link_basis": "time",
                }
            return resolved

    for sa in unresolved:
        resolved[sa["agent_id"]] = {
            "parent_link_status": "ambiguous" if remaining_calls else "unavailable",
        }
    return resolved


def normalize_claude(input_path, subagent_paths, output_path, expected_session_id=None):
    """Read a Claude Code session JSONL and write normalized events."""
    # Process main transcript
    main_events, session_id = normalize_stream(
        input_path,
        expected_session_id=expected_session_id,
    )

    all_events = list(main_events)
    subagent_links = _resolve_subagent_links(input_path, main_events, subagent_paths)

    # Process subagents
    for sa_path in subagent_paths:
        sa_path = sa_path.strip()
        if not sa_path:
            continue

        # Extract agent_id from filename: agent-{id}.jsonl
        agent_id = _agent_id_from_path(sa_path)
        link_info = subagent_links.get(agent_id, {"parent_link_status": "unavailable"})

        sa_events, _ = normalize_stream(
            sa_path,
            session_id_override=session_id,
            agent_id=agent_id,
            parent_call_id=link_info.get("parent_call_id"),
            root_turn_index=link_info.get("root_turn_index"),
            parent_link_status=link_info.get("parent_link_status"),
            parent_link_basis=link_info.get("parent_link_basis"),
        )
        all_events.extend(sa_events)

    # Sort by timestamp, then by original sequence
    all_events.sort(key=lambda e: (e.get("ts", ""), e.get("seq", 0), e.get("agent_id", "")))

    # Re-sequence
    for i, evt in enumerate(all_events, 1):
        evt["seq"] = i

    # Write output
    out = sys.stdout if output_path == "-" else open(output_path, "w")
    try:
        for evt in all_events:
            out.write(json.dumps(evt, ensure_ascii=False) + "\n")
    finally:
        if out is not sys.stdout:
            out.close()

    print(f"Wrote {len(all_events)} events to {output_path}", file=sys.stderr)
    if subagent_paths and any(p.strip() for p in subagent_paths):
        sa_count = sum(1 for e in all_events if e.get("agent_id"))
        print(f"  ({sa_count} subagent events)", file=sys.stderr)


def _discover_subagents(session_path: str) -> list[str]:
    """Auto-discover subagent JSONL files for a Claude Code session.

    Given /path/to/{sessionId}.jsonl, checks /path/to/{sessionId}/subagents/*.jsonl
    """
    session_dir = os.path.splitext(session_path)[0]
    subagents_dir = os.path.join(session_dir, "subagents")
    if not os.path.isdir(subagents_dir):
        return []
    paths = sorted(glob.glob(os.path.join(subagents_dir, "*.jsonl")))
    return paths


def main():
    parser = argparse.ArgumentParser(
        description="Normalize Claude Code session JSONL into common event model"
    )
    parser.add_argument("--input", required=True, help="Path to session JSONL file")
    parser.add_argument("--subagents", default="",
                        help="Comma-separated paths to subagent JSONL files")
    parser.add_argument("--auto-subagents", action="store_true",
                        help="Auto-discover subagent files from the session path")
    parser.add_argument("--session-root", default="",
                        help="Original session JSONL path for subagent discovery "
                             "(use when --input is a stripped copy)")
    parser.add_argument("--output", required=True,
                        help="Output normalized JSONL (- for stdout)")
    args = parser.parse_args()

    if args.auto_subagents:
        discover_from = args.session_root if args.session_root else args.input
        subagent_paths = _discover_subagents(discover_from)
        if subagent_paths:
            print(f"Auto-discovered {len(subagent_paths)} subagent(s)", file=sys.stderr)
    elif args.subagents:
        subagent_paths = [p for p in args.subagents.split(",") if p.strip()]
    else:
        subagent_paths = []

    expected_session_id = _session_id_from_path(args.session_root or "")
    normalize_claude(
        args.input,
        subagent_paths,
        args.output,
        expected_session_id=expected_session_id or None,
    )


if __name__ == "__main__":
    main()
