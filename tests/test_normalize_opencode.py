"""Tests for normalize_opencode.py."""

import json
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from normalize_opencode import normalize_opencode


def write_jsonl(lines: list[dict]) -> str:
    """Write dicts as JSONL to a temp file and return the path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for obj in lines:
        f.write(json.dumps(obj) + "\n")
    f.close()
    return f.name


def read_jsonl(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def base_session() -> dict:
    return {
        "type": "session",
        "info": {
            "id": "ses_001",
            "directory": "/tmp/project",
            "title": "OpenCode test session",
            "version": "1.1.12",
            "time": {"created": 1735689600000, "updated": 1735689720000},
        },
    }


def user_message(text: str, *, message_id: str = "msg_user_1", created: int = 1735689600000, diffs=None) -> dict:
    summary = {"diffs": diffs} if diffs is not None else None
    info = {
        "id": message_id,
        "sessionID": "ses_001",
        "role": "user",
        "time": {"created": created},
        "agent": "build",
        "model": {"providerID": "anthropic", "modelID": "claude-sonnet-4"},
    }
    if summary is not None:
        info["summary"] = summary
    return {
        "type": "message",
        "info": info,
        "parts": [
            {
                "id": f"part_{message_id}",
                "sessionID": "ses_001",
                "messageID": message_id,
                "type": "text",
                "text": text,
            }
        ],
    }


def assistant_message(parts: list[dict], *, message_id: str = "msg_asst_1", parent_id: str = "msg_user_1") -> dict:
    return {
        "type": "message",
        "info": {
            "id": message_id,
            "sessionID": "ses_001",
            "role": "assistant",
            "parentID": parent_id,
            "providerID": "anthropic",
            "modelID": "claude-sonnet-4",
            "agent": "build",
            "mode": "build",
            "path": {"cwd": "/tmp/project", "root": "/tmp/project"},
            "cost": 0,
            "tokens": {
                "input": 1,
                "output": 1,
                "reasoning": 0,
                "cache": {"read": 0, "write": 0},
            },
            "time": {"created": 1735689660000, "completed": 1735689720000},
        },
        "parts": parts,
    }


class TestNormalizeOpenCode:
    def test_basic_messages_and_reasoning(self, tmp_path: Path):
        input_path = write_jsonl([
            base_session(),
            user_message("Explain the bug"),
            assistant_message([
                {
                    "id": "part_reason",
                    "sessionID": "ses_001",
                    "messageID": "msg_asst_1",
                    "type": "reasoning",
                    "text": "Need to inspect the failing path.",
                    "time": {"start": 1735689661000, "end": 1735689662000},
                },
                {
                    "id": "part_text",
                    "sessionID": "ses_001",
                    "messageID": "msg_asst_1",
                    "type": "text",
                    "text": "I found the root cause in the auth middleware.",
                    "time": {"start": 1735689663000, "end": 1735689664000},
                },
            ]),
        ])
        output_path = tmp_path / "normalized.jsonl"

        normalize_opencode(input_path, str(output_path))
        events = read_jsonl(str(output_path))

        assert events[0]["kind"] == "meta"
        assert events[0]["provider"] == "opencode"
        assert events[0]["meta"]["cwd"] == "/tmp/project"
        assert events[0]["meta"]["model"] == "anthropic/claude-sonnet-4"

        user = next(evt for evt in events if evt["kind"] == "user_message")
        reasoning = next(evt for evt in events if evt["kind"] == "reasoning")
        assistant = next(evt for evt in events if evt["kind"] == "assistant_message")

        assert user["turn_index"] == 1
        assert reasoning["turn_index"] == 1
        assert assistant["turn_index"] == 1

    def test_completed_bash_tool_emits_command_and_screenshot(self, tmp_path: Path):
        input_path = write_jsonl([
            base_session(),
            user_message("Run a command"),
            assistant_message([
                {
                    "id": "part_tool",
                    "sessionID": "ses_001",
                    "messageID": "msg_asst_1",
                    "type": "tool",
                    "callID": "call_bash_1",
                    "tool": "bash",
                    "state": {
                        "status": "completed",
                        "input": {"command": "ls"},
                        "output": "file1.txt\nfile2.txt",
                        "title": "List files",
                        "metadata": {"exit": 0},
                        "time": {"start": 1735689661000, "end": 1735689662000},
                        "attachments": [
                            {
                                "id": "part_file_1",
                                "sessionID": "ses_001",
                                "messageID": "msg_asst_1",
                                "type": "file",
                                "mime": "image/png",
                                "filename": "capture.png",
                                "url": "data:image/png;base64,Zm9v",
                            }
                        ],
                    },
                }
            ]),
        ])
        output_path = tmp_path / "normalized.jsonl"

        normalize_opencode(input_path, str(output_path))
        events = read_jsonl(str(output_path))

        tool_use = next(evt for evt in events if evt["kind"] == "tool_use")
        command = next(evt for evt in events if evt["kind"] == "command")
        tool_result = next(evt for evt in events if evt["kind"] == "tool_result")
        screenshot = next(evt for evt in events if evt["kind"] == "screenshot")

        assert tool_use["tool"]["name"] == "bash"
        assert command["command"]["cmd"] == "ls"
        assert command["command"]["exit_code"] == 0
        assert command["command"]["status"] == "pass"
        assert tool_result["tool"]["output"] == "file1.txt\nfile2.txt"
        assert screenshot["media"]["data_b64"] == "Zm9v"
        assert screenshot["media"]["tool_name"] == "bash"

    def test_user_summary_diffs_emit_file_changes(self, tmp_path: Path):
        input_path = write_jsonl([
            base_session(),
            user_message(
                "Apply the auth fix",
                diffs=[
                    {
                        "file": "src/auth.ts",
                        "before": "const enabled = false;\n",
                        "after": "const enabled = true;\n",
                        "additions": 1,
                        "deletions": 1,
                        "status": "modified",
                    }
                ],
            ),
            assistant_message([
                {
                    "id": "part_text",
                    "sessionID": "ses_001",
                    "messageID": "msg_asst_1",
                    "type": "text",
                    "text": "Updated the auth flag.",
                }
            ]),
        ])
        output_path = tmp_path / "normalized.jsonl"

        normalize_opencode(input_path, str(output_path))
        events = read_jsonl(str(output_path))

        file_change = next(evt for evt in events if evt["kind"] == "file_change")
        assert file_change["file_change"]["path"] == "src/auth.ts"
        assert file_change["file_change"]["kind"] == "modify"
        assert "--- a/src/auth.ts" in file_change["file_change"]["diff"]
        assert "+++ b/src/auth.ts" in file_change["file_change"]["diff"]

    def test_compaction_part_emits_compaction_event(self, tmp_path: Path):
        input_path = write_jsonl([
            base_session(),
            user_message("Continue"),
            assistant_message([
                {
                    "id": "part_compaction",
                    "sessionID": "ses_001",
                    "messageID": "msg_asst_1",
                    "type": "compaction",
                    "auto": True,
                    "overflow": True,
                }
            ]),
        ])
        output_path = tmp_path / "normalized.jsonl"

        normalize_opencode(input_path, str(output_path))
        events = read_jsonl(str(output_path))

        compaction = next(evt for evt in events if evt["kind"] == "compaction")
        assert "automatically" in compaction["text"]
        assert "overflow" in compaction["text"]
