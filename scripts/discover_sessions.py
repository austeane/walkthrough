#!/usr/bin/env python3
"""Discover Codex CLI and Claude Code session JSONL files on disk."""

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def parse_relative_date(s: str) -> datetime:
    """Parse relative date like '7d', '30d' or ISO date string."""
    m = re.match(r"^(\d+)d$", s)
    if m:
        return datetime.now(timezone.utc) - timedelta(days=int(m.group(1)))
    # Try ISO parse
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def count_lines(path: str) -> int:
    count = 0
    with open(path, "rb") as f:
        for _ in f:
            count += 1
    return count


def discover_codex_sessions(root: str) -> list[dict]:
    """Discover Codex CLI session files."""
    sessions = []
    pattern = os.path.join(root, "**", "rollout-*.jsonl")
    for path in glob.glob(pattern, recursive=True):
        size = os.path.getsize(path)
        if size < 1024:
            continue
        try:
            with open(path) as f:
                first_line = f.readline()
            meta = json.loads(first_line)
            if meta.get("type") != "session_meta":
                continue
            payload = meta.get("payload", {})
            timestamp = payload.get("timestamp") or meta.get("timestamp")
            sessions.append({
                "provider": "codex",
                "path": path,
                "timestamp": timestamp,
                "size_bytes": size,
                "line_count": count_lines(path),
                "cwd": payload.get("cwd"),
                "model": payload.get("model_provider"),
                "subagent_paths": [],
            })
        except (json.JSONDecodeError, OSError):
            continue
    return sessions


def discover_claude_sessions(root: str) -> list[dict]:
    """Discover Claude Code session files."""
    sessions = []
    pattern = os.path.join(root, "*", "*.jsonl")
    for path in glob.glob(pattern):
        # Skip files inside subagents/ directories
        if "/subagents/" in path or "\\subagents\\" in path:
            continue
        size = os.path.getsize(path)
        if size < 1024:
            continue
        try:
            timestamp = None
            cwd = None
            session_id = None
            version = None
            model = None

            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    rtype = record.get("type")

                    if rtype == "user" and cwd is None:
                        cwd = record.get("cwd")
                        session_id = record.get("sessionId")
                        version = record.get("version")
                        timestamp = record.get("timestamp")

                    if rtype == "assistant" and model is None:
                        msg = record.get("message", {})
                        if isinstance(msg, dict):
                            model = msg.get("model")

                    if cwd is not None and model is not None:
                        break

            # Fall back to mtime for timestamp
            if not timestamp:
                mtime = os.path.getmtime(path)
                timestamp = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

            # Check for subagent directory
            project_dir = os.path.dirname(path)
            subagent_paths = []
            if session_id:
                session_dir = os.path.join(project_dir, session_id)
                subagents_dir = os.path.join(session_dir, "subagents")
                if os.path.isdir(subagents_dir):
                    for sa_file in glob.glob(os.path.join(subagents_dir, "*.jsonl")):
                        subagent_paths.append(sa_file)

            sessions.append({
                "provider": "claude",
                "path": path,
                "timestamp": timestamp,
                "size_bytes": size,
                "line_count": count_lines(path),
                "cwd": cwd,
                "model": model,
                "subagent_paths": subagent_paths,
            })
        except (json.JSONDecodeError, OSError):
            continue
    return sessions


def filter_sessions(sessions: list[dict], args: argparse.Namespace) -> list[dict]:
    """Apply --since, --until, --project, --cwd filters."""
    filtered = []
    since_dt = parse_relative_date(args.since) if args.since else None
    until_dt = parse_relative_date(args.until) if args.until else None

    for s in sessions:
        # Parse timestamp for comparison
        ts_str = s.get("timestamp")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                ts = None
        else:
            ts = None

        if since_dt and ts and ts < since_dt:
            continue
        if until_dt and ts and ts > until_dt:
            continue

        session_cwd = s.get("cwd") or ""
        if args.project and args.project not in session_cwd:
            continue
        if args.cwd and not session_cwd.startswith(args.cwd):
            continue

        filtered.append(s)
    return filtered


def main():
    parser = argparse.ArgumentParser(description="Discover session JSONL files")
    parser.add_argument(
        "--codex-root",
        default=os.path.expanduser("~/.codex/sessions"),
        help="Root directory for Codex sessions",
    )
    parser.add_argument(
        "--claude-root",
        default=os.path.expanduser("~/.claude/projects"),
        help="Root directory for Claude Code sessions",
    )
    parser.add_argument("--since", help="Only sessions after this date (ISO or relative like '7d')")
    parser.add_argument("--until", help="Only sessions before this date (ISO or relative like '7d')")
    parser.add_argument("--project", help="Substring match on session cwd")
    parser.add_argument("--cwd", help="Exact path prefix match on session cwd")
    args = parser.parse_args()

    sessions = []
    if os.path.isdir(args.codex_root):
        sessions.extend(discover_codex_sessions(args.codex_root))
    if os.path.isdir(args.claude_root):
        sessions.extend(discover_claude_sessions(args.claude_root))

    sessions = filter_sessions(sessions, args)

    # Sort by timestamp descending
    sessions.sort(key=lambda s: s.get("timestamp") or "", reverse=True)

    json.dump(sessions, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
