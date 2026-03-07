"""Tests for normalize_claude.py."""

import json
import tempfile
from pathlib import Path

import pytest

# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from normalize_claude import normalize_claude, normalize_stream, make_synthetic_diff


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def write_jsonl(lines: list[dict]) -> str:
    """Write dicts as JSONL to a temp file, return path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for obj in lines:
        f.write(json.dumps(obj) + "\n")
    f.close()
    return f.name


def make_user_record(text: str, ts: str = "2026-01-01T00:00:00Z",
                     session_id: str = "sess-001") -> dict:
    return {
        "type": "user",
        "timestamp": ts,
        "sessionId": session_id,
        "message": {
            "content": [{"type": "text", "text": text}],
        },
    }


def make_assistant_record(text: str, ts: str = "2026-01-01T00:01:00Z") -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "model": "claude-sonnet-4-20250514",
            "content": [{"type": "text", "text": text}],
        },
    }


def make_tool_use_record(name: str, call_id: str, tool_input: dict,
                         ts: str = "2026-01-01T00:01:00Z") -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "model": "claude-sonnet-4-20250514",
            "content": [
                {"type": "tool_use", "id": call_id, "name": name, "input": tool_input},
            ],
        },
    }


def make_tool_result_record(call_id: str, output: str,
                            is_error: bool = False,
                            ts: str = "2026-01-01T00:02:00Z") -> dict:
    return {
        "type": "user",
        "timestamp": ts,
        "message": {
            "content": [
                {"type": "tool_result", "tool_use_id": call_id, "content": output,
                 "is_error": is_error},
            ],
        },
    }


# ---------------------------------------------------------------------------
# Turn indexing
# ---------------------------------------------------------------------------

class TestTurnIndexing:
    def test_first_user_message_is_turn_1(self):
        """After the fix, first user message should be turn_index=1, not 0."""
        path = write_jsonl([make_user_record("hello")])
        events, _ = normalize_stream(path)
        user_events = [e for e in events if e["kind"] == "user_message"]
        assert len(user_events) == 1
        assert user_events[0]["turn_index"] == 1

    def test_meta_event_is_turn_0(self):
        """Meta event should always be turn_index=0."""
        path = write_jsonl([
            {**make_user_record("hello"), "cwd": "/tmp/test"},
        ])
        events, _ = normalize_stream(path)
        meta_events = [e for e in events if e["kind"] == "meta"]
        assert len(meta_events) == 1
        assert meta_events[0]["turn_index"] == 0

    def test_second_user_message_is_turn_2(self):
        path = write_jsonl([
            make_user_record("first", ts="2026-01-01T00:00:00Z"),
            make_assistant_record("response", ts="2026-01-01T00:01:00Z"),
            make_user_record("second", ts="2026-01-01T00:02:00Z"),
        ])
        events, _ = normalize_stream(path)
        user_events = [e for e in events if e["kind"] == "user_message"]
        assert len(user_events) == 2
        assert user_events[0]["turn_index"] == 1
        assert user_events[1]["turn_index"] == 2

    def test_tool_result_only_record_does_not_increment_turn(self):
        """A user record with only tool_result (no text) should NOT increment turn."""
        path = write_jsonl([
            make_user_record("hello", ts="2026-01-01T00:00:00Z"),
            make_tool_use_record("Bash", "call-1", {"command": "ls"}, ts="2026-01-01T00:01:00Z"),
            make_tool_result_record("call-1", "file1.txt\n", ts="2026-01-01T00:02:00Z"),
            make_user_record("next question", ts="2026-01-01T00:03:00Z"),
        ])
        events, _ = normalize_stream(path)
        user_events = [e for e in events if e["kind"] == "user_message"]
        assert user_events[0]["turn_index"] == 1
        assert user_events[1]["turn_index"] == 2

    def test_assistant_events_share_turn_with_preceding_user(self):
        path = write_jsonl([
            make_user_record("hello", ts="2026-01-01T00:00:00Z"),
            make_assistant_record("hi there", ts="2026-01-01T00:01:00Z"),
        ])
        events, _ = normalize_stream(path)
        user_evt = [e for e in events if e["kind"] == "user_message"][0]
        asst_evt = [e for e in events if e["kind"] == "assistant_message"][0]
        assert user_evt["turn_index"] == asst_evt["turn_index"] == 1

    def test_blank_text_block_does_not_increment_turn(self):
        path = write_jsonl([
            {
                "type": "user",
                "timestamp": "2026-01-01T00:00:00Z",
                "sessionId": "sess-001",
                "message": {"content": [{"type": "text", "text": "   "}]},
            },
            make_user_record("real question", ts="2026-01-01T00:01:00Z"),
        ])
        events, _ = normalize_stream(path)
        user_events = [e for e in events if e["kind"] == "user_message"]
        assert len(user_events) == 1
        assert user_events[0]["turn_index"] == 1


# ---------------------------------------------------------------------------
# File change extraction
# ---------------------------------------------------------------------------

class TestFileChangeExtraction:
    def test_edit_emits_file_change(self):
        path = write_jsonl([
            make_user_record("fix the bug"),
            make_tool_use_record("Edit", "call-edit-1", {
                "file_path": "src/app.py",
                "old_string": "foo",
                "new_string": "bar",
            }),
        ])
        events, _ = normalize_stream(path)
        fc_events = [e for e in events if e["kind"] == "file_change"]
        assert len(fc_events) == 1
        assert fc_events[0]["file_change"]["path"] == "src/app.py"
        assert fc_events[0]["file_change"]["kind"] == "modify"
        assert "diff" in fc_events[0]["file_change"]

    def test_write_emits_file_change_create(self):
        path = write_jsonl([
            make_user_record("create a file"),
            make_tool_use_record("Write", "call-write-1", {
                "file_path": "new_file.py",
                "content": "print('hello')",
            }),
        ])
        events, _ = normalize_stream(path)
        fc_events = [e for e in events if e["kind"] == "file_change"]
        assert len(fc_events) == 1
        assert fc_events[0]["file_change"]["path"] == "new_file.py"
        assert fc_events[0]["file_change"]["kind"] == "create"

    def test_bash_emits_command(self):
        path = write_jsonl([
            make_user_record("run tests"),
            make_tool_use_record("Bash", "call-bash-1", {
                "command": "pytest tests/",
            }),
        ])
        events, _ = normalize_stream(path)
        cmd_events = [e for e in events if e["kind"] == "command"]
        assert len(cmd_events) == 1
        assert cmd_events[0]["command"]["cmd"] == "pytest tests/"


# ---------------------------------------------------------------------------
# Synthetic diff
# ---------------------------------------------------------------------------

class TestSyntheticDiff:
    def test_basic_diff(self):
        diff = make_synthetic_diff("old line", "new line", "test.py")
        assert "--- a/test.py" in diff
        assert "+++ b/test.py" in diff
        assert "-old line" in diff
        assert "+new line" in diff


# ---------------------------------------------------------------------------
# Provider field
# ---------------------------------------------------------------------------

class TestProviderField:
    def test_all_events_have_provider_claude(self):
        path = write_jsonl([
            make_user_record("hello"),
            make_assistant_record("hi"),
        ])
        events, _ = normalize_stream(path)
        for evt in events:
            assert evt["provider"] == "claude"


class TestMetaHandling:
    def test_early_system_record_backfills_session_id(self):
        path = write_jsonl([
            {
                "type": "system",
                "timestamp": "2026-01-01T00:00:00Z",
                "subtype": "boot",
            },
            make_user_record("hello", ts="2026-01-01T00:01:00Z", session_id="sess-xyz"),
        ])
        events, session_id = normalize_stream(path)
        assert session_id == "sess-xyz"
        assert all(evt["session_id"] == "sess-xyz" for evt in events)

    def test_meta_emitted_once_and_collects_fields(self):
        path = write_jsonl([
            {
                **make_user_record("hello"),
                "cwd": "/tmp/project",
                "version": "1.2.3",
                "gitBranch": "feature/test",
            },
            make_assistant_record("hi"),
        ])
        events, _ = normalize_stream(path)
        meta_events = [e for e in events if e["kind"] == "meta"]
        assert len(meta_events) == 1
        meta = meta_events[0]["meta"]
        assert meta["cwd"] == "/tmp/project"
        assert meta["cli_version"] == "1.2.3"
        assert meta["git"]["branch"] == "feature/test"
        assert meta["model"] == "claude-sonnet-4-20250514"

    def test_expected_session_id_skips_mismatched_prelude_records(self):
        path = write_jsonl([
            make_user_record("[Request interrupted by user for tool use]", session_id="old-session"),
            make_user_record("real start", session_id="sess-xyz", ts="2026-01-01T00:00:01Z"),
        ])
        events, session_id = normalize_stream(path, expected_session_id="sess-xyz")
        user_events = [e for e in events if e["kind"] == "user_message"]
        assert session_id == "sess-xyz"
        assert len(user_events) == 1
        assert user_events[0]["text"] == "real start"
        assert user_events[0]["turn_index"] == 1


# ---------------------------------------------------------------------------
# Sequence numbering
# ---------------------------------------------------------------------------

class TestSequencing:
    def test_seq_is_monotonically_increasing(self):
        path = write_jsonl([
            make_user_record("first", ts="2026-01-01T00:00:00Z"),
            make_assistant_record("reply", ts="2026-01-01T00:01:00Z"),
            make_user_record("second", ts="2026-01-01T00:02:00Z"),
        ])
        events, _ = normalize_stream(path)
        seqs = [e["seq"] for e in events]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)  # no duplicates


# ---------------------------------------------------------------------------
# Screenshot extraction
# ---------------------------------------------------------------------------

class TestScreenshotExtraction:
    def test_image_tool_result_emits_screenshot(self):
        path = write_jsonl([
            make_user_record("look at screen"),
            {
                "type": "user",
                "timestamp": "2026-01-01T00:02:00Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call-ss-1",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": "iVBORw0KGgo=",
                                    },
                                },
                            ],
                        },
                    ],
                },
            },
        ])
        events, _ = normalize_stream(path)
        ss_events = [e for e in events if e["kind"] == "screenshot"]
        assert len(ss_events) == 1
        assert ss_events[0]["media"]["data_b64"] == "iVBORw0KGgo="
        assert ss_events[0]["media"]["source"] == "session"


class TestSubagentLinking:
    def test_progress_records_link_subagent_to_parent_call(self, tmp_path: Path):
        main_path = tmp_path / "main.jsonl"
        subagent_dir = tmp_path / "main" / "subagents"
        subagent_dir.mkdir(parents=True)
        sub_path = subagent_dir / "agent-agent-123.jsonl"
        out_path = tmp_path / "normalized.jsonl"

        main_records = [
            make_user_record("delegate this", session_id="sess-001"),
            make_tool_use_record("Agent", "call-agent-1", {"task": "investigate"}),
            {
                "type": "progress",
                "timestamp": "2026-01-01T00:01:30Z",
                "data": {
                    "agentId": "agent-123",
                    "parentToolUseID": "call-agent-1",
                },
            },
        ]
        subagent_records = [
            make_user_record("subagent work", session_id="sub-sess"),
            make_assistant_record("done", ts="2026-01-01T00:02:00Z"),
        ]
        main_path.write_text("".join(json.dumps(r) + "\n" for r in main_records), encoding="utf-8")
        sub_path.write_text("".join(json.dumps(r) + "\n" for r in subagent_records), encoding="utf-8")

        normalize_claude(str(main_path), [str(sub_path)], str(out_path))

        events = [
            json.loads(line)
            for line in out_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        sub_events = [evt for evt in events if evt.get("agent_id") == "agent-123"]
        assert sub_events
        assert all(evt["session_id"] == "sess-001" for evt in sub_events)
        assert all(evt.get("parent_call_id") == "call-agent-1" for evt in sub_events)
        assert all(evt.get("parent_link_basis") == "progress" for evt in sub_events)
