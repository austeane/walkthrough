"""Tests for batch_pipeline.py."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from batch_pipeline import concat_normalized


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.write_text("".join(json.dumps(evt) + "\n" for evt in events), encoding="utf-8")


class TestConcatNormalized:
    def test_resequences_and_orders_by_earliest_timestamp(self, tmp_path: Path):
        later = tmp_path / "later.jsonl"
        earlier = tmp_path / "earlier.jsonl"
        output = tmp_path / "combined.jsonl"

        _write_jsonl(
            later,
            [
                {"seq": 1, "session_id": "sess-b", "ts": "2026-01-01T00:10:00Z", "kind": "meta"},
                {"seq": 2, "session_id": "sess-b", "ts": "2026-01-01T00:11:00Z", "kind": "user_message"},
            ],
        )
        _write_jsonl(
            earlier,
            [
                {"seq": 1, "session_id": "sess-a", "ts": "2026-01-01T00:01:00Z", "kind": "meta"},
                {"seq": 2, "session_id": "sess-a", "ts": "2026-01-01T00:02:00Z", "kind": "user_message"},
            ],
        )

        count = concat_normalized([str(later), str(earlier)], str(output))
        events = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line.strip()]

        assert count == 4
        assert [evt["seq"] for evt in events] == [1, 2, 3, 4]
        assert [evt["session_id"] for evt in events] == ["sess-a", "sess-a", "sess-b", "sess-b"]
