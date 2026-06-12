"""First-run / cold-start guards.

The pipeline's runtime floor is Python 3.9 (the stock macOS python3): a new
user's first command must not die on syntax or import. These tests pin the
properties that keep that true, since the dev environment runs 3.11+ and
would never notice a regression.
"""

import ast
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
SCRIPT_FILES = sorted(
    p for p in SCRIPTS_DIR.glob("*.py") if p.name != "__init__.py"
)


def test_every_script_defers_annotations():
    """PEP 604 unions (`str | None`) in annotations crash Python 3.9 at import
    time unless annotations are deferred. Every script must carry the future
    import so new annotation syntax never breaks the stock interpreter."""
    missing = [
        p.name
        for p in SCRIPT_FILES
        if "from __future__ import annotations" not in p.read_text()
    ]
    assert not missing, f"scripts missing `from __future__ import annotations`: {missing}"


def test_no_python_310_only_syntax():
    """match statements are a hard SyntaxError on 3.9 — deferred annotations
    can't save them. Catch them structurally."""
    offenders = []
    for p in SCRIPT_FILES:
        tree = ast.parse(p.read_text())
        if any(isinstance(node, ast.Match) for node in ast.walk(tree)):
            offenders.append(p.name)
    assert not offenders, f"scripts using `match` (needs 3.10+): {offenders}"


def test_render_html_carries_inline_dependency_metadata():
    """`uv run scripts/render_html.py` must work from any working directory,
    which requires the PEP 723 block naming the render dependencies."""
    src = (SCRIPTS_DIR / "render_html.py").read_text()
    block = re.search(r"# /// script\n(.*?)# ///", src, re.DOTALL)
    assert block, "render_html.py is missing its PEP 723 inline metadata block"
    assert "jinja2" in block.group(1) and "pygments" in block.group(1)


def test_check_setup_runs_clean():
    """The doctor must always run and report (stdlib-only, no traceback)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "check_setup.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode in (0, 1), result.stderr
    assert "Traceback" not in result.stderr
    assert any(word in result.stdout for word in ("READY", "PARTIAL", "BLOCKED"))


def test_only_render_imports_third_party():
    """Steps 1-7 are promised stdlib-only in SKILL.md. A new top-level
    third-party import in any other script breaks the no-install first run.
    (Lazy imports inside functions, like playwright in capture_screenshots,
    stay allowed — they degrade gracefully at call time.)"""
    allowed_third_party = {"render_html.py"}
    stdlib = sys.stdlib_module_names
    offenders = []
    for p in SCRIPT_FILES:
        if p.name in allowed_third_party:
            continue
        tree = ast.parse(p.read_text())
        for node in tree.body:  # top level only
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            for name in names:
                if name and name not in stdlib and name != "scripts":
                    offenders.append(f"{p.name}: {name}")
    assert not offenders, f"non-stdlib top-level imports outside render: {offenders}"
