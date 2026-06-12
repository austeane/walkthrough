#!/usr/bin/env python3
"""Discover Codex CLI, Claude Code, and OpenCode sessions on disk."""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sqlite3
import subprocess
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


def epoch_ms_to_iso(value) -> str:
    """Convert milliseconds since epoch to an ISO8601 UTC timestamp."""
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_opencode_db_path(explicit_path: str | None, opencode_bin: str) -> str | None:
    """Resolve the OpenCode SQLite database path."""
    if explicit_path:
        path = os.path.expanduser(explicit_path)
        return path if os.path.isfile(path) else None

    try:
        result = subprocess.run(
            [opencode_bin, "db", "path"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None

    path = result.stdout.strip()
    return path if path and os.path.isfile(path) else None


def discover_opencode_sessions(db_path: str) -> list[dict]:
    """Discover OpenCode sessions from the local SQLite store."""
    sessions = []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    query = """
        SELECT
            s.id,
            s.parent_id,
            s.directory,
            s.title,
            s.version,
            s.time_created,
            s.time_updated,
            COALESCE(m.message_count, 0) AS message_count,
            COALESCE(p.part_count, 0) AS part_count,
            COALESCE(LENGTH(s.title), 0)
              + COALESCE(LENGTH(s.directory), 0)
              + COALESCE(m.message_bytes, 0)
              + COALESCE(p.part_bytes, 0) AS size_bytes
        FROM session s
        LEFT JOIN (
            SELECT
                session_id,
                COUNT(*) AS message_count,
                COALESCE(SUM(LENGTH(data)), 0) AS message_bytes
            FROM message
            GROUP BY session_id
        ) m ON m.session_id = s.id
        LEFT JOIN (
            SELECT
                session_id,
                COUNT(*) AS part_count,
                COALESCE(SUM(LENGTH(data)), 0) AS part_bytes
            FROM part
            GROUP BY session_id
        ) p ON p.session_id = s.id
        ORDER BY s.time_updated DESC
    """

    try:
        for row in conn.execute(query):
            timestamp = epoch_ms_to_iso(row["time_created"] or row["time_updated"])
            sessions.append({
                "provider": "opencode",
                "path": f"opencode://session/{row['id']}",
                "session_id": row["id"],
                "timestamp": timestamp,
                "size_bytes": row["size_bytes"] or 0,
                "line_count": 1 + (row["message_count"] or 0) + (row["part_count"] or 0),
                "cwd": row["directory"],
                "model": None,
                "subagent_paths": [],
                "parent_session_id": row["parent_id"] or None,
                "title": row["title"] or "",
                "cli_version": row["version"] or "",
            })
    except sqlite3.Error:
        return []
    finally:
        conn.close()

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
    parser = argparse.ArgumentParser(description="Discover Codex, Claude Code, and OpenCode sessions")
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
    parser.add_argument(
        "--opencode-db",
        help="Path to the OpenCode SQLite database (auto-detected via `opencode db path` if omitted)",
    )
    parser.add_argument(
        "--opencode-bin",
        default=os.environ.get("OPENCODE_BIN", "opencode"),
        help="OpenCode CLI binary used for DB auto-detection (default: opencode)",
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
    opencode_db = resolve_opencode_db_path(args.opencode_db, args.opencode_bin)
    if opencode_db:
        sessions.extend(discover_opencode_sessions(opencode_db))

    sessions = filter_sessions(sessions, args)

    # Sort by timestamp descending
    sessions.sort(key=lambda s: s.get("timestamp") or "", reverse=True)

    json.dump(sessions, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
