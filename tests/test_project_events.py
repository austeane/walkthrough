"""Tests for project_events.py."""

import json
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from project_events import project_events, compress_tool_result, build_call_index


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_event(kind: str, **kwargs) -> dict:
    evt = {
        "seq": kwargs.get("seq", 1),
        "kind": kind,
        "session_id": "sess-1",
        "turn_index": 1,
        "ts": "2026-01-01T00:00:00Z",
        "source_line": 1,
        "source_path": "test.jsonl",
        "provider": "claude",
    }
    evt.update(kwargs)
    return evt


def project(events: list[dict], **kwargs) -> list[dict]:
    """Run project_events on a list of events, return output events."""
    inp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for e in events:
        inp.write(json.dumps(e) + "\n")
    inp.close()

    out = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
    out.close()

    project_events(inp.name, out.name, **kwargs)

    result = []
    with open(out.name) as f:
        for line in f:
            line = line.strip()
            if line:
                result.append(json.loads(line))
    return result


# ---------------------------------------------------------------------------
# Drop kinds
# ---------------------------------------------------------------------------

class TestDropKinds:
    def test_file_snapshot_dropped(self):
        events = [
            make_event("user_message", text="hello"),
            make_event("file_snapshot", text='{"files": ["a.py"]}'),
        ]
        result = project(events)
        kinds = [e["kind"] for e in result]
        assert "file_snapshot" not in kinds
        assert "user_message" in kinds

    def test_turn_context_dropped(self):
        events = [
            make_event("user_message", text="hello"),
            make_event("turn_context", text="context data"),
        ]
        result = project(events)
        kinds = [e["kind"] for e in result]
        assert "turn_context" not in kinds

    def test_compaction_dropped(self):
        events = [
            make_event("user_message", text="hello"),
            make_event("compaction", text="compacted"),
        ]
        result = project(events)
        kinds = [e["kind"] for e in result]
        assert "compaction" not in kinds

    def test_keep_snapshots_flag(self):
        events = [
            make_event("file_snapshot", text='{"files": ["a.py"]}'),
        ]
        result = project(events, keep_snapshots=True)
        assert len(result) == 1
        assert result[0]["kind"] == "file_snapshot"

    def test_keep_turn_context_flag(self):
        events = [
            make_event("turn_context", text="context"),
        ]
        result = project(events, keep_turn_context=True)
        assert len(result) == 1
        assert result[0]["kind"] == "turn_context"


# ---------------------------------------------------------------------------
# Tool result compression
# ---------------------------------------------------------------------------

class TestToolResultCompression:
    def test_success_tool_result_compressed(self):
        events = [
            make_event("tool_use", tool={"name": "Bash", "call_id": "c1", "input": {}}),
            make_event("tool_result", tool={"call_id": "c1", "output": "line1\nline2\nline3"}),
        ]
        result = project(events)
        tr = [e for e in result if e["kind"] == "tool_result"][0]
        assert tr["tool"]["compressed"] is True
        assert tr["tool"]["success"] is True
        assert tr["tool"]["output_lines"] == 3
        assert "output" not in tr["tool"]  # full output removed

    def test_error_tool_result_kept_full(self):
        events = [
            make_event("tool_use", tool={"name": "Bash", "call_id": "c1", "input": {}}),
            make_event("tool_result", tool={
                "call_id": "c1",
                "output": "Error: file not found",
                "is_error": True,
            }),
        ]
        result = project(events)
        tr = [e for e in result if e["kind"] == "tool_result"][0]
        assert "compressed" not in tr.get("tool", {})
        assert tr["tool"]["output"] == "Error: file not found"
        assert tr["tool"]["is_error"] is True


# ---------------------------------------------------------------------------
# Screenshot base64 stripping
# ---------------------------------------------------------------------------

class TestScreenshotStripping:
    def test_screenshot_data_b64_removed(self):
        events = [
            make_event("screenshot", media={
                "data_b64": "iVBORw0KGgo=",
                "mime_type": "image/png",
                "context": "tool output",
                "source": "session",
            }),
        ]
        result = project(events)
        assert len(result) == 1
        assert result[0]["kind"] == "screenshot"
        assert "data_b64" not in result[0]["media"]
        # Other media fields preserved
        assert result[0]["media"]["mime_type"] == "image/png"
        assert result[0]["media"]["context"] == "tool output"
        assert result[0]["media"]["source"] == "session"

    def test_screenshot_without_data_b64_unchanged(self):
        events = [
            make_event("screenshot", media={
                "mime_type": "image/png",
                "context": "already stripped",
            }),
        ]
        result = project(events)
        assert len(result) == 1
        assert result[0]["media"]["context"] == "already stripped"


# ---------------------------------------------------------------------------
# Full fidelity preservation
# ---------------------------------------------------------------------------

class TestFullFidelity:
    def test_user_message_unchanged(self):
        events = [make_event("user_message", text="hello world")]
        result = project(events)
        assert len(result) == 1
        assert result[0]["text"] == "hello world"

    def test_assistant_message_unchanged(self):
        events = [make_event("assistant_message", text="I'll help")]
        result = project(events)
        assert len(result) == 1
        assert result[0]["text"] == "I'll help"

    def test_file_change_unchanged(self):
        events = [make_event("file_change", file_change={
            "path": "src/app.py", "kind": "modify", "diff": "-old\n+new",
        })]
        result = project(events)
        assert len(result) == 1
        assert result[0]["file_change"]["path"] == "src/app.py"

    def test_command_unchanged(self):
        events = [make_event("command", command={
            "cmd": "npm test", "exit_code": 0,
        })]
        result = project(events)
        assert len(result) == 1
        assert result[0]["command"]["cmd"] == "npm test"
