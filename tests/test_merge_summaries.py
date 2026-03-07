"""Tests for merge_summaries.py."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from merge_summaries import find_summary, merge_summaries, validate_summary


class TestFindSummary:
    def test_exact_hash_match_wins(self, tmp_path: Path):
        summaries_dir = tmp_path / "summaries"
        summaries_dir.mkdir()
        exact = summaries_dir / "chunk-0001.abcd1234.json"
        exact.write_text("{}", encoding="utf-8")
        (summaries_dir / "chunk-0001.deadbeef.json").write_text("{}", encoding="utf-8")

        found = find_summary(str(summaries_dir), "chunk-0001", "abcd1234ffff")
        assert found == str(exact)

    def test_missing_exact_match_returns_none(self, tmp_path: Path):
        summaries_dir = tmp_path / "summaries"
        summaries_dir.mkdir()
        (summaries_dir / "chunk-0001.deadbeef.json").write_text("{}", encoding="utf-8")

        found = find_summary(str(summaries_dir), "chunk-0001", "abcd1234ffff")
        assert found is None


class TestValidateSummary:
    def test_normalizes_string_evidence_shapes(self):
        result = validate_summary(
            {
                "chunk_id": "chunk-0001",
                "narrative": ["first", "second"],
                "commands": ["pytest -q [fail]"],
                "decisions": ["Use exact matches"],
                "errors": ["Command failed"],
                "files_changed": ["src/app.py"],
            }
        )

        assert result["narrative"] == "first second"
        assert result["commands"] == [{"cmd": "pytest -q", "status": "fail", "summary": ""}]
        assert result["decisions"] == [{"decision": "Use exact matches", "rationale": ""}]
        assert result["errors"] == [{"error": "Command failed", "resolution": ""}]
        assert result["files_changed"] == [{"path": "src/app.py", "kind": "unknown", "summary": ""}]


class TestFallbackMerge:
    def test_allow_fallback_emits_schema_valid_commands(self, tmp_path: Path):
        chunks_dir = tmp_path / "chunks"
        chunks_dir.mkdir()
        chunk_path = chunks_dir / "chunk-0001.jsonl"
        chunk_path.write_text(
            "\n".join(
                [
                    json.dumps({"kind": "user_message", "text": "Run the tests."}),
                    json.dumps({
                        "kind": "command",
                        "command": {"cmd": "pytest -q", "exit_code": 1, "output_preview": "1 failed"},
                    }),
                    json.dumps({
                        "kind": "file_change",
                        "file_change": {"path": "src/app.py", "kind": "modify"},
                    }),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        manifest_path = chunks_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "source": "normalized.jsonl",
                    "chunks": [
                        {
                            "chunk_id": "chunk-0001",
                            "path": "chunk-0001.jsonl",
                            "sha256": "abcd1234efgh5678",
                            "event_count": 3,
                            "time_range": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:01:00Z"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        output_path = tmp_path / "walkthrough.json"
        merge_summaries(
            str(manifest_path),
            str(tmp_path / "summaries"),
            str(output_path),
            repo_root="/tmp/project",
            allow_fallback=True,
        )

        walkthrough = json.loads(output_path.read_text(encoding="utf-8"))
        commands = walkthrough["steps"][0]["evidence"]["commands"]
        assert commands == [{"cmd": "pytest -q", "status": "fail", "summary": "1 failed"}]
        assert walkthrough["steps"][0]["evidence"]["files_changed"] == ["src/app.py"]
        assert walkthrough["meta"]["repo_root"] == "/tmp/project"
