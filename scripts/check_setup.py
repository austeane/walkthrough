#!/usr/bin/env python3
"""First-run setup check for the walkthrough skill.

Stdlib-only and safe on any Python >= 3.6, so it can always run and report —
even on the stock macOS interpreter. Prints what is available, what each gap
blocks, and the exact remedy. Exit 0 means a text-first walkthrough can be
produced end-to-end on this machine; exit 1 means something core is blocked.
"""

from __future__ import annotations

import glob
import os
import shutil
import sys

OK = "[ok]"
OPT = "[--]"
BAD = "[!!]"


def have_module(name):
    try:
        __import__(name)
        return True
    except Exception:
        return False


def main():
    lines = []
    blocked = []

    # --- Core: Python version ---
    v = sys.version_info
    pyver = "%d.%d.%d" % (v.major, v.minor, v.micro)
    if (v.major, v.minor) >= (3, 9):
        lines.append((OK, "python %s" % pyver, "pipeline scripts run on 3.9+"))
    else:
        lines.append((BAD, "python %s" % pyver,
                      "pipeline needs 3.9+ — install a newer python3 or use `uv run`"))
        blocked.append("python")

    # --- Core: render dependencies ---
    deps_here = have_module("jinja2") and have_module("pygments")
    uv = shutil.which("uv")
    if deps_here:
        lines.append((OK, "jinja2 + pygments", "render step ready with this interpreter"))
    elif uv:
        lines.append((OK, "uv", "render via `uv run scripts/render_html.py ...` "
                               "(inline metadata installs jinja2/pygments automatically)"))
    else:
        lines.append((BAD, "jinja2 + pygments", "render step blocked — run "
                      "`python3 -m pip install --user jinja2 pygments` (or install uv)"))
        blocked.append("render deps")
    if deps_here and uv:
        lines.append((OK, "uv", "also available for isolated runs"))

    # --- Optional libraries ---
    lines.append((OK if have_module("PIL") else OPT, "Pillow",
                  "optional — compresses embedded screenshots; without it images embed full-size"))
    lines.append((OK if have_module("playwright") else OPT, "playwright",
                  "optional — only for Path B git-history screenshot capture"))

    # --- Optional tools ---
    for tool, why in [
        ("likec4", "optional — architecture diagrams (npm install -g likec4); text-first works without it"),
        ("npx", "optional — needed to install/run likec4 and HyperFrames skills"),
        ("ffmpeg", "optional — video QA frame extraction (step 7d)"),
        ("opencode", "optional — only for OpenCode session discovery"),
    ]:
        lines.append((OK if shutil.which(tool) else OPT, tool, why))

    # --- Session sources ---
    home = os.path.expanduser("~")
    claude_root = os.path.join(home, ".claude", "projects")
    codex_root = os.path.join(home, ".codex", "sessions")
    n_claude = len(glob.glob(os.path.join(claude_root, "*", "*.jsonl")))
    n_codex = len(glob.glob(os.path.join(codex_root, "*", "*", "*", "rollout-*.jsonl")))
    lines.append((OK if n_claude else OPT, "claude sessions",
                  "%d files under %s" % (n_claude, claude_root)))
    lines.append((OK if n_codex else OPT, "codex sessions",
                  "%d files under %s" % (n_codex, codex_root)))
    if not n_claude and not n_codex and not shutil.which("opencode"):
        lines.append((BAD, "session sources", "no Claude/Codex sessions and no opencode binary — "
                      "nothing to walk through on this machine"))
        blocked.append("sessions")

    width = max(len(name) for _, name, _ in lines)
    for mark, name, detail in lines:
        print("%s %-*s  %s" % (mark, width, name, detail))

    print()
    if blocked:
        if blocked == ["render deps"]:
            print("PARTIAL: the pipeline (discovery through quality gate) can run now; "
                  "fix the [!!] line before the render step.")
        else:
            print("BLOCKED: %s. Fix the [!!] lines above before running the pipeline."
                  % ", ".join(blocked))
        return 1
    print("READY: text-first walkthrough can run end-to-end. "
          "[--] items are optional enhancements — never install them unprompted; "
          "offer them as follow-ups.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
