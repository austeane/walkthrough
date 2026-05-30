# Walkthrough

Generate evidence-backed walkthroughs from agent session histories.

## Prereq

- `uv`

## Install

Easiest:

```text
Clone this repo, read SKILL.md, and install the walkthrough skill.
```

Manual:

```bash
git clone <repo-url> ~/src/walkthrough
cd ~/src/walkthrough
uv sync
mkdir -p ~/.codex/skills ~/.claude/skills
ln -sfn "$(pwd)" ~/.codex/skills/walkthrough
ln -sfn "$(pwd)" ~/.claude/skills/walkthrough
```

If you only use one agent, only create that symlink.
