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

**Prime directive**: The walkthrough helps the developer understand their own codebase. It is NOT a transcript replay. If an agent did 100 things across 5 sessions, the walkthrough might be 5-10 steps. Compress, group, and editorialize. The right question is "what does this reader need for this purpose?" not "what happened chronologically?"

**Bias**: Prefer brevity and focus over completeness. A strong walkthrough deliberately omits low-signal changes, side quests, routine tool use, and repeated implementation detail. Cover the smallest set of concepts that lets the target reader accomplish the stated purpose.

## Setup

**First run on a new machine: run the doctor.**

```bash
python3 scripts/check_setup.py
```

It is stdlib-only, prints what is available and what each gap blocks (with the exact remedy), and exits 0 when a text-first walkthrough can be produced end-to-end. Facts it encodes:

- **Python 3.9+ is the floor.** Every pipeline script through step 7 (discovery → normalize → chunk → merge → quality gate) is stdlib-only and runs on the stock macOS `python3`. No venv, no install step.
- **Only rendering (step 8) has dependencies** (`jinja2`, `pygments`). Best-first ways to satisfy them: `uv run scripts/render_html.py ...` (the script carries PEP 723 inline metadata, so uv resolves deps in an isolated environment from any working directory); or `python3 -m pip install --user jinja2 pygments`; or, inside the skill repo itself, `uv sync` once. **Caution:** `uv run python3 scripts/render_html.py` from inside another project resolves *that project's* environment and fails — keep the script path as the command so the inline metadata wins.
- Optional libraries: `pillow` (screenshot compression), `playwright` (Path B git-history captures only).

**Paths**: the commands below are written relative to this skill's directory. When your working directory is the target repo (the normal case), invoke scripts by absolute path (e.g. `python3 ~/.claude/skills/walkthrough/scripts/discover_sessions.py`) and keep `out/` in the working directory.

**Optional tooling — never block a first walkthrough on it, never install it silently.** When the doctor shows LikeC4 missing (or HyperFrames, if video is in scope), fold one permission question into the step 1 scoping dialog: diagrams need a one-time install (npm package + a headless-Chromium download), install now in the background? Then:

- **Yes** → immediately spawn a **background install agent** and keep working — discovery, normalization, and chunking need none of this tooling, so the slow part (the Chromium download) runs concurrently instead of blocking the pipeline. In Claude Code use the Agent tool with `run_in_background: true`; agents without background subagents run the same commands as a detached shell with output to a log file. Install agent prompt:

  > Install diagram tooling for the walkthrough skill. Run `npm install -g likec4` (fall back to `brew install likec4` if npm is unavailable). Then trigger the one-time headless-Chromium download by exporting a throwaway model: write `specification { element system }`, `model { sys = system 'S' }`, `views { view index { include * } }` to `/tmp/likec4-smoke/model.c4` and run `likec4 export png /tmp/likec4-smoke -o /tmp/likec4-smoke/out`. Report `likec4 --version`, whether the export produced a PNG, and any failure verbatim. *(If video is in scope, also run `npx skills add heygen-com/hyperframes` and report whether `ffmpeg` is on PATH.)*

  Collect the agent's result before step 7 (assembly, where diagram authoring starts). If the install failed, say so and continue text-first — a failed optional install never blocks the walkthrough.
- **No** (or the user is unsure) → produce the text-first walkthrough (the gate's "no diagram" warning is acceptable on a first run) and offer diagrams/video as a follow-up.

Tooling reference, once per machine:

- **LikeC4** (diagrams — near-universal once available, see Editorial Rules):
  - CLI: `npm install -g likec4` (or `brew install likec4`). `likec4 export png` drives a bundled Playwright Chromium — the first export may download it.
  - Authoring skill: `npx skills add https://likec4.dev/` — loads the `likec4-dsl` skill (DSL syntax and patterns) for writing the `.c4` model.
  - Optional MCP server for querying an existing model (element search, relationship discovery): `claude mcp add likec4 -- npx -y @likec4/mcp`.
- **HyperFrames** (walkthrough videos, step 7d): `npx skills add heygen-com/hyperframes` — required before authoring any `video`. QA also wants `ffmpeg` on PATH for frame extraction (see 7d).

## Workflow

### 1. Reader Frame + Scoping Dialog

Ask the user for the reader frame before discovery unless the answer is self-evident from the prompt. Use AskUserQuestion when available; otherwise ask concise plain-text questions. Store these choices in your notes and in `meta` where possible (`scope`, `audience`, `purpose`, `detail_level`) so the editorial step can obey them.

If multiple fields are missing, ask them together rather than one at a time:

**Audience**: "Who is this walkthrough for?"
- "Me (refresh)" — I built this but need to re-learn it
- "Teammate/team" — Someone unfamiliar with this part of the codebase
- "Reviewer" — PR/code review context, focus on decisions and tradeoffs

**Level of detail**: "How deep should it go?"
- "High-level" — Concepts, outcomes, and navigation pointers
- "Technical detail" — Architecture, data flow, important files, and tricky code
- "Both/toggleable" — High-level skim path with deeper technical detail available on demand

**Purpose**: "What should the walkthrough help the reader do?"
- "Onboard" — Build enough context to work in the area
- "Understand what happened" — Regain the shape of recent work
- "Review a concept/PR" — Evaluate decisions, tradeoffs, risks, and test evidence

**Scope**: "What should it cover?"
- "Specific feature/change" — The named feature, PR, branch, or change set
- "Specific app area" — One subsystem, route, workflow, or integration
- "Specific sessions/time range" — The selected session files or custom date range

Avoid broad "everything" scope. If the user asks for everything, narrow it into a reader-centered slice before proceeding: what app area, what changed, or what decision they need to understand. Only produce an exhaustive walkthrough if the user explicitly asks for an archive-style artifact after you explain it will be less focused.

**Screenshots**: "Should this walkthrough include screenshots?"
- "No screenshots" — Text-only walkthrough (default)
- "Extract from sessions" — Use screenshots already captured during agent work
- "Capture from git history" — Reconstruct UI by checking out commits and screenshotting
- "Both" — Extract session screenshots AND capture from git

**Tooling installs** (ask only when `check_setup.py` flagged missing optional tooling): "Diagrams need a one-time install (likec4 + a headless-Chromium download). Install it now in the background while I gather context?"
- "Yes, install in background" — Spawn the background install agent (see Setup) and proceed straight to Discovery; the install and the context-gathering run concurrently
- "Not now" — Plan a text-first walkthrough; offer diagrams as a follow-up

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
> The final walkthrough will be brief and purpose-driven. Treat this chunk summary as raw material, not a requirement to cover everything. Preserve only the most important intent, causality, decisions, failures, files, and evidence that may matter to the target reader.
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
> - Do not emit claims, decisions, or errors about the agent's own workflow mechanics (subagents spawned, plan files copied, prompt revisions, model cross-checks, liveness probes, flaky tooling like browser relays or doc viewers) unless the event changed the direction of the work itself. Never include plan-copy `cp` commands, version checks, or housekeeping in `commands`.
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

**Subagent prompt**: Provide all chunk summaries for a session, ask the agent to merge them into a single coherent session summary under a **compression contract**: keep every claim that changes what the reader believes about the system; merge restatements into the single strongest claim (with merged source_refs); drop workflow mechanics. Each fact appears once, at its strongest. Record what was deliberately dropped in an `omitted` array (one line per cut theme, e.g. `"routine dependency bumps"`, `"a failed Redis experiment"`) so the editorial step can honor the omission instead of re-deriving it. Output the same JSON structure as chunk summaries plus `omitted`, at session level.

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

Read the draft, then apply editorial judgment: merge related steps, reorder for clarity, compress mechanical sequences, and add overview narrative. The orchestrator (you) has full editorial freedom. You receive all session summaries and decide: how many steps, what grouping, what order, what to emphasize, what to omit, and what to compress.

**Session cards as editorial context**: If `out/session-cards.json` exists (produced by `extract_session_cards.py` or `batch_pipeline.py`), pass it to the editorial agent alongside the draft. Cards give the editor a quick overview of all sessions — user intents, files touched, commands, errors, subagents — so it can make informed grouping decisions without reading every chunk summary in detail.

Provide session cards to the editorial agent with a prompt like:

> First, read the session cards at `out/session-cards.json` to understand the overall arc across all sessions. Then read the draft walkthrough at `out/draft-walkthrough.json` for the detailed chunk-level summaries. Use the session cards to inform your step groupings — the `user_intents` field shows what the user was trying to accomplish in each session, and session boundaries often (but not always) align with conceptual phase boundaries.

The cards are ~2KB each, so 50-60 cards fit in ~120KB — small enough to include alongside the draft walkthrough in a single Opus context window.

Read the walkthrough schema: `references/walkthrough-schema.md`

**Editorial frame**:
- **Audience** controls assumed context and tone.
- **Purpose** controls what information earns space.
- **Detail level** controls depth, not breadth.
- **Scope** controls what gets excluded.

**Architecture selection** — before writing any steps, pick the artifact's organizing principle from the frame (full selection table and step shapes: `references/walkthrough-architectures.md`):

- **The Descent** (question-led, destination-first) — the default for **onboard/handoff** purposes and cold-teammate audiences: steps answer, in order, *what exists now / how much can I trust it / why is it shaped this way / what fought back / where do I start*, with a proof-ledger step carrying the verification story in one place.
- **The Journey arc** (causal narrative) — for **review/decision** purposes ("should we standardize on X?"), me-refresh audiences, and sessions whose meaning lives in a dramatic hinge (an audit voiding a result, a forced pivot): steps trace build → harden → pivot → validate.
- Tiebreak: which question does the reader open with? *"What is here now?"* → Descent; *"How did this happen / was this right?"* → Journey. Still ambiguous → Descent.
- Whichever you pick, the Descent's two measured strengths are required: an explicit proof ledger (a step, or `end_state.constraints` carrying proven-vs-unproven with numbers) and a where-to-start landing (orientation step or `end_state.architecture` + key files).

Before writing final steps, state the frame to yourself in one sentence: "This walkthrough is for `<audience>`, at `<detail_level>`, to `<purpose>`, covering `<scope>`, shaped as a `<Descent|Journey>`." If any piece is missing and not obvious, ask before final assembly.

**Guidelines by audience**:
- **Me (refresh)**: Be direct. Focus on "what changed and why." Skip obvious context.
- **Teammate/team**: Explain architectural decisions. Include enough context to navigate the codebase.
- **Reviewer**: Emphasize decisions, tradeoffs, and error handling. Call out anything that deserves scrutiny.

**Guidelines by purpose**:
- **Onboard**: Explain the concept map, ownership boundaries, and where to start reading. Skip deep diffs unless they reveal the core shape.
- **Understand what happened**: Prioritize final outcomes, pivots, and the few implementation details needed to regain context.
- **Review a concept/PR**: Prioritize decisions, risks, test evidence, edge cases, and unresolved questions.

**Guidelines by detail level**:
- **High-level**: 4-7 steps. Keep code details in key file links and collapsed evidence.
- **Technical detail**: 6-10 steps. Include key data flows, APIs, schemas, and non-obvious implementation choices, but still omit routine edits.
- **Both/toggleable**: Keep the visible skim path high-level; put technical depth in claims, decisions, gotchas, and collapsed evidence. Do not double the step count to satisfy both modes.

**Assembly rules**:
- 5-10 steps is typical. Use 4-7 for high-level or narrow work. Use 10-12 only for genuinely complex, multi-session work. More than 12 final steps means the walkthrough is probably still a draft unless the user explicitly requested exhaustive coverage.
- Each step, claim, decision, gotcha, and command must earn its place by serving the audience, purpose, and scope. If it is only there because the agent did the work, cut it; agent-process adversity that genuinely changed the work's direction gets at most one journey-tagged line per step.
- Prefer one sharp walkthrough over a complete catalog. Leave routine commands, trivial file edits, exploratory dead ends, and duplicate screenshots out of the reader-facing narrative.
- Group by concept or subsystem, not chronology, unless chronology IS the story.
- Every step needs a `takeaway`: one declarative outcome sentence stating what changed and its net effect (distinct from the `title` topic and the `intent` why). This is the "broad shape" a reader scans first; the rendered page leads with it. **Skim test**: read the `takeaway` lines alone, top to bottom — they should form a complete, coherent summary of the whole session. If they don't, re-edit the steps until they do.
- **Takeaway grammar**: one outcome per line — never weld two *unrelated* outcomes with "and"/"alongside"/semicolons; split the step or demote the lesser outcome to a claim. But DO weld an outcome to its cause: "outcome — which is why/because…" is the template ("…the boundary is a separate, starved executor — which is the entire reason there are two services"). Length serves causality, not brevity: a two-clause takeaway that carries the why beats a terse one that forces the reader to descend for it. **The weld is one cause, not a clause chain**: outcome + its cause is the ceiling — a second outcome, a decorative qualifier, or evidence-rung detail (a tab ID, a byte count) moves down to a claim/gotcha, never onto the takeaway line. **Exception — integrity qualifiers stay**: when an outcome's proof status is itself the story (a claim narrowed to sandbox-only, a verification voided, a result that holds only partially), that qualifier is part of the outcome and belongs on the takeaway line; demoting it leaves a causal hole and reads as a content gap, not trimmed filler. Read each takeaway aloud once; if it needs a second pass to parse, untangle it — the rung meant for skimming must never require re-reading. A takeaway never restates its title: the title is the topic, the takeaway is what is now true. Journey-tagged steps lead with the durable payload (what was learned, validated, or decided), not activity narration. If a thread spans non-adjacent steps, the later takeaway marks the continuation explicitly (and when a later step replaces or restructures an earlier step's mechanism, say which survived); if narrative order deviates from causal order, the order-breaking takeaway carries the reconciling clause.
- **Titles are contracts; skim-band promises are debts.** Every noun a title promises, its takeaway covers — "X and the first quota walls" with a takeaway about only X is a broken contract (rename the title or extend the takeaway). Every fact promised higher up lands below: an overview.summary fix appears in some step's visible band; a constraint's `step_ref` points at a step whose claims/decisions/evidence actually substantiate it (a constraint with no landing spot in its own step is an orphan); a count promises an inventory ("ten OpenTofu modules" enumerates the ten somewhere, or stops counting).
- **No causal holes.** Read the takeaway sequence as a chain: every pivot must have its connecting beat present in some takeaway (a collapse at 34k TPS cannot jump to "deliverables rewritten around measured numbers" without the line that connects them). If compression cuts a step, its causal content moves into an adjacent takeaway — it never silently disappears. **Integrity beats are mandatory:** events that change how much the reader can trust the work (a fabricated verification voided and disclosed, an audit reclassifying findings, a claim that did not survive scrutiny) always keep a visible journey beat; cutting them is dishonest compression.
- **One fact, one rung.** Within a step a fact lives at exactly one altitude: claims carry what changed, decisions carry why plus the alternatives, gotchas carry symptom plus resolution — none re-narrates another. For a bug fix, the root cause goes in the claim or the decision rationale, never both. A headline fact (a measured number, a pass/fail result, a named ceiling) appears at most twice in the *whole artifact*: once in the skim band, once in the step where it lands. The third occurrence becomes a pointer or gets cut — "2-of-4 → 4-of-4" appearing in overview.summary, end_state.summary, a constraint, a takeaway, AND a claim is accumulation, not layering. **But deduplication never evicts the numbers from the skim band**: when measured results exist, `end_state.summary`'s measured-truth bullet states them outright — replacing them with a pointer ("what is proven vs unproven is itemized in the constraints below") defers the single most important destination fact and reads as indirection, not discipline. Dedupe by cutting the *lower* occurrences (a claim restating a constraint, a takeaway restating the summary), never the skim-band one. The same discipline applies to `meta.sessions`: list each session once (don't list raw paths and their normalized derivatives as separate entries).
- **Cold-reader rule.** The skim band (overview goal/summary, end_state, step titles, takeaways) must be self-contained for a stranger: every proper noun, acronym, codename, tenant, or milestone label is expanded at first skim-band use ("QC (the Quadball Canada tenant)", "D3 (Deliverable 3: live provisioning)") or cut. Codenames and phase labels appear only after the thing they name is established; if `meta.scope` promises a range (e.g. prod-v6 → prod-v10), the takeaway sequence accounts for both ends; avoid label collisions across steps. After assembly, run `extract_altitude_slices.py` and re-read the skim slice as a stranger before rendering.
- **Glossary carries the cold-reader rule below the skim band — and ~every walkthrough ships one.** The skim band expands every term inline at first use (rule above); body prose (claims, decisions, gotchas, intents) gets a top-level `glossary` instead: the viewer turns matching terms into hover tooltips, so the expansion follows the reader to every later occurrence without re-spelling it. Emit an entry for every acronym, codename, or project shorthand the cold-reader rule forced you to expand, plus the load-bearing file paths a new teammate would ask about — give those a `file` so the tooltip links to the source (GitHub when `meta.repo` is set, the local editor otherwise). Keep `definition` to one or two sentences, use `aliases` for variant spellings, and only define terms that actually appear in prose — the gate warns on dead entries, and warns when the glossary is missing entirely. Teammate/onboard audiences want a fuller glossary (roughly 10-30 entries); me-refresh still gets one, scoped to genuinely external jargon. See schema → Glossary.
- **Prose links are first-class — never post-process the HTML to add them.** The viewer hyperlinks narrative prose automatically: (1) repo-relative path tokens (`infra/live/dev`, `.github/workflows/infra.yml`, `scripts/ci/check-iam-authority.sh`, `justfile`) become GitHub `blob`/`tree` links from `meta.repo` + branch with zero authoring; (2) `meta.link_map` (`{ "<token>": "<repo-relative-path>" }`) links bare unit/module identifiers that are not literal paths (e.g. `project-foundation` → `infra/live/dev/project-foundation`); (3) inline markdown `[label](https://…)` anywhere in prose renders as a real anchor — the general escape hatch for ANY link (Confluence, Jira, dashboards). `meta.link_mode` picks the target: `"github"` (default when `meta.repo` is a GitHub repo), `"editor"` (local `cursor://`), or `"off"` (paths/identifiers plain; explicit markdown links still render). Links never wrap inside code/diffs/commands/glossary terms, and never nest. If you find yourself wanting a link, add it via the JSON + re-render — do not hand-edit `walkthrough.html`. See schema → Prose links.
- Every step needs at least one grounded claim with source_refs.
- **Evidence is verbatim or absent.** A `diff_hunks` entry carries actual before/after code copied from the session — never a prose description, a comment-annotated summary ("// FINDING: …"), or a plan-markdown excerpt standing in for the change. If only prose survives in the summaries, write a claim with a source_ref instead of a fake hunk; a reader who descends and finds paraphrase trusts the whole artifact less. Commands are reproducible invocations, not descriptions ("diff -q dev vs prod" is a paraphrase; the actual command line is evidence). And weight evidence by claim importance: the artifact's centerpiece claim gets its strongest hunks — the biggest claim must never be the least evidenced.
- **Claims never outrun their evidence.** A claim's strength matches the band below it: if the constraint says "PASSED (partial)", the step's claim says partial too — softening downstairs and rounding up upstairs is the honesty gloss reviewers catch first. Distinct claims cite distinct evidence: hanging two unrelated assertions off the same single line reads as citing a summary blob, not selecting proof. `confidence: "inferred"` is for genuine inference — a concrete observed event should be grounded or cut, and a positive diligence claim ("every doc was security-scanned") with no evidence is padding, not inference. Speculative cost-accounting ("would likely have cost the sprint") gets cut unless something in the session supports it.
- The overview.goal should be one sentence a stranger could understand.
- **Distinct framings.** `overview.goal`/`summary` (journey) and `end_state.goal`/`summary` (destination) must not restate the same bullets: the journey framing names the problem and the transformation; the end-state framing names the destination as a noun phrase. If the two goals could swap unnoticed, rewrite one. An "at a glance" step that merely re-expands `overview.end_state` is cut or tagged `"mode": "end-state"`.
- **Almost every walkthrough carries an architecture diagram** — anything multi-component does, in either architecture (in the Descent, the first destination-tour step anchors on it). Author a real LikeC4 model (a `diagrams/` folder with a `.c4` file beside the walkthrough JSON), then ship it twice: static theme-matched exports in `overview.diagram_image` (`likec4 export png diagrams --theme light --flat -o media/diagrams`, and `--theme dark`), and the **interactive embed** in `overview.diagram_likec4` (`likec4 codegen webcomponent diagrams -w c4 -o media/diagrams/likec4-views.js`, then `{ "views_js": "media/diagrams/likec4-views.js", "view": "index" }`) so readers can pan, zoom, and click into nested views. Give a step its own `diagram` + `diagram_likec4` (+ `diagram_caption`) when one component cluster deserves a dedicated view — one model, many views, one shared bundle. The static export is the print/bundle-missing fallback, so always provide both. By default the bundle is inlined into the HTML, so the artifact stays a **single self-contained file** (`"embed": false` switches to a sidecar — then ship `media/` alongside); keep `diagrams/` next to the JSON for provenance either way. Resolve paths relative to `meta.repo_root` first, then the walkthrough JSON directory. Mermaid/source diagrams are fallback-only via `overview.diagram_mermaid`. The gate warns when no diagram is present at all, and when an embed lacks its static sibling.
- If the diagram is too tiny to read (for example, only a few nodes in one line), remove it or expand it before rendering. A real LikeC4 view is usually better than inventing a small Mermaid diagram.
- **Height budget: a step reads in at most ~two laptop screens; the overview cover in ~1.2 screens of prose** (goal + summary bullets — the gate measures exactly those). The overview renders as a cover page: thesis, bullets, video, stats, jump grid, key files, reasoning maps. The diagram plus `end_state.architecture`/`constraints` render on a synthesized **"The system today"** section between the overview and step 1 (own TOC entry, nothing extra to author), so system-reference volume never bloats the cover. The viewer clamps overflowing zones (claims, callouts, constraints, reasoning maps) behind a "Show more" control, but the clamp is the safety net, not the design: when the gate warns that a step is over budget, first tighten to plain language, then demote detail down a rung (claims → evidence), then split the step. A step that carries a video gets a *smaller* prose budget, not the same one (see step 7d).
- Decisions and errors_encountered are high-value reasoning — the renderer shows them in the overview reasoning map and in the always-visible step narrative band (not inside the collapsed evidence), so write them as standalone but **non-duplicative** insights a scanning reader should catch (see "One fact, one rung"). Map entries are one-liners: the statement links to the step callout that carries the rationale or fix, so the statement itself must stand alone. Put the most important decision/gotcha first in each step; the overview map samples across steps before taking second items from any one step, hides overflow behind a collapsed "show more" control, and links directly to the matching callout.
- The rendered step is an altitude ladder: `title` → `takeaway` (gist) → `intent` (why) → claims + decisions + gotchas (visible narrative) → `evidence` diffs/commands/screenshots (collapsed proof, expand on demand). Put each fact at the altitude that matches how much a reader needs it.

**View modes (end-state vs journey)**: the viewer has a header toggle between an **End State** view (just where the work landed) and a **Journey** view (how we got there). Tag content with a `mode` so each view reads well — this is an editorial decision, like step grouping:

- Add `"mode": "journey"` to whole steps that are pure path/process (the thing you replaced, an ideation detour, a deploy chore, a throwaway experiment) — they vanish in End State.
- Add `"mode": "end-state"` to a step that is a redundant recap in the full story (e.g. an "at a glance" summary that journey readers don't need up front).
- Leave architecture/result steps as `both` (the default) — they belong in both views.
- For a **mixed** step (a pivot whose *outcome* is the end state but whose *struggle* is the journey), keep the step `both` and tag the individual `claims` — `"mode": "journey"` on the "how we struggled" claims, `both` on the claims that describe the final shape.
- `decisions` default to `both`; their `alternatives_considered` are auto-hidden in End State (forks-not-taken are journey detail). `errors_encountered` (gotchas) default to `journey`; tag a gotcha `"mode": "both"` only when it is a *live, current* constraint (e.g. a Node version pin), so it survives into End State.
- Write `overview.end_state = { goal, summary }` so the overview hero/deck title has a destination-first framing in End State; `overview.goal`/`summary` stay the journey framing. Apply the **skim test** to *both* framings: the End State `summary` should read as a coherent description of the final system; the journey `takeaway` lines should read as the coherent story.
- Give `end_state.architecture` entries every step that details the component — `"step_refs": ["step-3", "step-5"]` (legacy single `step_ref` still works) — so descent from a component card never lands one step short. Write `end_state.constraints` entries as `{ "text": "...", "step_ref": "step-id" }` when a step substantiates the constraint; a constraint with no step beneath it should usually become or cite one.
- **Constraints carry the operational truth — and are exempt from the brevity bias.** `end_state.constraints` is the block returning authors and reviewers read first; thin it and destination clarity collapses. State what is proven vs unproven *with the measured numbers* ("p99 < 200ms is proven only to ~1,000 TPS; 50k TPS remains unproven"), environment caveats ("verified against Square sandbox, not live card processing"), pinned versions/literals tests depend on, deferred roadmap items by name, and live costs ("min-instances=1, ~$9.60/mo"). Likewise give `end_state.summary` a measured-truth bullet when the work produced hard numbers. Compression budget comes out of step prose, never out of this block.

See `references/walkthrough-schema.md` → *View modes* for the full table and defaults.

For large sessions (15+ draft steps), use Opus (`model: "opus"`) for editorial assembly — it handles complex compression (e.g. 276→15 steps) significantly better than Sonnet.

Write the result to `out/walkthrough.json`. Validate it has all required fields per the schema. Include `meta.repo_root` set to the project's absolute path so cursor:// and vscode:// editor links work correctly in the rendered HTML.

Run the finished-walkthrough quality gate before rendering or sharing:

```bash
python3 scripts/validate_walkthrough_quality.py \
  --input out/walkthrough.json \
  --max-steps 12
```

If this fails, the artifact is still a draft. Re-edit instead of rendering a final HTML. The common failures are exactly the ones readers notice: `chunk-001: N events` titles, missing takeaways, no grounded claims, too many uncompressed steps, or non-reader-facing files like `/tmp`, `.env`, worklogs, or `~/.claude/plans` in overview key files. `merge_summaries --allow-fallback` is acceptable for an intermediate draft, but fallback chunk summaries must not survive into the final walkthrough.

The gate also verifies **source-ref integrity**: every cited `session_path` must exist on disk (resolved relative to the walkthrough JSON's directory, then `meta.repo_root`, then the cwd) and every line range must be within the file's bounds — dangling refs are the fastest way to lose a reader's trust on descent. Pass `--no-fs-refs` to downgrade these to warnings when validating off the producing machine. It warns on provenance smells: refs not declared in `meta.sessions`, spans over 200 lines (select evidence, don't partition the transcript), one identical range cited by 3+ claims, an all-grounded confidence monoculture (20+ claims), and a missing `overview.end_state`. It lints the `glossary` (warnings only): missing entirely, malformed or duplicate entries, definitions over 300 chars, `file` paths that don't resolve, dead terms that never appear in reader-facing prose, and more than 50 entries. And it enforces the **defaults and the height budget** as warnings: no architecture diagram anywhere, a step estimated over ~two laptop screens, an overview cover over ~1.2 screens of prose (goal + summary; the system reference renders on its own section and is not counted), a video step that kept its full prose load, `video` src/poster paths that don't resolve, and `diagram_likec4` embeds that are malformed, point at a missing bundle, or lack a static export sibling. Treat the height warnings as editing instructions, not noise — the viewer will clamp, but a clamped step is a step that needed editing. The gate **binds at render time**: `render_html.py` refuses to render a failing walkthrough unless given `--allow-draft`.

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

### 7d. Hyperframe Video (optional)

A walkthrough can carry short rendered videos — a 60–120s overview tour, or a per-step explainer for the one step that benefits from motion (an architecture build-up, a before/after). Videos are produced with **HyperFrames** (HTML-as-video: GSAP timelines + `data-*` timing attributes, rendered to mp4 by a CLI) and attached via the schema's `video` fields.

> **Prerequisite — this part needs the HyperFrames skills installed.** Anyone using this skill must first run:
>
> ```bash
> npx skills add heygen-com/hyperframes
> ```
>
> which installs the `hyperframes` skill family (composition authoring, CLI dev loop, media preprocessing). If the skills are not installed or `npx hyperframes` is unavailable, skip this step entirely — video is an enhancement, never a dependency.

**The displacement rule**: a video is not decoration on top of the prose — it *replaces* prose. When the overview carries a tour video, cut the summary to the 3 bullets the video can't carry (measured numbers, integrity caveats); when a step carries a video, its visible band shrinks to the takeaway, the intent, and the few claims that need to be quotable/searchable as text. Numbers and caveats always survive in text (video is unsearchable and unskimmable); connective narration moves into the video. The gate warns when a video step keeps ~full prose height.

**Authoring flow** (follow the `hyperframes` skill for composition rules):

1. Scaffold an isolated project: `npx hyperframes init out/<ns>/media-project` (keep it inside the walkthrough namespace; never at the repo root).
2. Write the composition from `walkthrough.json` content — the artifact is the script: `overview.goal` → title card; the five takeaways/answers → one beat each; measured numbers → stat scenes; the headline constraint/integrity caveat → its own card (honesty survives in the video too). Use the walkthrough's accent palette for a `design.md` so the video matches the HTML reader.
3. Verify and render:
   ```bash
   npx hyperframes lint && npx hyperframes validate
   npx hyperframes inspect
   npx hyperframes render --output ../media/overview.mp4
   ```
4. Attach to the walkthrough JSON and re-render the HTML:
   ```json
   "overview": { "video": { "src": "media/overview.mp4", "poster": "media/overview-poster.png", "caption": "90-second tour of what was built and what is proven" } }
   ```
   Steps take the same object as `step.video`. Paths resolve like diagrams (`meta.repo_root`, then the JSON's directory). By default the renderer links the mp4 by a path relative to the output HTML, so **ship the `media/` folder alongside `walkthrough.html`** when sharing — or add `"embed": true` to inline the bytes (base64, ~33% larger) and keep the artifact one self-contained file. Embed short tours (the gate warns above ~15 MB); leave long captures as sidecars.
5. Optional: TTS narration + synced captions via the `hyperframes-media` skill (`tts` → `transcribe` → captions), when the walkthrough will be consumed away from a desk.

> **QA the mp4 like a reader, not like a compiler.** `lint`/`validate`/`inspect` all passing does not prove the video reads well. Two checks caught real defects on the first production run:
> - **Frame extraction**: `for t in 5 20 35 50 65 78; do ffmpeg -ss $t -i overview.mp4 -frames:v 1 /tmp/f-$t.png; done` — a near-empty frame shows up as a tiny PNG (a solid-background frame is ~9KB vs ~250KB for content). The first render had a 2s fully-blank scene boundary: every scene's entrance started >1.2s after its transition began, leaving the incoming scene visible but empty.
> - **The animation map** (`hyperframes` skill → Animation Map) reports dead zones outright — the same render had six. Entrances should land 0.3–0.6s after a transition starts, and a scene's body should follow its title within ~1s.

### 8. Rendering

```bash
python3 scripts/render_html.py \
  --input out/walkthrough.json \
  --output walkthrough.html \
  --normalized out/normalized.jsonl \
  --captures-manifest out/captures/manifest.json
```

If `python3` lacks jinja2/pygments, substitute `uv run scripts/render_html.py ...` — the script's inline metadata resolves them in an isolated environment (see Setup).

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
- `references/walkthrough-architectures.md` — The two step architectures (Journey arc vs the Descent) + selection rule

## Scripts

All scripts are available as `uv run` commands via entry points (e.g., `uv run walkthrough-validate`), or directly as `python3 scripts/<name>.py`.

| Script | Entry Point | Purpose | Input | Output |
|--------|------------|---------|-------|--------|
| `check_setup.py` | `walkthrough-doctor` | First-run environment check | none | Readiness report |
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
| `validate_walkthrough_quality.py` | `walkthrough-quality` | Final editorial quality gate | walkthrough.json | pass/fail report |
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
