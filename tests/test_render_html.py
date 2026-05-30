"""Tests for render_html.py screenshot bridging and resolution."""

import base64
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import render_html
from render_html import (
    DEFAULT_TEMPLATE,
    bridge_screenshots_to_media,
    normalize_file_ref,
    prepare_data,
    render,
    resolve_media,
    summarize_evidence,
)


# ---------------------------------------------------------------------------
# bridge_screenshots_to_media
# ---------------------------------------------------------------------------

class TestBridgeScreenshotsToMedia:
    def test_converts_screenshots_to_media(self):
        data = {
            "steps": [{
                "id": "step-1",
                "evidence": {
                    "screenshots": [
                        {
                            "event_seq": 42,
                            "context": "Login page after changes",
                            "relevance": "high",
                        },
                    ],
                },
            }],
        }
        result = bridge_screenshots_to_media(data)
        media = result["steps"][0]["evidence"]["media"]
        assert len(media) == 1
        assert media[0]["type"] == "screenshot"
        assert media[0]["caption"] == "Login page after changes"
        assert media[0]["id"] == "step-1-ss-1"

    def test_preserves_existing_media(self):
        data = {
            "steps": [{
                "id": "step-1",
                "evidence": {
                    "media": [{"id": "existing", "type": "screenshot", "data_uri": "data:..."}],
                    "screenshots": [
                        {"context": "New screenshot"},
                    ],
                },
            }],
        }
        result = bridge_screenshots_to_media(data)
        media = result["steps"][0]["evidence"]["media"]
        assert len(media) == 2
        assert media[0]["id"] == "existing"

    def test_handles_source_ref(self):
        data = {
            "steps": [{
                "id": "step-1",
                "evidence": {
                    "screenshots": [{
                        "context": "screenshot with ref",
                        "source_ref": {"session_path": "/path/to/session.jsonl", "line_start": 42},
                    }],
                },
            }],
        }
        result = bridge_screenshots_to_media(data)
        media = result["steps"][0]["evidence"]["media"]
        assert media[0]["source_ref"]["session_path"] == "/path/to/session.jsonl"
        assert media[0]["source_ref"]["line_start"] == 42

    def test_handles_source_refs_array(self):
        """source_refs (plural) should also work."""
        data = {
            "steps": [{
                "id": "step-1",
                "evidence": {
                    "screenshots": [{
                        "context": "screenshot",
                        "source_refs": [
                            {"session_path": "/path/session.jsonl", "line_start": 10},
                        ],
                    }],
                },
            }],
        }
        result = bridge_screenshots_to_media(data)
        media = result["steps"][0]["evidence"]["media"]
        assert media[0]["source_ref"]["line_start"] == 10

    def test_no_screenshots_is_noop(self):
        data = {"steps": [{"id": "step-1", "evidence": {"files_changed": ["a.py"]}}]}
        result = bridge_screenshots_to_media(data)
        assert "media" not in result["steps"][0]["evidence"]

    def test_empty_screenshots_is_noop(self):
        data = {"steps": [{"id": "step-1", "evidence": {"screenshots": []}}]}
        result = bridge_screenshots_to_media(data)
        assert "media" not in result["steps"][0]["evidence"]

    def test_does_not_mutate_input(self):
        data = {
            "steps": [{
                "id": "step-1",
                "evidence": {
                    "screenshots": [{"context": "test"}],
                },
            }],
        }
        _ = bridge_screenshots_to_media(data)
        # Original should not have media
        assert "media" not in data["steps"][0]["evidence"]


# ---------------------------------------------------------------------------
# resolve_media — source_ref matching
# ---------------------------------------------------------------------------

class TestResolveMediaMatching:
    def _make_normalized(self, events: list[dict]) -> str:
        """Write normalized events to a temp file."""
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        for evt in events:
            f.write(json.dumps(evt) + "\n")
        f.close()
        return f.name

    def test_matches_by_session_path_and_line_start(self):
        """Summary naming: session_path + line_start should match source_path + source_line."""
        normalized_path = self._make_normalized([
            {
                "seq": 1,
                "kind": "screenshot",
                "source_path": "/path/to/session.jsonl",
                "source_line": 42,
                "ts": "2026-01-01T00:00:00Z",
                "media": {
                    "data_b64": "aVZCT1J3MEtHZw==",  # tiny valid base64
                    "mime_type": "image/png",
                },
            },
        ])

        data = {
            "steps": [{
                "id": "step-1",
                "evidence": {
                    "media": [{
                        "id": "media-1",
                        "type": "screenshot",
                        "caption": "test",
                        "source_ref": {
                            "session_path": "/path/to/session.jsonl",
                            "line_start": 42,
                        },
                    }],
                },
            }],
        }

        result = resolve_media(data, Path(normalized_path))
        media = result["steps"][0]["evidence"]["media"]
        assert media[0].get("data_uri") is not None

    def test_matches_by_source_path_and_source_line(self):
        """Normalized naming: source_path + source_line should also work."""
        normalized_path = self._make_normalized([
            {
                "seq": 1,
                "kind": "screenshot",
                "source_path": "/path/to/session.jsonl",
                "source_line": 42,
                "ts": "2026-01-01T00:00:00Z",
                "media": {
                    "data_b64": "aVZCT1J3MEtHZw==",
                    "mime_type": "image/png",
                },
            },
        ])

        data = {
            "steps": [{
                "id": "step-1",
                "evidence": {
                    "media": [{
                        "id": "media-1",
                        "type": "screenshot",
                        "caption": "test",
                        "source_ref": {
                            "source_path": "/path/to/session.jsonl",
                            "source_line": 42,
                        },
                    }],
                },
            }],
        }

        result = resolve_media(data, Path(normalized_path))
        media = result["steps"][0]["evidence"]["media"]
        assert media[0].get("data_uri") is not None

    def test_no_match_leaves_media_unchanged(self):
        """If no matching screenshot, the media item should remain without data_uri."""
        normalized_path = self._make_normalized([
            {
                "seq": 1,
                "kind": "screenshot",
                "source_path": "/other/session.jsonl",
                "source_line": 99,
                "ts": "2026-01-01T00:00:00Z",
                "media": {
                    "data_b64": "aVZCT1J3MEtHZw==",
                    "mime_type": "image/png",
                },
            },
        ])

        data = {
            "steps": [{
                "id": "step-1",
                "evidence": {
                    "media": [{
                        "id": "media-1",
                        "type": "screenshot",
                        "caption": "test",
                        "source_ref": {
                            "session_path": "/path/to/session.jsonl",
                            "line_start": 42,
                        },
                    }],
                },
            }],
        }

        result = resolve_media(data, Path(normalized_path))
        media = result["steps"][0]["evidence"]["media"]
        assert media[0].get("data_uri") is None


class TestResolveMediaFromPaths:
    def test_resolves_relative_media_path(self, tmp_path: Path):
        tiny_png_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+lmX0AAAAASUVORK5CYII="
        )
        image_path = tmp_path / "captures" / "shot.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(base64.b64decode(tiny_png_b64))

        data = {
            "steps": [{
                "id": "step-1",
                "evidence": {
                    "media": [{
                        "id": "m1",
                        "type": "screenshot",
                        "path": "captures/shot.png",
                    }],
                },
            }],
        }

        result = resolve_media(data, normalized_path=None, media_base_dir=tmp_path)
        media = result["steps"][0]["evidence"]["media"]
        assert media[0].get("data_uri", "").startswith("data:image/")

    def test_missing_media_path_does_not_crash(self, tmp_path: Path):
        data = {
            "steps": [{
                "id": "step-1",
                "evidence": {
                    "media": [{
                        "id": "m1",
                        "type": "screenshot",
                        "path": "captures/missing.png",
                    }],
                },
            }],
        }

        result = resolve_media(data, normalized_path=None, media_base_dir=tmp_path)
        media = result["steps"][0]["evidence"]["media"]
        assert media[0].get("data_uri") is None


class TestPrepareData:
    def test_normalizes_file_refs_for_relative_and_absolute_paths(self):
        ref = normalize_file_ref("src/app.py", "/tmp/project")
        assert ref["label_path"] == "src/app.py"
        assert ref["abs_path"] == "/tmp/project/src/app.py"

        external = normalize_file_ref("/opt/shared/file.txt", "/tmp/project")
        assert external["label_path"] == "/opt/shared/file.txt"
        assert external["abs_path"] == "/opt/shared/file.txt"

    def test_filters_out_of_repo_sensitive_and_worklog_refs(self):
        prepared = prepare_data(
            {
                "meta": {"repo_root": "/tmp/project"},
                "overview": {
                    "key_files": [
                        "src/app.py",
                        "docs/plans/plan.md",
                        ".env.local",
                        "worklog.md",
                        "/tmp/shared.sql",
                        "/Users/austin/.claude/plans/plan.md",
                    ]
                },
                "steps": [
                    {
                        "id": "step-1",
                        "evidence": {
                            "files_changed": [
                                "src/app.py",
                                "docs/plans/plan.md",
                                ".env.e2e",
                                "e2e-test-results/manual-test-worklog.md",
                                "/tmp/seed-edge-case-configs.sql",
                            ]
                        },
                    }
                ],
            }
        )

        overview_paths = [ref["label_path"] for ref in prepared["overview"]["key_file_refs"]]
        step_paths = [ref["label_path"] for ref in prepared["steps"][0]["_file_refs"]]

        assert overview_paths == ["src/app.py", "docs/plans/plan.md"]
        assert step_paths == ["src/app.py", "docs/plans/plan.md"]
        assert prepared["overview"]["key_files"] == ["src/app.py", "docs/plans/plan.md"]
        assert prepared["steps"][0]["evidence"]["files_changed"] == ["src/app.py", "docs/plans/plan.md"]

    def test_prepare_data_adds_rendered_mermaid_svg(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(render_html, "render_mermaid_svg", lambda _: "<svg class='diagram'></svg>")
        prepared = prepare_data(
            {
                "meta": {"repo_root": "/tmp/project"},
                "overview": {
                    "diagram_mermaid": "flowchart LR\nA-->B",
                },
                "steps": [],
            }
        )
        assert prepared["overview"]["_diagram_svg"] == "<svg class='diagram'></svg>"

    def test_drops_untrusted_diff_html_and_generates_rendered_html(self):
        prepared = prepare_data(
            {
                "meta": {"repo_root": "/tmp/project"},
                "overview": {},
                "steps": [
                    {
                        "id": "step-1",
                        "evidence": {
                            "diff_hunks": [
                                {
                                    "file": "src/app.py",
                                    "diff": "--- a/src/app.py\n+++ b/src/app.py\n-old\n+new",
                                    "html": "<script>alert(1)</script>",
                                }
                            ]
                        },
                    }
                ],
            }
        )
        hunk = prepared["steps"][0]["evidence"]["diff_hunks"][0]
        assert "html" not in hunk
        assert "rendered_html" in hunk
        assert "<script>alert(1)</script>" not in hunk["rendered_html"]


class TestRenderHtml:
    def test_template_marks_programmatic_navigation_steps_visible(self):
        template = Path(DEFAULT_TEMPLATE).read_text(encoding="utf-8")
        assert "revealStep(step)" in template
        assert "step.classList.add('visible');" in template
        assert "this.scrollToStep(this.steps[idx]);" in template

    def test_render_escapes_hostile_content_and_inlines_no_external_dependencies(self, tmp_path: Path):
        walkthrough = {
            "meta": {"repo_root": "/tmp/project"},
            "overview": {
                "goal": "</script><script>alert('x')</script>",
                "summary": ["<img src=x onerror=alert(1)>"],
                "key_files": ["src/app.py"],
            },
            "steps": [
                {
                    "id": "step-1",
                    "title": "<svg onload=alert(1)>",
                    "intent": "Show the change",
                    "claims": [{"text": "<b>unsafe</b>", "confidence": "grounded"}],
                    "evidence": {
                        "files_changed": ["src/app.py"],
                        "screenshots": [{"context": "screen"}],
                        "commands": [{"cmd": "pytest -q", "status": "pass"}],
                    },
                }
            ],
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert "<script>alert('x')</script>" not in html
        assert "</script><script>" not in html
        assert "<\\/script><script>alert('x')<\\/script>" in html
        assert "&lt;svg onload=alert(1)&gt;" in html
        assert "&lt;b&gt;unsafe&lt;/b&gt;" in html
        assert "fonts.googleapis.com" not in html
        assert "cdn.jsdelivr.net" not in html

    def test_render_inlines_rendered_mermaid_svg(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        def fake_render_mermaid_svg(_: str) -> str:
            return "<svg class=\"mermaid-svg\" viewBox=\"0 0 10 10\"><rect width=\"10\" height=\"10\" /></svg>"

        monkeypatch.setattr(render_html, "render_mermaid_svg", fake_render_mermaid_svg)
        walkthrough = {
            "meta": {"repo_root": "/tmp/project"},
            "overview": {
                "goal": "Walkthrough",
                "diagram_mermaid": "flowchart LR\nA-->B",
            },
            "steps": [],
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert '<svg class="mermaid-svg"' in html
        assert '<pre>flowchart LR' not in html

    def test_render_evidence_summary_does_not_double_count_bridged_screenshots(self, tmp_path: Path):
        walkthrough = {
            "meta": {"repo_root": "/tmp/project"},
            "overview": {"goal": "Walkthrough"},
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "claims": [],
                    "evidence": {
                        "commands": [{"cmd": "pytest -q", "status": "pass"}],
                        "screenshots": [{"context": "login page"}],
                    },
                }
            ],
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert ">1 cmd · 1 shot<" in html
        assert "2 shots" not in html


class TestAltitudeLadder:
    """The step layout: takeaway lead -> visible narrative -> collapsed proof."""

    def _render(self, tmp_path: Path, step: dict) -> str:
        walkthrough = {
            "meta": {"repo_root": "/tmp/project"},
            "overview": {"goal": "Walkthrough"},
            "steps": [step],
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")
        render(input_path, output_path, DEFAULT_TEMPLATE)
        return output_path.read_text(encoding="utf-8")

    def test_renders_takeaway_lead(self, tmp_path: Path):
        html = self._render(tmp_path, {
            "id": "step-1",
            "title": "Title",
            "takeaway": "Auth now issues JWTs and sessions are gone.",
            "claims": [{"text": "c", "confidence": "grounded"}],
        })
        assert 'class="step-takeaway' in html
        assert "Auth now issues JWTs and sessions are gone." in html

    def test_evidence_is_collapsed_by_default(self, tmp_path: Path):
        html = self._render(tmp_path, {
            "id": "step-1",
            "title": "Title",
            "evidence": {"commands": [{"cmd": "pytest", "status": "pass"}]},
        })
        assert '<details class="evidence reveal">' in html
        assert '<details class="evidence reveal" open>' not in html

    def test_decisions_and_gotchas_render_in_visible_band_not_evidence(self, tmp_path: Path):
        html = self._render(tmp_path, {
            "id": "step-1",
            "title": "Title",
            "evidence": {"commands": [{"cmd": "pytest", "status": "pass"}]},
            "decisions": [{"decision": "Use RS256", "rationale": "public-key verify"}],
            "errors_encountered": [{"error": "bad signature", "resolution": "unified keys"}],
        })
        # The callouts live in the always-visible band ...
        assert 'class="callouts' in html
        assert "Use RS256" in html
        assert "bad signature" in html
        # ... and no longer inside the collapsed evidence body.
        assert 'evidence__group-label">Decisions' not in html
        assert 'evidence__group-label">Gotchas' not in html

    def test_no_collapsible_when_evidence_has_only_files(self, tmp_path: Path):
        html = self._render(tmp_path, {
            "id": "step-1",
            "title": "Title",
            "evidence": {"files_changed": ["src/app.py"]},
        })
        # Files alone surface as chips; an empty evidence collapsible is not rendered.
        assert '<details class="evidence' not in html
        assert "src/app.py" in html


class TestSummarizeEvidenceScent:
    def test_all_pass_format_is_stable(self):
        assert summarize_evidence(
            {"commands": [{"cmd": "x", "status": "pass"}], "media": [{}]}
        ) == "1 cmd · 1 shot"

    def test_failed_command_is_flagged(self):
        assert summarize_evidence(
            {"commands": [{"cmd": "x", "status": "fail"}, {"cmd": "y", "status": "pass"}]}
        ) == "2 cmds · 1 failed"

    def test_full_strip_order(self):
        assert summarize_evidence({
            "files_changed": ["a", "b"],
            "diff_hunks": [{}],
            "commands": [{"cmd": "x", "status": "pass"}],
            "media": [{}],
        }) == "2 files · 1 diff · 1 cmd · 1 shot"

    def test_empty_returns_placeholder(self):
        assert summarize_evidence({}) == "View Evidence"
        assert summarize_evidence(None) == "View Evidence"


class TestMermaidRendering:
    def test_render_mermaid_svg_invokes_cli_and_sanitizes_wrapper(self, monkeypatch: pytest.MonkeyPatch):
        def fake_run(cmd, check, capture_output, text):
            output_path = Path(cmd[cmd.index("--output") + 1])
            output_path.write_text(
                "<?xml version=\"1.0\"?><svg class=\"ok\" viewBox=\"0 0 10 10\"></svg>",
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(render_html.subprocess, "run", fake_run)
        svg = render_html.render_mermaid_svg("flowchart LR\nA-->B")
        assert svg == '<svg class="ok" viewBox="0 0 10 10"></svg>'

    def test_render_mermaid_svg_rejects_scripted_svg(self, monkeypatch: pytest.MonkeyPatch):
        def fake_run(cmd, check, capture_output, text):
            output_path = Path(cmd[cmd.index("--output") + 1])
            output_path.write_text(
                "<svg viewBox=\"0 0 10 10\"><script>alert(1)</script></svg>",
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(render_html.subprocess, "run", fake_run)
        svg = render_html.render_mermaid_svg("flowchart LR\nA-->B")
        assert svg == ""
