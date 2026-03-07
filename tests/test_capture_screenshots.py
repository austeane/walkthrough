"""Tests for capture_screenshots.py helpers."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from capture_screenshots import extract_key_commits, should_skip_capture


def test_extract_key_commits_reads_cmd_and_summary():
    walkthrough = {
        "steps": [
            {
                "evidence": {
                    "commands": [
                        {
                            "cmd": "echo done",
                            "summary": "Validated fix from commit 2e96ee1",
                        },
                        {
                            "cmd": "git show 79148d2",
                            "summary": "inspected commit",
                        },
                    ]
                }
            }
        ]
    }

    commits = extract_key_commits(walkthrough)
    assert "2e96ee1" in commits
    assert "79148d2" in commits


def test_extract_key_commits_deduplicates():
    walkthrough = {
        "steps": [
            {
                "evidence": {
                    "commands": [
                        {"cmd": "git show 2e96ee1", "summary": "commit 2e96ee1"},
                        {"cmd": "git checkout 2e96ee1", "summary": "same commit"},
                    ]
                }
            }
        ]
    }

    commits = extract_key_commits(walkthrough)
    assert commits.count("2e96ee1") == 1


def test_should_skip_capture_for_http_error_status():
    skip, reason = should_skip_capture(500, "text/html", "<html>Error</html>")
    assert skip is True
    assert reason == "http_status_500"


def test_should_skip_capture_for_json_error_payload():
    payload = '{"status":500,"unhandled":true,"message":"HTTPError"}'
    skip, reason = should_skip_capture(200, "application/json", payload)
    assert skip is True
    assert reason in {"json_response", "error_payload"}


def test_should_skip_capture_allows_normal_html():
    skip, reason = should_skip_capture(200, "text/html", "<html><body>Welcome</body></html>")
    assert skip is False
    assert reason == ""
