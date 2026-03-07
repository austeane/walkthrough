"""Tests for validate_pipeline.py."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from validate_pipeline import validate_normalized


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.write_text("".join(json.dumps(evt) + "\n" for evt in events), encoding="utf-8")


class TestValidateNormalized:
    def test_accepts_subagent_streams_with_independent_turn_sequences(self, tmp_path: Path):
        path = tmp_path / "normalized.jsonl"
        _write_jsonl(
            path,
            [
                {
                    "seq": 1,
                    "kind": "meta",
                    "turn_index": 0,
                    "ts": "2026-01-01T00:00:00Z",
                    "provider": "claude",
                    "session_id": "sess-001",
                    "source_path": "/tmp/main.jsonl",
                },
                {
                    "seq": 2,
                    "kind": "user_message",
                    "turn_index": 1,
                    "ts": "2026-01-01T00:00:01Z",
                    "provider": "claude",
                    "session_id": "sess-001",
                    "source_path": "/tmp/main.jsonl",
                    "text": "delegate",
                },
                {
                    "seq": 3,
                    "kind": "meta",
                    "turn_index": 0,
                    "ts": "2026-01-01T00:00:02Z",
                    "provider": "claude",
                    "session_id": "sess-001",
                    "agent_id": "agent-1",
                    "source_path": "/tmp/agent.jsonl",
                },
                {
                    "seq": 4,
                    "kind": "user_message",
                    "turn_index": 1,
                    "ts": "2026-01-01T00:00:03Z",
                    "provider": "claude",
                    "session_id": "sess-001",
                    "agent_id": "agent-1",
                    "source_path": "/tmp/agent.jsonl",
                    "text": "subtask",
                },
            ],
        )

        result = validate_normalized(str(path))
        assert result.failed == 0

    def test_fails_on_empty_session_id(self, tmp_path: Path):
        path = tmp_path / "normalized.jsonl"
        _write_jsonl(
            path,
            [
                {
                    "seq": 1,
                    "kind": "meta",
                    "turn_index": 0,
                    "ts": "2026-01-01T00:00:00Z",
                    "provider": "claude",
                    "session_id": "",
                    "source_path": "/tmp/main.jsonl",
                }
            ],
        )

        result = validate_normalized(str(path))
        assert result.failed >= 1
        assert any("missing session_id" in message for message in result.messages)

    def test_fails_on_non_increasing_seq(self, tmp_path: Path):
        path = tmp_path / "normalized.jsonl"
        _write_jsonl(
            path,
            [
                {
                    "seq": 2,
                    "kind": "meta",
                    "turn_index": 0,
                    "ts": "2026-01-01T00:00:00Z",
                    "provider": "codex",
                    "session_id": "sess-001",
                    "source_path": "/tmp/main.jsonl",
                },
                {
                    "seq": 2,
                    "kind": "user_message",
                    "turn_index": 1,
                    "ts": "2026-01-01T00:00:01Z",
                    "provider": "codex",
                    "session_id": "sess-001",
                    "source_path": "/tmp/main.jsonl",
                    "text": "hello",
                },
            ],
        )

        result = validate_normalized(str(path))
        assert result.failed >= 1
        assert any("seq is not strictly increasing" in message for message in result.messages)

    def test_fails_when_first_user_turn_is_not_one(self, tmp_path: Path):
        path = tmp_path / "normalized.jsonl"
        _write_jsonl(
            path,
            [
                {
                    "seq": 1,
                    "kind": "meta",
                    "turn_index": 0,
                    "ts": "2026-01-01T00:00:00Z",
                    "provider": "claude",
                    "session_id": "sess-001",
                    "source_path": "/tmp/main.jsonl",
                },
                {
                    "seq": 2,
                    "kind": "user_message",
                    "turn_index": 2,
                    "ts": "2026-01-01T00:00:01Z",
                    "provider": "claude",
                    "session_id": "sess-001",
                    "source_path": "/tmp/main.jsonl",
                    "text": "hello",
                },
            ],
        )

        result = validate_normalized(str(path))
        assert result.failed >= 1
        assert any("expected 1" in message for message in result.messages)
