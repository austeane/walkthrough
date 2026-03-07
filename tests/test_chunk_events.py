"""Tests for chunk_events.py."""

import json
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from chunk_events import _build_groups, _chunk_groups, main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_event(kind: str, call_id: str = "", session_id: str = "sess-1",
               agent_id: str = None, turn_index: int = 1, seq: int = 1) -> dict:
    evt = {
        "seq": seq,
        "kind": kind,
        "session_id": session_id,
        "turn_index": turn_index,
        "ts": "2026-01-01T00:00:00Z",
        "source_line": seq,
        "source_path": "test.jsonl",
        "provider": "claude",
    }
    if kind in ("tool_use", "tool_result"):
        evt["tool"] = {"call_id": call_id}
        if kind == "tool_use":
            evt["tool"]["name"] = "Bash"
    if agent_id:
        evt["agent_id"] = agent_id
    return evt


def to_lines(events: list[dict]) -> list[str]:
    return [json.dumps(e) + "\n" for e in events]


# ---------------------------------------------------------------------------
# Group building
# ---------------------------------------------------------------------------

class TestBuildGroups:
    def test_tool_use_result_paired(self):
        """tool_use and matching tool_result should be in the same group."""
        events = [
            make_event("tool_use", call_id="c1", seq=1),
            make_event("tool_result", call_id="c1", seq=2),
        ]
        lines = to_lines(events)
        groups = _build_groups(lines, events)
        assert len(groups) == 1
        assert groups[0] == [0, 1]

    def test_file_change_between_tool_pair_included(self):
        """file_change between tool_use and tool_result should be in the same group."""
        events = [
            make_event("tool_use", call_id="c1", seq=1),
            make_event("file_change", seq=2),
            make_event("tool_result", call_id="c1", seq=3),
        ]
        lines = to_lines(events)
        groups = _build_groups(lines, events)
        assert len(groups) == 1
        assert groups[0] == [0, 1, 2]

    def test_command_between_tool_pair_included(self):
        events = [
            make_event("tool_use", call_id="c1", seq=1),
            make_event("command", seq=2),
            make_event("tool_result", call_id="c1", seq=3),
        ]
        lines = to_lines(events)
        groups = _build_groups(lines, events)
        assert len(groups) == 1
        assert groups[0] == [0, 1, 2]

    def test_standalone_events_get_own_group(self):
        events = [
            make_event("user_message", seq=1),
            make_event("assistant_message", seq=2),
        ]
        lines = to_lines(events)
        groups = _build_groups(lines, events)
        assert len(groups) == 2
        assert groups[0] == [0]
        assert groups[1] == [1]

    def test_cross_session_tool_use_does_not_stop_scan(self):
        """A tool_use from a different session should not close the current group."""
        events = [
            make_event("tool_use", call_id="c1", session_id="sess-1", seq=1),
            make_event("tool_use", call_id="c2", session_id="sess-2", seq=2),
            make_event("tool_result", call_id="c1", session_id="sess-1", seq=3),
        ]
        lines = to_lines(events)
        groups = _build_groups(lines, events)
        # c1's group should contain [0, 2], c2's should be [1]
        c1_group = None
        for g in groups:
            if 0 in g:
                c1_group = g
                break
        assert c1_group is not None
        assert 2 in c1_group  # tool_result paired with tool_use

    def test_same_session_tool_use_stops_scan(self):
        """A new tool_use from the same session should close the current group."""
        events = [
            make_event("tool_use", call_id="c1", session_id="sess-1", seq=1),
            make_event("tool_use", call_id="c2", session_id="sess-1", seq=2),
            make_event("tool_result", call_id="c1", session_id="sess-1", seq=3),
        ]
        lines = to_lines(events)
        groups = _build_groups(lines, events)
        # c1's group should only contain [0] since c2 interrupted it
        c1_group = None
        for g in groups:
            if 0 in g:
                c1_group = g
                break
        assert c1_group is not None
        assert 2 not in c1_group

    def test_cross_session_file_change_not_included(self):
        """file_change from a different session should NOT be in the group."""
        events = [
            make_event("tool_use", call_id="c1", session_id="sess-1", seq=1),
            make_event("file_change", session_id="sess-2", seq=2),
            make_event("tool_result", call_id="c1", session_id="sess-1", seq=3),
        ]
        lines = to_lines(events)
        groups = _build_groups(lines, events)
        c1_group = None
        for g in groups:
            if 0 in g:
                c1_group = g
                break
        assert 1 not in c1_group  # file_change from sess-2 excluded

    def test_subagent_tool_use_does_not_stop_parent_scan(self):
        """A tool_use from a subagent (same session, different agent_id) should not close parent group."""
        events = [
            make_event("tool_use", call_id="c1", session_id="sess-1", agent_id=None, seq=1),
            make_event("tool_use", call_id="c2", session_id="sess-1", agent_id="sub-1", seq=2),
            make_event("tool_result", call_id="c1", session_id="sess-1", agent_id=None, seq=3),
        ]
        lines = to_lines(events)
        groups = _build_groups(lines, events)
        c1_group = None
        for g in groups:
            if 0 in g:
                c1_group = g
                break
        assert c1_group is not None
        assert 2 in c1_group  # tool_result paired despite subagent interleaving

    def test_subagent_file_change_not_in_parent_group(self):
        """file_change from subagent should not be grouped with parent tool_use."""
        events = [
            make_event("tool_use", call_id="c1", session_id="sess-1", agent_id=None, seq=1),
            make_event("file_change", session_id="sess-1", agent_id="sub-1", seq=2),
            make_event("tool_result", call_id="c1", session_id="sess-1", agent_id=None, seq=3),
        ]
        lines = to_lines(events)
        groups = _build_groups(lines, events)
        c1_group = None
        for g in groups:
            if 0 in g:
                c1_group = g
                break
        assert 1 not in c1_group  # subagent's file_change excluded from parent group


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

class TestChunking:
    def test_single_group_fits_in_chunk(self):
        events = [make_event("user_message", seq=i) for i in range(5)]
        lines = to_lines(events)
        groups = _build_groups(lines, events)
        chunks = _chunk_groups(lines, events, groups, target_bytes=100_000)
        assert len(chunks) == 1

    def test_oversized_group_gets_own_chunk(self):
        """A single group larger than target_bytes gets its own chunk."""
        big_event = make_event("user_message", seq=1)
        big_event["text"] = "x" * 500_000
        events = [
            make_event("user_message", seq=0),
            big_event,
            make_event("user_message", seq=2),
        ]
        lines = to_lines(events)
        groups = _build_groups(lines, events)
        chunks = _chunk_groups(lines, events, groups, target_bytes=1000)
        # The big event should be isolated
        assert len(chunks) >= 2


# ---------------------------------------------------------------------------
# End-to-end via main()
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_main_writes_manifest(self):
        events = [
            make_event("user_message", seq=1),
            make_event("tool_use", call_id="c1", seq=2),
            make_event("tool_result", call_id="c1", seq=3),
        ]
        inp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        for e in events:
            inp.write(json.dumps(e) + "\n")
        inp.close()

        with tempfile.TemporaryDirectory() as outdir:
            main(["--input", inp.name, "--output-dir", outdir, "--target-bytes", "100000"])
            manifest_path = Path(outdir) / "manifest.json"
            assert manifest_path.exists()
            manifest = json.loads(manifest_path.read_text())
            assert "chunks" in manifest
            assert len(manifest["chunks"]) >= 1
            # Verify chunk files exist
            for chunk in manifest["chunks"]:
                chunk_path = Path(outdir) / chunk["path"]
                assert chunk_path.exists()
