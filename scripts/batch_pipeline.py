#!/usr/bin/env python3
"""Batch pipeline: strip, normalize, project, concatenate, and chunk sessions.

Automates the strip → normalize → project → concat → chunk workflow for projects
with many sessions (e.g. 100+ Codex sessions). No LLM calls — purely deterministic.

Pipeline flow:
    strip → normalize → PROJECT → concat projected → chunk
                       ↘ extract card

Usage:
    # Discover sessions first
    python3 scripts/discover_sessions.py --cwd /path/to/project > sessions.json

    # Run the batch pipeline
    python3 scripts/batch_pipeline.py \
      --sessions sessions.json \
      --output-dir out/ \
      --target-bytes 300000

    # Skip projection (backward compat)
    python3 scripts/batch_pipeline.py \
      --sessions sessions.json \
      --output-dir out/ \
      --no-project
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def run(cmd: list[str], desc: str) -> subprocess.CompletedProcess:
    """Run a command, printing a description and checking for errors."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FAIL: {desc}", file=sys.stderr)
        print(f"  cmd: {' '.join(cmd)}", file=sys.stderr)
        if result.stderr:
            print(f"  stderr: {result.stderr[:500]}", file=sys.stderr)
        return result
    return result


def process_session(
    session: dict,
    batch_dir: str,
    idx: int,
    python_cmd: list[str],
    preserve_screenshots: bool = False,
) -> str | None:
    """Strip and normalize a single session. Returns path to normalized JSONL or None."""
    provider = session["provider"]
    session_path = session["path"]
    tag = f"session-{idx:04d}-{provider}"

    stripped_path = os.path.join(batch_dir, f"{tag}-stripped.jsonl")
    normalized_path = os.path.join(batch_dir, f"{tag}-normalized.jsonl")

    # Strip binary
    strip_cmd = [
        *python_cmd, str(SCRIPT_DIR / "strip_binary.py"),
        "--input", session_path, "--output", stripped_path,
    ]
    if preserve_screenshots:
        strip_cmd.append("--preserve-screenshots")
    result = run(strip_cmd, f"strip {tag}")
    if result.returncode != 0:
        return None

    # Normalize
    if provider == "codex":
        result = run(
            [*python_cmd, str(SCRIPT_DIR / "normalize_codex.py"),
             "--input", stripped_path, "--output", normalized_path],
            f"normalize {tag}",
        )
    elif provider == "claude":
        result = run(
            [*python_cmd, str(SCRIPT_DIR / "normalize_claude.py"),
             "--input", stripped_path,
             "--auto-subagents", "--session-root", session_path,
             "--output", normalized_path],
            f"normalize {tag}",
        )
    else:
        print(f"SKIP: Unknown provider '{provider}' for {session_path}", file=sys.stderr)
        return None

    if result.returncode != 0:
        return None

    return normalized_path


def concat_normalized(paths: list[str], output_path: str) -> int:
    """Concatenate sessions contiguously and resequence across the serialized artifact."""
    sessions_data: list[tuple[str, str, list[dict]]] = []
    total_events = 0

    for path in paths:
        session_events: list[dict] = []
        earliest_ts = ""
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                session_events.append(obj)
                ts = obj.get("ts", "")
                if ts and (not earliest_ts or ts < earliest_ts):
                    earliest_ts = ts
        sessions_data.append((earliest_ts, path, session_events))
        total_events += len(session_events)

    sessions_data.sort(key=lambda item: (item[0] or "9999-12-31T23:59:59Z", item[1]))

    seq = 0
    with open(output_path, "w") as f:
        for _, _, session_events in sessions_data:
            for event in session_events:
                seq += 1
                event["seq"] = seq
                f.write(json.dumps(event, ensure_ascii=False) + "\n")

    return total_events


def project_session(
    normalized_path: str,
    batch_dir: str,
    tag: str,
    python_cmd: list[str],
) -> str | None:
    """Run event projection on a normalized session. Returns projected path or None."""
    projected_path = os.path.join(batch_dir, f"{tag}-projected.jsonl")
    result = run(
        [*python_cmd, str(SCRIPT_DIR / "project_events.py"),
         "--input", normalized_path, "--output", projected_path],
        f"project {tag}",
    )
    if result.returncode != 0:
        return None
    return projected_path


def extract_card(
    normalized_path: str,
    cards_dir: str,
    tag: str,
    python_cmd: list[str],
) -> str | None:
    """Extract a session card from a normalized session. Returns card path or None."""
    card_path = os.path.join(cards_dir, f"{tag}-card.json")
    result = run(
        [*python_cmd, str(SCRIPT_DIR / "extract_session_cards.py"),
         "--input", normalized_path, "--output", card_path],
        f"card {tag}",
    )
    if result.returncode != 0:
        return None
    return card_path


def main():
    parser = argparse.ArgumentParser(
        description="Batch strip, normalize, project, concatenate, and chunk sessions"
    )
    parser.add_argument(
        "--sessions", required=True,
        help="Path to sessions.json (output of discover_sessions.py)"
    )
    parser.add_argument(
        "--output-dir", required=True,
        help="Output directory for normalized.jsonl and chunks/"
    )
    parser.add_argument(
        "--target-bytes", type=int, default=300_000,
        help="Target byte size per chunk (default: 300000)"
    )
    parser.add_argument(
        "--no-project", action="store_true",
        help="Skip projection step and chunk raw normalized data (backward compat)"
    )
    parser.add_argument(
        "--preserve-screenshots", action="store_true",
        help="Pass --preserve-screenshots to strip_binary.py",
    )
    args = parser.parse_args()

    with open(args.sessions) as f:
        sessions = json.load(f)

    if not sessions:
        print("No sessions to process.", file=sys.stderr)
        sys.exit(1)

    # Determine python command — use uv run if pyproject.toml exists
    python_cmd = ["python3"]
    if os.path.isfile("pyproject.toml"):
        python_cmd = ["uv", "run", "python3"]

    output_dir = args.output_dir
    batch_dir = os.path.join(output_dir, "batch")
    cards_dir = os.path.join(output_dir, "cards")
    os.makedirs(batch_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, "chunks"), exist_ok=True)
    os.makedirs(cards_dir, exist_ok=True)

    # Process each session: strip → normalize → project → card
    normalized_paths = []
    projected_paths = []
    card_paths = []
    failed = 0
    for i, session in enumerate(sessions):
        provider = session["provider"]
        tag = f"session-{i:04d}-{provider}"

        normalized_path = process_session(
            session,
            batch_dir,
            i,
            python_cmd,
            preserve_screenshots=args.preserve_screenshots,
        )
        if not normalized_path:
            failed += 1
            continue

        normalized_paths.append(normalized_path)

        # Project events (unless --no-project)
        if not args.no_project:
            projected_path = project_session(normalized_path, batch_dir, tag, python_cmd)
            if projected_path:
                projected_paths.append(projected_path)

        # Extract session card
        card_path = extract_card(normalized_path, cards_dir, tag, python_cmd)
        if card_path:
            card_paths.append(card_path)

    if not normalized_paths:
        print("ERROR: All sessions failed to process.", file=sys.stderr)
        sys.exit(1)

    # Concatenate normalized (always, for debugging/reference)
    concat_path = os.path.join(output_dir, "normalized.jsonl")
    event_count = concat_normalized(normalized_paths, concat_path)

    # Concatenate projected (if projection ran)
    projected_concat_path = None
    projected_event_count = 0
    if projected_paths:
        projected_concat_path = os.path.join(output_dir, "projected.jsonl")
        projected_event_count = concat_normalized(projected_paths, projected_concat_path)

    # Decide which concatenated file to chunk
    chunk_input = concat_path
    if projected_concat_path and not args.no_project:
        chunk_input = projected_concat_path

    # Chunk
    chunks_dir = os.path.join(output_dir, "chunks")
    result = run(
        [*python_cmd, str(SCRIPT_DIR / "chunk_events.py"),
         "--input", chunk_input,
         "--output-dir", chunks_dir,
         "--target-bytes", str(args.target_bytes)],
        "chunk events",
    )
    if result.returncode != 0:
        print("ERROR: Chunking failed.", file=sys.stderr)
        sys.exit(1)

    # Read manifest to get chunk count
    manifest_path = os.path.join(chunks_dir, "manifest.json")
    chunk_count = 0
    if os.path.isfile(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)
        chunk_count = len(manifest.get("chunks", []))

    # Merge all session cards into session-cards.json
    all_cards = []
    for cp in sorted(card_paths):
        try:
            with open(cp) as f:
                all_cards.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass

    cards_merged_path = os.path.join(output_dir, "session-cards.json")
    with open(cards_merged_path, "w") as f:
        json.dump(all_cards, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Summary
    codex_count = sum(1 for s in sessions if s["provider"] == "codex")
    claude_count = sum(1 for s in sessions if s["provider"] == "claude")
    norm_bytes = os.path.getsize(concat_path) if os.path.isfile(concat_path) else 0
    print(f"\nBatch pipeline complete:", file=sys.stderr)
    print(f"  Sessions: {len(sessions)} ({codex_count} Codex, {claude_count} Claude)", file=sys.stderr)
    if failed:
        print(f"  Failed:   {failed}", file=sys.stderr)
    print(f"  Events:   {event_count:,} normalized", file=sys.stderr)
    if projected_concat_path:
        proj_bytes = os.path.getsize(projected_concat_path) if os.path.isfile(projected_concat_path) else 0
        reduction = round((1 - proj_bytes / norm_bytes) * 100) if norm_bytes > 0 else 0
        print(f"  Projected: {projected_event_count:,} events ({reduction}% byte reduction)", file=sys.stderr)
    print(f"  Cards:    {len(all_cards)}", file=sys.stderr)
    print(f"  Chunks:   {chunk_count}", file=sys.stderr)
    print(f"  Output:   {chunk_input}", file=sys.stderr)
    print(f"  Manifest: {manifest_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
