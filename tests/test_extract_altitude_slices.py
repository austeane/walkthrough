import json
import subprocess
import sys
from pathlib import Path

from scripts.extract_altitude_slices import build_scan, build_skim

SAMPLE = {
    "meta": {"scope": "auth rewrite"},
    "overview": {
        "goal": "Replace session auth with tokens.",
        "summary": ["Tokens now issued by the gateway."],
        "key_files": [{"path": "src/auth.ts", "reason": "token issuance"}],
        "end_state": {
            "goal": "Stateless auth everywhere.",
            "summary": ["One token service."],
            "architecture": [{"component": "Gateway", "summary": "Issues tokens.", "step_ref": "step-1"}],
            "constraints": ["Refresh tokens rotate weekly."],
        },
    },
    "steps": [
        {
            "id": "step-1",
            "title": "Token service",
            "takeaway": "The gateway now issues signed tokens.",
            "intent": "Sessions did not scale across regions.",
            "mode": "both",
            "claims": [{"text": "JWTs are signed with KMS keys.", "confidence": "grounded"}],
            "decisions": [{"decision": "KMS over local keys", "rationale": "rotation"}],
            "errors_encountered": [{"error": "clock skew", "resolution": "60s leeway"}],
            "evidence": {"diff_hunks": [{"file": "src/auth.ts", "before": "SECRET_OLD", "after": "SECRET_NEW"}]},
        },
        {"id": "step-2", "title": "Cleanup", "mode": "journey", "claims": ["legacy string claim"]},
    ],
}


def test_skim_contains_takeaways_and_endstate_but_no_narrative():
    skim = build_skim(SAMPLE)
    assert "The gateway now issues signed tokens." in skim
    assert "(no takeaway)" in skim  # step-2 has none
    assert "Stateless auth everywhere." in skim
    assert "Gateway: Issues tokens." in skim
    assert "2. Cleanup [journey]" in skim
    # narrative band and evidence stay out of the skim
    assert "JWTs are signed" not in skim
    assert "clock skew" not in skim
    assert "SECRET_OLD" not in skim


def test_scan_contains_narrative_band_but_no_evidence():
    scan = build_scan(SAMPLE)
    assert "JWTs are signed with KMS keys. [grounded]" in scan
    assert "KMS over local keys — rotation" in scan
    assert "clock skew — resolved: 60s leeway" in scan
    assert "src/auth.ts — token issuance" in scan
    # evidence never leaks into the scan slice
    assert "SECRET_OLD" not in scan
    assert "SECRET_NEW" not in scan


def test_cli_writes_both_slices(tmp_path: Path):
    src = tmp_path / "walkthrough.json"
    src.write_text(json.dumps(SAMPLE), encoding="utf-8")
    out_dir = tmp_path / "slices"
    subprocess.run(
        [sys.executable, "scripts/extract_altitude_slices.py", "--input", str(src), "--output-dir", str(out_dir)],
        check=True,
        capture_output=True,
    )
    assert (out_dir / "skim.md").read_text(encoding="utf-8").startswith("# Skim slice")
    assert "Claims:" in (out_dir / "scan.md").read_text(encoding="utf-8")
