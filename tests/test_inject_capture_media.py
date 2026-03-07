"""Tests for capture manifest media injection."""

import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from inject_capture_media import attach_capture_media


def _base_walkthrough():
    return {
        "steps": [
            {
                "id": "step-1",
                "title": "Implement registration wizard",
                "intent": "Build registration flow and forms",
                "claims": [{"text": "Added register route support"}],
                "evidence": {"media": []},
            },
            {
                "id": "step-2",
                "title": "Harden dashboard telemetry",
                "intent": "Improve dashboard and analytics stability",
                "claims": [{"text": "Updated dashboard views"}],
                "evidence": {"media": []},
            },
        ]
    }


def _manifest():
    return {
        "captures": {
            "commit-aaa1111": [
                {"route": "/events/fall-fest/register", "path": "captures/a-register.png"},
                {"route": "/dashboard", "path": "captures/a-dashboard.png"},
            ],
            "commit-bbb2222": [
                {"route": "/events/fall-fest/register", "path": "captures/b-register.png"},
                {"route": "/dashboard", "path": "captures/b-dashboard.png"},
            ],
        },
        "commit_order": ["commit-aaa1111", "commit-bbb2222"],
    }


def test_attach_capture_media_assigns_by_route_and_groups_before_after():
    walkthrough = _base_walkthrough()
    manifest = _manifest()

    with tempfile.TemporaryDirectory() as d:
        manifest_path = Path(d) / "captures" / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("{}")

        result, injected = attach_capture_media(
            walkthrough,
            manifest,
            manifest_path=manifest_path,
            replace_managed=True,
        )

    assert injected == 4

    step1_media = result["steps"][0]["evidence"]["media"]
    step2_media = result["steps"][1]["evidence"]["media"]

    register_items = [m for m in step1_media if m.get("route") == "/events/fall-fest/register"]
    dashboard_items = [m for m in step2_media if m.get("route") == "/dashboard"]

    assert len(register_items) == 2
    assert len(dashboard_items) == 2
    assert {m.get("group_role") for m in register_items} == {"before", "after"}
    assert {m.get("group_role") for m in dashboard_items} == {"before", "after"}


def test_attach_capture_media_replaces_only_managed_items():
    walkthrough = _base_walkthrough()
    walkthrough["steps"][0]["evidence"]["media"] = [
        {"id": "manual", "type": "screenshot", "caption": "keep me"},
        {"id": "managed", "type": "screenshot", "source": "capture_manifest"},
    ]

    with tempfile.TemporaryDirectory() as d:
        manifest_path = Path(d) / "captures" / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("{}")

        result, _ = attach_capture_media(
            walkthrough,
            _manifest(),
            manifest_path=manifest_path,
            replace_managed=True,
        )

    media = result["steps"][0]["evidence"]["media"]
    assert any(item.get("id") == "manual" for item in media)
    assert not any(item.get("id") == "managed" for item in media)


def test_attach_capture_media_falls_back_to_last_step_when_no_match():
    walkthrough = {
        "steps": [
            {"id": "step-1", "title": "Init", "intent": "bootstrap", "claims": [], "evidence": {"media": []}},
            {"id": "step-2", "title": "Finalize", "intent": "ship", "claims": [], "evidence": {"media": []}},
        ]
    }
    manifest = {
        "captures": {
            "commit-abc1234": [{"route": "/very/custom/path", "path": "captures/one.png"}],
        }
    }

    result, injected = attach_capture_media(walkthrough, manifest, manifest_path=None, replace_managed=True)
    assert injected == 1
    assert len(result["steps"][0]["evidence"]["media"]) == 0
    assert len(result["steps"][1]["evidence"]["media"]) == 1
