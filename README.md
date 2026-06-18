# Walkthrough

Generate evidence-backed walkthroughs from agent session histories.

This is an agent **skill**: it reads Codex CLI, Claude Code, and OpenCode session
histories, summarizes them, and produces a `walkthrough.json` + a self-contained
`walkthrough.html` that narrates what an agent actually built — with optional
LikeC4 diagrams and HyperFrames video.

## Prereq

- **Python 3.9+** — the stock macOS `python3` works. The pipeline (discovery → normalize → chunk → merge → quality gate) is stdlib-only, with no venv or install step.
- **`uv` recommended** — only the final render step has dependencies. `uv run scripts/render_html.py …` resolves them automatically via the script's inline PEP 723 metadata. (Or `python3 -m pip install --user jinja2 pygments`.)
- **Optional tooling** (never required for a first walkthrough): [LikeC4](https://likec4.dev) for diagrams, the [HyperFrames](https://www.npmjs.com/package/hyperframes) skills for video. The doctor below reports what's missing.

## Install

Clone the repo, then symlink it into your agent's skills directory so the agent
can discover `SKILL.md`.

```bash
# 1. Clone (HTTPS — or use git@github.com:austeane/walkthrough.git for SSH)
git clone https://github.com/austeane/walkthrough.git ~/src/walkthrough
cd ~/src/walkthrough

# 2. Install the skill for whichever agent(s) you use.
#    Only create the symlink for the agent you actually run.
mkdir -p ~/.claude/skills ~/.codex/skills
ln -sfn "$(pwd)" ~/.claude/skills/walkthrough   # Claude Code
ln -sfn "$(pwd)" ~/.codex/skills/walkthrough     # Codex CLI

# 3. Verify your machine (no install required — stdlib only)
python3 scripts/check_setup.py
```

The clone path (`~/src/walkthrough`) is arbitrary; the symlink is what matters.
`check_setup.py` reports your Python version and which optional tools are
present (uv, LikeC4, ffmpeg, Pillow, …) plus how many local agent sessions it
found — missing optional tools are fine and never block a first walkthrough.

`uv sync` is optional and only needed for the dev/test environment (running the
test suite).

## Usage

In your agent, invoke the skill — e.g. `/walkthrough` in Claude Code, or just
ask it to "walk me through what the agent built." For a present-tense system
description aimed at a technical PM (no chronology), ask for an **end-state**
walkthrough. See [`SKILL.md`](SKILL.md) for the full workflow.
