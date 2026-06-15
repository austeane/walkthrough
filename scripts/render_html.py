#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["jinja2>=3.1", "pygments>=2.17"]
# ///
"""Render walkthrough.json into a single-file walkthrough.html.

Reads a walkthrough JSON file, generates Pygments CSS for syntax-highlighted
diff hunks, renders the Jinja2 template, embeds the JSON data for client-side
interactivity, and writes a self-contained HTML file.

This is the only pipeline script with third-party dependencies. The inline
metadata block above lets `uv run scripts/render_html.py ...` resolve them in
an isolated environment from any working directory (note: the script path must
be the command — `uv run python3 scripts/render_html.py` ignores the block and
uses whatever project environment the working directory resolves to).
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import DiffLexer, get_lexer_for_filename, TextLexer

try:
    from scripts.inject_capture_media import attach_capture_media
except Exception:
    try:
        from inject_capture_media import attach_capture_media
    except Exception:
        attach_capture_media = None

try:
    from scripts.validate_walkthrough_quality import validate_walkthrough
except Exception:
    try:
        from validate_walkthrough_quality import validate_walkthrough
    except Exception:
        validate_walkthrough = None

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = SCRIPT_DIR.parent / "assets" / "walkthrough-template.html"
DISPLAYABLE_ROOT_DIRS = {"src", "e2e", "scripts", "docs", "db", "repos", "likec4"}
MAX_OVERVIEW_INDEX_ITEMS = 10
MAX_OVERVIEW_TEASER_CHARS = 180

# --- View modes -----------------------------------------------------------
# Every step / claim / decision / gotcha carries an optional `mode` saying which
# of the two reader views it belongs to. The viewer can toggle between:
#   "end-state" — just where the work landed (the final architecture/result).
#   "journey"   — how we got there (the chronology, pivots, dead-ends).
# `both` (the default for most content) shows in either view. Gotchas default to
# `journey` because a problem-hit-and-fixed is by nature "how we got here"; tag a
# gotcha `both`/`end-state` when it is really a live, current constraint.
VIEW_VALUES = {"both", "journey", "end-state"}
DEFAULT_DECISION_VIEW = "both"
DEFAULT_GOTCHA_VIEW = "journey"

# --- Optional UI features (meta.ui) ----------------------------------------
# Viewer chrome features are gated by booleans in the walkthrough's `meta.ui`
# block, all defaulting to ON so existing walkthroughs render unchanged:
#   view_switcher     — the End State / Journey segmented control (drop it to
#                       lock the document to the End State view).
#   present_mode      — the slideshow / Present toggle (drop it to keep the page
#                       in reading mode only).
#   stats             — the overview/deck stat strip (steps/files/commands/...).
#   confidence_legend — the grounded/inferred/speculative confidence legend
#                       (only ever shown when non-grounded claims exist).
# A missing `meta`/`meta.ui`, or a non-bool/missing key, coerces to the default.
UI_FEATURE_DEFAULTS = {
    "view_switcher": True,
    "present_mode": True,
    "stats": True,
    "confidence_legend": True,
}


def resolve_ui_flags(meta: object) -> dict[str, bool]:
    """Read `meta.ui` feature flags, coercing missing/non-bool values to their default."""
    ui = meta.get("ui") if isinstance(meta, dict) else None
    ui = ui if isinstance(ui, dict) else {}
    return {
        key: bool(ui.get(key)) if isinstance(ui.get(key), bool) else default
        for key, default in UI_FEATURE_DEFAULTS.items()
    }


def normalize_view(value: object, default: str) -> str:
    """Clamp an authored `mode` value to one of {both, journey, end-state}."""
    text = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
    if text in VIEW_VALUES:
        return text
    if text in {"endstate", "end"}:
        return "end-state"
    return default


def effective_item_view(step_view: str, item_view: str) -> str:
    """A step pinned to one view forces its items there; otherwise use the item's own view."""
    return step_view if step_view != "both" else item_view


def get_pygments_css() -> str:
    """Generate Pygments CSS for the 'monokai' style scoped to .highlight."""
    formatter = HtmlFormatter(style="monokai", cssclass="highlight", nobackground=True)
    return formatter.get_style_defs(".highlight")


def highlight_diff_hunk(hunk: dict) -> dict:
    """Add a trusted rendered diff HTML field derived only from structured diff data."""
    result = {k: v for k, v in dict(hunk).items() if k != "html"}
    raw_diff = result.get("diff", "")

    if not raw_diff and (result.get("before") is not None or result.get("after") is not None):
        lines = []
        before = result.get("before", "") or ""
        after = result.get("after", "") or ""
        for line in before.splitlines():
            lines.append(f"- {line}")
        for line in after.splitlines():
            lines.append(f"+ {line}")
        raw_diff = "\n".join(lines)

    if not raw_diff:
        return result

    formatter = HtmlFormatter(nowrap=False, cssclass="highlight", nobackground=True)
    try:
        lexer = DiffLexer()
        html = highlight(raw_diff, lexer, formatter)
    except Exception:
        html = f"<pre>{_escape(raw_diff)}</pre>"

    result["rendered_html"] = html
    return result


def _escape(text: str) -> str:
    """HTML-escape a string."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )




def _compact_text(value: object) -> str:
    """Collapse model prose into a one-line UI string."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    break_at = text.rfind(" ", 0, max_chars + 1)
    if break_at < int(max_chars * 0.65):
        break_at = max_chars
    return text[:break_at].rstrip(" .,;:") + "..."


def derive_step_overview_teaser(step: dict) -> str:
    """Pick the best compact line for overview navigation."""
    for key in ("takeaway", "intent"):
        text = _compact_text(step.get(key))
        if text:
            return _truncate_text(text, MAX_OVERVIEW_TEASER_CHARS)

    claims = step.get("claims") or []
    if isinstance(claims, list):
        for claim in claims:
            text = _compact_text(claim.get("text") if isinstance(claim, dict) else claim)
            if text:
                return _truncate_text(text, MAX_OVERVIEW_TEASER_CHARS)

    return ""


def normalize_step_reasoning_items(step: dict) -> None:
    """Normalize legacy string decisions/gotchas into the renderer object shape."""
    step["decisions"] = _normalize_reasoning_list(step.get("decisions"), "decision")
    gotchas = step.get("errors_encountered")
    if gotchas is None:
        gotchas = step.get("gotchas")
    step["errors_encountered"] = _normalize_reasoning_list(gotchas, "gotcha")


def _normalize_reasoning_list(items: object, kind: str) -> list[dict]:
    if not isinstance(items, list):
        items = [items] if _compact_text(items) else []

    normalized: list[dict] = []
    for item in items:
        if isinstance(item, dict):
            next_item = dict(item)
            if kind == "decision":
                text = _compact_text(
                    next_item.get("decision") or next_item.get("text") or next_item.get("message")
                )
                if not text:
                    continue
                next_item["decision"] = text
                if "rationale" not in next_item and next_item.get("detail"):
                    next_item["rationale"] = _compact_text(next_item.get("detail"))
            else:
                text = _compact_text(
                    next_item.get("error") or next_item.get("text") or next_item.get("message")
                )
                if not text:
                    continue
                next_item["error"] = text
                if "resolution" not in next_item:
                    resolution = _compact_text(next_item.get("fix") or next_item.get("detail"))
                    if resolution:
                        next_item["resolution"] = resolution
            normalized.append(next_item)
            continue

        text = _compact_text(item)
        if not text:
            continue
        normalized.append({"decision": text} if kind == "decision" else {"error": text})

    return normalized


def normalize_file_ref(file_path: object, repo_root: str = "") -> dict:
    """Build consistent labels and editor targets for file references."""
    if isinstance(file_path, dict):
        raw_path = str(file_path.get("path") or file_path.get("file") or "")
    else:
        raw_path = str(file_path or "")
    repo_root = str(repo_root or "").rstrip("/")
    if not raw_path:
        return {
            "raw_path": "",
            "label_path": "",
            "abs_path": "",
            "cursor_href": "",
            "vscode_href": "",
        }

    if os.path.isabs(raw_path):
        abs_path = os.path.normpath(raw_path)
    elif repo_root:
        abs_path = os.path.normpath(os.path.join(repo_root, raw_path))
    else:
        abs_path = raw_path

    label_path = raw_path[2:] if raw_path.startswith("./") else raw_path
    if repo_root and abs_path and os.path.isabs(abs_path):
        try:
            if os.path.commonpath([os.path.realpath(abs_path), os.path.realpath(repo_root)]) == os.path.realpath(repo_root):
                label_path = os.path.relpath(abs_path, repo_root)
        except ValueError:
            label_path = raw_path
    elif os.path.isabs(raw_path):
        label_path = raw_path

    encoded_abs = quote(abs_path, safe="/") if abs_path else ""
    cursor_href = f"cursor://file/{encoded_abs}" if encoded_abs else ""
    vscode_href = f"vscode://file/{encoded_abs}" if encoded_abs else ""
    return {
        "raw_path": raw_path,
        "label_path": label_path,
        "abs_path": abs_path,
        "cursor_href": cursor_href,
        "vscode_href": vscode_href,
    }


def is_in_repo(abs_path: str, repo_root: str) -> bool:
    """Return True when abs_path resolves inside repo_root."""
    if not abs_path or not repo_root or not os.path.isabs(abs_path):
        return False
    try:
        return os.path.commonpath([os.path.realpath(abs_path), os.path.realpath(repo_root)]) == os.path.realpath(repo_root)
    except ValueError:
        return False


def should_display_file_ref(ref: dict, repo_root: str, *, overview: bool = False) -> bool:
    """Filter obvious noise/sensitive refs so the walkthrough stays repo-focused."""
    raw_path = str(ref.get("raw_path") or "")
    abs_path = str(ref.get("abs_path") or "")
    label_path = str(ref.get("label_path") or raw_path)

    if not raw_path and not abs_path:
        return False

    base_name = os.path.basename(label_path).lower()
    if base_name.startswith(".env"):
        return False
    if "worklog" in base_name and base_name.endswith(".md"):
        return False

    normalized_label = label_path.replace("\\", "/").lstrip("./")
    if normalized_label.startswith("e2e-test-results/"):
        return False

    if (raw_path.startswith("/tmp/") or abs_path.startswith("/tmp/")) and not is_in_repo(abs_path, repo_root):
        return False

    if repo_root:
        if abs_path and os.path.isabs(abs_path) and not is_in_repo(abs_path, repo_root):
            return False
        if is_in_repo(abs_path, repo_root):
            rel_path = os.path.relpath(os.path.realpath(abs_path), os.path.realpath(repo_root)).replace("\\", "/")
            top_level = rel_path.split("/", 1)[0]
            if overview and top_level not in DISPLAYABLE_ROOT_DIRS:
                return False

    return True


def filter_file_refs(file_paths: list[object], repo_root: str, *, overview: bool = False) -> list[dict]:
    """Normalize, filter, and deduplicate displayed file refs while preserving order."""
    refs: list[dict] = []
    seen: set[str] = set()
    for file_path in file_paths or []:
        ref = normalize_file_ref(file_path, repo_root)
        key = ref.get("abs_path") or ref.get("raw_path")
        if not key or key in seen:
            continue
        if not should_display_file_ref(ref, repo_root, overview=overview):
            continue
        seen.add(str(key))
        refs.append(ref)
    return refs


def _normalize_overview_index_item(
    item: dict,
    step: dict,
    step_number: int,
    kind: str,
    item_number: int,
    view: str = "both",
) -> dict | None:
    """Convert a decision/gotcha into a compact overview jump item."""
    if not isinstance(item, dict):
        return None
    if kind == "decision":
        text = item.get("decision") or item.get("text") or ""
        detail = item.get("rationale") or ""
    else:
        text = item.get("error") or item.get("text") or item.get("message") or ""
        detail = item.get("resolution") or ""
    text = str(text or "").strip()
    if not text:
        return None
    step_id = step.get("id") or f"step-{step_number}"
    return {
        "kind": kind,
        "step_id": step_id,
        "step_number": step_number,
        "step_title": step.get("title") or f"Step {step_number}",
        "item_number": item_number,
        "target_id": f"{step_id}-{kind}-{item_number}",
        "text": text,
        "detail": str(detail or "").strip(),
        "view": view,
    }


def build_overview_indices(steps: list[dict]) -> dict[str, list[dict]]:
    """Build compact decision/gotcha jump indices for the overview.

    The overview is capped, so take the first item from each step before taking
    second items. That keeps one dense step from hiding later work phases.
    """
    per_step_decisions: list[list[dict]] = []
    per_step_gotchas: list[list[dict]] = []
    for idx, step in enumerate(steps or [], start=1):
        if not isinstance(step, dict):
            continue
        step_view = normalize_view(step.get("mode"), "both")
        step_decisions: list[dict] = []
        for item_idx, decision in enumerate(step.get("decisions") or [], start=1):
            view = effective_item_view(
                step_view,
                normalize_view((decision or {}).get("mode"), DEFAULT_DECISION_VIEW)
                if isinstance(decision, dict) else DEFAULT_DECISION_VIEW,
            )
            item = _normalize_overview_index_item(decision, step, idx, "decision", item_idx, view)
            if item:
                step_decisions.append(item)
        if step_decisions:
            per_step_decisions.append(step_decisions)
        step_gotchas: list[dict] = []
        for item_idx, error in enumerate(step.get("errors_encountered") or [], start=1):
            view = effective_item_view(
                step_view,
                normalize_view((error or {}).get("mode"), DEFAULT_GOTCHA_VIEW)
                if isinstance(error, dict) else DEFAULT_GOTCHA_VIEW,
            )
            item = _normalize_overview_index_item(error, step, idx, "gotcha", item_idx, view)
            if item:
                step_gotchas.append(item)
        if step_gotchas:
            per_step_gotchas.append(step_gotchas)
    decision_total = sum(len(group) for group in per_step_decisions)
    gotcha_total = sum(len(group) for group in per_step_gotchas)
    decisions = _round_robin_cap(per_step_decisions, decision_total)
    gotchas = _round_robin_cap(per_step_gotchas, gotcha_total)
    return {
        "decisions": decisions[:MAX_OVERVIEW_INDEX_ITEMS],
        "decision_overflow": decisions[MAX_OVERVIEW_INDEX_ITEMS:],
        "gotchas": gotchas[:MAX_OVERVIEW_INDEX_ITEMS],
        "gotcha_overflow": gotchas[MAX_OVERVIEW_INDEX_ITEMS:],
        "decision_total": decision_total,
        "gotcha_total": gotcha_total,
    }


def _round_robin_cap(groups: list[list[dict]], limit: int) -> list[dict]:
    result: list[dict] = []
    depth = 0
    while len(result) < limit:
        added = False
        for group in groups:
            if depth < len(group):
                result.append(group[depth])
                added = True
                if len(result) >= limit:
                    break
        if not added:
            break
        depth += 1
    return result


def sanitize_svg(svg: str) -> str:
    """Strip wrapper noise and reject obviously dangerous SVG content."""
    cleaned = re.sub(r"^\s*<\?xml[^>]*>\s*", "", svg, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*<!DOCTYPE[^>]*>\s*", "", cleaned, flags=re.IGNORECASE)
    forbidden_patterns = (
        r"<\s*script\b",
        r"\son\w+\s*=",
        r"(?:href|xlink:href)\s*=\s*['\"]\s*javascript:",
    )
    if any(re.search(pattern, cleaned, flags=re.IGNORECASE) for pattern in forbidden_patterns):
        return ""
    return cleaned if "<svg" in cleaned.lower() else ""


def render_mermaid_svg(diagram_mermaid: str) -> str:
    """Render Mermaid source to inline SVG using the local Mermaid CLI."""
    if not diagram_mermaid.strip():
        return ""

    with tempfile.TemporaryDirectory(prefix="walkthrough-mermaid-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / "diagram.mmd"
        output_path = tmp_path / "diagram.svg"
        config_path = tmp_path / "mermaid-config.json"
        input_path.write_text(diagram_mermaid, encoding="utf-8")
        config_path.write_text(
            json.dumps(
                {
                    "securityLevel": "strict",
                    "theme": "neutral",
                    "flowchart": {"htmlLabels": False},
                }
            ),
            encoding="utf-8",
        )
        try:
            subprocess.run(
                [
                    "mmdc",
                    "--quiet",
                    "--backgroundColor",
                    "transparent",
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--configFile",
                    str(config_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            return ""

        try:
            return sanitize_svg(output_path.read_text(encoding="utf-8"))
        except OSError:
            return ""


def _image_to_data_uri(path: Path, max_width: int = 1920) -> str:
    """Embed an image file as a data URI, downscaling to max_width when Pillow is available.

    Preserves transparency (re-encodes to PNG when resized). Falls back to embedding
    the raw bytes if Pillow is missing or the image is already within max_width.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    import base64

    mime = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml",
    }.get(path.suffix.lower(), "image/png")
    try:
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(raw))
        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize((max_width, max(1, int(img.height * ratio))), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"
    except Exception:
        pass
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _resolve_existing_path(ref: str, base_dir: Path, repo_root: str) -> Path | None:
    """Resolve an image ref to an existing file: absolute, then repo-root-relative, then base-dir-relative."""
    if not ref:
        return None
    p = Path(ref)
    candidates: list[Path] = [p] if p.is_absolute() else []
    if not p.is_absolute():
        if repo_root:
            candidates.append(Path(repo_root) / ref)
        candidates.append(base_dir / ref)
    return next((c for c in candidates if c.exists()), None)


def embed_overview_diagram_images(overview: dict, base_dir: Path, repo_root: str) -> None:
    """Resolve overview.diagram_image into embedded data URIs (_diagram_image_light / _dark).

    ``diagram_image`` may be a string (one image, used for both themes) or an object
    ``{"light": <path>, "dark": <path>}``. Paths resolve against repo_root then base_dir.
    This is preferred over a Mermaid diagram when present (e.g. a real LikeC4 export).
    """
    spec = overview.get("diagram_image")
    if not spec:
        return
    if isinstance(spec, str):
        light_ref = dark_ref = spec
    elif isinstance(spec, dict):
        light_ref = spec.get("light") or spec.get("dark") or ""
        dark_ref = spec.get("dark") or spec.get("light") or ""
    else:
        return
    light_path = _resolve_existing_path(light_ref, base_dir, repo_root)
    dark_path = _resolve_existing_path(dark_ref, base_dir, repo_root)
    if light_path is None and dark_path is None:
        print(f"Warning: overview diagram_image not found: {spec}", file=sys.stderr)
        return
    if light_path is not None:
        overview["_diagram_image_light"] = _image_to_data_uri(light_path)
    if dark_path is not None:
        overview["_diagram_image_dark"] = _image_to_data_uri(dark_path)


def embed_step_diagram_images(step: dict, base_dir: Path, repo_root: str) -> None:
    """Resolve step.diagram into embedded data URIs (_diagram_image_light / _dark).

    Mirrors embed_overview_diagram_images but per-step, so a step can carry its own
    architecture diagram rendered as an always-visible figure (a server-side <img>),
    rather than a lazy, JS-injected thumbnail inside the collapsed evidence block.
    ``diagram`` may be a string path or ``{"light": <path>, "dark": <path>}``; an
    optional ``diagram_caption`` becomes ``_diagram_caption``.
    """
    spec = step.get("diagram")
    if not spec:
        return
    if isinstance(spec, str):
        light_ref = dark_ref = spec
    elif isinstance(spec, dict):
        light_ref = spec.get("light") or spec.get("dark") or ""
        dark_ref = spec.get("dark") or spec.get("light") or ""
    else:
        return
    light_path = _resolve_existing_path(light_ref, base_dir, repo_root)
    dark_path = _resolve_existing_path(dark_ref, base_dir, repo_root)
    if light_path is None and dark_path is None:
        print(f"Warning: step {step.get('id', '?')} diagram not found: {spec}", file=sys.stderr)
        return
    if light_path is not None and light_path == dark_path:
        # Single theme-agnostic source — embed once (avoids duplicating the bytes).
        step["_diagram_image"] = _image_to_data_uri(light_path)
    else:
        if light_path is not None:
            step["_diagram_image_light"] = _image_to_data_uri(light_path)
        if dark_path is not None:
            step["_diagram_image_dark"] = _image_to_data_uri(dark_path)
    caption = step.get("diagram_caption")
    if caption:
        step["_diagram_caption"] = caption


def resolve_walkthrough_video(
    node: dict, base_dir: Path, repo_root: str, html_dir: Path, label: str
) -> None:
    """Resolve a ``video`` spec (overview-level or step-level) into ``_video``.

    ``video`` is ``{"src": <path-or-url>, "poster": <path?>, "caption": <str?>,
    "embed": <bool?>}`` (a bare string is treated as ``src``). By default the
    video bytes are NOT embedded — a rendered mp4 is orders of magnitude larger
    than an image, so the HTML references the file by a path relative to the
    rendered output. ``"embed": true`` inlines the bytes as a base64 data URI
    instead, keeping the artifact a single self-contained file (sensible for
    short tours; the gate warns above ~15 MB). The poster image, when present,
    is always embedded like a diagram.
    """
    spec = node.get("video")
    if not spec:
        return
    if isinstance(spec, str):
        spec = {"src": spec}
    if not isinstance(spec, dict):
        return
    src = str(spec.get("src") or "").strip()
    if not src:
        return
    embedded = False
    if src.startswith(("http://", "https://")):
        src_href = src
    else:
        src_path = _resolve_existing_path(src, base_dir, repo_root)
        if src_path is None:
            print(f"Warning: {label} video not found: {src}", file=sys.stderr)
            return
        if spec.get("embed"):
            # Chromium's media pipeline rejects large data: URIs as a direct
            # <video src>, so the template parks the payload in a
            # data-embedded-src attribute and the viewer JS revives it as a
            # blob URL at load.
            mime = {
                ".webm": "video/webm",
                ".mov": "video/quicktime",
            }.get(src_path.suffix.lower(), "video/mp4")
            encoded = base64.b64encode(src_path.read_bytes()).decode("ascii")
            src_href = f"data:{mime};base64,{encoded}"
            embedded = True
        else:
            src_href = Path(os.path.relpath(src_path.resolve(), html_dir)).as_posix()
    video: dict = {"src": src_href}
    if embedded:
        video["embedded"] = True
    poster_ref = str(spec.get("poster") or "").strip()
    if poster_ref:
        poster_path = _resolve_existing_path(poster_ref, base_dir, repo_root)
        if poster_path is not None:
            video["poster"] = _image_to_data_uri(poster_path)
        else:
            print(f"Warning: {label} video poster not found: {poster_ref}", file=sys.stderr)
    caption = spec.get("caption")
    if caption:
        video["caption"] = caption
    node["_video"] = video


_LIKEC4_TAG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$")


def resolve_walkthrough_likec4(
    node: dict, base_dir: Path, repo_root: str, html_dir: Path, label: str
) -> None:
    """Resolve a ``diagram_likec4`` spec (overview-level or step-level) into ``_likec4``.

    ``diagram_likec4`` is ``{"views_js": <path>, "view": <view-id>,
    "tag": <custom-element>?, "height": <css-length>?, "caption": <str>?,
    "embed": <bool>?}``. ``views_js`` is the bundle produced by ``likec4
    codegen webcomponent``; by default it is inlined into the HTML so the
    artifact stays one self-contained file, while ``"embed": false`` keeps it
    as a sidecar referenced relative to the rendered HTML. ``tag`` defaults to
    ``c4-view`` (generate the bundle with ``-w c4``).
    """
    spec = node.get("diagram_likec4")
    if not spec or not isinstance(spec, dict):
        return
    views_js = str(spec.get("views_js") or "").strip()
    view_id = str(spec.get("view") or "").strip()
    if not views_js or not view_id:
        print(
            f"Warning: {label} diagram_likec4 needs both views_js and view — skipped",
            file=sys.stderr,
        )
        return
    if views_js.startswith(("http://", "https://")):
        # Unlike a video src, views_js becomes an executable <script src> —
        # a remote URL would let a JSON edit inject arbitrary JS into the
        # artifact. Local bundles only.
        print(
            f"Warning: {label} diagram_likec4 views_js must be a local file, not a URL — skipped",
            file=sys.stderr,
        )
        return
    src_path = _resolve_existing_path(views_js, base_dir, repo_root)
    if src_path is None:
        print(f"Warning: {label} diagram_likec4 views_js not found: {views_js}", file=sys.stderr)
        return
    src_href = Path(os.path.relpath(src_path.resolve(), html_dir)).as_posix()
    tag = str(spec.get("tag") or "c4-view").strip()
    if not _LIKEC4_TAG_RE.match(tag):
        print(
            f"Warning: {label} diagram_likec4 tag {tag!r} is not a valid custom-element name — using c4-view",
            file=sys.stderr,
        )
        tag = "c4-view"
    likec4: dict = {
        "src": src_href,
        "view": view_id,
        "tag": tag,
        # Inline the bundle into the HTML by default so the artifact stays a
        # single self-contained file; {"embed": false} opts into a sidecar
        # <script src> (e.g. several walkthroughs sharing one bundle).
        "embed": bool(spec.get("embed", True)),
        "_src_abs": str(src_path.resolve()),
    }
    height = str(spec.get("height") or "").strip()
    if height:
        if re.match(r"^\d{1,4}(?:px|vh|rem|em)$", height):
            likec4["height"] = height
        else:
            print(
                f"Warning: {label} diagram_likec4 height {height!r} is not a simple CSS length — ignored",
                file=sys.stderr,
            )
    caption = spec.get("caption")
    if caption:
        likec4["caption"] = caption
    node["_likec4"] = likec4


def summarize_evidence(evidence: dict) -> str:
    """Build the one-line scent label for the collapsed evidence block.

    The label is the reader's information scent: it says what is inside before
    they open it. A failing command is surfaced here (``N failed``) so a reader
    scanning sees trouble without expanding. The all-pass case stays a plain
    ``files · diffs · cmds · shots`` strip.
    """
    if not isinstance(evidence, dict):
        return "View Evidence"
    counts = []
    files = evidence.get("files_changed") or []
    if isinstance(files, list) and files:
        counts.append(f"{len(files)} {'file' if len(files) == 1 else 'files'}")
    hunks = evidence.get("diff_hunks") or []
    if isinstance(hunks, list) and hunks:
        counts.append(f"{len(hunks)} {'diff' if len(hunks) == 1 else 'diffs'}")
    commands = evidence.get("commands") or []
    if isinstance(commands, list) and commands:
        counts.append(f"{len(commands)} {'cmd' if len(commands) == 1 else 'cmds'}")
        failed = sum(
            1 for c in commands
            if isinstance(c, dict) and str(c.get("status", "")).lower() == "fail"
        )
        if failed:
            counts.append(f"{failed} failed")
    media_items = evidence.get("media") or evidence.get("screenshots") or []
    if isinstance(media_items, list) and media_items:
        counts.append(f"{len(media_items)} {'shot' if len(media_items) == 1 else 'shots'}")
    return " · ".join(counts) if counts else "View Evidence"


def serialize_script_data(data: dict) -> Markup:
    """Serialize JSON safely for inline <script> embedding."""
    text = json.dumps(data, ensure_ascii=False)
    text = text.replace("</", "<\\/")
    text = text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return Markup(text)

def prepare_data(data: dict) -> dict:
    """Process walkthrough data for safe rendering and consistent provenance links."""
    data = json.loads(json.dumps(data))  # deep copy
    repo_root = ((data.get("meta") or {}).get("repo_root") or "").rstrip("/")

    overview = data.get("overview")
    if not isinstance(overview, dict):
        overview = {}
        data["overview"] = overview
    overview["key_file_refs"] = filter_file_refs(overview.get("key_files", []), repo_root, overview=True)
    overview["key_files"] = [ref["raw_path"] for ref in overview["key_file_refs"]]

    # End-state framing: an optional alternate goal/summary shown in the
    # "end state" view. `goal`/`summary` stay the journey (and fallback) framing.
    end_state = overview.get("end_state")
    if isinstance(end_state, dict):
        es_goal = _compact_text(end_state.get("goal"))
        if es_goal:
            overview["_end_state_goal"] = es_goal
        es_summary = end_state.get("summary")
        if not isinstance(es_summary, list):
            es_summary = [es_summary] if _compact_text(es_summary) else []
        es_summary = [str(s).strip() for s in es_summary if _compact_text(s)]
        if es_summary:
            overview["_end_state_summary"] = es_summary
        # "How it works today" component panel + current constraints, shown only
        # in the end-state view. `architecture[].step_ref` links a component to
        # the step that details it (resolved to a step number + anchor here).
        steps_for_ref = data.get("steps") if isinstance(data.get("steps"), list) else []
        id_to_num = {
            s["id"]: i + 1
            for i, s in enumerate(steps_for_ref)
            if isinstance(s, dict) and s.get("id")
        }
        architecture = end_state.get("architecture")
        if isinstance(architecture, list):
            resolved = []
            for entry in architecture:
                if not isinstance(entry, dict):
                    continue
                component = _compact_text(entry.get("component"))
                if not component:
                    continue
                # A component may span several steps: `step_refs` lists them all;
                # legacy `step_ref` stays supported and leads the list.
                raw_refs = [entry.get("step_ref")] if entry.get("step_ref") else []
                if isinstance(entry.get("step_refs"), list):
                    raw_refs += [r for r in entry["step_refs"] if r and r not in raw_refs]
                refs = [
                    {"step_id": ref, "step_label": f"Step {id_to_num[ref]}"}
                    for ref in raw_refs
                    if id_to_num.get(ref)
                ]
                resolved.append({
                    "component": component,
                    "summary": _compact_text(entry.get("summary")),
                    # single-ref cards stay fully clickable; multi-ref cards
                    # render one link per step instead.
                    "step_id": refs[0]["step_id"] if len(refs) == 1 else "",
                    "step_label": refs[0]["step_label"] if len(refs) == 1 else "",
                    "refs": refs if len(refs) > 1 else [],
                })
            if resolved:
                overview["_end_state_architecture"] = resolved
        es_constraints = end_state.get("constraints")
        if isinstance(es_constraints, list):
            resolved_constraints = []
            for c in es_constraints:
                if isinstance(c, dict):
                    text = _compact_text(c.get("text"))
                    if not text:
                        continue
                    num = id_to_num.get(c.get("step_ref"))
                    resolved_constraints.append({
                        "text": text,
                        "step_id": c.get("step_ref") if num else "",
                        "step_label": f"Step {num}" if num else "",
                    })
                elif _compact_text(c):
                    resolved_constraints.append({"text": str(c).strip(), "step_id": "", "step_label": ""})
            if resolved_constraints:
                overview["_end_state_constraints"] = resolved_constraints
    has_diagram_image = bool(
        overview.get("diagram_image")
        or overview.get("_diagram_image_light")
        or overview.get("_diagram_image_dark")
    )
    overview["_diagram_svg"] = (
        ""
        if has_diagram_image
        else render_mermaid_svg(str(overview.get("diagram_mermaid") or ""))
    )
    steps = data.get("steps") if isinstance(data.get("steps"), list) else []
    any_es_order = False
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        normalize_step_reasoning_items(step)
        step["_overview_teaser"] = derive_step_overview_teaser(step)
        # Per-view ordering: the journey view keeps authored (chronological)
        # order; the end-state view uses `end_state_order` so it can read as a
        # reference (what -> how -> tradeoffs). Steps without an order trail in
        # authored order (they are typically journey-only and hidden there).
        step["_jy_order"] = idx + 1
        es_order = step.get("end_state_order")
        if isinstance(es_order, bool):
            es_order = None
        if isinstance(es_order, (int, float)):
            step["_es_order"] = int(es_order)
            any_es_order = True
        else:
            step["_es_order"] = 900 + idx
    overview["_reorder"] = bool(any_es_order)

    indices = build_overview_indices(steps)
    overview["_decision_index"] = indices["decisions"]
    overview["_gotcha_index"] = indices["gotchas"]
    overview["_decision_overflow"] = indices["decision_overflow"]
    overview["_gotcha_overflow"] = indices["gotcha_overflow"]
    overview["_decision_total"] = indices["decision_total"]
    overview["_gotcha_total"] = indices["gotcha_total"]

    for step in steps:
        if not isinstance(step, dict):
            continue
        evidence = step.get("evidence", {})
        if not evidence:
            step["_evidence_summary"] = "View Evidence"
            step["_file_refs"] = []
            continue
        hunks = evidence.get("diff_hunks", [])
        evidence["diff_hunks"] = [highlight_diff_hunk(h) for h in hunks if isinstance(h, dict)]
        step["_file_refs"] = filter_file_refs(evidence.get("files_changed", []), repo_root)
        evidence["files_changed"] = [ref["raw_path"] for ref in step["_file_refs"]]
        step["_evidence_summary"] = summarize_evidence(evidence)

    return data


def bridge_screenshots_to_media(data: dict) -> dict:
    """Bridge legacy evidence.screenshots[] into evidence.media[] stubs.

    Older summary outputs populate `evidence.screenshots` (not used by the
    template). Convert those entries into media items so `resolve_media()` can
    hydrate them from normalized screenshot events.
    """
    data = json.loads(json.dumps(data))  # deep copy

    for step in data.get("steps", []):
        evidence = step.get("evidence", {})
        if not isinstance(evidence, dict):
            continue

        screenshots = evidence.get("screenshots", [])
        if not isinstance(screenshots, list) or not screenshots:
            continue

        media_items = evidence.get("media", [])
        if not isinstance(media_items, list):
            media_items = []

        for idx, ss in enumerate(screenshots):
            if not isinstance(ss, dict):
                continue

            caption = ss.get("caption") or ss.get("context") or ""
            source_ref = ss.get("source_ref")
            if not source_ref and isinstance(ss.get("source_refs"), list) and ss["source_refs"]:
                first = ss["source_refs"][0]
                if isinstance(first, dict):
                    source_ref = first

            item = {
                "id": ss.get("id") or f"{step.get('id', 'step')}-ss-{idx + 1}",
                "type": "screenshot",
                "caption": caption,
            }
            if isinstance(source_ref, dict):
                item["source_ref"] = source_ref
            if ss.get("group"):
                item["group"] = ss.get("group")
            if ss.get("group_role"):
                item["group_role"] = ss.get("group_role")
            if ss.get("data_uri"):
                item["data_uri"] = ss.get("data_uri")
            if ss.get("thumbnail_uri"):
                item["thumbnail_uri"] = ss.get("thumbnail_uri")

            media_items.append(item)

        evidence["media"] = media_items

    return data


def resolve_media(
    data: dict,
    normalized_path: Path | None,
    media_base_dir: Path | None = None,
) -> dict:
    """Resolve media references from normalized JSONL and compress images."""
    import base64

    base_dir = media_base_dir or Path.cwd()

    # Load screenshot events from normalized JSONL (if available)
    screenshots = []
    if normalized_path and normalized_path.exists():
        with open(normalized_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if evt.get("kind") == "screenshot" and evt.get("media"):
                    screenshots.append(evt)

    # Index screenshots by source reference
    # Normalized events use (source_path, source_line); summaries use
    # (session_path, line_start).  Index by both to support either naming.
    by_source = {}
    for ss in screenshots:
        key1 = (ss.get("source_path", ""), ss.get("source_line", 0))
        by_source[key1] = ss
        # Also index by seq for fallback matching
        seq = ss.get("seq")
        if seq is not None:
            by_source[("__seq__", seq)] = ss

    # Try to import Pillow for compression
    try:
        from PIL import Image
        import io
        has_pillow = True
    except ImportError:
        has_pillow = False
        print("Warning: Pillow not installed. Screenshots will be embedded without compression.", file=sys.stderr)
        print("  Install with: pip install Pillow", file=sys.stderr)

    def compress_image(data_b64: str, mime_type: str = "image/png") -> tuple[str, int, int]:
        """Compress image to JPEG, cap at 1280px wide, return (data_uri, width, height)."""
        raw = base64.b64decode(data_b64)

        if not has_pillow:
            # Return as-is with data URI
            uri = f"data:{mime_type};base64,{data_b64}"
            return uri, 0, 0

        img = Image.open(io.BytesIO(raw))
        orig_w, orig_h = img.size

        # Cap width at 1280px
        if orig_w > 1280:
            ratio = 1280 / orig_w
            img = img.resize((1280, int(orig_h * ratio)), Image.LANCZOS)

        # Convert to RGB if necessary (for JPEG)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Compress to JPEG
        buf = io.BytesIO()
        quality = 80
        img.save(buf, format='JPEG', quality=quality, optimize=True)

        # If still over 200KB, reduce quality
        while buf.tell() > 200 * 1024 and quality > 30:
            quality -= 10
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=quality, optimize=True)

        w, h = img.size
        encoded = base64.b64encode(buf.getvalue()).decode('ascii')
        uri = f"data:image/jpeg;base64,{encoded}"
        return uri, w, h

    def make_thumbnail(data_b64: str, mime_type: str = "image/png") -> str:
        """Generate a 300px-wide thumbnail, return data URI."""
        if not has_pillow:
            return ""

        raw = base64.b64decode(data_b64)
        img = Image.open(io.BytesIO(raw))

        # Scale to 300px wide
        ratio = 300 / max(img.size[0], 1)
        img = img.resize((300, int(img.size[1] * ratio)), Image.LANCZOS)

        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=70, optimize=True)
        encoded = base64.b64encode(buf.getvalue()).decode('ascii')
        return f"data:image/jpeg;base64,{encoded}"

    # Resolve media items in walkthrough steps
    for step in data.get("steps", []):
        evidence = step.get("evidence", {})
        media_items = evidence.get("media", [])

        for item in media_items:
            # If already has data_uri, just generate thumbnail
            if item.get("data_uri"):
                if has_pillow and not item.get("thumbnail_uri"):
                    try:
                        # Extract base64 from data URI
                        _, b64 = item["data_uri"].split(",", 1)
                        item["thumbnail_uri"] = make_thumbnail(b64)
                    except Exception:
                        pass
                continue

            # Resolve local media path (used by Path B capture manifest injection)
            path_value = item.get("path") or item.get("file_path")
            if path_value:
                try:
                    path = Path(str(path_value))
                    if not path.is_absolute():
                        path = (base_dir / path).resolve()
                    if path.exists():
                        mime_type = mimetypes.guess_type(str(path))[0] or "image/png"
                        data_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
                        data_uri, w, h = compress_image(data_b64, mime_type)
                        item["data_uri"] = data_uri
                        if w:
                            item["width"] = w
                        if h:
                            item["height"] = h
                        item["thumbnail_uri"] = make_thumbnail(data_b64, mime_type)
                        continue
                except Exception as e:
                    print(f"Warning: Failed to resolve media path '{path_value}': {e}", file=sys.stderr)

            # Try to resolve from normalized data via source_ref
            src_ref = item.get("source_ref", {})
            if src_ref:
                # Try summary naming (session_path, line_start) first,
                # then normalized naming (source_path, source_line)
                key = (src_ref.get("session_path", ""), src_ref.get("line_start", 0))
                ss = by_source.get(key)
                if ss is None:
                    key = (src_ref.get("source_path", ""), src_ref.get("source_line", 0))
                    ss = by_source.get(key)
                if ss and ss.get("media", {}).get("data_b64"):
                    media = ss["media"]
                    try:
                        data_uri, w, h = compress_image(
                            media["data_b64"],
                            media.get("mime_type", "image/png"),
                        )
                        item["data_uri"] = data_uri
                        if w:
                            item["width"] = w
                        if h:
                            item["height"] = h
                        item["thumbnail_uri"] = make_thumbnail(
                            media["data_b64"],
                            media.get("mime_type", "image/png"),
                        )
                    except Exception as e:
                        print(f"Warning: Failed to process screenshot: {e}", file=sys.stderr)

    return data


def render(
    input_path: Path,
    output_path: Path,
    template_path: Path,
    normalized_path: Path | None = None,
    captures_manifest_path: Path | None = None,
) -> None:
    """Read walkthrough.json, render HTML, write output."""
    with open(input_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    raw_data = bridge_screenshots_to_media(raw_data)

    manifest_path = captures_manifest_path
    if manifest_path is None:
        auto_manifest = input_path.parent / "captures" / "manifest.json"
        if auto_manifest.exists():
            manifest_path = auto_manifest

    if manifest_path and manifest_path.exists() and attach_capture_media is not None:
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                capture_manifest = json.load(f)
            raw_data, injected = attach_capture_media(
                raw_data,
                capture_manifest,
                manifest_path=manifest_path.resolve(),
                replace_managed=False,
            )
            if injected:
                print(
                    f"Attached {injected} capture media item(s) from {manifest_path}",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"Warning: Failed to attach capture manifest media: {e}", file=sys.stderr)

    raw_data = resolve_media(raw_data, normalized_path, media_base_dir=input_path.parent)

    repo_root = ((raw_data.get("meta") or {}).get("repo_root") or "").rstrip("/")
    embed_overview_diagram_images(
        raw_data.setdefault("overview", {}), input_path.parent, repo_root
    )
    html_dir = output_path.parent.resolve()
    resolve_walkthrough_video(
        raw_data.setdefault("overview", {}), input_path.parent, repo_root, html_dir, "overview"
    )
    resolve_walkthrough_likec4(
        raw_data.setdefault("overview", {}), input_path.parent, repo_root, html_dir, "overview"
    )
    for _step in raw_data.get("steps", []) or []:
        if isinstance(_step, dict):
            embed_step_diagram_images(_step, input_path.parent, repo_root)
            resolve_walkthrough_video(
                _step, input_path.parent, repo_root, html_dir, f"step {_step.get('id', '?')}"
            )
            resolve_walkthrough_likec4(
                _step, input_path.parent, repo_root, html_dir, f"step {_step.get('id', '?')}"
            )

    # Every distinct webcomponent bundle referenced by an interactive LikeC4
    # embed becomes exactly one script in the rendered page: inlined by default
    # (the artifact stays one self-contained file), or a sidecar <script src>
    # when the spec says {"embed": false}. The inline payload is embedded as a
    # JSON string with every "<" escaped to \\u003c and revived via eval — the
    # bundle contains sequences ("<!--", "<script") that would otherwise put
    # the HTML parser into a state where our closing script tag breaks.
    likec4_scripts: list[dict] = []
    _likec4_seen: list[str] = []
    for _node in [raw_data.get("overview") or {}, *(raw_data.get("steps") or [])]:
        if not isinstance(_node, dict):
            continue
        _lc4 = _node.get("_likec4")
        if not isinstance(_lc4, dict):
            continue
        _src_abs = _lc4.pop("_src_abs", None)
        _embed = _lc4.pop("embed", True)
        if _lc4.get("src") in _likec4_seen:
            continue
        _likec4_seen.append(_lc4["src"])
        if _embed and _src_abs:
            _code = Path(_src_abs).read_text(encoding="utf-8")
            _payload = json.dumps(_code).replace("<", "\\u003c")
            likec4_scripts.append({"inline": True, "code": Markup(f"(0,eval)({_payload})")})
        else:
            likec4_scripts.append({"inline": False, "src": _lc4["src"]})

    data = prepare_data(raw_data)
    pygments_css = Markup(get_pygments_css())

    # Serialize data for embedding as <script>const DATA = ...;</script>.
    # Strip the heavy server-rendered diagram payloads — the client JS never reads
    # them (the diagram is rendered once in the Jinja template), so keeping them in
    # DATA would double the embedded image/SVG bytes.
    script_data = json.loads(json.dumps(data))
    _ov = script_data.get("overview")
    if isinstance(_ov, dict):
        for _k in ("_diagram_image_light", "_diagram_image_dark", "_diagram_svg", "_video", "_likec4"):
            _ov.pop(_k, None)
    # Per-step diagram/video payloads are rendered once in the Jinja template; the
    # client JS never reads them, so drop them from DATA to avoid doubling the bytes.
    for _st in script_data.get("steps", []) or []:
        if isinstance(_st, dict):
            for _k in ("_diagram_image", "_diagram_image_light", "_diagram_image_dark", "_video", "_likec4"):
                _st.pop(_k, None)
    data_json = serialize_script_data(script_data)

    # Set up Jinja2
    template_dir = template_path.parent
    template_name = template_path.name
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(enabled_extensions=("html", "htm"), default=True),
    )
    template = env.get_template(template_name)

    ui = resolve_ui_flags(data.get("meta"))

    html = template.render(
        data=data,
        data_json=data_json,
        pygments_css=pygments_css,
        likec4_scripts=likec4_scripts,
        ui=ui,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Rendered {output_path} ({len(html):,} bytes)", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render walkthrough.json into a single-file HTML walkthrough."
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to walkthrough.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path for output HTML file",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=DEFAULT_TEMPLATE,
        help=f"Path to Jinja2 template (default: {DEFAULT_TEMPLATE})",
    )
    parser.add_argument(
        "--normalized",
        type=Path,
        default=None,
        help="Path to normalized.jsonl for resolving screenshot media",
    )
    parser.add_argument(
        "--captures-manifest",
        type=Path,
        default=None,
        help=(
            "Optional path to captures/manifest.json to attach Path B screenshots. "
            "If omitted, auto-discovers sibling captures/manifest.json next to --input."
        ),
    )
    parser.add_argument(
        "--allow-draft",
        action="store_true",
        help="Render even if the editorial quality gate fails (draft output)",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    if not args.template.exists():
        print(f"Error: template not found: {args.template}", file=sys.stderr)
        sys.exit(1)

    # The quality gate binds at render time: a failing walkthrough is a draft,
    # and drafts only render with an explicit --allow-draft.
    if validate_walkthrough is not None and not args.allow_draft:
        gate_data = json.loads(args.input.read_text(encoding="utf-8"))
        gate_report = validate_walkthrough(
            gate_data, base_dir=str(args.input.resolve().parent)
        )
        if not gate_report.ok:
            for error in gate_report.errors:
                print(f"QUALITY GATE ERROR: {error}", file=sys.stderr)
            print(
                "Error: quality gate failed — re-edit the walkthrough or pass --allow-draft to render a draft.",
                file=sys.stderr,
            )
            sys.exit(1)

    render(
        args.input,
        args.output,
        args.template,
        normalized_path=args.normalized,
        captures_manifest_path=args.captures_manifest,
    )


if __name__ == "__main__":
    main()
