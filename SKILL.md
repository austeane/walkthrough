---
name: walkthrough
description: >-
  Generate evidence-backed walkthroughs from agent session histories.
  Reads Codex CLI, Claude Code, and OpenCode session histories, processes them with
  recursive summarization, and produces walkthrough.json + walkthrough.html.
  Use when the user wants to understand what an agent built, review agent work,
  walk through recent changes, onboard onto agent-written code, or generate
  a narrative explanation of a feature/PR built by an AI agent.
---

# Walkthrough Skill

Generate walkthroughs that teach developers what was built, why, and how — from agent session histories.

**Prime directive**: The walkthrough helps the developer understand their own codebase. It is NOT a transcript replay. If an agent did 100 things across 5 sessions, the walkthrough might be 8-12 steps. Compress, group, and editorialize. The right question is "what do I need to understand?" not "what happened chronologically?"

**Dependencies**: Scripts require `jinja2` and `pygments`. Optional: `pillow` (image compression for screenshots), `playwright` (Path B git-history captures). If using a project with `pyproject.toml`, prefix commands with `uv run` (e.g., `uv run python3 scripts/render_html.py ...`).

## Workflow

### 1. Scoping Dialog

Ask the user what to walk through and for whom. Use AskUserQuestion:

**Question 1 — Scope**: "What should this walkthrough cover?"
- "Recent work" — Last 1-3 days of agent sessions in this project
- "Specific sessions" — I'll point you to the session files
- "Time range" — A custom date range
- "Everything" — All agent sessions for this project

**Question 2 — Audience**: "Who is this walkthrough for?"
- "Me (refresh)" — I built this but need to re-learn it
- "Teammate" — Someone unfamiliar with this part of the codebase
- "Reviewer" — PR/code review context, focus on decisions and tradeoffs

Store the audience choice — it affects narrative tone in step 7.

**Question 3 — Screenshots**: "Should this walkthrough include screenshots?"
- "No screenshots" — Text-only walkthrough (default)
- "Extract from sessions" — Use screenshots already captured during agent work
- "Capture from git history" — Reconstruct UI by checking out commits and screenshotting
- "Both" — Extract session screenshots AND capture from git

Store the choice as `media_mode` (`none`, `extract`, `capture`, or `both`). It controls whether `--preserve-screenshots` is passed to strip_binary, whether `capture_screenshots.py` runs, and whether the HTML gallery renders.
For Path B (`capture`/`both`), capture files are written to `out/captures/manifest.json`; inject those captures into `out/walkthrough.json` before rendering (step 7c).

> **Gotcha — `extract` mode currently loses Claude Code browser screenshots.** `strip_binary --preserve-screenshots` keeps the base64 image blocks in `stripped.jsonl` (they live at `message.content[N].source.data` in browser-tool `tool_result` records), but `normalize_claude.py` emits a `screenshot` event *without* carrying the base64 forward, so by `normalized.jsonl` the `data_uri` is empty and there is nothing for the renderer to attach. Until this is fixed, `media_mode=extract` on Claude sessions yields a text-only walkthrough. (TODO: `normalize_claude.py` should copy the image `source.data`/media-type into the `screenshot` event — e.g. as `data_uri` — so `render_html.py` can bridge it into `evidence.media`.) Also note that browser-verification sessions often contain *error/phantom* frames (failed captures, stale-tab errors); filter by relevance before attaching. If screenshots matter and this gap blocks you, say so and fall back to text-first rather than silently dropping them.

### 2. Discovery

Run the discovery script to find session files:

```bash
python3 scripts/discover_sessions.py \
  --codex-root ~/.codex/sessions \
  --claude-root ~/.claude/projects \
  --cwd "$(pwd)" \
  --since <from_scope>
```

If OpenCode is installed, `discover_sessions.py` also auto-detects its local session database via `opencode db path` and includes matching OpenCode sessions in the result set.

Present the discovered sessions to the user (provider, timestamp, line count, cwd). Let them confirm or deselect sessions. If no sessions found, widen the search (remove --cwd, extend --since).

> **Gotcha — planning vs. implementation often live in different sessions.** "This session" is ambiguous: a feature is frequently *planned* in one session (research, plan file, scoping dialog) and *implemented* in another (the actual edits, tests, verification). Before committing to a scope, peek at each candidate's session card (`extract_session_cards.py`) — `files_touched` and `commands_run` tell you which session holds the real changes. The session with the most `file_change`/Edit/Write activity is usually the one the user means by "the changes," even if they pointed you at the planning session.

**Subagent-assisted discovery (recommended when many sessions are found)**:
- Spawn 2-4 subagents to score relevance in parallel from discovery metadata (timestamp, cwd, line count, filename/session id patterns, and optional user keywords).
- Ask each subagent to return: `top_sessions`, `why_relevant`, and `risk_of_false_positive`.
- Merge their overlap first, then present a concise recommended shortlist to the user before normalization.

### 3. Normalization

For each selected session, run strip_binary then the appropriate normalizer:

```bash
# Strip binary content first
python3 scripts/strip_binary.py --input <session.jsonl> --output <out/stripped.jsonl>

# Codex sessions
python3 scripts/normalize_codex.py --input <out/stripped.jsonl> --output <out/normalized.jsonl>

# Claude Code sessions (auto-discovers subagents from original session path)
python3 scripts/normalize_claude.py --input <out/stripped.jsonl> \
  --auto-subagents --session-root <original_session.jsonl> --output <out/normalized.jsonl>

# OpenCode sessions (export first, then normalize)
python3 scripts/export_opencode.py --session-id <session-id> --output <out/opencode-session.jsonl>
python3 scripts/normalize_opencode.py --input <out/opencode-session.jsonl> --output <out/normalized.jsonl>
```

If multiple sessions, concatenate normalized outputs into a single file sorted by timestamp.

**Screenshot preservation**: When `media_mode` is "extract" or "both", pass `--preserve-screenshots` to strip_binary:
```bash
python3 scripts/strip_binary.py --input <session.jsonl> --output <out/stripped.jsonl> --preserve-screenshots
```

### 3b. Event Projection

Project normalized events to remove noise before chunking. This compresses the data by ~60% so each chunk contains 2-3x more signal for the LLM summarizer.

```bash
python3 scripts/project_events.py \
  --input <out/normalized.jsonl> \
  --output <out/projected.jsonl>
```

**What projection does:**
- **Drops** `file_snapshot` (Codex context dumps), `turn_context` (Codex metadata), and `compaction` (context compression markers) — zero reasoning value
- **Compresses** non-error `tool_result` events to a stub with byte/line counts and first output line — preserves the fact that a tool ran and whether it succeeded, discards the verbose output
- **Keeps at full fidelity** everything else: `user_message`, `assistant_message`, `tool_use`, `file_change`, `command`, `reasoning`, `meta`, `system`, error `tool_result`s

**Escape hatches**: `--keep-snapshots` and `--keep-turn-context` to preserve dropped event kinds for debugging.

**Impact**: On a 63MB/44K-event dataset, projection produced 25MB/38K events — 61% byte reduction, chunking from 217 chunks down to 85. Each chunk contained ~3x more reasoning per byte, and LLM summaries were richer (more claims, more files, more decisions surfaced).

Use `projected.jsonl` as input to chunking (step 4). Keep `normalized.jsonl` as the full-fidelity reference for source_refs and screenshot resolution.

### 3c. Session Card Extraction

Extract a ~2KB deterministic summary card per session for overview context:

```bash
python3 scripts/extract_session_cards.py \
  --input <out/session-0001-normalized.jsonl> \
  --output <out/cards/session-0001-card.json>
```

Cards capture: session_id, provider, model, timestamps, turn count, subagents, files_touched, commands_run, errors, and user_intents (first sentence of each user_message). No LLM calls — purely deterministic.

Cards are useful for giving the editorial agent (step 7) an overview of all sessions in one pass before it reads the full draft walkthrough.

### 4. Chunking

```bash
python3 scripts/chunk_events.py \
  --input <out/projected.jsonl> \
  --output-dir out/chunks \
  --target-bytes 300000
```

**With screenshots**: Screenshot events increase chunk sizes. When screenshots are present, consider larger chunks:
```bash
python3 scripts/chunk_events.py \
  --input <out/projected.jsonl> \
  --output-dir out/chunks \
  --target-bytes 500000
```

This produces `chunk-001.jsonl`, `chunk-002.jsonl`, ... and a `manifest.json`. The manifest is the source of truth for the pipeline — do not proceed if any chunk is missing a summary.

**Batch processing (20+ sessions)**: For Codex-heavy projects with many small sessions, use the batch pipeline script instead of processing sessions individually. It automates steps 3-4 (strip → normalize → project → extract cards → concat → chunk) for all sessions:

```bash
# Save discover_sessions.py output to a file first
python3 scripts/discover_sessions.py --cwd "$(pwd)" --since 14d > sessions.json

python3 scripts/batch_pipeline.py \
  --sessions sessions.json \
  --output-dir out/ \
  --target-bytes 300000
```

This produces `out/batch/` (per-session normalized + projected files), `out/cards/` (per-session cards), `out/session-cards.json` (merged cards), `out/normalized.jsonl` (full fidelity), `out/projected.jsonl` (noise-reduced), and `out/chunks/` (chunked from projected data).

Use `--no-project` to skip projection and chunk raw normalized data (backward compat).

Then skip to step 5 (Chunk Summarization) with the generated `out/chunks/manifest.json`.

### 4b. Pipeline Validation

After chunking (or at any stage), run contract validation to catch regressions:

```bash
# Validate all stages
python3 scripts/validate_pipeline.py \
  --normalized out/normalized.jsonl \
  --projected out/projected.jsonl \
  --chunks out/chunks/manifest.json
```

Checks include: turn_index conventions (meta=0, first visible user=1), per-stream validation for subagents, session contiguity, tool_use/tool_result pairing integrity, no data_b64 in projected output, chunk SHA256 and byte_size correctness, and seq monotonicity.

> **Gotcha — `turn_index regression` on compacted/continued sessions.** A session that hit `/compact` (or was resumed from a summary) restarts its turn numbering partway through, which trips the `turn_index regression` check as a *false* failure. The data is fine. Treat this specific failure as a warning when you know the session was compacted, and don't block the pipeline on it. (TODO for the validator: in `validate_pipeline.py`, the `turn_index regression` issue in `_validate_stream_file` should be downgradeable to a warning via an `--allow-turn-regression` flag, since compaction legitimately resets turn numbers.)

### 5. Chunk Summarization

For each chunk, spawn a Sonnet subagent to produce a structured summary. The subagent identifies the **narrative arc** of its chunk: what was the agent trying to do, what went wrong, what did it learn, what did it build. Use `model: "haiku"` as a fast/cheap fallback for draft walkthroughs or very large sessions (20+ chunks).

**Cache by chunk hash**: Write summaries to `out/summaries/<chunk_id>.<sha256>.json`. Reuse summaries only on an exact chunk ID + hash match; do not fuzzy-match older files by prefix.

**Claude Code** — spawn subagents in parallel:
```
Agent tool, model: "sonnet", subagent_type: "general-purpose"
```

**Codex** — process chunks sequentially (no parallel subagent support).

**Subagent prompt template** (adapt per chunk):

> You are summarizing a chunk of an agent session transcript for a code walkthrough.
>
> Read the chunk file at: `{chunk_path}`
>
> Produce a JSON summary with this structure:
> ```json
> {
>   "chunk_id": "{chunk_id}",
>   "narrative": "2-4 sentence description of what happened in this chunk",
>   "claims": [
>     {"text": "claim text", "confidence": "grounded|inferred|speculative", "source_refs": [{"session_path": "...", "line_start": N, "line_end": N}]}
>   ],
>   "files_changed": [{"path": "...", "kind": "create|modify|delete", "summary": "what changed"}],
>   "commands": [{"cmd": "...", "status": "pass|fail", "summary": "..."}],
>   "decisions": [{"decision": "...", "rationale": "...", "alternatives_considered": []}],
>   "diff_hunks": [{"file": "...", "before": "code before", "after": "code after", "summary": "what changed"}],
>   "errors": [{"error": "...", "resolution": "..."}],
>   "key_concepts": ["concept1", "concept2"]
> }
> ```
>
> Rules:
> - Each claim must have a confidence level and source_refs pointing to line numbers in the source session
> - "grounded" = directly stated in the logs. "inferred" = logical conclusion from context. "speculative" = editorial judgment
> - Focus on INTENT and CAUSALITY, not mechanical listing of tool calls
> - Identify decisions, errors, and recoveries — these are high-value for the walkthrough
> - Extract diff_hunks from file_change events in the chunk. Look for events with kind "file_change" — they contain a "diff" field with unified diff format. Extract the most important 2-3 hunks per file (not all hunks — pick the ones that show the key change). For each, extract a short before/after snippet (5-15 lines each) and a one-sentence summary.
> - Extract commands from command events. Include the command, exit status, and a summary of the output.
> - If the chunk contains `screenshot` events, note them in a `screenshots` field:
>   ```json
>   "screenshots": [{"event_seq": N, "context": "what was being shown", "relevance": "high|medium|low"}]
>   ```
> - Mark relevance "high" for screenshots showing key UI changes or error states, "medium" for routine progress, "low" for repeated/similar screenshots
> - Write the summary as JSON only, no surrounding text
>
> **Critical**: Output MUST be a single JSON object matching the schema above exactly. Do not wrap in markdown code fences. Do not add extra top-level keys. `narrative` must be a string (not a list). `files_changed` must be an array of objects with `path`, `kind`, and `summary` keys.

Write each summary to `out/summaries/<chunk_id>.<sha256>.json`.

**Verification**: After all subagents complete, verify that every chunk in the manifest has a corresponding summary file on disk. Subagents may report success without actually writing files (especially at scale with 20+ parallel agents). Check with:

```bash
python3 scripts/merge_summaries.py \
  --manifest out/chunks/manifest.json \
  --summaries-dir out/summaries \
  --output /dev/null --dry-run
```

Re-run any missing chunks before proceeding.

### 6. Session Synthesis

If there are multiple chunks from a single session, or multiple sessions, spawn a Sonnet-class subagent to unify the chunk summaries into session-level summaries.

First, verify all chunks in the manifest have corresponding summary files. Refuse to proceed if any are missing.

**Subagent prompt**: Provide all chunk summaries for a session, ask the agent to merge them into a single coherent session summary that preserves all claims, deduplicates overlapping evidence, and identifies the overall narrative arc. Output the same JSON structure as chunk summaries but at session level.

### 7. Walkthrough Assembly

This is the editorial step. First, generate a draft walkthrough from the summaries:

```bash
python3 scripts/merge_summaries.py \
  --manifest out/chunks/manifest.json \
  --summaries-dir out/summaries \
  --repo-root "$(pwd)" \
  --output out/draft-walkthrough.json
```

**If some summaries are missing** (e.g., you only summarized a subset of chunks), use `--allow-fallback` to fill gaps with deterministic extraction instead of erroring:

```bash
python3 scripts/merge_summaries.py \
  --manifest out/chunks/manifest.json \
  --summaries-dir out/summaries \
  --repo-root "$(pwd)" \
  --output out/draft-walkthrough.json \
  --allow-fallback
```

Fallback summaries extract files, commands, errors, and user intents directly from the chunk JSONL — no LLM needed. They emit schema-valid command/decision/error objects and produce narratives like `"chunk-011: 168 events. User intents: set up terraform. Files: main.tf, variables.tf. 4 commands run. 1 error."` instead of the old empty `"contains N events"` stubs.

Read the draft, then apply editorial judgment: merge related steps, reorder for clarity, compress mechanical sequences, and add overview narrative. The orchestrator (you) has full editorial freedom. You receive all session summaries and decide: how many steps, what grouping, what order, what to emphasize, what to compress.

**Session cards as editorial context**: If `out/session-cards.json` exists (produced by `extract_session_cards.py` or `batch_pipeline.py`), pass it to the editorial agent alongside the draft. Cards give the editor a quick overview of all sessions — user intents, files touched, commands, errors, subagents — so it can make informed grouping decisions without reading every chunk summary in detail.

Provide session cards to the editorial agent with a prompt like:

> First, read the session cards at `out/session-cards.json` to understand the overall arc across all sessions. Then read the draft walkthrough at `out/draft-walkthrough.json` for the detailed chunk-level summaries. Use the session cards to inform your step groupings — the `user_intents` field shows what the user was trying to accomplish in each session, and session boundaries often (but not always) align with conceptual phase boundaries.

The cards are ~2KB each, so 50-60 cards fit in ~120KB — small enough to include alongside the draft walkthrough in a single Opus context window.

Read the walkthrough schema: `references/walkthrough-schema.md`

**Guidelines by audience**:
- **Me (refresh)**: Be direct. Focus on "what changed and why." Skip obvious context.
- **Teammate**: Explain architectural decisions. Include enough context to navigate the codebase.
- **Reviewer**: Emphasize decisions, tradeoffs, and error handling. Call out anything that deserves scrutiny.

**Assembly rules**:
- 8-20 steps is typical. Fewer for simple features, more for complex multi-session work.
- Group by concept or subsystem, not chronology, unless chronology IS the story.
- Every step needs a `takeaway`: one declarative outcome sentence stating what changed and its net effect (distinct from the `title` topic and the `intent` why). This is the "broad shape" a reader scans first; the rendered page leads with it. **Skim test**: read the `takeaway` lines alone, top to bottom — they should form a complete, coherent summary of the whole session. If they don't, re-edit the steps until they do.
- Every step needs at least one grounded claim with source_refs.
- The overview.goal should be one sentence a stranger could understand.
- Include a Mermaid/source diagram in overview if the work involved multiple interacting components.
- If the diagram is too tiny to read (for example, only a few nodes in one line), remove it or expand it before rendering.
- Decisions and errors_encountered are high-value reasoning — the renderer shows them in the always-visible narrative band (not inside the collapsed evidence), so write them as standalone insights a scanning reader should catch.
- The rendered step is an altitude ladder: `title` → `takeaway` (gist) → `intent` (why) → claims + decisions + gotchas (visible narrative) → `evidence` diffs/commands/screenshots (collapsed proof, expand on demand). Put each fact at the altitude that matches how much a reader needs it.

For large sessions (15+ draft steps), use Opus (`model: "opus"`) for editorial assembly — it handles complex compression (e.g. 276→15 steps) significantly better than Sonnet.

Write the result to `out/walkthrough.json`. Validate it has all required fields per the schema. Include `meta.repo_root` set to the project's absolute path so cursor:// and vscode:// editor links work correctly in the rendered HTML.

> **Gotcha — `out/` is a single hardcoded namespace.** The pipeline reads and writes `out/walkthrough.json`, `out/chunks/`, `out/summaries/`, etc. with no per-walkthrough subfolder. Running a *second* walkthrough (e.g. a meta walkthrough, or a different scope in the same repo) silently clobbers the first — and in this repo `out/walkthrough.json` is also the test fixture. When producing an additional walkthrough, isolate it in a subdirectory (e.g. `out/<name>/...` for every stage and `--output out/<name>/walkthrough.html`) so you don't overwrite an existing one or the test sample.

> **Gotcha — `merge_summaries.py` coverage report can under-count.** During the meta run, `merge_summaries --dry-run` reported `0/3` summary coverage even though all three `<chunk_id>.<sha256>.json` files were present and their shas matched the manifest (the `load_summaries` resolver at the top of the script finds them correctly). If the draft step insists summaries are missing while the files are demonstrably on disk, don't trust the count: verify directly (`for c in manifest.chunks: (summaries_dir / f"{c.chunk_id}.{c.sha256}.json").exists()`), and if they're all there, proceed — the editorial assembly reads the summary JSON files itself, so you can hand-author `walkthrough.json` from them and skip the broken draft. (TODO: reconcile the dry-run coverage counter with `load_summaries`.)

### 7b. Media Capture (Path B only)

If the user chose "capture" or "both" for `media_mode`, capture screenshots from git history:

- Ask for `--dev-cmd`, `--url`, and `--routes` if they are not obvious.
- Prefer non-interactive dev commands and explicit host/port (`--host 127.0.0.1 --strictPort` for Vite-style servers).
- Use `--server-timeout 90` by default; 30 seconds is often too short on cold starts.

```bash
python3 scripts/capture_screenshots.py \
  --walkthrough out/walkthrough.json \
  --repo-root "$(pwd)" \
  --dev-cmd "CI=1 npm run dev -- --host 127.0.0.1 --port 3000 --strictPort" \
  --url http://127.0.0.1:3000 \
  --routes "/,/login,/dashboard" \
  --server-timeout 90 \
  --output-dir out/captures
```

If commit auto-detection is wrong, rerun with explicit SHAs:

```bash
python3 scripts/capture_screenshots.py \
  --walkthrough out/walkthrough.json \
  --repo-root "$(pwd)" \
  --dev-cmd "CI=1 npm run dev -- --host 127.0.0.1 --port 3000 --strictPort" \
  --url http://127.0.0.1:3000 \
  --routes "/,/login,/dashboard" \
  --server-timeout 90 \
  --output-dir out/captures \
  --commits "<sha1>,<sha2>"
```

Verify capture success before continuing:

```bash
python3 - <<'PY'
import json
manifest = json.load(open("out/captures/manifest.json"))
count = manifest.get("total_screenshots", 0)
print(f"total_screenshots={count}")
if count == 0:
    raise SystemExit("No screenshots captured. Fix --dev-cmd/--url/--routes/--commits and rerun.")
PY
```

If captured pages are error payloads (4xx/5xx, raw JSON error body, missing app shell), do not attach them. Fix env first (commonly `BASE_URL` / `VITE_BASE_URL`) or switch to live-environment captures (for example, `qcdev`) via Chrome DevTools and attach those image paths into `evidence.media`.

### 7c. Inject Captures Into Walkthrough Media (Path B)

Path B capture writes files and a manifest. Inject these into `step.evidence.media` before rendering:

```bash
python3 scripts/inject_capture_media.py \
  --walkthrough out/walkthrough.json \
  --manifest out/captures/manifest.json
```

### 8. Rendering

```bash
python3 scripts/render_html.py \
  --input out/walkthrough.json \
  --output walkthrough.html \
  --normalized out/normalized.jsonl \
  --captures-manifest out/captures/manifest.json
```

If media was curated manually in `out/walkthrough.json` (for example, live `qcdev` DevTools captures already attached), render without auto-manifest attachment to avoid accidental duplicate/legacy media injection:

```bash
python3 scripts/render_html.py \
  --input out/walkthrough.json \
  --output walkthrough.html \
  --normalized out/normalized.jsonl \
  --captures-manifest /tmp/does-not-exist-manifest.json
```

Open the result:
```bash
open walkthrough.html
```

The rendered HTML is expected to be self-contained and offline-safe: no CDN fonts, no runtime Mermaid fetches, and editor links should resolve correctly for both repo-relative and absolute file references.

Quick QA checks:

```bash
python3 - <<'PY'
import json
w = json.load(open("out/walkthrough.json"))
mode = (w.get("meta", {}).get("media_mode") or "none").lower()
media_count = sum(len(step.get("evidence", {}).get("media", [])) for step in w.get("steps", []))
print(f"media_items={media_count}")
if mode in {"extract", "capture", "both"} and media_count == 0:
    raise SystemExit("media_mode expects screenshots, but no evidence.media items were attached.")
PY
```

If Chrome DevTools MCP is available, also verify rendered thumbnail counts match JSON media counts (catches gallery duplication regressions):

```js
(() => {
  return DATA.steps.map((s) => {
    const expected = (s.evidence?.media || []).length;
    const rendered = document.querySelectorAll(`#media-${s.id} .media-thumb`).length;
    return { id: s.id, expected, rendered, ok: expected === rendered };
  });
})()
```

Present to the user: file path, step count, key highlights. Ask if they want adjustments.

## Operational Notes

### Surviving a flaky tool-result channel
If tool results start returning empty for long stretches and then flush in a burst (an environment/transport stall, not an RTK or script bug — it hits Read and ToolSearch too, not just Bash), the pipeline is still runnable; minimize round-trips and make every step recoverable:
- **Bundle stages into one command.** Run `strip → normalize → project → cards → chunk → validate` as a single `{ ...; } 2>&1 | tee out/<ns>/pipeline.log` so one round-trip does the whole pre-summary pipeline, and the log survives a stalled result.
- **Write results to files, not stdout.** `python … > out/<ns>/foo.txt 2>&1` then Read the file; a corrupted result channel mangles inline stdout but the on-disk file is intact.
- **Prefer the disk as source of truth.** After any step, re-derive state by listing/reading output files rather than trusting the (possibly empty) command result.
- **Don't bundle file edits behind a command that can fail.** A Bash that exits non-zero cancels every other tool call sent in the same batch; issue `Edit`/`Write` calls on their own so a failing probe can't discard them.
- **Use background commands + `ScheduleWakeup`** for long stages so a stall doesn't strand the turn; the harness re-invokes on completion.
- **Don't trust browser/tool output you can't tie to a real handle.** A stalled channel can return plausible-looking garbage; verify against a freshly created tab id / a re-read file before acting on it. (This skill's own meta walkthrough recorded a fabricated browser pass caused by exactly this.)

### Meta / recursive walkthroughs
You can run this skill on the very sessions where you changed this skill (dogfooding). Output to an isolated namespace (see the `out/` gotcha above). A single small session (≈1 chunk) can be summarized inline instead of via subagent fan-out; multi-chunk sessions still fan out to parallel Sonnet subagents as usual.

## Provider-Specific Notes

### Codex CLI
- Sessions at `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`
- See `references/codex-session-format.md` for event type details
- Has explicit `fileChange` events and `aggregate_diff` at turn boundaries
- Process chunks sequentially (no parallel subagent spawning)

### Claude Code
- Sessions at `~/.claude/projects/{encoded-cwd}/{sessionId}.jsonl`
- See `references/claude-session-format.md` for record type details
- Diffs reconstructed from Edit/Write tool calls (no explicit fileChange events)
- Subagent transcripts may be in `{sessionId}/subagents/`
- Use Agent tool with `model: "sonnet"` for chunk summarization subagents (or `"haiku"` for fast/cheap drafts)

### OpenCode
- Sessions are discovered from the local SQLite store (resolved via `opencode db path`)
- Selected sessions are exported through `opencode export <session-id>` before normalization
- File changes are reconstructed from per-turn OpenCode diff summaries and patch parts

## Reference Docs

- `references/codex-session-format.md` — Codex JSONL event types
- `references/claude-session-format.md` — Claude Code JSONL record types
- `references/normalized-event-model.md` — Common event schema
- `references/walkthrough-schema.md` — Output JSON schema + evidence rules

## Scripts

All scripts are available as `uv run` commands via entry points (e.g., `uv run walkthrough-validate`), or directly as `python3 scripts/<name>.py`.

| Script | Entry Point | Purpose | Input | Output |
|--------|------------|---------|-------|--------|
| `discover_sessions.py` | `walkthrough-discover` | Find sessions | CLI flags | JSON list to stdout |
| `strip_binary.py` | `walkthrough-strip` | Remove base64/binary | JSONL | Cleaned JSONL |
| `normalize_codex.py` | `walkthrough-normalize-codex` | Codex → normalized | JSONL | Normalized JSONL |
| `normalize_claude.py` | `walkthrough-normalize-claude` | Claude → normalized | JSONL + subagents | Normalized JSONL |
| `export_opencode.py` | `walkthrough-export-opencode` | OpenCode export → JSONL | Session ID | JSONL |
| `normalize_opencode.py` | `walkthrough-normalize-opencode` | OpenCode → normalized | JSONL | Normalized JSONL |
| `project_events.py` | `walkthrough-project` | Drop noise, compress tool_results | Normalized JSONL | Projected JSONL |
| `extract_session_cards.py` | `walkthrough-cards` | Per-session summary card | Normalized JSONL | Card JSON |
| `chunk_events.py` | `walkthrough-chunk` | Split for LLM context | Projected JSONL | Chunks + manifest |
| `batch_pipeline.py` | `walkthrough-batch` | Batch strip+normalize+project+chunk | sessions.json | projected.jsonl + chunks/ + cards/ |
| `merge_summaries.py` | `walkthrough-merge` | Draft walkthrough from summaries | Manifest + summaries | draft-walkthrough.json |
| `capture_screenshots.py` | `walkthrough-capture` | Git-reconstruct UI screenshots + manifest | walkthrough.json + repo | captures/ |
| `inject_capture_media.py` | `walkthrough-inject-media` | Attach capture manifest items to `evidence.media` | walkthrough.json + captures/manifest.json | walkthrough.json |
| `render_html.py` | `walkthrough-render` | JSON → HTML viewer | walkthrough.json | walkthrough.html |
| `validate_pipeline.py` | `walkthrough-validate` | Contract validation checks | normalized/projected/chunks | Pass/fail report |

## Output Structure

```
out/
├── batch/                   # Per-session intermediate files
│   ├── session-0000-claude-stripped.jsonl
│   ├── session-0000-claude-normalized.jsonl
│   ├── session-0000-claude-projected.jsonl
│   └── ...
├── cards/                   # Per-session deterministic cards
│   ├── session-0000-claude-card.json
│   └── ...
├── session-cards.json       # All cards merged
├── normalized.jsonl         # Full-fidelity concatenated events
├── projected.jsonl          # Noise-reduced concatenated events
├── chunks/
│   ├── chunk-001.jsonl      # Chunked from projected data
│   ├── chunk-002.jsonl
│   └── manifest.json
├── summaries/
│   ├── chunk-001.<sha>.json
│   └── chunk-002.<sha>.json
├── captures/                # Path B screenshots (if enabled)
│   ├── commit-abc1234-index-commit-abc1234.png
│   └── manifest.json
├── draft-walkthrough.json   # 1:1 chunk-to-step draft
├── walkthrough.json         # Final editorially assembled walkthrough
└── walkthrough.html         # Rendered HTML viewer
```
