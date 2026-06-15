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

    def test_prepare_data_builds_overview_reasoning_indices(self):
        prepared = prepare_data(
            {
                "meta": {"repo_root": "/tmp/project"},
                "overview": {},
                "steps": [
                    {
                        "id": "step-1",
                        "title": "Auth Flow",
                        "decisions": [
                            {"decision": "Keep auth in the wizard", "rationale": "Avoids redirect churn."}
                        ],
                        "errors_encountered": [
                            {"error": "Hydration reset user input", "resolution": "Guarded reset by user key."}
                        ],
                    }
                ],
            }
        )

        assert prepared["overview"]["_decision_index"] == [
            {
                "kind": "decision",
                "step_id": "step-1",
                "step_number": 1,
                "step_title": "Auth Flow",
                "item_number": 1,
                "target_id": "step-1-decision-1",
                "text": "Keep auth in the wizard",
                "detail": "Avoids redirect churn.",
                "view": "both",
            }
        ]
        assert prepared["overview"]["_gotcha_index"][0]["text"] == "Hydration reset user input"
        assert prepared["overview"]["_gotcha_index"][0]["target_id"] == "step-1-gotcha-1"
        # Gotchas default to the "journey" view (a problem hit-and-fixed is the path).
        assert prepared["overview"]["_gotcha_index"][0]["view"] == "journey"
        assert prepared["overview"]["_decision_overflow"] == []
        assert prepared["overview"]["_gotcha_overflow"] == []
        assert prepared["overview"]["_decision_total"] == 1
        assert prepared["overview"]["_gotcha_total"] == 1

    def test_prepare_data_round_robins_overview_indices_across_steps(self):
        prepared = prepare_data(
            {
                "meta": {"repo_root": "/tmp/project"},
                "overview": {},
                "steps": [
                    {
                        "id": "step-1",
                        "title": "Step 1",
                        "decisions": [
                            {"decision": "Step 1 decision 1"},
                            {"decision": "Step 1 decision 2"},
                        ],
                    },
                    {
                        "id": "step-2",
                        "title": "Step 2",
                        "decisions": [{"decision": "Step 2 decision 1"}],
                    },
                ],
            }
        )

        assert [item["text"] for item in prepared["overview"]["_decision_index"]] == [
            "Step 1 decision 1",
            "Step 2 decision 1",
            "Step 1 decision 2",
        ]
        assert prepared["overview"]["_decision_total"] == 3

    def test_prepare_data_derives_overview_teaser_when_takeaway_is_missing(self):
        prepared = prepare_data(
            {
                "meta": {"repo_root": "/tmp/project"},
                "overview": {},
                "steps": [
                    {
                        "id": "step-1",
                        "title": "Intent fallback",
                        "intent": "Built the ingestion path and verified it with load tests.",
                    },
                    {
                        "id": "step-2",
                        "title": "Claim fallback",
                        "claims": [{"text": "The worker now retries transient queue failures."}],
                    },
                ],
            }
        )

        assert prepared["steps"][0]["_overview_teaser"] == (
            "Built the ingestion path and verified it with load tests."
        )
        assert prepared["steps"][1]["_overview_teaser"] == (
            "The worker now retries transient queue failures."
        )

    def test_prepare_data_normalizes_string_decisions_and_gotchas(self):
        prepared = prepare_data(
            {
                "meta": {"repo_root": "/tmp/project"},
                "overview": {},
                "steps": [
                    {
                        "id": "step-1",
                        "title": "Legacy reasoning",
                        "decisions": ["Keep the queue worker separate."],
                        "errors_encountered": ["Queue credentials were missing."],
                    }
                ],
            }
        )

        step = prepared["steps"][0]
        assert step["decisions"] == [{"decision": "Keep the queue worker separate."}]
        assert step["errors_encountered"] == [{"error": "Queue credentials were missing."}]
        assert prepared["overview"]["_decision_index"][0]["text"] == "Keep the queue worker separate."
        assert prepared["overview"]["_gotcha_index"][0]["text"] == "Queue credentials were missing."

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

    def test_render_includes_safe_glossary_tooltip_support(self, tmp_path: Path):
        walkthrough = {
            "meta": {"repo_root": "/tmp/project"},
            "overview": {
                "goal": "IaC foundation",
                "summary": ["IaC keeps GCP resources reviewable from src/app.py."],
            },
            "glossary": [
                {
                    "term": "IaC",
                    "expanded": "Infrastructure as Code",
                    "definition": "</script><script>alert(1)</script>",
                    "aliases": ["Infrastructure as Code"],
                },
                {
                    "term": "src/app.py",
                    "definition": "Entry point for the app.",
                    "file": "src/app.py",
                }
            ],
            "steps": [],
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert "glossary-term" in html
        assert "glossary-term--link" in html
        assert "githubFileHref" in html
        assert "initGlossary()" in html
        assert "createTreeWalker" in html
        assert "Infrastructure as Code" in html
        assert "src/app.py" in html
        assert "</script><script>alert(1)</script>" not in html
        assert "<\\/script><script>alert(1)<\\/script>" in html

    def test_render_uses_body_level_glossary_tooltip_that_cannot_be_clipped(
        self, tmp_path: Path
    ):
        """Tooltips are a shared body-level fixed element positioned by JS, not a
        pseudo-element on each term (which an ancestor's overflow or the sticky
        header could clip). The JS must flip the tooltip below the term and clamp
        it into the viewport, and print must still hide it."""
        walkthrough = {
            "meta": {"repo_root": "/tmp/project"},
            "overview": {
                "goal": "IaC foundation",
                "summary": ["Each unit is a deployable boundary."],
            },
            "glossary": [
                {"term": "unit", "definition": "A deployable Terragrunt boundary."}
            ],
            "steps": [],
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        # Shared body-level node + JS positioning hooks are wired in.
        assert "glossary-tooltip" in html
        assert "initGlossaryTooltip()" in html
        assert "positionGlossaryTooltip" in html
        assert "getBoundingClientRect" in html
        assert "document.body.appendChild" in html
        # The old pseudo-element tooltip is gone (no double tooltip, no clipping).
        assert 'content: attr(data-glossary-tooltip)' not in html
        # Print keeps tooltips hidden.
        assert ".glossary-tooltip { display: none !important; }" in html

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

    def test_render_includes_overview_reasoning_map(self, tmp_path: Path):
        walkthrough = {
            "meta": {"repo_root": "/tmp/project"},
            "overview": {"goal": "Walkthrough"},
            "steps": [
                {
                    "id": "step-1",
                    "title": "Auth Flow",
                    "takeaway": "Auth now happens in-place.",
                    "claims": [],
                    "decisions": [{"decision": "Keep auth in the wizard", "rationale": "Avoid redirect churn."}],
                    "errors_encountered": [{"error": "Hydration reset user input", "resolution": "Guarded reset."}],
                }
            ],
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert "Decision map" in html
        assert "Gotcha map" in html
        assert "Keep auth in the wizard" in html
        assert 'href="#step-1-decision-1"' in html
        assert 'href="#step-1-gotcha-1"' in html
        assert 'id="step-1-decision-1"' in html
        assert 'id="step-1-gotcha-1"' in html

    def test_render_labels_capped_reasoning_map_counts(self, tmp_path: Path):
        steps = []
        for i in range(11):
            steps.append(
                {
                    "id": f"step-{i + 1}",
                    "title": f"Step {i + 1}",
                    "claims": [],
                    "decisions": [{"decision": f"Decision {i + 1}"}],
                }
            )
        walkthrough = {
            "meta": {"repo_root": "/tmp/project"},
            "overview": {"goal": "Walkthrough"},
            "steps": steps,
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert '<span class="reasoning-map__count">10 of 11</span>' in html
        assert "Show 1 more decisions" in html

    def test_render_includes_collapsed_overflow_for_capped_gotchas(self, tmp_path: Path):
        steps = []
        for i in range(11):
            steps.append(
                {
                    "id": f"step-{i + 1}",
                    "title": f"Step {i + 1}",
                    "claims": [],
                    "errors_encountered": [{"error": f"Gotcha {i + 1}"}],
                }
            )
        walkthrough = {
            "meta": {"repo_root": "/tmp/project"},
            "overview": {"goal": "Walkthrough"},
            "steps": steps,
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert '<span class="reasoning-map__count">10 of 11</span>' in html
        assert "Show 1 more gotchas" in html

    def test_render_places_step_jump_grid_before_reasoning_map(self, tmp_path: Path):
        walkthrough = {
            "meta": {"repo_root": "/tmp/project"},
            "overview": {"goal": "Walkthrough"},
            "steps": [
                {
                    "id": "step-1",
                    "title": "Auth Flow",
                    "takeaway": "Auth now happens in-place.",
                    "claims": [],
                    "decisions": [{"decision": "Keep auth in the wizard"}],
                }
            ],
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert html.index('class="jump-grid reveal"') < html.index('class="reasoning-map reveal"')

    def test_render_places_step_jump_grid_before_overview_key_files(self, tmp_path: Path):
        walkthrough = {
            "meta": {"repo_root": "/tmp/project"},
            "overview": {"goal": "Walkthrough", "key_files": ["src/app.ts"]},
            "steps": [
                {
                    "id": "step-1",
                    "title": "Auth Flow",
                    "takeaway": "Auth now happens in-place.",
                    "claims": [],
                }
            ],
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert html.index('class="jump-grid reveal"') < html.index('class="overview-files reveal"')

    def test_render_jump_cards_show_decision_and_gotcha_scent(self, tmp_path: Path):
        walkthrough = {
            "meta": {"repo_root": "/tmp/project"},
            "overview": {"goal": "Walkthrough"},
            "steps": [
                {
                    "id": "step-1",
                    "title": "Auth Flow",
                    "takeaway": "Auth now happens in-place.",
                    "claims": [],
                    "decisions": [{"decision": "Keep auth in wizard"}, {"decision": "Store state"}],
                    "errors_encountered": [{"error": "Hydration reset"}],
                }
            ],
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert "jump-card__badge jump-card__badge--decision" in html
        assert "2 decisions" in html
        assert "jump-card__badge jump-card__badge--gotcha" in html
        assert "1 gotcha" in html

    def test_render_jump_cards_show_intent_when_takeaway_is_missing(self, tmp_path: Path):
        walkthrough = {
            "meta": {"repo_root": "/tmp/project"},
            "overview": {"goal": "Walkthrough"},
            "steps": [
                {
                    "id": "step-1",
                    "title": "Auth Flow",
                    "intent": "Replaced redirects with in-place auth so the wizard keeps state.",
                    "claims": [],
                }
            ],
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert "Replaced redirects with in-place auth so the wizard keeps state." in html
        assert "jump-card__d" in html

    def test_render_string_decisions_and_gotchas_in_map_and_callouts(self, tmp_path: Path):
        walkthrough = {
            "meta": {"repo_root": "/tmp/project"},
            "overview": {"goal": "Walkthrough"},
            "steps": [
                {
                    "id": "step-1",
                    "title": "Legacy reasoning",
                    "claims": [],
                    "decisions": ["Keep the queue worker separate."],
                    "errors_encountered": ["Queue credentials were missing."],
                }
            ],
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert "Keep the queue worker separate." in html
        assert "Queue credentials were missing." in html
        assert 'href="#step-1-decision-1"' in html
        assert 'id="step-1-gotcha-1"' in html

    def test_template_highlights_targeted_callouts(self):
        template = Path(DEFAULT_TEMPLATE).read_text(encoding="utf-8")
        assert ".callout:target" in template
        assert ".callout--gotcha:target" in template

    def test_render_prefers_diagram_image_over_mermaid(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        def fail_if_called(_: str) -> str:
            raise AssertionError("Mermaid should not render when diagram_image is present")

        monkeypatch.setattr(render_html, "render_mermaid_svg", fail_if_called)
        (tmp_path / "overview.png").write_bytes(_TINY_PNG)
        walkthrough = {
            "meta": {"repo_root": "/tmp/project"},
            "overview": {
                "goal": "Walkthrough",
                "diagram_image": "overview.png",
                "diagram_mermaid": "flowchart LR\nA-->B",
            },
            "steps": [],
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert '<img class="wt-diagram-img wt-diagram-dark"' in html
        assert '<img class="wt-diagram-img wt-diagram-light"' in html
        assert '<pre>flowchart LR' not in html
        assert "mermaid-svg" not in html
        # The image appears in the server-rendered tags only; DATA omits the
        # heavy embedded payload so the HTML does not double in size.
        assert html.count("data:image/png;base64,") == 2

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


class TestViewModes:
    """End State vs Journey: the toggle, the data-view-tag stamping, defaults."""

    def _render(self, tmp_path: Path, walkthrough: dict) -> str:
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")
        render(input_path, output_path, DEFAULT_TEMPLATE)
        return output_path.read_text(encoding="utf-8")

    def test_render_includes_view_toggle_defaulting_to_end_state(self, tmp_path: Path):
        html = self._render(
            tmp_path,
            {"meta": {"repo_root": "/tmp/p"}, "overview": {"goal": "G"}, "steps": []},
        )
        assert 'data-view="endstate"' in html
        assert 'id="viewEndstate"' in html and 'id="viewJourney"' in html
        # The filter rules and the JS controller must be present.
        assert 'html[data-view="endstate"] [data-view-tag="journey"]' in html
        assert "walkthrough-view" in html  # localStorage key persists the choice

    def test_steps_claims_and_callouts_are_tagged_by_view(self, tmp_path: Path):
        walkthrough = {
            "meta": {"repo_root": "/tmp/p"},
            "overview": {"goal": "G"},
            "steps": [
                {"id": "step-1", "title": "Origin", "mode": "journey", "claims": []},
                {"id": "step-2", "title": "Result", "mode": "end-state", "claims": []},
                {
                    "id": "step-3",
                    "title": "Mixed",
                    "claims": [
                        {"text": "Final shape.", "confidence": "grounded"},
                        {"text": "How we struggled.", "confidence": "grounded", "mode": "journey"},
                    ],
                    "decisions": [{"decision": "The kept call"}],
                    "errors_encountered": [{"error": "A transient snag"}],
                },
            ],
        }
        html = self._render(tmp_path, walkthrough)
        # Whole-step tagging on the article (and its TOC entry + jump card).
        assert 'data-step-id="step-1"' in html and 'data-view-tag="journey"' in html
        assert 'data-step-id="step-2"' in html and 'data-view-tag="end-state"' in html
        # A both-step is not tagged.
        assert 'id="step-3"' in html
        # Per-claim tagging: the journey claim is tagged, the default claim is not.
        assert 'data-view-tag="journey">How we struggled.' in html
        assert "<p class=\"claim claim--grounded\">Final shape." in html
        # Decisions default to both (untagged); gotchas default to journey (tagged).
        assert 'id="step-3-decision-1">' in html  # no data-view-tag on the decision
        assert 'id="step-3-gotcha-1" data-view-tag="journey">' in html

    def test_gotcha_can_opt_into_both_as_a_live_constraint(self, tmp_path: Path):
        walkthrough = {
            "meta": {"repo_root": "/tmp/p"},
            "overview": {"goal": "G"},
            "steps": [
                {
                    "id": "step-1",
                    "title": "Engine",
                    "claims": [],
                    "errors_encountered": [
                        {"error": "Segfaults on Node 25; pinned to Node 22.", "mode": "both"}
                    ],
                }
            ],
        }
        html = self._render(tmp_path, walkthrough)
        # A both-tagged gotcha carries no data-view-tag, so it shows in either view.
        assert 'id="step-1-gotcha-1">' in html
        # And it is not journey-tagged.
        assert 'id="step-1-gotcha-1" data-view-tag' not in html

    def test_overview_end_state_framing_renders_both_variants(self, tmp_path: Path):
        walkthrough = {
            "meta": {"repo_root": "/tmp/p"},
            "overview": {
                "goal": "Journey goal walking the path.",
                "summary": ["We started here.", "Then pivoted.", "Finally landed."],
                "end_state": {
                    "goal": "End state goal: the final shape.",
                    "summary": ["Two services.", "One engine, many tenants."],
                },
            },
            "steps": [{"id": "step-1", "title": "S", "claims": []}],
        }
        html = self._render(tmp_path, walkthrough)
        assert '<h1 class="hero__title reveal" data-view-tag="end-state">End state goal: the final shape.' in html
        assert '<h1 class="hero__title reveal" data-view-tag="journey">Journey goal walking the path.' in html
        assert 'data-view-tag="end-state">' in html  # end-state summary list
        assert "Two services." in html and "We started here." in html

    def test_reasoning_index_items_carry_a_view(self):
        prepared = prepare_data(
            {
                "meta": {"repo_root": "/tmp/p"},
                "overview": {},
                "steps": [
                    {
                        "id": "step-1",
                        "title": "Journey step",
                        "mode": "journey",
                        "decisions": [{"decision": "A path decision"}],
                    },
                    {
                        "id": "step-2",
                        "title": "Mixed step",
                        "decisions": [{"decision": "A kept decision"}],
                        "errors_encountered": [{"error": "A snag"}],
                    },
                ],
            }
        )
        decisions = prepared["overview"]["_decision_index"]
        by_text = {d["text"]: d["view"] for d in decisions}
        # A journey step forces its decision to journey; an untagged decision in a
        # both-step stays both; a gotcha defaults to journey.
        assert by_text["A path decision"] == "journey"
        assert by_text["A kept decision"] == "both"
        assert prepared["overview"]["_gotcha_index"][0]["view"] == "journey"


class TestUiFeatureFlags:
    """meta.ui gates the view switcher, present mode, stat strip, and confidence
    legend; all default ON so existing walkthroughs render unchanged."""

    ALL_ON = {
        "view_switcher": True,
        "present_mode": True,
        "stats": True,
        "confidence_legend": True,
    }

    def _render(self, tmp_path: Path, walkthrough: dict) -> str:
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")
        render(input_path, output_path, DEFAULT_TEMPLATE)
        return output_path.read_text(encoding="utf-8")

    def _walkthrough(self, ui: dict | None = None) -> dict:
        meta = {"repo_root": "/tmp/p"}
        if ui is not None:
            meta["ui"] = ui
        return {
            "meta": meta,
            "overview": {"goal": "G", "summary": ["A line."]},
            "steps": [
                {
                    "id": "step-1",
                    "title": "Only step",
                    "intent": "Do the thing",
                    # A non-grounded claim ensures the confidence legend would
                    # otherwise render (the legend shows only when one exists).
                    "claims": [
                        {"text": "It works.", "confidence": "grounded"},
                        {"text": "Probably fast.", "confidence": "inferred"},
                    ],
                }
            ],
        }

    def test_resolve_ui_flags_defaults_to_all_on(self):
        # Missing meta, missing meta.ui, and non-bool/missing keys all coerce to True.
        assert render_html.resolve_ui_flags(None) == self.ALL_ON
        assert render_html.resolve_ui_flags({}) == self.ALL_ON
        assert render_html.resolve_ui_flags({"ui": {}}) == self.ALL_ON
        assert render_html.resolve_ui_flags({"ui": {"view_switcher": "no"}}) == self.ALL_ON
        assert render_html.resolve_ui_flags({"ui": {"stats": 1}}) == self.ALL_ON

    def test_resolve_ui_flags_honors_explicit_bools(self):
        assert render_html.resolve_ui_flags(
            {"ui": {
                "view_switcher": False,
                "present_mode": False,
                "stats": False,
                "confidence_legend": False,
            }}
        ) == {
            "view_switcher": False,
            "present_mode": False,
            "stats": False,
            "confidence_legend": False,
        }
        # Flags are independent — setting one leaves the others at their default.
        assert render_html.resolve_ui_flags({"ui": {"stats": False}}) == {
            "view_switcher": True,
            "present_mode": True,
            "stats": False,
            "confidence_legend": True,
        }

    def test_default_absent_meta_ui_keeps_all_features(self, tmp_path: Path):
        html = self._render(tmp_path, self._walkthrough(ui=None))
        assert 'id="viewSeg"' in html
        assert 'id="modeToggle"' in html
        # The deck slideshow renders by default.
        assert 'id="deckViewport"' in html
        assert 'class="slide slide--title active"' in html
        # The stat strip and the confidence legend render by default.
        assert 'class="stat-strip' in html
        assert 'class="legend reveal"' in html

    def test_view_switcher_false_omits_control_and_locks_endstate(self, tmp_path: Path):
        html = self._render(
            tmp_path, self._walkthrough(ui={"view_switcher": False})
        )
        # The segmented control and its buttons are gone.
        assert 'id="viewSeg"' not in html
        assert 'id="viewEndstate"' not in html
        assert 'id="viewJourney"' not in html
        # The document is locked to the end-state view.
        assert 'data-view="endstate"' in html
        # Present mode is independent and still on by default.
        assert 'id="modeToggle"' in html
        # Reading content is intact.
        assert 'id="overview"' in html
        assert 'data-step-id="step-1"' in html

    def test_present_mode_false_omits_toggle_and_slideshow(self, tmp_path: Path):
        html = self._render(
            tmp_path, self._walkthrough(ui={"present_mode": False})
        )
        # The Present toggle and the whole deck section are gone.
        assert 'id="modeToggle"' not in html
        assert 'id="deckViewport"' not in html
        assert 'id="deckStage"' not in html
        assert 'class="slide' not in html
        # The page stays in reading mode with content intact.
        assert 'class="reading-view"' in html
        assert 'data-step-id="step-1"' in html
        # The view switcher is independent and still on by default.
        assert 'id="viewSeg"' in html

    def test_both_false_omits_everything_but_keeps_reading(self, tmp_path: Path):
        html = self._render(
            tmp_path,
            self._walkthrough(ui={"view_switcher": False, "present_mode": False}),
        )
        assert 'id="viewSeg"' not in html
        assert 'id="modeToggle"' not in html
        assert 'id="deckViewport"' not in html
        assert 'class="slide' not in html
        # Locked to end-state reading view, content intact, other chrome retained.
        assert 'data-view="endstate"' in html
        assert 'class="reading-view"' in html
        assert 'id="themeToggle"' in html
        assert 'id="searchInput"' in html
        assert 'data-step-id="step-1"' in html

    def test_stats_false_omits_stat_strip_both_views(self, tmp_path: Path):
        html = self._render(tmp_path, self._walkthrough(ui={"stats": False}))
        # Neither the reading-view strip nor the present-mode mirror renders.
        assert 'class="stat-strip' not in html
        assert 'class="slide__stats"' not in html
        assert 'id="readTime"' not in html
        # Independent features stay on; reading content intact.
        assert 'id="viewSeg"' in html
        assert 'id="modeToggle"' in html
        assert 'data-step-id="step-1"' in html
        # The confidence legend is independent and still renders (non-grounded
        # claim present), proving the stats gate did not collapse it. Match the
        # rendered markup, not the CSS rule that shares the BEM class name.
        assert 'class="legend reveal"' in html

    def test_confidence_legend_false_omits_legend_even_with_nongrounded_claims(
        self, tmp_path: Path
    ):
        # Fixture carries an inferred claim, so the legend would normally show.
        html = self._render(tmp_path, self._walkthrough(ui={"confidence_legend": False}))
        # The legend markup is gone (the CSS rules sharing the BEM class names
        # still exist, so assert on the rendered block, not the class token).
        assert 'class="legend reveal"' not in html
        assert '<span class="legend__label">Confidence</span>' not in html
        assert 'class="legend__item legend__item--grounded"' not in html
        # The stat strip is independent and still renders.
        assert 'class="stat-strip' in html
        assert 'data-step-id="step-1"' in html

    def test_confidence_legend_still_absent_when_all_grounded(self, tmp_path: Path):
        # No non-grounded claim -> legend never rendered, regardless of the flag.
        walkthrough = {
            "meta": {"repo_root": "/tmp/p"},
            "overview": {"goal": "G", "summary": ["A line."]},
            "steps": [
                {
                    "id": "step-1",
                    "title": "Only step",
                    "claims": [{"text": "It works.", "confidence": "grounded"}],
                }
            ],
        }
        html = self._render(tmp_path, walkthrough)
        assert 'class="legend reveal"' not in html
        assert '<span class="legend__label">Confidence</span>' not in html
        # But the stat strip (default on) is present.
        assert 'class="stat-strip' in html


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


# ---------------------------------------------------------------------------
# embed_overview_diagram_images
# ---------------------------------------------------------------------------

# A 1x1 transparent PNG.
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


class TestEmbedOverviewDiagramImages:
    def test_object_spec_resolves_both_themes(self, tmp_path: Path):
        (tmp_path / "ov.light.png").write_bytes(_TINY_PNG)
        (tmp_path / "ov.dark.png").write_bytes(_TINY_PNG)
        overview = {"diagram_image": {"light": "ov.light.png", "dark": "ov.dark.png"}}
        render_html.embed_overview_diagram_images(overview, tmp_path, repo_root="")
        assert overview["_diagram_image_light"].startswith("data:image/")
        assert overview["_diagram_image_dark"].startswith("data:image/")

    def test_string_spec_used_for_both_themes(self, tmp_path: Path):
        (tmp_path / "ov.png").write_bytes(_TINY_PNG)
        overview = {"diagram_image": "ov.png"}
        render_html.embed_overview_diagram_images(overview, tmp_path, repo_root="")
        assert overview["_diagram_image_light"].startswith("data:image/")
        assert overview["_diagram_image_dark"].startswith("data:image/")

    def test_missing_file_sets_nothing_and_does_not_raise(self, tmp_path: Path):
        overview = {"diagram_image": {"light": "nope.png", "dark": "missing.png"}}
        render_html.embed_overview_diagram_images(overview, tmp_path, repo_root="")
        assert "_diagram_image_light" not in overview
        assert "_diagram_image_dark" not in overview

    def test_no_spec_is_noop(self, tmp_path: Path):
        overview = {}
        render_html.embed_overview_diagram_images(overview, tmp_path, repo_root="")
        assert overview == {}


class TestWalkthroughVideo:
    def test_render_embeds_overview_and_step_video(self, tmp_path: Path):
        media = tmp_path / "media"
        media.mkdir()
        (media / "tour.mp4").write_bytes(b"\x00fakevideo")
        (media / "step.mp4").write_bytes(b"\x00fakevideo")
        poster = media / "poster.png"
        poster.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDATx\x9cc\xf8"
            b"\x0f\x00\x01\x01\x01\x00\x1b\xb6\xee\x56\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        walkthrough = {
            "meta": {"repo_root": str(tmp_path)},
            "overview": {
                "goal": "Show the video embed.",
                "summary": ["One", "Two", "Three"],
                "video": {
                    "src": "media/tour.mp4",
                    "poster": "media/poster.png",
                    "caption": "Ninety-second tour",
                },
            },
            "steps": [
                {
                    "id": "step-1",
                    "title": "A Step With Video",
                    "takeaway": "The step shows a clip.",
                    "intent": "Demonstrate per-step video.",
                    "video": "media/step.mp4",
                    "claims": [{"text": "Clip attached.", "confidence": "grounded"}],
                }
            ],
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert '<video controls preload="metadata"' in html
        assert 'src="media/tour.mp4"' in html
        assert 'src="media/step.mp4"' in html
        assert 'poster="data:image/png;base64,' in html
        assert "Ninety-second tour" in html
        # The resolved payloads stay out of the embedded DATA blob.
        assert '"_video"' not in html

    def test_embed_true_inlines_video_as_data_uri(self, tmp_path: Path):
        media = tmp_path / "media"
        media.mkdir()
        (media / "tour.mp4").write_bytes(b"\x00fakevideo")
        walkthrough = {
            "meta": {"repo_root": str(tmp_path)},
            "overview": {
                "goal": "Single-file video embed.",
                "summary": ["One", "Two", "Three"],
                "video": {"src": "media/tour.mp4", "embed": True, "caption": "Tour"},
            },
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step",
                    "takeaway": "T.",
                    "intent": "I.",
                    "claims": [{"text": "ok", "confidence": "grounded"}],
                }
            ],
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert 'data-embedded-src="data:video/mp4;base64,' in html
        assert 'src="media/tour.mp4"' not in html
        assert "initEmbeddedVideos" in html

    def test_render_skips_missing_video(self, tmp_path: Path):
        walkthrough = {
            "meta": {"repo_root": str(tmp_path)},
            "overview": {
                "goal": "No video on disk.",
                "summary": ["One", "Two", "Three"],
                "video": {"src": "media/gone.mp4"},
            },
            "steps": [
                {
                    "id": "step-1",
                    "title": "Plain Step",
                    "takeaway": "Nothing to see.",
                    "intent": "Check the warning path.",
                    "claims": [{"text": "ok", "confidence": "grounded"}],
                }
            ],
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert "<video" not in html


class TestLikeC4Embed:
    @staticmethod
    def _walkthrough_with_embeds(tmp_path: Path) -> dict:
        diagrams = tmp_path / "media" / "diagrams"
        diagrams.mkdir(parents=True)
        (diagrams / "likec4-views.js").write_text("// likec4 bundle", encoding="utf-8")
        return {
            "meta": {"repo_root": str(tmp_path)},
            "overview": {
                "goal": "Show the interactive diagram embed.",
                "summary": ["One", "Two", "Three"],
                "diagram_likec4": {
                    "views_js": "media/diagrams/likec4-views.js",
                    "view": "index",
                    "caption": "Click into any box.",
                },
            },
            "steps": [
                {
                    "id": "step-1",
                    "title": "A Step With A Live View",
                    "takeaway": "The step gets its own view.",
                    "intent": "Demonstrate per-step embeds.",
                    "diagram_likec4": {
                        "views_js": "media/diagrams/likec4-views.js",
                        "view": "cicd",
                        "height": "44vh",
                    },
                    "claims": [{"text": "Embed attached.", "confidence": "grounded"}],
                }
            ],
        }

    def test_render_embeds_overview_and_step_views(self, tmp_path: Path):
        walkthrough = self._walkthrough_with_embeds(tmp_path)
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert 'view-id="index"' in html
        assert 'view-id="cicd"' in html
        assert "<c4-view data-likec4-view" in html
        assert 'style="height: 44vh"' in html
        assert "Click into any box." in html
        # Inline by default: one parser-safe eval script — even with two embeds
        # referencing the same bundle — and no sidecar reference.
        assert html.count("(0,eval)(") == 1
        assert "// likec4 bundle" in html
        assert "<script src=" not in html
        # The resolved payloads stay out of the embedded DATA blob.
        assert '"_likec4"' not in html
        assert "_likec4_sources" not in html

    def test_embed_false_keeps_sidecar_script(self, tmp_path: Path):
        walkthrough = self._walkthrough_with_embeds(tmp_path)
        walkthrough["overview"]["diagram_likec4"]["embed"] = False
        walkthrough["steps"][0]["diagram_likec4"]["embed"] = False
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert html.count('<script src="media/diagrams/likec4-views.js"></script>') == 1
        assert "(0,eval)(" not in html

    def test_inline_bundle_is_parser_safe(self, tmp_path: Path):
        walkthrough = self._walkthrough_with_embeds(tmp_path)
        bundle = tmp_path / "media" / "diagrams" / "likec4-views.js"
        bundle.write_text('var x = "<!--<script></scr" + "ipt>";', encoding="utf-8")
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        # Every "<" in the payload is <-escaped, so none of the bundle's
        # parser-hostile sequences survive into the script element's text.
        start = html.index("(0,eval)(")
        end = html.index("</script>", start)
        chunk = html[start:end]
        assert "<" not in chunk
        assert "\\u003c!--" in chunk

    def test_render_skips_missing_bundle(self, tmp_path: Path):
        walkthrough = self._walkthrough_with_embeds(tmp_path)
        walkthrough["overview"]["diagram_likec4"]["views_js"] = "media/diagrams/gone.js"
        walkthrough["steps"][0].pop("diagram_likec4")
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert "<c4-view" not in html
        assert '<div class="likec4-frame"' not in html
        assert "<script src=" not in html

    def test_remote_views_js_is_refused(self, tmp_path: Path):
        walkthrough = self._walkthrough_with_embeds(tmp_path)
        walkthrough["overview"]["diagram_likec4"]["views_js"] = "https://evil.example.com/x.js"
        walkthrough["steps"][0].pop("diagram_likec4")
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert "<c4-view" not in html
        assert "evil.example.com" not in html.split("const DATA")[0]
        assert "<script src=" not in html

    def test_invalid_tag_falls_back_to_c4_view(self, tmp_path: Path):
        walkthrough = self._walkthrough_with_embeds(tmp_path)
        walkthrough["overview"]["diagram_likec4"]["tag"] = "div onclick=alert(1)"
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        # The invalid tag never reaches markup (the raw spec string survives
        # only as escaped JSON inside the DATA blob).
        assert "<div onclick" not in html
        assert "<c4-view data-likec4-view" in html

    def test_static_fallback_rides_inside_embed(self, tmp_path: Path):
        walkthrough = self._walkthrough_with_embeds(tmp_path)
        png = tmp_path / "media" / "diagrams" / "index.png"
        png.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDATx\x9cc\xf8"
            b"\x0f\x00\x01\x01\x01\x00\x1b\xb6\xee\x56\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        walkthrough["overview"]["diagram_image"] = "media/diagrams/index.png"
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert 'class="likec4-fallback"' in html
        assert html.index('<div class="likec4-frame"') < html.index('<div class="likec4-fallback">')


class TestTallContentClamp:
    def test_template_ships_clamp_zones_and_controller(self, tmp_path: Path):
        walkthrough = {
            "meta": {"repo_root": str(tmp_path)},
            "overview": {
                "goal": "Clamp wiring.",
                "summary": ["One", "Two", "Three"],
                "end_state": {
                    "goal": "Done thing.",
                    "summary": ["Bullet."],
                    "constraints": ["A live constraint."],
                },
            },
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step",
                    "takeaway": "It happened.",
                    "intent": "Show clamp attributes.",
                    "claims": [{"text": "ok", "confidence": "grounded"}],
                    "decisions": [{"decision": "Choose X", "rationale": "Y"}],
                }
            ],
        }
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")

        render(input_path, output_path, DEFAULT_TEMPLATE)
        html = output_path.read_text(encoding="utf-8")

        assert 'class="claims reveal" data-view-collapsible data-clamp=' in html
        assert 'class="callouts reveal" data-view-collapsible data-clamp=' in html
        assert 'class="es-constraints reveal" data-view-tag="end-state" data-clamp=' in html
        assert "initClamps()" in html
        assert "clamp-toggle" in html


class TestSystemSection:
    """The system reference (diagram + arch cards + constraints) renders as its
    own synthesized section between the overview cover and step 1."""

    def _render(self, tmp_path: Path, walkthrough: dict) -> str:
        input_path = tmp_path / "walkthrough.json"
        output_path = tmp_path / "walkthrough.html"
        input_path.write_text(json.dumps(walkthrough), encoding="utf-8")
        render(input_path, output_path, DEFAULT_TEMPLATE)
        return output_path.read_text(encoding="utf-8")

    def _walkthrough_with_end_state(self) -> dict:
        return {
            "meta": {"repo_root": "/tmp/p"},
            "overview": {
                "goal": "G",
                "end_state": {
                    "goal": "The destination.",
                    "architecture": [
                        {"component": "API layer", "summary": "Serves requests.", "step_ref": "step-1"}
                    ],
                    "constraints": [{"text": "Only one region.", "step_ref": "step-1"}],
                },
            },
            "steps": [{"id": "step-1", "title": "Build", "claims": []}],
        }

    def test_system_section_synthesized_from_end_state(self, tmp_path: Path):
        html = self._render(tmp_path, self._walkthrough_with_end_state())
        assert 'id="system"' in html
        assert "The system today" in html
        # The cards and constraints live in the system section, not the overview.
        overview_part = html.split('<section class="system step"')[0].split('id="overview"')[1]
        system_part = html.split('<section class="system step"')[1].split('<article class="step"')[0]
        assert "es-arch" not in overview_part and "es-constraints" not in overview_part
        assert "API layer" in system_part and "Only one region." in system_part
        # TOC gains the entry between Overview and step 1.
        assert '<a class="toc-link" data-step="1" href="#system">' in html
        # Steps shift by one ordinal (sections and TOC pair by array index).
        assert 'id="step-1" data-step="2"' in html
        assert 'data-step="2" href="#step-1"' in html or 'href="#step-1"' in html

    def test_section_ordinals_shift_only_when_system_exists(self, tmp_path: Path):
        plain = {
            "meta": {"repo_root": "/tmp/p"},
            "overview": {"goal": "G"},
            "steps": [{"id": "step-1", "title": "Build", "claims": []}],
        }
        html = self._render(tmp_path, plain)
        assert 'id="system"' not in html
        assert 'id="step-1" data-step="1"' in html

    def test_system_section_end_state_only_without_diagram(self, tmp_path: Path):
        html = self._render(tmp_path, self._walkthrough_with_end_state())
        # No diagram: hidden in journey view along with its TOC entry.
        assert 'id="system" data-step="1" style="--es-order:0;--jy-order:0" data-view-tag="end-state"' in html

    def test_diagram_renders_in_system_section_and_keeps_it_both_views(self, tmp_path: Path):
        walkthrough = self._walkthrough_with_end_state()
        walkthrough["overview"]["diagram_mermaid"] = "graph TD; A-->B"
        html = self._render(tmp_path, walkthrough)
        system_part = html.split('<section class="system step"')[1].split('<article class="step"')[0]
        assert "overview-diagram" in system_part
        # With a diagram the section serves both views: no view tag on it.
        assert 'id="system" data-step="1" style="--es-order:0;--jy-order:0">' in html

    def test_diagram_only_walkthrough_titles_section_system_map(self, tmp_path: Path):
        walkthrough = {
            "meta": {"repo_root": "/tmp/p"},
            "overview": {"goal": "G", "diagram_mermaid": "graph TD; A-->B"},
            "steps": [{"id": "step-1", "title": "Build", "claims": []}],
        }
        html = self._render(tmp_path, walkthrough)
        assert 'id="system"' in html
        assert "System map" in html

    def test_reasoning_map_renders_one_liners_without_rationale(self, tmp_path: Path):
        walkthrough = {
            "meta": {"repo_root": "/tmp/p"},
            "overview": {"goal": "G"},
            "steps": [
                {
                    "id": "step-1",
                    "title": "Build",
                    "claims": [],
                    "decisions": [{"decision": "Pick X over Y", "rationale": "X is simpler to operate."}],
                }
            ],
        }
        html = self._render(tmp_path, walkthrough)
        # The map links the decision but carries no rationale paragraph;
        # the rationale still renders inside the step itself.
        assert "reasoning-map__text" in html
        assert "reasoning-map__detail" not in html
        assert "X is simpler to operate." in html


# ---------------------------------------------------------------------------
# Prose links: auto path-linkify, meta.link_map, markdown links, link_mode
# ---------------------------------------------------------------------------

import shutil
import subprocess
import textwrap


def _render(tmp_path: Path, walkthrough: dict) -> str:
    input_path = tmp_path / "walkthrough.json"
    output_path = tmp_path / "walkthrough.html"
    input_path.write_text(json.dumps(walkthrough), encoding="utf-8")
    render(input_path, output_path, DEFAULT_TEMPLATE)
    return output_path.read_text(encoding="utf-8")


class TestProseLinksTemplateWiring:
    """The prose-link logic is client-side JS, so assert it ships in the template
    and is wired into the init sequence before the glossary (so glossary's tree
    walker — which skips inside <a> — can never double-wrap a linked token)."""

    def test_template_defines_prose_link_methods(self):
        t = Path(DEFAULT_TEMPLATE).read_text(encoding="utf-8")
        for needed in (
            "initProseLinks()",
            "proseLinkMode()",
            "normalizeLinkMap()",
            "proseLinkRegexes(",
            "linkifyProseTextNode(",
            "resolveProseHref(",
            "githubTreeOrBlobHref(",
            "glossaryLinkLookup()",
            "proseLinkTooltip(",
            "'xref'",
        ):
            assert needed in t, needed

    def test_tooltip_links_reuse_glossary_engine(self):
        """A tooltip'd prose link adds `glossary-term` and `data-glossary-tooltip`
        so the existing body-level tooltip engine (which keys off `.glossary-term`)
        shows it with zero engine changes — and the flip-below positioner applies."""
        t = Path(DEFAULT_TEMPLATE).read_text(encoding="utf-8")
        assert "a.classList.add('glossary-term')" in t
        assert "a.dataset.glossaryTooltip = tip" in t
        # Confirm the body-level engine still targets any .glossary-term (covers
        # our anchors) and that the flip-below positioner keys off the same class.
        assert "closest('.glossary-term')" in t
        assert ".glossary-term" in t  # positionGlossaryTooltip operates on the term

    def test_prose_links_run_before_glossary(self):
        t = Path(DEFAULT_TEMPLATE).read_text(encoding="utf-8")
        assert t.index("this.initProseLinks();") < t.index("this.initGlossary();")

    def test_xref_style_present(self):
        t = Path(DEFAULT_TEMPLATE).read_text(encoding="utf-8")
        assert ".xref {" in t

    def test_link_map_and_link_mode_round_trip_into_data(self, tmp_path: Path):
        walkthrough = {
            "meta": {
                "repo": "github.com/example-org/example-repo",
                "git": {"branch": "main"},
                "link_mode": "github",
                "link_map": {"project-foundation": "infra/live/dev/project-foundation"},
            },
            "overview": {"goal": "G", "summary": ["Touches infra/live/dev and project-foundation."]},
            "steps": [{"id": "step-1", "title": "Build", "claims": []}],
        }
        html = _render(tmp_path, walkthrough)
        # meta survives into the embedded DATA so client JS can read it.
        assert '"link_mode": "github"' in html or '"link_mode":"github"' in html
        assert "project-foundation" in html
        assert "infra/live/dev/project-foundation" in html


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not available")
class TestProseLinksBehavior:
    """Exercise the ACTUAL JS helpers extracted from the template under node, with
    a minimal stub for `this`/DATA, so the load-bearing regexes and href resolver
    are tested for real (not just for presence)."""

    @staticmethod
    def _extract_method(source: str, name: str) -> str:
        """Extract the method DEFINITION `name(...) { ... }` (a definition starts a
        line, unlike call sites which are preceded by `.` or `(`) by brace-matching."""
        import re as _re
        m = _re.search(r"\n[ \t]*(" + _re.escape(name) + r"\([^)]*\)\s*\{)", source)
        assert m, f"could not find method definition {name}"
        start = m.start(1)
        i = source.index("{", start)
        depth = 0
        j = i
        while j < len(source):
            c = source[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return source[start : j + 1]
            j += 1
        raise AssertionError(f"could not extract method {name}")

    def _run(self, data_meta: dict, calls_js: str) -> dict:
        template = Path(DEFAULT_TEMPLATE).read_text(encoding="utf-8")
        methods = [
            "githubFileHref", "githubTreeOrBlobHref", "getRepoRoot", "normalizeFileRef",
            "proseLinkMode", "normalizeLinkMap", "proseLinkRegexes", "resolveProseHref",
            "normalizeGlossary", "normalizeGlossaryHref", "glossaryRegex",
            "glossaryLinkLookup", "proseLinkTooltip",
        ]
        method_src = ",\n".join(self._extract_method(template, m) for m in methods)
        # A glossary, when given, sits at DATA top level (as initGlossary reads it),
        # not under meta. Callers pass it via the special "_glossary" meta key.
        data_meta = dict(data_meta)  # don't mutate a shared class-attr dict
        glossary = data_meta.pop("_glossary", None)
        data = {"meta": data_meta}
        if glossary is not None:
            data["glossary"] = glossary
        harness = textwrap.dedent(
            """
            const DATA = %s;
            const obj = {
            %s
            };
            const out = (function(){ %s })();
            console.log(JSON.stringify(out));
            """
        ) % (
            json.dumps(data),
            method_src,
            calls_js,
        )
        proc = subprocess.run(
            [NODE, "-e", harness],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout.strip())

    def _eval(self, meta: dict, body: str):
        return self._run(meta, body)

    GH_META = {"repo": "github.com/example-org/example-repo", "git": {"branch": "main"}}

    def test_path_to_github_blob_and_tree(self):
        out = self._eval(self.GH_META, """
            const mode = obj.proseLinkMode();
            return {
                mode,
                dir: obj.resolveProseHref('infra/live/dev', mode, true, false),
                file: obj.resolveProseHref('infra/modules/monitoring/main.tf', mode, true, false),
                justfile: obj.resolveProseHref('justfile', mode, true, false),
            };
        """)
        assert out["mode"] == "github"
        assert out["dir"] == "https://github.com/example-org/example-repo/tree/main/infra/live/dev"
        assert out["file"] == "https://github.com/example-org/example-repo/blob/main/infra/modules/monitoring/main.tf"
        assert out["justfile"] == "https://github.com/example-org/example-repo/blob/main/justfile"

    def test_link_mode_off_drops_path_but_keeps_explicit(self):
        out = self._eval({**self.GH_META, "link_mode": "off"}, """
            const mode = obj.proseLinkMode();
            return {
                mode,
                path: obj.resolveProseHref('infra/live/dev', mode, true, false),
                explicit: obj.resolveProseHref('https://example.com', mode, true, true),
            };
        """)
        assert out["mode"] == "off"
        assert out["path"] == ""
        assert out["explicit"] == "https://example.com"

    def test_editor_mode_uses_cursor(self):
        out = self._eval({"repo_root": "/Users/dev/proj", "link_mode": "editor"}, """
            const mode = obj.proseLinkMode();
            return { mode, path: obj.resolveProseHref('infra/live/dev', mode, true, false) };
        """)
        assert out["mode"] == "editor"
        assert out["path"].startswith("cursor://file//Users/dev/proj/infra/live/dev")

    def test_default_mode_without_repo_is_off(self):
        out = self._eval({}, "return { mode: obj.proseLinkMode() };")
        assert out["mode"] == "off"

    def test_default_mode_with_github_repo_is_github(self):
        out = self._eval(self.GH_META, "return { mode: obj.proseLinkMode() };")
        assert out["mode"] == "github"

    def test_link_map_normalized_longest_first(self):
        out = self._eval(
            {**self.GH_META, "link_map": {"gemini": "infra/x", "gemini-search": "infra/modules/gemini-search"}},
            "return obj.normalizeLinkMap();",
        )
        assert out[0]["token"] == "gemini-search"

    def test_path_regex_matches_real_tokens(self):
        out = self._eval(self.GH_META, """
            const res = obj.proseLinkRegexes([]);
            const probe = (s) => { res.path.lastIndex = 0; const m = res.path.exec(s); return m ? m[1] : null; };
            return {
                a: probe('see infra/live/dev for details'),
                b: probe('the .github/workflows/infra.yml file'),
                c: probe('run justfile now'),
                d: probe('no path here at all'),
                e: probe('scripts/ci/check-iam-authority.sh runs'),
            };
        """)
        assert out["a"] == "infra/live/dev"
        assert out["b"] == ".github/workflows/infra.yml"
        assert out["c"] == "justfile"
        assert out["d"] is None
        assert out["e"] == "scripts/ci/check-iam-authority.sh"

    def test_markdown_link_regex(self):
        out = self._eval(self.GH_META, r"""
            const res = obj.proseLinkRegexes([]);
            const m = res.md.exec('see [the docs](https://example.com/x) here');
            return { label: m[1], url: m[2].trim() };
        """)
        assert out["label"] == "the docs"
        assert out["url"] == "https://example.com/x"

    def test_markdown_link_regex_captures_double_quoted_title(self):
        out = self._eval(self.GH_META, r"""
            const res = obj.proseLinkRegexes([]);
            const m = res.md.exec('see [the docs](https://example.com/x "hover text") here');
            return { label: m[1], url: m[2].trim(), title: m[3] };
        """)
        assert out["label"] == "the docs"
        assert out["url"] == "https://example.com/x"
        assert out["title"] == "hover text"

    def test_markdown_link_regex_captures_single_quoted_title(self):
        out = self._eval(self.GH_META, r"""
            const res = obj.proseLinkRegexes([]);
            const m = res.md.exec("see [the docs](https://example.com/x 'tip!') here");
            return { url: m[2].trim(), title3: m[3], title4: m[4] };
        """)
        assert out["url"] == "https://example.com/x"
        # The single-quoted title is captured in group 4.
        assert out["title4"] == "tip!"

    def test_link_map_object_form_carries_path_and_tooltip(self):
        out = self._eval(
            {
                **self.GH_META,
                "link_map": {
                    "project-adopt": {"path": "infra/live/prod/project-adopt", "tooltip": "Adopts the live project"},
                    "plain-token": "infra/x",
                },
            },
            "return obj.normalizeLinkMap();",
        )
        by_token = {e["token"]: e for e in out}
        assert by_token["project-adopt"]["target"] == "infra/live/prod/project-adopt"
        assert by_token["project-adopt"]["tooltip"] == "Adopts the live project"
        # String form still works and yields an empty tooltip.
        assert by_token["plain-token"]["target"] == "infra/x"
        assert by_token["plain-token"]["tooltip"] == ""

    def test_link_map_object_form_accepts_href(self):
        out = self._eval(
            {**self.GH_META, "link_map": {"ext": {"href": "https://example.com/ext", "tooltip": "External"}}},
            "return obj.normalizeLinkMap();",
        )
        assert out[0]["target"] == "https://example.com/ext"
        assert out[0]["tooltip"] == "External"

    GLOSS_META = {
        **GH_META,
        "_glossary": [
            {"term": "Terragrunt", "aliases": ["TG"], "definition": "IaC orchestration tool"},
            {"term": "audit-logging", "definition": "The audit module", "file": "infra/modules/audit-logging"},
        ],
    }

    def test_tooltip_precedence_explicit_wins(self):
        out = self._eval(self.GLOSS_META, """
            return {
                explicit: obj.proseLinkTooltip('Author tip', 'Terragrunt', 'infra/modules/audit-logging'),
            };
        """)
        # Explicit author text beats any glossary inheritance.
        assert out["explicit"] == "Author tip"

    def test_tooltip_inherits_glossary_by_text(self):
        out = self._eval(self.GLOSS_META, """
            return {
                exact: obj.proseLinkTooltip('', 'Terragrunt', 'infra/live/dev'),
                alias: obj.proseLinkTooltip('', 'TG', 'infra/live/dev'),
                caseInsensitive: obj.proseLinkTooltip('', 'terragrunt', 'infra/live/dev'),
            };
        """)
        assert "Terragrunt" in out["exact"] and "IaC orchestration tool" in out["exact"]
        # Alias resolves to the same entry's tooltip.
        assert "Terragrunt" in out["alias"]
        assert "Terragrunt" in out["caseInsensitive"]

    def test_tooltip_inherits_glossary_by_target_path(self):
        out = self._eval(self.GLOSS_META, """
            return {
                byPath: obj.proseLinkTooltip('', 'some link text', 'infra/modules/audit-logging'),
                byPathLeadingDot: obj.proseLinkTooltip('', 'x', './infra/modules/audit-logging'),
            };
        """)
        assert "audit-logging" in out["byPath"] and "The audit module" in out["byPath"]
        assert "audit-logging" in out["byPathLeadingDot"]

    def test_tooltip_empty_when_no_match(self):
        out = self._eval(self.GLOSS_META, """
            return { none: obj.proseLinkTooltip('', 'no-such-term', 'infra/no/match') };
        """)
        assert out["none"] == ""


@pytest.mark.skipif(NODE is None, reason="node not available")
class TestProseLinkTooltipDom:
    """Exercise the real DOM-mutating linkifyProseTextNode under node with a tiny
    DOM shim, so the anchor it builds — and the tooltip it attaches — are tested
    for real. The shim implements only what the method touches: createElement /
    createTextNode / createDocumentFragment and node.replaceChild."""

    DOM_SHIM = r"""
        class Node {
            constructor(){ this.childNodes = []; this.parentNode = null; }
            appendChild(c){ c.parentNode = this; this.childNodes.push(c); return c; }
            replaceChild(neu, old){
                const i = this.childNodes.indexOf(old);
                if (i < 0) return;
                // A fragment splices its children in place.
                const kids = (neu.nodeType === 11) ? neu.childNodes.slice() : [neu];
                kids.forEach(k => { k.parentNode = this; });
                this.childNodes.splice(i, 1, ...kids);
            }
        }
        class TextNode extends Node {
            constructor(v){ super(); this.nodeType = 3; this.nodeValue = v; }
            get textContent(){ return this.nodeValue; }
        }
        class Element extends Node {
            constructor(tag){ super(); this.nodeType = 1; this.tagName = tag.toUpperCase();
                this.attributes = {}; this.dataset = {}; this._classes = new Set();
                this._href=''; this._target=''; this._rel=''; }
            set className(v){ this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
            get className(){ return Array.from(this._classes).join(' '); }
            get classList(){ const s=this._classes; return { add:(c)=>s.add(c), contains:(c)=>s.has(c) }; }
            setAttribute(k,v){ this.attributes[k]=v; }
            getAttribute(k){ return this.attributes[k]; }
            set href(v){ this._href=v; } get href(){ return this._href; }
            set target(v){ this._target=v; } get target(){ return this._target; }
            set rel(v){ this._rel=v; } get rel(){ return this._rel; }
            set textContent(v){ this.childNodes=[new TextNode(v)]; } get textContent(){ return this.childNodes.map(c=>c.textContent||'').join(''); }
        }
        class Fragment extends Node { constructor(){ super(); this.nodeType = 11; } }
        const document = {
            createElement:(t)=>new Element(t),
            createTextNode:(v)=>new TextNode(v),
            createDocumentFragment:()=>new Fragment(),
        };
    """

    def _run_linkify(self, meta: dict, prose_text: str) -> dict:
        """Linkify a single prose text node; return a serialized view of the result
        children (anchors carry class/href/target/rel/text/tooltip/aria)."""
        template = Path(DEFAULT_TEMPLATE).read_text(encoding="utf-8")
        extract = TestProseLinksBehavior._extract_method
        methods = [
            "githubFileHref", "githubTreeOrBlobHref", "getRepoRoot", "normalizeFileRef",
            "proseLinkMode", "normalizeLinkMap", "proseLinkRegexes", "resolveProseHref",
            "normalizeGlossary", "normalizeGlossaryHref", "glossaryRegex",
            "glossaryLinkLookup", "proseLinkTooltip", "linkifyProseTextNode",
        ]
        method_src = ",\n".join(extract(template, m) for m in methods)
        harness = textwrap.dedent(
            """
            %s
            const DATA = %s;
            const obj = {
            %s
            };
            // Build a parent element holding one text node, then linkify it.
            const parent = document.createElement('div');
            const node = document.createTextNode(%s);
            parent.appendChild(node);
            const res = obj.proseLinkRegexes(obj.normalizeLinkMap());
            obj.linkifyProseTextNode(node, res, obj.proseLinkMode(), obj.normalizeLinkMap());
            const out = parent.childNodes.map(c => {
                if (c.nodeType === 3) return { type: 'text', text: c.nodeValue };
                return {
                    type: 'a',
                    class: c.className,
                    href: c.href,
                    target: c.target,
                    rel: c.rel,
                    text: c.textContent,
                    tooltip: c.dataset.glossaryTooltip || null,
                    aria: c.getAttribute('aria-label') || null,
                };
            });
            console.log(JSON.stringify(out));
            """
        ) % (
            self.DOM_SHIM,
            json.dumps({"meta": meta} if "glossary" not in meta else {"meta": {k: v for k, v in meta.items() if k != "glossary"}, "glossary": meta["glossary"]}),
            method_src,
            json.dumps(prose_text),
        )
        proc = subprocess.run([NODE, "-e", harness], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout.strip())

    GH_META = {"repo": "github.com/example-org/example-repo", "git": {"branch": "main"}}

    def _anchors(self, result):
        return [c for c in result if c["type"] == "a"]

    def test_link_map_object_form_produces_anchor_with_tooltip(self):
        meta = {
            **self.GH_META,
            "link_mode": "github",
            "link_map": {"project-adopt": {"path": "infra/live/prod/project-adopt", "tooltip": "Adopts the live project"}},
        }
        result = self._run_linkify(meta, "We run project-adopt last.")
        anchors = self._anchors(result)
        assert len(anchors) == 1
        a = anchors[0]
        assert a["text"] == "project-adopt"
        assert "xref" in a["class"] and "glossary-term" in a["class"]
        assert a["tooltip"] == "Adopts the live project"
        assert a["aria"] == "Adopts the live project"
        assert a["href"].endswith("/tree/main/infra/live/prod/project-adopt")
        # Still a real link.
        assert a["target"] == "_blank"
        assert "noreferrer" in a["rel"]

    def test_inline_markdown_title_becomes_tooltip(self):
        meta = {**self.GH_META, "link_mode": "github"}
        result = self._run_linkify(meta, 'See [the runbook](https://example.com/rb "How to recover") for steps.')
        anchors = self._anchors(result)
        assert len(anchors) == 1
        a = anchors[0]
        assert a["text"] == "the runbook"
        assert a["href"] == "https://example.com/rb"
        assert a["tooltip"] == "How to recover"
        assert "glossary-term" in a["class"]

    def test_plain_markdown_link_has_no_tooltip(self):
        meta = {**self.GH_META, "link_mode": "github"}
        result = self._run_linkify(meta, "See [the runbook](https://example.com/rb) for steps.")
        anchors = self._anchors(result)
        assert len(anchors) == 1
        assert anchors[0]["tooltip"] is None
        assert "glossary-term" not in anchors[0]["class"]

    def test_link_inherits_glossary_tooltip_by_text(self):
        meta = {
            **self.GH_META,
            "link_mode": "github",
            "link_map": {"Terragrunt": "infra/live/dev"},
            "glossary": [{"term": "Terragrunt", "definition": "IaC orchestration tool"}],
        }
        result = self._run_linkify(meta, "We adopt Terragrunt for IaC.")
        anchors = self._anchors(result)
        assert len(anchors) == 1
        a = anchors[0]
        assert a["text"] == "Terragrunt"
        assert a["tooltip"] is not None
        assert "Terragrunt" in a["tooltip"] and "IaC orchestration tool" in a["tooltip"]
        assert "glossary-term" in a["class"]

    def test_link_inherits_glossary_tooltip_by_target_path(self):
        meta = {
            **self.GH_META,
            "link_mode": "github",
            "link_map": {"the audit module": "infra/modules/audit-logging"},
            "glossary": [{"term": "audit-logging", "definition": "Org-level data access logs", "file": "infra/modules/audit-logging"}],
        }
        # Link text does not match the glossary term, but the resolved target path does.
        result = self._run_linkify(meta, "Configured by the audit module here.")
        anchors = self._anchors(result)
        assert len(anchors) == 1
        a = anchors[0]
        assert a["tooltip"] is not None
        assert "audit-logging" in a["tooltip"] and "Org-level data access logs" in a["tooltip"]

    def test_explicit_tooltip_beats_glossary_inheritance(self):
        meta = {
            **self.GH_META,
            "link_mode": "github",
            "link_map": {"Terragrunt": {"path": "infra/live/dev", "tooltip": "Our pinned wrapper"}},
            "glossary": [{"term": "Terragrunt", "definition": "IaC orchestration tool"}],
        }
        result = self._run_linkify(meta, "We adopt Terragrunt for IaC.")
        anchors = self._anchors(result)
        assert len(anchors) == 1
        assert anchors[0]["tooltip"] == "Our pinned wrapper"

    def test_path_link_with_no_matching_glossary_stays_untooltipd(self):
        meta = {
            **self.GH_META,
            "link_mode": "github",
            "glossary": [{"term": "Terragrunt", "definition": "IaC orchestration tool"}],
        }
        result = self._run_linkify(meta, "Edit infra/live/dev to change it.")
        anchors = self._anchors(result)
        assert len(anchors) == 1
        a = anchors[0]
        assert a["text"] == "infra/live/dev"
        assert a["tooltip"] is None
        assert "glossary-term" not in a["class"]
