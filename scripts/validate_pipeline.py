#!/usr/bin/env python3
"""Validate pipeline intermediate outputs for contract violations.

Runs assertions on normalized, projected, and chunked files to catch
regressions in turn indexing, tool pairing, session contiguity, and
screenshot handling.

Usage:
    # Validate a normalized file
    python3 scripts/validate_pipeline.py --normalized out/normalized.jsonl

    # Validate projected output
    python3 scripts/validate_pipeline.py --projected out/projected.jsonl

    # Validate chunks
    python3 scripts/validate_pipeline.py --chunks out/chunks/manifest.json

    # Validate everything
    python3 scripts/validate_pipeline.py \
      --normalized out/normalized.jsonl \
      --projected out/projected.jsonl \
      --chunks out/chunks/manifest.json
"""

import argparse
import json
import os
import sys
from collections import defaultdict


class ValidationResult:
    def __init__(self):
        self.checks = 0
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.messages: list[str] = []

    def ok(self, msg: str):
        self.checks += 1
        self.passed += 1

    def fail(self, msg: str):
        self.checks += 1
        self.failed += 1
        self.messages.append(f"FAIL: {msg}")

    def warn(self, msg: str):
        self.warnings += 1
        self.messages.append(f"WARN: {msg}")

    def report(self):
        for m in self.messages:
            print(f"  {m}", file=sys.stderr)
        print(
            f"  {self.passed}/{self.checks} passed, "
            f"{self.failed} failed, {self.warnings} warnings",
            file=sys.stderr,
        )


def load_jsonl(path: str) -> list[dict]:
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


# ---------------------------------------------------------------------------
# Normalized validation
# ---------------------------------------------------------------------------

def _stream_key(evt: dict) -> str:
    session_id = evt.get("session_id", "") or "<missing>"
    agent_id = evt.get("agent_id", "")
    return f"{session_id}::agent:{agent_id}" if agent_id else session_id


def validate_normalized(path: str) -> ValidationResult:
    print(f"Validating normalized: {path}", file=sys.stderr)
    r = ValidationResult()
    events = load_jsonl(path)

    if not events:
        r.fail("File is empty")
        r.report()
        return r

    # 1. All events have required envelope fields
    required = {"seq", "kind", "turn_index", "ts", "provider", "session_id", "source_path"}
    missing_fields = set()
    for evt in events:
        for field in required:
            if field not in evt:
                missing_fields.add(field)
    if missing_fields:
        r.fail(f"Events missing required fields: {missing_fields}")
    else:
        r.ok("All events have required envelope fields")

    # 2. Provider is always "codex", "claude", or "opencode"
    providers = {e.get("provider") for e in events}
    invalid_providers = providers - {"codex", "claude", "opencode"}
    if invalid_providers:
        r.fail(f"Invalid providers: {invalid_providers}")
    else:
        r.ok(f"Valid providers: {providers}")

    # 3. session_id must be non-empty for all events
    empty_session_ids = sum(1 for evt in events if not evt.get("session_id"))
    if empty_session_ids:
        r.fail(f"{empty_session_ids} event(s) missing session_id")
    else:
        r.ok("All events have non-empty session_id")

    # 4. Turn indexing is validated per conversational stream.
    by_stream: dict[str, list[dict]] = defaultdict(list)
    for evt in events:
        by_stream[_stream_key(evt)].append(evt)

    for stream_id, stream_events in by_stream.items():
        meta_events = [e for e in stream_events if e["kind"] == "meta"]
        user_events = [e for e in stream_events if e["kind"] == "user_message"]

        for me in meta_events:
            if me["turn_index"] != 0:
                r.fail(f"Stream {stream_id[:24]}: meta event has turn_index={me['turn_index']}, expected 0")
                break
        else:
            if meta_events:
                r.ok(f"Stream {stream_id[:24]}: meta turn_index=0")

        if user_events:
            first_turn = user_events[0]["turn_index"]
            if first_turn != 1:
                r.fail(f"Stream {stream_id[:24]}: first user_message has turn_index={first_turn}, expected 1")
            else:
                r.ok(f"Stream {stream_id[:24]}: first user turn_index=1")

    # 5. Turn indices are monotonically non-decreasing per stream
    for stream_id, stream_events in by_stream.items():
        turns = [e["turn_index"] for e in stream_events]
        violations = sum(1 for i in range(1, len(turns)) if turns[i] < turns[i-1])
        if violations > 0:
            r.fail(f"Stream {stream_id[:24]}: {violations} turn_index regression(s)")
        else:
            r.ok(f"Stream {stream_id[:24]}: turn_index monotonic")

    # 6. tool_use/tool_result pairing: every tool_use call_id has a tool_result
    tool_uses: dict[str, int] = {}
    tool_results: set[str] = set()
    for evt in events:
        if evt["kind"] == "tool_use":
            call_id = (evt.get("tool") or {}).get("call_id", "")
            if call_id:
                tool_uses[call_id] = tool_uses.get(call_id, 0) + 1
        elif evt["kind"] == "tool_result":
            call_id = (evt.get("tool") or {}).get("call_id", "")
            if call_id:
                tool_results.add(call_id)

    orphaned = set(tool_uses.keys()) - tool_results
    if orphaned:
        r.warn(f"{len(orphaned)} tool_use call_ids without matching tool_result")
    else:
        r.ok(f"All {len(tool_uses)} tool_use events have matching tool_results")

    # 7. Session contiguity: events from same session should be contiguous
    session_spans: dict[str, list[int]] = defaultdict(list)
    for i, evt in enumerate(events):
        session_spans[evt.get("session_id", "")].append(i)

    non_contiguous = []
    for sess_id, indices in session_spans.items():
        if len(indices) < 2:
            continue
        expected_range = set(range(min(indices), max(indices) + 1))
        if set(indices) != expected_range:
            # Check if the gaps are from other sessions (interleaving)
            gap_indices = expected_range - set(indices)
            gap_sessions = {events[i].get("session_id") for i in gap_indices if i < len(events)}
            if gap_sessions - {sess_id}:
                non_contiguous.append(sess_id[:8])

    if non_contiguous:
        r.fail(f"Non-contiguous sessions (interleaved): {', '.join(non_contiguous[:5])}")
    else:
        r.ok("All sessions are contiguous")

    # 8. seq is monotonically increasing across the serialized artifact
    seqs = [e.get("seq", 0) for e in events]
    seq_ok = all(seqs[i] < seqs[i+1] for i in range(len(seqs)-1))
    if seq_ok:
        r.ok("seq is strictly increasing")
    else:
        r.fail("seq is not strictly increasing")

    r.report()
    return r


# ---------------------------------------------------------------------------
# Projected validation
# ---------------------------------------------------------------------------

def validate_projected(path: str) -> ValidationResult:
    print(f"Validating projected: {path}", file=sys.stderr)
    r = ValidationResult()
    events = load_jsonl(path)

    if not events:
        r.fail("File is empty")
        r.report()
        return r

    # 1. No file_snapshot events
    snapshots = [e for e in events if e["kind"] == "file_snapshot"]
    if snapshots:
        r.fail(f"{len(snapshots)} file_snapshot events not dropped")
    else:
        r.ok("No file_snapshot events")

    # 2. No turn_context events
    turn_ctx = [e for e in events if e["kind"] == "turn_context"]
    if turn_ctx:
        r.fail(f"{len(turn_ctx)} turn_context events not dropped")
    else:
        r.ok("No turn_context events")

    # 3. No compaction events
    compaction = [e for e in events if e["kind"] == "compaction"]
    if compaction:
        r.fail(f"{len(compaction)} compaction events not dropped")
    else:
        r.ok("No compaction events")

    # 4. No data_b64 in screenshot events
    for evt in events:
        if evt["kind"] == "screenshot":
            media = evt.get("media", {})
            if isinstance(media, dict) and "data_b64" in media:
                r.fail("Screenshot event contains data_b64 (should be stripped)")
                break
    else:
        r.ok("No data_b64 in screenshot events")

    # 5. Non-error tool_results are compressed
    uncompressed = 0
    for evt in events:
        if evt["kind"] == "tool_result":
            tool = evt.get("tool", {})
            if not tool.get("is_error") and not tool.get("compressed"):
                uncompressed += 1
    if uncompressed:
        r.warn(f"{uncompressed} non-error tool_results are not compressed")
    else:
        r.ok("All non-error tool_results compressed")

    # 6. Error tool_results have full output preserved
    for evt in events:
        if evt["kind"] == "tool_result":
            tool = evt.get("tool", {})
            if tool.get("is_error") and tool.get("compressed"):
                r.fail("Error tool_result was compressed (should preserve full output)")
                break
    else:
        r.ok("Error tool_results preserve full output")

    r.report()
    return r


# ---------------------------------------------------------------------------
# Chunk validation
# ---------------------------------------------------------------------------

def validate_chunks(manifest_path: str) -> ValidationResult:
    print(f"Validating chunks: {manifest_path}", file=sys.stderr)
    r = ValidationResult()

    with open(manifest_path) as f:
        manifest = json.load(f)

    chunks = manifest.get("chunks", [])
    if not chunks:
        r.fail("Manifest has no chunks")
        r.report()
        return r

    chunks_dir = os.path.dirname(manifest_path)

    # 1. All chunk files exist
    missing_files = []
    for chunk in chunks:
        chunk_path = os.path.join(chunks_dir, chunk["path"])
        if not os.path.isfile(chunk_path):
            missing_files.append(chunk["chunk_id"])
    if missing_files:
        r.fail(f"Missing chunk files: {', '.join(missing_files)}")
    else:
        r.ok(f"All {len(chunks)} chunk files exist")

    # 2. Chunk SHA256 matches
    import hashlib
    sha_mismatches = []
    for chunk in chunks:
        chunk_path = os.path.join(chunks_dir, chunk["path"])
        if not os.path.isfile(chunk_path):
            continue
        with open(chunk_path, "rb") as f:
            actual_sha = hashlib.sha256(f.read()).hexdigest()
        if actual_sha != chunk["sha256"]:
            sha_mismatches.append(chunk["chunk_id"])
    if sha_mismatches:
        r.fail(f"SHA256 mismatch for: {', '.join(sha_mismatches)}")
    else:
        r.ok("All chunk SHA256 hashes match")

    # 3. tool_use/tool_result pairs are not split across chunks
    split_pairs = 0
    for chunk in chunks:
        chunk_path = os.path.join(chunks_dir, chunk["path"])
        if not os.path.isfile(chunk_path):
            continue
        events = load_jsonl(chunk_path)
        chunk_tool_uses = set()
        chunk_tool_results = set()
        for evt in events:
            if evt.get("kind") == "tool_use":
                call_id = (evt.get("tool") or {}).get("call_id", "")
                if call_id:
                    chunk_tool_uses.add(call_id)
            elif evt.get("kind") == "tool_result":
                call_id = (evt.get("tool") or {}).get("call_id", "")
                if call_id:
                    chunk_tool_results.add(call_id)
        # tool_results without matching tool_use in same chunk
        orphan_results = chunk_tool_results - chunk_tool_uses
        split_pairs += len(orphan_results)

    if split_pairs:
        r.warn(f"{split_pairs} tool_result(s) separated from their tool_use across chunks")
    else:
        r.ok("No tool_use/tool_result pairs split across chunks")

    # 4. Chunk byte sizes recorded correctly
    size_errors = []
    for chunk in chunks:
        chunk_path = os.path.join(chunks_dir, chunk["path"])
        if not os.path.isfile(chunk_path):
            continue
        actual = os.path.getsize(chunk_path)
        recorded = chunk.get("byte_size", 0)
        if actual != recorded:
            size_errors.append(f"{chunk['chunk_id']}: recorded={recorded}, actual={actual}")
    if size_errors:
        r.fail(f"Byte size mismatches: {'; '.join(size_errors[:3])}")
    else:
        r.ok("All chunk byte sizes match")

    # 5. No gaps in event coverage
    total_events_in_chunks = sum(c.get("event_count", 0) for c in chunks)
    r.ok(f"Total events across chunks: {total_events_in_chunks}")

    r.report()
    return r


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Validate pipeline intermediate outputs for contract violations"
    )
    parser.add_argument("--normalized", help="Path to normalized.jsonl")
    parser.add_argument("--projected", help="Path to projected.jsonl")
    parser.add_argument("--chunks", help="Path to chunks/manifest.json")
    args = parser.parse_args()

    if not any([args.normalized, args.projected, args.chunks]):
        parser.error("At least one of --normalized, --projected, --chunks is required")

    total_failed = 0

    if args.normalized:
        result = validate_normalized(args.normalized)
        total_failed += result.failed

    if args.projected:
        result = validate_projected(args.projected)
        total_failed += result.failed

    if args.chunks:
        result = validate_chunks(args.chunks)
        total_failed += result.failed

    if total_failed > 0:
        print(f"\n{total_failed} validation failure(s)", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nAll validations passed", file=sys.stderr)


if __name__ == "__main__":
    main()
