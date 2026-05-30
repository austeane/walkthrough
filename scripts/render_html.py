#!/usr/bin/env python3
"""Render walkthrough.json into a single-file walkthrough.html.

Reads a walkthrough JSON file, generates Pygments CSS for syntax-highlighted
diff hunks, renders the Jinja2 template, embeds the JSON data for client-side
interactivity, and writes a self-contained HTML file.
"""

from __future__ import annotations

import argparse
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

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = SCRIPT_DIR.parent / "assets" / "walkthrough-template.html"
DISPLAYABLE_ROOT_DIRS = {"src", "e2e", "scripts", "docs", "db"}


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

    overview = data.get("overview") or {}
    overview["key_file_refs"] = filter_file_refs(overview.get("key_files", []), repo_root, overview=True)
    overview["key_files"] = [ref["raw_path"] for ref in overview["key_file_refs"]]
    overview["_diagram_svg"] = render_mermaid_svg(str(overview.get("diagram_mermaid") or ""))

    for step in data.get("steps", []):
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

    data = prepare_data(raw_data)
    pygments_css = Markup(get_pygments_css())

    # Serialize data for embedding as <script>const DATA = ...;</script>
    data_json = serialize_script_data(data)

    # Set up Jinja2
    template_dir = template_path.parent
    template_name = template_path.name
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(enabled_extensions=("html", "htm"), default=True),
    )
    template = env.get_template(template_name)

    html = template.render(
        data=data,
        data_json=data_json,
        pygments_css=pygments_css,
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
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    if not args.template.exists():
        print(f"Error: template not found: {args.template}", file=sys.stderr)
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
