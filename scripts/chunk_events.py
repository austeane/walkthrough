#!/usr/bin/env python3
"""Split normalized event JSONL into byte-bounded chunks for LLM processing.

Produces chunk-001.jsonl, chunk-002.jsonl, ... plus a manifest.json that
drives the downstream summarization pipeline.

Chunking rules:
- Target approximate byte size per chunk (default 300KB)
- Never split tool_use / tool_result pairs (matched by call_id)
- Never split file_change or command records from surrounding tool context
- Prefer splitting at turn boundaries (after user_message events)
- Oversized single records get their own chunk
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Chunk normalized JSONL into byte-bounded segments"
    )
    p.add_argument("--input", required=True, help="Path to normalized.jsonl")
    p.add_argument("--output-dir", required=True, help="Directory for chunk files + manifest")
    p.add_argument(
        "--target-bytes",
        type=int,
        default=300_000,
        help="Target byte size per chunk (default: 300000)",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Grouping helpers
# ---------------------------------------------------------------------------

def _build_groups(lines: list[str], records: list[dict]) -> list[list[int]]:
    """Return groups of line indices that must stay together.

    A group is either:
    - A tool_use followed by its matching tool_result (and any file_change /
      command records between them that share the same call_id context)
    - A standalone record that doesn't participate in tool pairing
    """
    n = len(records)
    consumed: set[int] = set()
    groups: list[list[int]] = []

    for i in range(n):
        if i in consumed:
            continue
        rec = records[i]
        kind = rec.get("kind", "")

        if kind == "tool_use":
            call_id = (rec.get("tool") or {}).get("call_id")
            session_id = rec.get("session_id")
            agent_id = rec.get("agent_id")
            group = [i]
            consumed.add(i)

            if call_id:
                # Gather subsequent records that belong to this tool invocation
                for j in range(i + 1, n):
                    if j in consumed:
                        continue
                    rj = records[j]
                    rj_kind = rj.get("kind", "")
                    rj_call_id = (rj.get("tool") or {}).get("call_id")
                    rj_session_id = rj.get("session_id")
                    rj_agent_id = rj.get("agent_id")
                    # Same stream = same session AND same agent (or both None)
                    same_stream = (rj_session_id == session_id
                                   and rj_agent_id == agent_id)

                    if rj_kind in ("file_change", "command"):
                        # Attach contextual records that sit between
                        # tool_use and tool_result
                        if same_stream:
                            group.append(j)
                            consumed.add(j)
                        continue

                    if rj_kind == "tool_result" and rj_call_id == call_id and same_stream:
                        group.append(j)
                        consumed.add(j)
                        # Also grab any file_change/command immediately after
                        # the tool_result that still belong to this context
                        for k in range(j + 1, n):
                            if k in consumed:
                                continue
                            rk = records[k]
                            if (
                                rk.get("session_id") == session_id
                                and rk.get("agent_id") == agent_id
                                and rk.get("kind", "") in ("file_change", "command")
                            ):
                                group.append(k)
                                consumed.add(k)
                            else:
                                break
                        break

                    if rj_kind == "tool_use":
                        # Next tool invocation in the same stream — stop gathering.
                        # A tool_use from another session/agent does not close this group.
                        if same_stream:
                            break
                        continue

                    # Other record types between tool_use and tool_result:
                    # include them in the group to avoid orphaning
                    if same_stream:
                        group.append(j)
                        consumed.add(j)

            groups.append(group)
        else:
            consumed.add(i)
            groups.append([i])

    return groups


def _is_turn_boundary(records: list[dict], group: list[int]) -> bool:
    """True if the last record in the group is a user_message (turn boundary)."""
    return records[group[-1]].get("kind") == "user_message"


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _chunk_groups(
    lines: list[str],
    records: list[dict],
    groups: list[list[int]],
    target_bytes: int,
) -> list[list[int]]:
    """Partition groups into chunks respecting the byte target.

    Returns a list of chunks, where each chunk is a flat list of line indices.
    """
    chunks: list[list[int]] = []
    current_chunk: list[int] = []
    current_bytes = 0

    for gi, group in enumerate(groups):
        group_bytes = sum(len(lines[idx]) for idx in group)

        # If the group alone exceeds the target, give it its own chunk
        if group_bytes >= target_bytes:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_bytes = 0
            chunks.append(list(group))
            continue

        # Would adding this group exceed the target?
        if current_bytes + group_bytes > target_bytes and current_chunk:
            # Try to find a better split point: look back for a turn boundary
            # within the current chunk's groups. We'll split after the last
            # turn boundary if one exists in the latter half.
            chunks.append(current_chunk)
            current_chunk = list(group)
            current_bytes = group_bytes
        else:
            current_chunk.extend(group)
            current_bytes += group_bytes

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _refine_at_turn_boundaries(
    lines: list[str],
    records: list[dict],
    groups: list[list[int]],
    raw_chunks: list[list[int]],
    target_bytes: int,
) -> list[list[int]]:
    """Post-process chunks to prefer splitting at turn boundaries.

    If a chunk is over-target and contains a user_message event, try to split
    at the last turn boundary that keeps both halves non-empty.
    """
    refined: list[list[int]] = []

    for chunk_indices in raw_chunks:
        chunk_bytes = sum(len(lines[idx]) for idx in chunk_indices)
        if chunk_bytes <= target_bytes:
            refined.append(chunk_indices)
            continue

        # Find turn boundary positions within the chunk
        best_split = None
        running = 0
        for pos, idx in enumerate(chunk_indices):
            running += len(lines[idx])
            if records[idx].get("kind") == "user_message" and pos > 0 and pos < len(chunk_indices) - 1:
                # Prefer splitting after user_message where the first half
                # is closest to but not exceeding the target
                if running <= target_bytes:
                    best_split = pos + 1

        if best_split is not None:
            refined.append(chunk_indices[:best_split])
            refined.append(chunk_indices[best_split:])
        else:
            refined.append(chunk_indices)

    return refined


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ts_range(records: list[dict], indices: list[int]) -> dict:
    timestamps = [records[i].get("ts") for i in indices if records[i].get("ts")]
    if not timestamps:
        return {"start": None, "end": None}
    return {"start": min(timestamps), "end": max(timestamps)}


def _write_chunk(
    output_dir: Path,
    chunk_id: str,
    lines: list[str],
    indices: list[int],
) -> tuple[str, int, str]:
    """Write a chunk file. Returns (filename, byte_size, sha256)."""
    filename = f"{chunk_id}.jsonl"
    content = b"".join(lines[i] if isinstance(lines[i], bytes) else lines[i].encode() for i in indices)
    path = output_dir / filename
    path.write_bytes(content)
    return filename, len(content), _sha256(content)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    target_bytes = args.target_bytes

    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Read all lines and parse records
    raw_lines: list[str] = input_path.read_text().splitlines(keepends=True)
    if not raw_lines:
        print("Error: input file is empty", file=sys.stderr)
        sys.exit(1)

    # Ensure each line ends with newline for consistent byte counting
    lines: list[str] = []
    records: list[dict] = []
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rec = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        lines.append(stripped + "\n")
        records.append(rec)

    if not records:
        print("Error: no valid JSON records found", file=sys.stderr)
        sys.exit(1)

    # Build atomic groups, then chunk them
    groups = _build_groups(lines, records)
    raw_chunks = _chunk_groups(lines, records, groups, target_bytes)
    chunks = _refine_at_turn_boundaries(lines, records, groups, raw_chunks, target_bytes)

    # Write chunk files and build manifest
    manifest_chunks = []
    for ci, chunk_indices in enumerate(chunks):
        chunk_id = f"chunk-{ci + 1:03d}"
        filename, byte_size, sha = _write_chunk(output_dir, chunk_id, lines, chunk_indices)

        # line_start/line_end are 1-indexed, referring to positions in the
        # normalized input file
        source_lines = [records[i].get("source_line", i + 1) for i in chunk_indices]
        line_start = min(source_lines) if source_lines else 1
        line_end = max(source_lines) if source_lines else 1

        manifest_chunks.append({
            "chunk_id": chunk_id,
            "path": filename,
            "line_start": line_start,
            "line_end": line_end,
            "byte_size": byte_size,
            "event_count": len(chunk_indices),
            "time_range": _ts_range(records, chunk_indices),
            "sha256": sha,
        })

    manifest = {
        "source": str(input_path),
        "target_bytes": target_bytes,
        "chunks": manifest_chunks,
    }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    total_chunks = len(chunks)
    total_events = len(records)
    print(f"Wrote {total_chunks} chunk(s) from {total_events} events to {output_dir}/")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
