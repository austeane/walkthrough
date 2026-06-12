# Walkthrough

Generate evidence-backed walkthroughs from agent session histories.

## Prereq

- Python 3.9+ (the stock macOS `python3` works — the pipeline is stdlib-only)
- `uv` recommended (only the final render step has dependencies; `uv run scripts/render_html.py` resolves them automatically, or `pip install jinja2 pygments`)

## Install

Easiest:

```text
Clone this repo, read SKILL.md, and install the walkthrough skill.
```

Manual:

```bash
git clone <repo-url> ~/src/walkthrough
cd ~/src/walkthrough
mkdir -p ~/.codex/skills ~/.claude/skills
ln -sfn "$(pwd)" ~/.codex/skills/walkthrough
ln -sfn "$(pwd)" ~/.claude/skills/walkthrough
```

If you only use one agent, only create that symlink. `uv sync` is optional (dev/test environment); first-time users can verify their machine with:

```bash
python3 scripts/check_setup.py
```
