"""Tests for validate_walkthrough_quality.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from validate_walkthrough_quality import validate_walkthrough


def _valid_walkthrough() -> dict:
    return {
        "meta": {"repo_root": "/tmp/project"},
        "overview": {
            "goal": "Explain the registration flow changes.",
            "summary": ["One", "Two", "Three"],
            "key_files": ["src/app.ts", "docs/notes.md"],
        },
        "steps": [
            {
                "id": "step-1",
                "title": "Create The Registration Route",
                "takeaway": "The public event page now has a single registration entry point.",
                "intent": "Unify the route shape before wiring form behavior.",
                "claims": [
                    {
                        "text": "A registration route was added.",
                        "confidence": "grounded",
                        "source_refs": [{"session_path": "chunk.jsonl", "line_start": 1, "line_end": 2}],
                    }
                ],
            }
        ],
    }


class TestValidateWalkthroughQuality:
    def test_accepts_reader_facing_walkthrough(self):
        report = validate_walkthrough(_valid_walkthrough())
        assert report.ok
        assert report.errors == []

    def test_rejects_chunk_metadata_titles_and_missing_takeaways(self):
        data = _valid_walkthrough()
        data["steps"][0]["title"] = "chunk-001: 395 events. User intents: wire auth."
        data["steps"][0].pop("takeaway")

        report = validate_walkthrough(data)

        assert not report.ok
        assert any("raw chunk metadata" in error for error in report.errors)
        assert any("missing takeaway" in error for error in report.errors)

    def test_rejects_raw_chunk_text_in_overview_summary_and_intent(self):
        data = _valid_walkthrough()
        data["overview"]["summary"][1] = "chunk-011: 168 events. User intents: set up terraform."
        data["steps"][0]["intent"] = "168 events. User intents: update the wizard."

        report = validate_walkthrough(data)

        assert not report.ok
        assert any("overview.summary item 2" in error for error in report.errors)
        assert any("intent still looks like raw chunk metadata" in error for error in report.errors)

    def test_rejects_missing_grounded_claim_refs(self):
        data = _valid_walkthrough()
        data["steps"][0]["claims"] = [{"text": "Looks done", "confidence": "inferred"}]

        report = validate_walkthrough(data)

        assert not report.ok
        assert any("no grounded claim" in error for error in report.errors)

    def test_rejects_noisy_overview_files(self):
        data = _valid_walkthrough()
        data["overview"]["key_files"] = [
            "/Users/austin/.claude/plans/plan.md",
            "/tmp/query.sql",
            "/tmp/project/src/app.ts",
        ]

        report = validate_walkthrough(data)

        assert not report.ok
        assert any("non-reader-facing paths" in error for error in report.errors)

    def test_rejects_too_many_final_steps(self):
        data = _valid_walkthrough()
        data["steps"] = [dict(data["steps"][0], id=f"step-{i}") for i in range(13)]

        report = validate_walkthrough(data)

        assert not report.ok
        assert any("max allowed" in error for error in report.errors)
