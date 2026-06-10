# Walkthrough JSON Schema

The `walkthrough.json` file is the primary output of the walkthrough skill. It contains a structured, evidence-backed narrative that teaches a developer what was built, why, and how.

## Top-Level Structure

```json
{
  "version": "0.1.0",
  "meta": { ... },
  "overview": { ... },
  "glossary": [ ... ],
  "steps": [ ... ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Schema version (semver) |
| `meta` | object | Generation metadata |
| `overview` | object | High-level summary of what was built |
| `glossary` | array or object | Optional acronym/jargon definitions that the HTML viewer turns into hover/focus tooltips in narrative prose |
| `steps` | array | Ordered walkthrough steps |

## Meta

```json
{
  "generated_at": "2026-03-01T14:30:00Z",
  "sessions": [
    {
      "provider": "codex",
      "path": "/path/to/session.jsonl",
      "timestamp": "2026-03-01T10:00:00Z"
    }
  ],
  "repo": "github.com/user/project",
  "repo_root": "/Users/dev/project",
  "scope": "auth module rewrite",
  "audience": "teammate",
  "purpose": "onboard",
  "detail_level": "both/toggleable",
  "media_mode": "none"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `generated_at` | string | ISO8601 generation timestamp |
| `sessions` | array | Source sessions used |
| `sessions[].provider` | string | `"codex"`, `"claude"`, or `"opencode"` |
| `sessions[].path` | string | Path to source JSONL |
| `sessions[].timestamp` | string | Session start time |
| `repo` | string | Repository identifier (if available) |
| `repo_root` | string | Absolute path to the project root. Used by the HTML viewer to build editor links and repo-relative labels when possible. |
| `git` | object | Best-effort git metadata for the source sessions (`branch`, `commit`, `dirty`) |
| `scope` | string | User-specified scope of the walkthrough |
| `audience` | string | Target reader, e.g. `"self"`, `"teammate"`, or `"reviewer"`. Used by the editorial process, not the renderer. |
| `purpose` | string | Why the walkthrough exists, e.g. `"onboard"`, `"understand"`, or `"review"`. Used to decide what earns space. |
| `detail_level` | string | Desired depth, e.g. `"high-level"`, `"technical"`, or `"both/toggleable"`. Controls depth, not breadth. |
| `media_mode` | string | Screenshot mode: `"none"`, `"extract"`, `"capture"`, or `"both"` |

## Glossary

Use `glossary` for acronyms, product names, and project shorthand that a new teammate may not know. The HTML viewer annotates matching terms in prose after load, so normal text escaping still applies and glossary terms are not injected into code blocks, diffs, commands, links, or controls.

```json
[
  {
    "term": "WIF",
    "expanded": "Workload Identity Federation",
    "definition": "Keyless GitHub Actions authentication into GCP.",
    "aliases": ["Workload Identity Federation"]
  },
  {
    "term": "infra/root.hcl",
    "definition": "Shared Terragrunt keystone that generates backend, provider, versions, and encryption blocks for every unit.",
    "file": "infra/root.hcl"
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `term` | string | Primary acronym, jargon term, or project shorthand to annotate |
| `expanded` | string | Optional expansion shown as `term = expansion` in the tooltip |
| `definition` | string | Short explanation for a new reader |
| `aliases` | array | Optional additional spellings that use the same tooltip |
| `href` | string | Optional explicit link. When present, the rendered term is an anchor, so Cmd/Ctrl-click opens the target in a new tab. |
| `file` | string | Optional repo-relative file path. When `href` is absent, the viewer builds a GitHub `blob` link from `meta.repo` and `meta.git.branch` or `meta.git.commit`; without a usable `meta.repo` it falls back to a local editor link built from `meta.repo_root`. |
| `github_path` | string | Alias for `file` when callers want to make the GitHub intent explicit |
| `github_ref` | string | Optional branch, tag, or commit override for generated GitHub file links |
| `max_occurrences` | number | Optional cap per term per rendered view; defaults to 4 for plain terms and 20 for linked terms |

## Overview

```json
{
  "goal": "Rewrite the authentication module from session-based to JWT",
  "summary": [
    "Replaced express-session with jsonwebtoken",
    "Added refresh token rotation",
    "Updated all 12 route handlers to use Bearer auth"
  ],
  "key_files": [
    "src/auth/jwt.ts",
    "src/middleware/auth.ts",
    "src/routes/api.ts"
  ],
  "diagram_image": {
    "light": "out/diagrams/auth.light.png",
    "dark": "out/diagrams/auth.dark.png"
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `goal` | string | One-sentence description of what was accomplished |
| `summary` | array of strings | 3-7 bullet points covering the key outcomes |
| `key_files` | array of strings | Most important files that were created or modified |
| `diagram_image` | string or object | Preferred overview diagram input. Use a string path for one exported image, or `{ "light": "...", "dark": "..." }` for theme-matched LikeC4 exports. Paths resolve against `meta.repo_root`, then the walkthrough JSON directory, and are embedded as data URIs during rendering. |
| `diagram_mermaid` | string | Optional fallback source diagram text showing architecture or flow. Prefer LikeC4 image exports for new walkthroughs; the renderer uses Mermaid only when no `diagram_image` is present, and if local Mermaid rendering is unavailable, the viewer shows inert preformatted text. |
| `end_state` | object | Optional End State framing: `{ "goal": "...", "summary": [...] }`. Shown in the viewer's End State view; `goal`/`summary` remain the Journey framing and the fallback. See [View modes](#view-modes). |

The renderer also derives overview-only `_decision_index`, `_gotcha_index`,
overflow lists, `_decision_total`, and `_gotcha_total` fields from per-step
`decisions` and `errors_encountered`. The visible overview map samples across
steps before taking second items from any one step; overflow stays available
behind collapsed "show more" controls, and each item links to the matching
decision/gotcha callout. Authors should not write those private fields directly;
make the first decision/gotcha in each step the one a scanning teammate should
see first.

## Steps

Each step represents a logical unit of work in the walkthrough. Steps are ordered for narrative clarity, not necessarily chronologically.

```json
{
  "id": "step-1",
  "title": "Replace session store with JWT infrastructure",
  "takeaway": "Auth now signs and verifies JWTs; the Redis session store is gone.",
  "intent": "The agent needed to remove the Redis-backed session dependency and establish JWT signing/verification as the new auth primitive.",
  "claims": [ ... ],
  "evidence": { ... },
  "decisions": [ ... ],
  "errors_encountered": [ ... ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique step identifier (`step-1`, `step-2`, ...) |
| `title` | string | Short, descriptive title (the topic) |
| `takeaway` | string | One declarative outcome sentence: the broad shape of what happened. The line a reader scans to decide whether this step matters. Distinct from `title` (topic) and `intent` (why). **Grammar:** one outcome per line (never weld two *unrelated* outcomes), but DO weld the outcome to its cause — "outcome — which is why…" is the template; length serves causality, not brevity. The weld is one cause, not a clause chain: caveats, second outcomes, and evidence-rung detail move down a rung; a takeaway that needs a second read to parse must be untangled. Never restate the title — and cover every noun the title promises. Journey steps lead with the durable payload, not activity narration. The takeaway sequence must read as a causal chain with no holes. |
| `intent` | string | What the agent was trying to accomplish and why |
| `claims` | array | Individual narrative statements with confidence levels |
| `evidence` | object | Grounded artifacts from the session logs |
| `decisions` | array | Key decisions made during this step. Canonical entries are objects with `decision`, optional `rationale`, and optional `alternatives_considered`; the renderer tolerates legacy string entries. |
| `errors_encountered` | array | Problems hit and how they were resolved. Canonical entries are objects with `error` and optional `resolution`; the renderer tolerates legacy string entries. |
| `mode` | string | Optional view tag: `"end-state"`, `"journey"`, or `"both"` (default). Controls whether the step appears in the viewer's End State view, Journey view, or both. See [View modes](#view-modes). |
| `end_state_order` | integer | Optional. Position of this step in the **End State view** only (Journey stays chronological). See [Per-view step ordering](#per-view-step-ordering). |

### The altitude ladder

Each step is rendered as a descent through altitudes, so a reader can stop at
whatever depth they need:

1. **`title`** — the topic (also the TOC and jump-grid label).
2. **`takeaway`** — the gist, as a prominent lead. **Skim test:** the sequence
   of `takeaway` lines read alone should form a complete summary of the whole
   session. If it does not, the steps need re-editing.
3. **`intent`** — the why / context.
4. **Narrative** — `claims` (with confidence), plus `decisions` and
   `errors_encountered`. These render in the always-visible band: decisions and
   gotchas are reasoning, not raw artifacts, so they are never buried.
   **One fact, one rung:** claims carry what changed, decisions carry why plus
   alternatives, gotchas carry symptom plus resolution — none re-narrates
   another. A bug's root cause lives in the claim or the decision rationale,
   never both.
5. **Proof** — `evidence` (`diff_hunks`, `commands`, `media`) renders inside a
   collapsed `<details>` with a one-line scent label, expandable on demand.

`takeaway` is optional in the renderer (older walkthroughs omit it), but the
editorial step should always write one. When it is missing, overview jump cards
fall back to `intent` or the first claim so old drafts remain navigable; the
quality gate still fails final artifacts that omit `takeaway`.

### Claims

Claims are the narrative content of each step, broken into individual statements with confidence tracking.

```json
{
  "text": "The old system used express-session with a Redis store for auth state",
  "confidence": "grounded",
  "source_refs": [
    {
      "session_path": "/path/to/session.jsonl",
      "line_start": 142,
      "line_end": 145
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `text` | string | The claim statement |
| `confidence` | string | Confidence level (see below) |
| `source_refs` | array | References to source log lines |
| `mode` | string | Optional view tag (`end-state` / `journey` / `both`, default `both`). Lets a `both` step keep its end-state claims while hiding its "how we got here" claims in the End State view. See [View modes](#view-modes). |

#### Confidence Levels

| Level | Meaning | HTML Rendering |
|-------|---------|----------------|
| `grounded` | Directly evidenced in the session logs. The claim can be verified by reading the referenced source lines. | Rendered normally, no special indicator |
| `inferred` | A reasonable conclusion drawn from context. Not directly stated in logs but logically follows from the evidence. | Rendered with a subtle visual indicator |
| `speculative` | Editorial or predictive statement. The agent's judgment without direct evidence. | Rendered with a visible "speculative" badge |

### Evidence

Evidence fields contain artifacts extracted deterministically from session logs by the pipeline scripts. They are always grounded by construction.

```json
{
  "files_changed": [
    "src/auth/jwt.ts",
    "src/middleware/auth.ts"
  ],
  "diff_hunks": [
    {
      "file": "src/auth/jwt.ts",
      "before": "import session from 'express-session';",
      "after": "import jwt from 'jsonwebtoken';"
    }
  ],
  "commands": [
    {
      "cmd": "npm test",
      "status": "pass",
      "summary": "All 42 tests passed after JWT migration"
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `files_changed` | array of strings | File paths modified in this step |
| `diff_hunks` | array | Selected diff hunks (not full diffs). `before`/`after` carry verbatim code from the session — never prose descriptions or annotated summaries. If only prose survives, write a claim with a `source_ref` instead of a paraphrased hunk. |
| `diff_hunks[].file` | string | File path |
| `diff_hunks[].before` | string | Code before the change (verbatim) |
| `diff_hunks[].after` | string | Code after the change (verbatim) |
| `commands` | array | Shell commands executed |
| `commands[].cmd` | string | The command — a reproducible invocation, not a description of one |
| `commands[].status` | string | `"pass"` or `"fail"` |
| `commands[].summary` | string | Brief description of the outcome |
| `screenshots` | array | Legacy screenshot references. The renderer bridges these into `media` and should not double-count them in the UI. |

### Media

```json
"media": [
  {
    "id": "media-001",
    "type": "screenshot",
    "data_uri": "data:image/jpeg;base64,...",
    "path": "out/captures/commit-abc123-index.png",
    "caption": "Login page after adding OAuth buttons",
    "source_ref": {"session_path": "...", "line_start": 42, "line_end": 42},
    "group": "login-redesign",
    "group_role": "after",
    "width": 800,
    "height": 600
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique media ID across the walkthrough |
| `type` | string | `"screenshot"` (future: `"video"`) |
| `data_uri` | string | Base64 data URI (JPEG, max 200KB each). Optional pre-render; renderer can populate this. |
| `path` / `file_path` | string | Optional local image path for deferred media resolution at render time |
| `caption` | string | Describes what the screenshot shows |
| `source_ref` | object | Points to session log line where captured |
| `group` | string | Groups related media (e.g., "login-page") |
| `group_role` | string | `"before"`, `"after"`, or `"standalone"` |
| `width` | number | Image width in pixels |
| `height` | number | Image height in pixels |

### Decisions

```json
{
  "decision": "Use RS256 algorithm instead of HS256 for JWT signing",
  "rationale": "RS256 allows public key verification without sharing the signing secret, better for microservice architecture",
  "alternatives_considered": [
    "HS256 — simpler but requires shared secret across services",
    "ES256 — smaller signatures but less library support"
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `decision` | string | What was decided |
| `rationale` | string | Why this choice was made |
| `alternatives_considered` | array of strings | Other options that were evaluated |

### Errors Encountered

```json
{
  "error": "JWT verification failed with 'invalid signature' on refresh token endpoint",
  "resolution": "The refresh token was being signed with a different key pair. Unified all signing to use the same RSA key.",
  "evidence_ref": {
    "session_path": "/path/to/session.jsonl",
    "line_start": 350,
    "line_end": 380
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `error` | string | Description of the problem |
| `resolution` | string | How it was fixed |
| `evidence_ref` | object | Reference to the relevant log section |

## View modes

The HTML viewer has a header toggle with two reader views:

- **End State** — just where the work landed: the final architecture and result.
- **Journey** — how we got there: the chronology, the pivots, the dead-ends.

The reader's choice is remembered (localStorage); the viewer opens in **End State**
on a first visit. Every step, claim, decision, and gotcha may carry an optional
`mode`:

| Value | Shows in End State | Shows in Journey |
|-------|:---:|:---:|
| `both` (default for steps/claims/decisions) | ✓ | ✓ |
| `end-state` | ✓ | — |
| `journey` (default for gotchas) | — | ✓ |

Defaults are chosen so an un-tagged walkthrough still behaves sensibly:

- **Steps / claims / decisions** default to `both`.
- **`errors_encountered` (gotchas)** default to `journey` — a problem hit-and-fixed
  is by nature "how we got here". Tag a gotcha `"both"` (or `"end-state"`) when it is
  really a *live, current* constraint (e.g. "pinned to Node 22 because newer Node
  segfaults"), so it survives into the End State view.
- **`alternatives_considered`** on a decision are always hidden in End State — the
  forks not taken are journey detail. The decision and its rationale stay visible.
- A step pinned to one view forces all of its items into that view.

```json
{
  "id": "step-6",
  "title": "Picking the sandbox engine",
  "mode": "both",
  "claims": [
    { "text": "isolated-vm enforces a hard memory limit.", "confidence": "grounded" },
    { "text": "A QuickJS-WASM spike went red first.", "confidence": "grounded", "mode": "journey" }
  ],
  "errors_encountered": [
    { "error": "Segfaults on Node 25; pinned to Node 22.", "resolution": "...", "mode": "both" }
  ]
}
```

### Overview framing per view

`overview.goal` and `overview.summary` are the **journey** framing (and the fallback
when no end-state framing is supplied). Add `overview.end_state` to give the End State
view its own, destination-first framing:

```json
"overview": {
  "goal": "Decide whether to standardize on X — by walking the path that led there.",
  "summary": ["We started on …", "We then …", "Finally we …"],
  "end_state": {
    "goal": "X is two services stamped from one multi-tenant engine.",
    "summary": ["Two Cloud Run services …", "One engine, per-tenant profiles …"],
    "architecture": [
      { "component": "Surface", "summary": "Five verbs over one engine.", "step_ref": "step-8" },
      { "component": "Boundary", "summary": "Two services; the gateway authors provenance.", "step_ref": "step-3" }
    ],
    "constraints": ["Executor is Node-pinned for the native binary.", "Egress enforcement deferred to R1."]
  }
}
```

When `end_state` is present the viewer renders both framings (hero + deck title) and
shows the one matching the active view; when absent, the journey framing is used in
both. The overview stat counts and reasoning maps recompute to the active view.

**Distinct framings:** the journey `goal`/`summary` and the end-state `goal`/`summary`
must not restate the same bullets. The journey framing names the problem and the
transformation; the end-state framing names the destination as a noun phrase. If the
two goals could swap unnoticed, rewrite one.

`end_state` also accepts two optional fields that build a **destination-first reference**
for readers who skip the chronology, both rendered in the End State view only:

| Field | Type | Notes |
| --- | --- | --- |
| `architecture` | array | A "How it works today" component panel. Each entry is `{ "component": "...", "summary": "...", "step_refs": ["step-id", ...] }` — list **every** step that details the component so descent never lands one step short (legacy single `step_ref` still accepted; a single ref makes the whole card clickable, multiple refs render one link per step). Organize by system part, not by time. |
| `constraints` | array | A "Current constraints" list — live limitations/roadmap items only (not historical gotchas). Entries are strings or `{ "text": "...", "step_ref": "step-id" }`; the ref renders as a link to the step that substantiates the constraint. A constraint no step substantiates should usually become or cite one. **This block carries the operational truth of the destination and is exempt from the brevity bias**: proven-vs-unproven with measured numbers, environment caveats (sandbox vs live), pinned versions/literals, deferred roadmap items, live costs. |

### Per-view step ordering

By default both views show steps in authored (chronological) order. Add `end_state_order`
(an integer) to any step to give the **End State view** a different reading order — so it
can read as a reference (what → how → tradeoffs) while the Journey view stays chronological.
Steps without `end_state_order` trail in authored order (typically `mode: "journey"` steps,
which are hidden in the End State view anyway). Ordering activates only when at least one
step sets `end_state_order` — otherwise both views use authored order, unchanged.

```json
{ "id": "step-8", "title": "The surface", "mode": "both", "end_state_order": 2 }
```

## Evidence Rules

The walkthrough schema enforces a clear separation between narrative (claims) and artifacts (evidence):

1. **Claims are the agent's narrative.** Each claim is an individual statement tagged with a confidence level. The agent producing the walkthrough is responsible for honest confidence assessment.

2. **Evidence is deterministic.** The `evidence.*` fields (`files_changed`, `diff_hunks`, `commands`) come from the pipeline scripts, not from LLM inference. They are always grounded by construction and cannot have a confidence level other than factual.

3. **Source refs enable verification.** Every claim can point to specific line ranges in the source session logs, allowing a reader to verify the claim against the raw transcript.

4. **The HTML viewer respects confidence.** Grounded claims render normally. Inferred claims get a subtle visual indicator. Speculative claims get a visible badge so readers know to treat them with appropriate skepticism.

5. **Steps are editorial, not mechanical.** The orchestrator model decides how many steps, what grouping, what emphasis, and what to omit. 100 agent actions across 5 sessions might become 5-10 steps. The goal is teaching for a specific reader and purpose, not transcript replay.
