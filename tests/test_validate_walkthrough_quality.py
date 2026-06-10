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


def _session_file(tmp_path: Path, lines: int = 10) -> Path:
    session = tmp_path / "normalized.jsonl"
    session.write_text("\n".join(f'{{"seq": {i}}}' for i in range(lines)) + "\n", encoding="utf-8")
    return session


def _walkthrough_with_refs(tmp_path: Path) -> dict:
    session = _session_file(tmp_path)
    data = _valid_walkthrough()
    data["meta"]["sessions"] = [{"provider": "claude", "path": str(session)}]
    data["steps"][0]["claims"][0]["source_refs"] = [
        {"session_path": str(session), "line_start": 1, "line_end": 3}
    ]
    return data


class TestSourceRefIntegrity:
    def test_valid_refs_pass_fs_checks(self, tmp_path: Path):
        data = _walkthrough_with_refs(tmp_path)

        report = validate_walkthrough(data, base_dir=str(tmp_path))

        assert report.ok
        assert not any("source_refs" in w for w in report.warnings)

    def test_missing_ref_file_fails_with_base_dir(self, tmp_path: Path):
        data = _walkthrough_with_refs(tmp_path)
        data["steps"][0]["claims"][0]["source_refs"] = [
            {"session_path": str(tmp_path / "gone.jsonl"), "line_start": 1, "line_end": 3}
        ]

        report = validate_walkthrough(data, base_dir=str(tmp_path))

        assert not report.ok
        assert any("do not exist" in error for error in report.errors)

    def test_fs_checks_skipped_without_base_dir(self, tmp_path: Path):
        data = _walkthrough_with_refs(tmp_path)
        data["steps"][0]["claims"][0]["source_refs"] = [
            {"session_path": str(tmp_path / "gone.jsonl"), "line_start": 1, "line_end": 3}
        ]

        report = validate_walkthrough(data)

        assert report.ok

    def test_out_of_bounds_line_range_fails(self, tmp_path: Path):
        data = _walkthrough_with_refs(tmp_path)
        data["steps"][0]["claims"][0]["source_refs"][0]["line_end"] = 9999

        report = validate_walkthrough(data, base_dir=str(tmp_path))

        assert not report.ok
        assert any("out of bounds" in error for error in report.errors)

    def test_no_fs_refs_downgrades_to_warnings(self, tmp_path: Path):
        data = _walkthrough_with_refs(tmp_path)
        data["steps"][0]["claims"][0]["source_refs"] = [
            {"session_path": str(tmp_path / "gone.jsonl"), "line_start": 1, "line_end": 3}
        ]

        report = validate_walkthrough(data, base_dir=str(tmp_path), fs_refs=False)

        assert report.ok
        assert any("do not exist" in warning for warning in report.warnings)

    def test_undeclared_session_path_warns(self, tmp_path: Path):
        data = _walkthrough_with_refs(tmp_path)
        other = tmp_path / "other.jsonl"
        other.write_text("{}\n" * 5, encoding="utf-8")
        data["steps"][0]["claims"][0]["source_refs"].append(
            {"session_path": str(other), "line_start": 1, "line_end": 2}
        )

        report = validate_walkthrough(data, base_dir=str(tmp_path))

        assert report.ok
        assert any("not declared in meta.sessions" in warning for warning in report.warnings)

    def test_grounded_monoculture_warns(self):
        data = _valid_walkthrough()
        claim = data["steps"][0]["claims"][0]
        data["steps"][0]["claims"] = [dict(claim, text=f"Claim {i}") for i in range(20)]

        report = validate_walkthrough(data)

        assert any("rubber-stamped" in warning for warning in report.warnings)

    def test_wide_span_warns(self):
        data = _valid_walkthrough()
        data["steps"][0]["claims"][0]["source_refs"] = [
            {"session_path": "chunk.jsonl", "line_start": 1, "line_end": 760}
        ]

        report = validate_walkthrough(data)

        assert any("span more than" in warning for warning in report.warnings)

    def test_shared_range_across_claims_warns(self):
        data = _valid_walkthrough()
        claim = data["steps"][0]["claims"][0]
        data["steps"][0]["claims"] = [dict(claim, text=f"Claim {i}") for i in range(3)]

        report = validate_walkthrough(data)

        assert any("distinct assertions" in warning for warning in report.warnings)

    def test_missing_end_state_warns_and_presence_clears(self):
        data = _valid_walkthrough()
        report = validate_walkthrough(data)
        assert any("end_state missing" in warning for warning in report.warnings)

        data["overview"]["end_state"] = {"goal": "The system now does X.", "summary": ["One service."]}
        report = validate_walkthrough(data)
        assert not any("end_state missing" in warning for warning in report.warnings)
