# Walkthrough

Generate evidence-backed walkthroughs from agent session histories. Reads Codex CLI and Claude Code JSONL transcripts, processes them with recursive summarization, and produces `walkthrough.json` + `walkthrough.html`.

Use when you want to understand what an agent built, review agent work, walk through recent changes, onboard onto agent-written code, or generate a narrative explanation of a feature/PR built by an AI agent.

## Prereq

- `uv`

## Install

```bash
git clone <repo-url> ~/src/walkthrough
cd ~/src/walkthrough
uv sync
```

Optional extras:
- `uv sync --extra media` — Pillow for image compression
- `uv sync --extra capture` — Playwright for git-history screenshot capture

### Link as an agent skill

```bash
# Claude Code
mkdir -p ~/.claude/skills
ln -sfn "$(pwd)" ~/.claude/skills/walkthrough

# Codex
mkdir -p ~/.codex/skills
ln -sfn "$(pwd)" ~/.codex/skills/walkthrough
```

If you only use one agent, only create that symlink.

## Usage

Invoke the skill from Claude Code or Codex:

```
/walkthrough
```

The skill guides you through a scoping dialog, discovers relevant sessions, normalizes and chunks the data, summarizes chunks via subagents, and assembles an editorially compressed walkthrough with HTML output.

See [SKILL.md](SKILL.md) for the full workflow specification.

## Scripts

All scripts can be run directly (`python3 scripts/<name>.py`) or via entry points (`uv run walkthrough-<command>`).

| Script | Entry Point | Purpose |
|--------|------------|---------|
| `discover_sessions.py` | `walkthrough-discover` | Find agent sessions by provider/date/project |
| `strip_binary.py` | `walkthrough-strip` | Remove base64/binary content from JSONL |
| `normalize_codex.py` | `walkthrough-normalize-codex` | Codex JSONL → normalized events |
| `normalize_claude.py` | `walkthrough-normalize-claude` | Claude JSONL → normalized events |
| `project_events.py` | `walkthrough-project` | Drop noise, compress tool results |
| `extract_session_cards.py` | `walkthrough-cards` | Per-session deterministic summary card |
| `chunk_events.py` | `walkthrough-chunk` | Split events into LLM-sized chunks |
| `batch_pipeline.py` | `walkthrough-batch` | Batch process multiple sessions |
| `merge_summaries.py` | `walkthrough-merge` | Draft walkthrough from chunk summaries |
| `capture_screenshots.py` | `walkthrough-capture` | Capture UI screenshots from git history |
| `inject_capture_media.py` | `walkthrough-inject-media` | Attach captures to walkthrough steps |
| `render_html.py` | `walkthrough-render` | Render walkthrough JSON to HTML |
| `validate_pipeline.py` | `walkthrough-validate` | Validate pipeline contracts |

## Tests

```bash
uv run pytest
```

## Architecture

Deterministic Python scripts handle parsing, normalization, chunking, and rendering. LLM subagents handle judgment work — what matters, why it matters, how to teach it. The skill instructions in SKILL.md encode the recursive summarization workflow.

See [PLAN.md](PLAN.md) for the full implementation plan and architecture.

## Reference Docs

- `references/codex-session-format.md` — Codex JSONL event types
- `references/claude-session-format.md` — Claude Code JSONL record types
- `references/normalized-event-model.md` — Common event schema
- `references/walkthrough-schema.md` — Output JSON schema + evidence rules
