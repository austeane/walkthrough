"""Tests for normalize_codex.py."""

import json
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from normalize_codex import normalize_codex, coerce_int, parse_jsonish


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def write_jsonl(lines: list[dict]) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for obj in lines:
        f.write(json.dumps(obj) + "\n")
    f.close()
    return f.name


def read_events(path: str) -> list[dict]:
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def make_session_meta(ts: str = "2026-01-01T00:00:00Z") -> dict:
    return {
        "timestamp": ts,
        "type": "session_meta",
        "payload": {
            "id": "codex-sess-001",
            "cwd": "/tmp/project",
            "model_provider": "o4-mini",
        },
    }


def make_user_message(text: str, ts: str = "2026-01-01T00:01:00Z") -> dict:
    return {
        "timestamp": ts,
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": text}],
        },
    }


def make_assistant_message(text: str, ts: str = "2026-01-01T00:02:00Z") -> dict:
    return {
        "timestamp": ts,
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text}],
        },
    }


def make_custom_tool_call(name: str, call_id: str, arguments: dict,
                          ts: str = "2026-01-01T00:02:00Z") -> dict:
    return {
        "timestamp": ts,
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call",
            "name": name,
            "call_id": call_id,
            "input": json.dumps(arguments),
        },
    }


def make_custom_tool_output(call_id: str, output: str,
                            ts: str = "2026-01-01T00:03:00Z") -> dict:
    return {
        "timestamp": ts,
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call_output",
            "call_id": call_id,
            "output": output,
        },
    }


# ---------------------------------------------------------------------------
# Turn indexing
# ---------------------------------------------------------------------------

class TestTurnIndexing:
    def test_first_user_is_turn_1(self):
        inp = write_jsonl([
            make_session_meta(),
            make_user_message("hello"),
        ])
        out = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
        normalize_codex(inp, out)
        events = read_events(out)
        user_events = [e for e in events if e["kind"] == "user_message"]
        assert len(user_events) == 1
        assert user_events[0]["turn_index"] == 1

    def test_meta_is_turn_0(self):
        inp = write_jsonl([
            make_session_meta(),
            make_user_message("hello"),
        ])
        out = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
        normalize_codex(inp, out)
        events = read_events(out)
        meta_events = [e for e in events if e["kind"] == "meta"]
        assert len(meta_events) == 1
        assert meta_events[0]["turn_index"] == 0

    def test_second_user_is_turn_2(self):
        inp = write_jsonl([
            make_session_meta(),
            make_user_message("first", ts="2026-01-01T00:01:00Z"),
            make_assistant_message("reply", ts="2026-01-01T00:02:00Z"),
            make_user_message("second", ts="2026-01-01T00:03:00Z"),
        ])
        out = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
        normalize_codex(inp, out)
        events = read_events(out)
        user_events = [e for e in events if e["kind"] == "user_message"]
        assert user_events[0]["turn_index"] == 1
        assert user_events[1]["turn_index"] == 2

    def test_blank_user_message_does_not_advance_turn(self):
        inp = write_jsonl([
            make_session_meta(),
            {
                "timestamp": "2026-01-01T00:01:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "   "}],
                },
            },
            make_assistant_message("reply", ts="2026-01-01T00:02:00Z"),
            make_user_message("real question", ts="2026-01-01T00:03:00Z"),
        ])
        out = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
        normalize_codex(inp, out)
        events = read_events(out)
        user_events = [e for e in events if e["kind"] == "user_message"]
        assert len(user_events) == 1
        assert user_events[0]["turn_index"] == 1


# ---------------------------------------------------------------------------
# file_change extraction from custom_tool_call
# ---------------------------------------------------------------------------

class TestFileChangeExtraction:
    def test_fileChange_emits_file_change_event(self):
        inp = write_jsonl([
            make_session_meta(),
            make_user_message("fix it"),
            make_custom_tool_call("fileChange", "call-fc-1", {
                "path": "/tmp/project/src/app.py",
                "kind": "modify",
                "diff": "--- a/src/app.py\n+++ b/src/app.py\n-old\n+new",
            }),
        ])
        out = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
        normalize_codex(inp, out)
        events = read_events(out)
        fc_events = [e for e in events if e["kind"] == "file_change"]
        assert len(fc_events) == 1
        assert fc_events[0]["file_change"]["path"] == "/tmp/project/src/app.py"
        assert fc_events[0]["file_change"]["kind"] == "modify"
        assert "diff" in fc_events[0]["file_change"]

    def test_fileChange_case_insensitive(self):
        """Tool name matching should be case-insensitive."""
        inp = write_jsonl([
            make_session_meta(),
            make_user_message("fix it"),
            make_custom_tool_call("filechange", "call-fc-2", {
                "path": "src/index.ts",
                "kind": "create",
            }),
        ])
        out = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
        normalize_codex(inp, out)
        events = read_events(out)
        fc_events = [e for e in events if e["kind"] == "file_change"]
        assert len(fc_events) == 1

    def test_fileChange_also_emits_tool_use(self):
        """file_change is synthetic; the original tool_use should still exist."""
        inp = write_jsonl([
            make_session_meta(),
            make_user_message("fix it"),
            make_custom_tool_call("fileChange", "call-fc-3", {
                "path": "src/app.py",
                "kind": "modify",
            }),
        ])
        out = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
        normalize_codex(inp, out)
        events = read_events(out)
        tool_use_events = [e for e in events if e["kind"] == "tool_use"]
        fc_events = [e for e in events if e["kind"] == "file_change"]
        assert len(tool_use_events) >= 1
        assert len(fc_events) == 1


# ---------------------------------------------------------------------------
# command extraction from custom_tool_call
# ---------------------------------------------------------------------------

class TestCommandExtraction:
    def test_commandExecution_emits_command_event(self):
        inp = write_jsonl([
            make_session_meta(),
            make_user_message("run tests"),
            make_custom_tool_call("commandExecution", "call-cmd-1", {
                "command": "npm test",
                "exitCode": 0,
                "status": "pass",
            }),
        ])
        out = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
        normalize_codex(inp, out)
        events = read_events(out)
        cmd_events = [e for e in events if e["kind"] == "command"]
        assert len(cmd_events) == 1
        assert cmd_events[0]["command"]["cmd"] == "npm test"
        assert cmd_events[0]["command"]["exit_code"] == 0

    def test_command_from_tool_output(self):
        """Commands can also appear in custom_tool_call_output with structured JSON."""
        inp = write_jsonl([
            make_session_meta(),
            make_user_message("run it"),
            make_custom_tool_call("commandExecution", "call-cmd-2", {
                "command": "make build",
            }),
            make_custom_tool_output("call-cmd-2", json.dumps({
                "command": "make build",
                "exitCode": 1,
                "status": "fail",
                "output": "error: undefined reference",
            })),
        ])
        out = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
        normalize_codex(inp, out)
        events = read_events(out)
        cmd_events = [e for e in events if e["kind"] == "command"]
        # Should have at least 2: one from tool_call args, one from output
        assert len(cmd_events) >= 2
        exit_codes = [c["command"].get("exit_code") for c in cmd_events]
        assert 1 in exit_codes


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_coerce_int_basic(self):
        assert coerce_int(0) == 0
        assert coerce_int(1) == 1
        assert coerce_int("42") == 42
        assert coerce_int(None) is None
        assert coerce_int(True) is None  # booleans rejected
        assert coerce_int("abc") is None

    def test_parse_jsonish_string(self):
        assert parse_jsonish('{"a": 1}') == {"a": 1}
        assert parse_jsonish("not json") == "not json"
        assert parse_jsonish(42) == 42


# ---------------------------------------------------------------------------
# Provider field
# ---------------------------------------------------------------------------

class TestProviderField:
    def test_all_events_have_provider_codex(self):
        inp = write_jsonl([
            make_session_meta(),
            make_user_message("hello"),
        ])
        out = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
        normalize_codex(inp, out)
        events = read_events(out)
        for evt in events:
            assert evt["provider"] == "codex"


class TestMetaPreservation:
    def test_session_meta_preserves_git_metadata(self):
        inp = write_jsonl([
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": "codex-sess-001",
                    "cwd": "/tmp/project",
                    "model_provider": "o4-mini",
                    "git": {
                        "branch": "main",
                        "commit": "abc123",
                        "dirty": True,
                        "repository_url": "https://example.com/repo.git",
                    },
                },
            },
        ])
        out = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
        normalize_codex(inp, out)
        events = read_events(out)
        meta = [e for e in events if e["kind"] == "meta"][0]["meta"]
        assert meta["git"]["branch"] == "main"
        assert meta["git"]["commit"] == "abc123"
        assert meta["git"]["dirty"] is True
        assert meta["git"]["repository_url"] == "https://example.com/repo.git"


# ---------------------------------------------------------------------------
# Screenshot detection from file paths in tool output
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# aggregate_diff and plan_update
# ---------------------------------------------------------------------------

class TestAggregateDiff:
    def test_turn_diff_updated_as_event_msg(self):
        inp = write_jsonl([
            make_session_meta(),
            make_user_message("do something"),
            {
                "timestamp": "2026-01-01T00:03:00Z",
                "type": "event_msg",
                "payload": {
                    "type": "turn/diff/updated",
                    "diff": "--- a/src/app.py\n+++ b/src/app.py\n-old\n+new",
                },
            },
        ])
        out = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
        normalize_codex(inp, out)
        events = read_events(out)
        diff_events = [e for e in events if e["kind"] == "aggregate_diff"]
        assert len(diff_events) == 1
        assert "old" in diff_events[0]["text"]

    def test_turn_diff_updated_as_top_level(self):
        inp = write_jsonl([
            make_session_meta(),
            make_user_message("do something"),
            {
                "timestamp": "2026-01-01T00:03:00Z",
                "type": "turn/diff/updated",
                "payload": {
                    "diff": "cumulative diff here",
                },
            },
        ])
        out = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
        normalize_codex(inp, out)
        events = read_events(out)
        diff_events = [e for e in events if e["kind"] == "aggregate_diff"]
        assert len(diff_events) == 1


class TestPlanUpdate:
    def test_plan_update_as_event_msg(self):
        inp = write_jsonl([
            make_session_meta(),
            make_user_message("plan the work"),
            {
                "timestamp": "2026-01-01T00:03:00Z",
                "type": "event_msg",
                "payload": {
                    "type": "turn/plan/updated",
                    "plan": "1. First step\n2. Second step",
                },
            },
        ])
        out = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
        normalize_codex(inp, out)
        events = read_events(out)
        plan_events = [e for e in events if e["kind"] == "plan_update"]
        assert len(plan_events) == 1


class TestCompaction:
    def test_compacted_record_emits_compaction_event(self):
        inp = write_jsonl([
            make_session_meta(),
            make_user_message("do the work"),
            {
                "timestamp": "2026-01-01T00:03:00Z",
                "type": "compacted",
                "payload": {
                    "message": "",
                    "replacement_history": [{"type": "message"}, {"type": "message"}],
                },
            },
        ])
        out = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
        normalize_codex(inp, out)
        events = read_events(out)
        compaction_events = [e for e in events if e["kind"] == "compaction"]
        assert len(compaction_events) == 1
        assert "replacement_history items: 2" in compaction_events[0]["text"]

    def test_plan_update_as_top_level(self):
        inp = write_jsonl([
            make_session_meta(),
            make_user_message("plan the work"),
            {
                "timestamp": "2026-01-01T00:03:00Z",
                "type": "turn/plan/updated",
                "payload": {
                    "plan": ["step 1", "step 2"],
                },
            },
        ])
        out = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
        normalize_codex(inp, out)
        events = read_events(out)
        plan_events = [e for e in events if e["kind"] == "plan_update"]
        assert len(plan_events) == 1


class TestScreenshotDetection:
    def test_image_path_in_output_emits_screenshot(self):
        inp = write_jsonl([
            make_session_meta(),
            make_user_message("take screenshot"),
            {
                "timestamp": "2026-01-01T00:02:00Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "screenshot",
                    "call_id": "call-ss-1",
                    "arguments": "{}",
                },
            },
            {
                "timestamp": "2026-01-01T00:03:00Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "call-ss-1",
                    "output": "Screenshot saved to /tmp/screenshot.png",
                },
            },
        ])
        out = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name
        normalize_codex(inp, out)
        events = read_events(out)
        ss_events = [e for e in events if e["kind"] == "screenshot"]
        assert len(ss_events) == 1
        assert ss_events[0]["media"]["file_path"] == "/tmp/screenshot.png"
