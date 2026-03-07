# Walkthrough Skill — Implementation Plan

## Context

AI agents build code fast but leave no cognitive trail. Developers lose familiarity with their own codebase as they ship agent-driven features. **Walkthrough** is an Agent Skill that reads existing Codex CLI and Claude Code session histories (JSONL files on disk), recursively summarizes them using native subagents, and produces an evidence-backed `walkthrough.json` + `walkthrough.html` artifact that teaches the developer what was built, why, and how.

**Architecture**: deterministic Python scripts for session discovery, normalization, chunking, and HTML rendering. Native subagent spawning (Haiku for chunk summarization, orchestrator model for narrative assembly). No RLM library dependency — the recursive pattern is encoded in the skill instructions. **Scripts handle deterministic work (parsing, chunking, rendering). Agents handle judgment work (what matters, why it matters, how to teach it).** Trust the agents — the models doing this work are highly capable; don't over-constrain them with rigid templates when they can make better editorial decisions with latitude.

**Prime directive**: The walkthrough exists to help the developer understand their own codebase — the what and the why. It is NOT a 1:1 transcript replay. If an agent did 100 distinct things across 5 sessions, the walkthrough might be 8-12 steps, not 100 slides. The agent must compress, group, and editorialize. The right question is "what do I need to understand?" not "what happened chronologically?"

**Development**: `/Users/austin/dev/walkthrough/`, symlinked into `~/.claude/skills/walkthrough` and `~/.codex/skills/walkthrough`. Uses `uv` for Python dependency management. Post-hoc only (reads existing histories, no WORKLOG.md recording in v1).

**HTML presentation**: Adapted from the `frontend-slides` skill (`~/.claude/skills/frontend-slides/SKILL.md`), which already solves single-file HTML generation, viewport-fitting, slide navigation, animation, and responsive design. We build the walkthrough viewer on top of those patterns rather than from scratch.

---

## Skill Directory Structure

```
walkthrough/
├── SKILL.md                           # Agent Skills spec frontmatter + workflow instructions
├── pyproject.toml                     # uv/Python project config
├── agents/
│   └── openai.yaml                    # Codex UI metadata (allow_implicit_invocation: false)
├── scripts/
│   ├── discover_sessions.py           # Find sessions by provider/date/project
│   ├── normalize_codex.py             # Codex JSONL → normalized events
│   ├── normalize_claude.py            # Claude Code JSONL → normalized events
│   ├── chunk_events.py                # Split normalized events into LLM-sized chunks
│   ├── strip_binary.py                # Remove base64/binary content from JSONL
│   └── render_html.py                 # walkthrough.json → walkthrough.html
├── references/
│   ├── codex-session-format.md        # Codex JSONL event type docs
│   ├── claude-session-format.md       # Claude Code JSONL record type docs
│   ├── normalized-event-model.md      # Common event schema spec
│   └── walkthrough-schema.md          # Output JSON schema spec + evidence rules
└── assets/
    └── walkthrough-template.html      # Single-file HTML viewer template
```

---

## Implementation Steps

### Step 1: Project scaffolding

Create the directory structure, `pyproject.toml` (with uv), and symlinks.

```
pyproject.toml:
  - name: walkthrough
  - python >= 3.11
  - dependencies: pygments (syntax highlighting), jinja2 (HTML templating)
  - [project.scripts] walkthrough = "scripts.cli:main" (optional CLI entry)
```

Symlinks:
- `~/.claude/skills/walkthrough → /Users/austin/dev/walkthrough`
- `~/.codex/skills/walkthrough → /Users/austin/dev/walkthrough`
- `~/.agents/skills/walkthrough → /Users/austin/dev/walkthrough` (Codex also reads from `$HOME/.agents/skills/`)

### Step 2: `scripts/discover_sessions.py`

**Inputs** (CLI args): `--codex-root`, `--claude-root`, `--since`, `--until`, `--project`, `--cwd`
**Output** (stdout JSON): list of `{provider, path, timestamp, size_bytes, line_count, cwd, model, subagent_paths[]}`

Logic:
- Codex: glob `{root}/**/rollout-*.jsonl`, read line 1 (`session_meta`) for cwd/model/git
- Claude: glob `{root}/*/*.jsonl` (skip `subagents/` dirs), read first `user` record for cwd/sessionId, then check `{sessionId}/subagents/` for linked subagent files
- Filter by date (mtime or parsed timestamp), cwd substring, project name
- Skip files < 1KB

### Step 3: `scripts/strip_binary.py`

**Input**: `--input <file.jsonl>` `--output <cleaned.jsonl>` `--max-field-bytes 100000`
**Purpose**: Prevent context window blowouts. The agent reading chunks is smart enough to decide what's important — this script just removes content that would waste tokens without adding signal.

- **Base64 detection**: strings > 1000 chars matching `^[A-Za-z0-9+/=\n]+$` → replace with `[BASE64: N bytes, source_path:line_no]`
- **Field size cap**: any string field > `--max-field-bytes` (default 100KB) gets truncated with `[TRUNCATED at N bytes, source_path:line_no]`. Generous limit — diffs and command outputs are valuable and the agent can handle them.
- **Every replacement records a pointer** back to `(source_path, line_number)` so the agent can fetch full content from raw logs if it decides it needs it.

### Step 4: `scripts/normalize_codex.py`

**Input**: `--input <rollout.jsonl>` `--output <normalized.jsonl>`
**Output**: normalized event model (one JSON object per line)

Mapping:
| Codex type | Normalized kind |
|---|---|
| `session_meta` | `meta` |
| `response_item` role=user | `user_message` |
| `response_item` role=assistant | `assistant_message` |
| `response_item/function_call` | `tool_use` |
| `response_item/function_call_output` | `tool_result` |
| `response_item/fileChange` | `file_change` (extract `path`, `kind`, `diff`) |
| `response_item/commandExecution` | `command` (extract `command`, `exitCode`, `status`, truncated `output`) |
| `response_item/reasoning` | `reasoning` (extract `summary` only, skip encrypted) |
| `turn/diff/updated` | `aggregate_diff` (session-level cumulative diff — high value for overview) |
| `turn/plan/updated` | `plan_update` (agent's plan changes) |
| `compacted` | `compaction` (marks where cognitive trail was summarized — note in walkthrough) |
| `turn_context` | `turn_context` |
| `event_msg/token_count` | skip |
| `event_msg/user_message` | `user_message` |
| `event_msg/agent_message` | `assistant_message` |

### Step 5: `scripts/normalize_claude.py`

**Input**: `--input <session.jsonl>` `--subagents <path1,path2,...>` `--output <normalized.jsonl>`

Mapping:
| Claude type | Normalized kind |
|---|---|
| `user` with text content | `user_message` |
| `assistant` with `tool_use` content | `tool_use` |
| `user` with `tool_result` content | `tool_result` |
| `assistant` with `text` content | `assistant_message` |
| `file-history-snapshot` | `file_snapshot` |
| `queue-operation` | skip |
| `progress` | skip |
| `system` | `system` |

Subagent handling: treat subagent transcripts as **child streams attached to the parent invocation**, not flat timestamp interleaving. For each subagent file:
- Prefer explicit progress metadata (`agentId` + `parentToolUseID`) when present
- Otherwise fall back to deterministic single-match or timestamp-based matching, and mark ambiguous cases explicitly
- Link with `parent_call_id` and `root_turn_index` (which turn in the main session spawned it)
- Subagent events get the spawning agent's `agent_id` field set
- Note: subagent transcripts may be missing the user prompts that initiated them (known bug). Fall back to the parent invocation's context when this happens.

Diff reconstruction from tool calls: Claude Code doesn't emit explicit `fileChange` events like Codex. Reconstruct them:
- `Edit` tool calls have `old_string` and `new_string` in `tool.input` — emit a `file_change` event with `kind: "modify"` and a synthetic diff
- `Write` tool calls have the full file content in `tool.input` — emit a `file_change` event with `kind: "create"` or `"overwrite"` and the file path
- This brings Claude Code walkthrough quality close to Codex's without needing git access

### Step 6: Normalized event model

Common schema (documented in `references/normalized-event-model.md`):

```json
{
  "seq": 1,
  "source_line": 42,
  "source_path": "/path/to/session.jsonl",
  "provider": "codex|claude",
  "session_id": "uuid",
  "ts": "ISO8601",
  "kind": "meta|user_message|assistant_message|tool_use|tool_result|file_change|command|reasoning|turn_context|aggregate_diff|plan_update|compaction|file_snapshot|system",
  "turn_index": 3,
  "agent_id": null,
  "parent_call_id": null,
  "root_turn_index": null,
  "text": "...",
  "tool": { "name": "...", "call_id": "...", "input": {}, "output": "...", "is_error": false },
  "file_change": { "path": "...", "kind": "create|modify|delete", "diff": "..." },
  "command": { "cmd": "...", "exit_code": 0, "status": "pass|fail", "output_preview": "...", "output_lines": 42 },
  "meta": { "cwd": "...", "model": "...", "git": {} }
}
```

### Step 7: `scripts/chunk_events.py`

**Input**: `--input <normalized.jsonl>` `--output-dir <dir>` `--target-bytes 300000`
**Output**: `chunk-001.jsonl`, `chunk-002.jsonl`, ... + `manifest.json`

Chunking rules:
- Chunk by **approximate bytes** (target ~300KB per chunk), not line count — one Claude Code line can be 10MB, making line count an unreliable proxy
- Never split tool_use/tool_result pairs
- Never split a file_change or command record from its surrounding context
- Prefer splitting at turn boundaries (after a `user_message`)
- If a single record exceeds the target size, it gets its own chunk (already truncated by strip_binary)
- Manifest includes: chunk_id, path, line_start, line_end, byte_size, time_range, sha256 hash

The manifest is the **source of truth** for the recursive summarization pipeline. The assembler refuses to proceed if any chunk is missing a summary.

### Step 8: Walkthrough JSON schema

Documented in `references/walkthrough-schema.md`. Key structure:

```json
{
  "version": "0.1.0",
  "meta": { "generated_at", "sessions[]", "repo", "scope" },
  "overview": { "goal", "summary[]", "key_files[]", "diagram_mermaid" },
  "steps": [{
    "id": "step-1",
    "title": "...",
    "intent": "...",
    "claims": [{
      "text": "The old system used express-session with Redis store",
      "confidence": "grounded",
      "source_refs": [{ "session_path", "line_start", "line_end" }]
    }, {
      "text": "JWT was chosen for simpler deployment requirements",
      "confidence": "inferred",
      "source_refs": [{ "session_path", "line_start", "line_end" }]
    }],
    "evidence": {
      "files_changed": [],
      "diff_hunks": [{ "file", "before", "after" }],
      "commands": [{ "cmd", "status", "summary" }]
    },
    "decisions": [{ "decision", "rationale", "alternatives_considered" }],
    "errors_encountered": [{ "error", "resolution", "evidence_ref" }]
  }]
}
```

Evidence rules:
- Each step contains `claims[]` — the agent's narrative broken into individual statements, each with its own `confidence` level and `source_refs[]` pointing to specific log line ranges
- `evidence.*` fields (`files_changed`, `diff_hunks`, `commands`) are always grounded by construction — they come from the deterministic scripts, not from LLM inference
- Confidence is per-claim: `grounded` (directly evidenced in logs), `inferred` (reasonable conclusion from context), `speculative` (editorial/predictive, no direct evidence)
- The HTML viewer renders grounded claims normally, inferred claims with a subtle indicator, and speculative claims with a visible "inferred" badge
- The agent producing the walkthrough is capable of making these distinctions reliably — this is a reasoning task, not a mechanical one

### Step 9: SKILL.md

Frontmatter:
```yaml
---
name: walkthrough
description: >-
  Generate evidence-backed walkthroughs from agent session histories.
  Reads Codex CLI and Claude Code JSONL transcripts, processes them using
  recursive decomposition, and produces walkthrough.json + walkthrough.html.
  Use when the user wants to understand what an agent built or review agent work.
---
```

Body encodes the recursive workflow:

1. **Scoping dialog** — ask user what to walk through (PR, feature, time range, sessions) and audience (self, teammate, reviewer)
2. **Discovery** — run `scripts/discover_sessions.py`, present candidates, user confirms
3. **Normalization** — run `strip_binary.py` then appropriate normalizer per provider
4. **Chunking** — run `chunk_events.py` on normalized output
5. **Chunk summarization** — spawn Haiku subagents per chunk. Each subagent should identify the **narrative arc** of its chunk: what was the agent trying to do, what went wrong, what did it learn, what did it build. Not just mechanical field extraction — Haiku is capable of understanding intent and causality within a chunk. Returns structured summary with claims (each tagged with confidence + source refs), key file changes, decisions, and errors. **Cache by chunk hash**: write summaries to `out/summaries/chunk-001.<sha256>.json`. If hash unchanged on re-run, reuse cached summary (skip LLM call).
6. **Session synthesis** — for multi-chunk sessions, spawn Sonnet subagent to unify chunk summaries. The manifest drives this: assembler checks all chunks have summaries before proceeding.
7. **Walkthrough assembly** — the orchestrator (Opus/GPT-5) has full editorial freedom here. It receives all session summaries and decides: how many steps, what grouping, what order, what to emphasize, what to compress. The prime directive is teaching — help the developer understand their codebase. 100 agent actions might become 8 deep steps or 20 shallow ones depending on complexity. The orchestrator may group by concept, by chronological phase, by subsystem, or however best serves understanding. Trust the model's editorial judgment — it has the full context and is better at this than a rigid template. Writes `walkthrough.json`.
8. **Rendering** — run `render_html.py` to produce `walkthrough.html`

Provider-specific notes: point to reference docs. Claude Code uses Agent tool with `model: "haiku"` for chunk subagents. Codex processes chunks sequentially.

### Step 10: `assets/walkthrough-template.html` + `scripts/render_html.py`

**Adapt the `frontend-slides` skill** (`~/.claude/skills/frontend-slides/SKILL.md`) as the foundation for the HTML viewer. The frontend-slides skill already solves single-file HTML generation, animation, keyboard navigation, and responsive design. We adapt its patterns rather than building from scratch:

- Default to a dossier-style scrolling document, with an optional presentation-mode toggle for slide-like navigation
- Keep keyboard/swipe navigation, but scope it to visible steps when search filters the document
- Use its typography and responsive `clamp()` scaling
- Use its single-file zero-dependency approach (inline CSS/JS)
- Adapt its style presets (from `STYLE_PRESETS.md`) for a "code walkthrough" aesthetic

**Walkthrough-specific additions on top of frontend-slides patterns**:
- Sidebar table of contents (persistent, highlights current step)
- Syntax-highlighted diff hunks (Pygments generates CSS classes, inline in template) — show **selected hunks** only, not full diffs
- **Evidence as modal overlay** with focus management: click "Evidence" on a step → full-screen overlay with its own scroll context, showing source lines, selected diffs, commands, and screenshots.
- Dark/light mode toggle
- Editor links: `vscode://file/{path}:{line}` and `cursor://file/{path}:{line}`
- GitHub blob links when repo info available
- Search across steps

**`render_html.py`**: reads `walkthrough.json`, normalizes provenance links, regenerates trusted diff HTML from structured diff data, embeds JSON safely as `<script>const DATA = {...}</script>`, and writes a self-contained HTML artifact with no external runtime dependencies.

### Step 11: `agents/openai.yaml`

```yaml
interface:
  display_name: "Walkthrough"
  short_description: "Generate walkthroughs from agent sessions"
  default_prompt: "Use $walkthrough to walk me through the agent work on this project"
policy:
  allow_implicit_invocation: false
```

### Step 12: Reference docs

Write the four reference files documenting:
- Codex JSONL event types (from real schema analysis)
- Claude Code JSONL record types (from real schema analysis)
- Normalized event model specification
- Walkthrough JSON schema + evidence rules

---

## Build Order

**Phase 1 — Pipeline scripts** (Steps 1-7)
1. Project scaffolding + pyproject.toml + symlinks
2. `discover_sessions.py` — test against real `~/.codex/sessions/` and `~/.claude/projects/`
3. `strip_binary.py`
4. `normalize_codex.py` — test against a real medium-sized rollout
5. `normalize_claude.py` — test against a real session + subagents
6. `chunk_events.py`
7. Normalized event model reference doc

**Phase 2 — Skill core** (Steps 8-9)
8. Walkthrough JSON schema reference doc
9. SKILL.md with full recursive workflow instructions

**Phase 3 — Presentation** (Step 10)
10. HTML template + render script

**Phase 4 — Polish** (Steps 11-12)
11. openai.yaml
12. Provider-specific reference docs

---

## Verification

1. **Script unit tests**: Run each script against real session files from this machine:
   - `discover_sessions.py --since 7d` should find sessions in both providers
   - `normalize_codex.py` on `~/.codex/sessions/2026/02/28/rollout-*.jsonl` should produce valid normalized output
   - `normalize_claude.py` on a solstice project session should handle subagents
   - `strip_binary.py` on a Claude Code session with base64 content should reduce file size dramatically

2. **End-to-end**: Run the full pipeline manually (scripts + manual walkthrough.json creation) on a small 2-3 session set to validate the normalized event model captures enough signal

3. **Skill invocation**: With symlinks in place, invoke `/walkthrough` from Claude Code and verify the agent follows the SKILL.md workflow correctly

4. **HTML output**: Open `walkthrough.html` in browser, verify navigation, diff rendering, evidence expansion, and editor links work

---

## Key Files to Reuse/Reference

- `/Users/austin/.claude/skills/frontend-slides/SKILL.md` — HTML generation pattern, viewport-fitting, single-file approach
- `/Users/austin/.codex/skills/.system/skill-creator/SKILL.md` — canonical Agent Skills spec for SKILL.md structure
- `/Users/austin/dev/_libraries/rlm/rlm/core/rlm.py` — recursive decomposition pattern (inspiration, not dependency)
- `/Users/austin/dev/walkthrough/5.2-pro-planning.md` — full planning context and schema drafts

---

## Future Work

These are out of scope for v1 but represent the natural evolution of the skill.

### WORKLOG.md Integration (`walkthrough-record` skill)
A companion skill that instructs the agent to maintain a `WORKLOG.md` during development — recording decisions, dead ends, architectural rationale, and context that isn't captured in tool call logs. The walkthrough generator would consume this as a high-signal supplementary input alongside the JSONL histories, producing richer "why" explanations with less inference.

### Live / Streaming Walkthroughs
Instead of post-hoc generation, hook into agent sessions as they happen (via Claude Code hooks at `Stop` or Codex `--json` streaming) to produce a walkthrough artifact incrementally. This enables a "watch the walkthrough build in real-time" experience and removes the need for users to remember to run the skill after the fact.

### Additional Provider Adapters
- **Cursor**: hooks support audit trail logging — write an adapter for Cursor's hook output format
- **OpenCode / other CLI agents**: configurable adapter that accepts a user-specified JSONL directory
- **Codex App Server**: richer event stream with plan updates, approval flows, and streaming diffs — a premium adapter for deeper Codex integration

### Indexed Session Warehouse (Option C from planning)
A persistent local store (SQLite/DuckDB) that indexes all normalized events with full-text search. Enables fast cross-session queries ("show me all failures during testing", "when did we last change the auth module"), incremental updates (only process new lines), and cached chunk summaries keyed by `(session_hash, chunk_id, model)` to avoid re-summarizing unchanged history.

### Interactive Q&A Mode
After generating the walkthrough, let the user ask follow-up questions ("why did we choose Postgres over SQLite?", "what broke during the migration?") with answers grounded in the evidence pack. The agent is bound to the walkthrough's evidence refs rather than roaming the entire repo, keeping answers precise and preventing confident hallucination.

### PR / CI Integration
- Auto-generate walkthrough artifacts on PR creation (via GitHub Action or hook)
- Post the walkthrough HTML as a PR comment or artifact attachment
- Reviewers get a narrative walkthrough alongside the diff

### Team / Hosted Layer
- Hosted walkthrough hub: search, indexing, retention controls, SSO, permissions
- Analytics: time-to-understand, hotspots, "what changed since I last touched this"
- This is the closed/paid layer if the skill becomes a product (schema + local generator stay open source)

### IDE Extension
A VS Code / Cursor extension that reads `walkthrough.json` and renders it inline — "click step, open file at exact line, highlight hunk, next step." Only worth building if the HTML viewer proves insufficient for the target audience. The HTML viewer with `vscode://file/` links may be enough.

### Evidence Compiler Pipeline (Option D from planning)
Stricter evidence discipline: extract claim candidates from summaries, build evidence packs per claim (log ranges, diffs, command outputs), then have the LLM narrate *only from evidence*. This makes walkthroughs trustworthy enough for formal code review and onboarding, where "eloquent but wrong" is unacceptable.

### Multi-Repo / Monorepo Support
Handle features that span multiple repositories or services. The session discovery and walkthrough assembly steps would need to understand cross-repo relationships and produce walkthroughs that tell the story across boundaries.

### Walkthrough Diffing
Compare two walkthroughs of the same area of code to show what changed between iterations — useful for "what's new since the last walkthrough" or tracking how a feature evolved over multiple development cycles.

### Global Sources Index (Schema Optimization)
De-duplicate evidence references by maintaining a top-level `sources` map (`"S1": {path, line_start, line_end, excerpt_preview, sha256}`) and referencing by ID in each step. `render_html.py` can do this deduplication at render time without changing the schema contract — the LLM writes inline refs (simpler to prompt for), the renderer deduplicates. Only promote to a schema-level feature if JSON size becomes a real problem.

### Deeper Claude Code Diff Reconstruction
v1 reconstructs diffs from `Edit` (old_string/new_string) and `Write` (full content) tool calls. Future versions could also use: (a) `file-history-snapshot` records to diff consecutive file states, (b) `git diff` between session start/end commits for files not captured by tool calls. This would catch changes made by `Bash` tool (e.g., `sed`, `mv`) that don't flow through Edit/Write.
