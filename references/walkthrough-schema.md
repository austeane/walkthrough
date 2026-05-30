# Walkthrough JSON Schema

The `walkthrough.json` file is the primary output of the walkthrough skill. It contains a structured, evidence-backed narrative that teaches a developer what was built, why, and how.

## Top-Level Structure

```json
{
  "version": "0.1.0",
  "meta": { ... },
  "overview": { ... },
  "steps": [ ... ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Schema version (semver) |
| `meta` | object | Generation metadata |
| `overview` | object | High-level summary of what was built |
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
| `media_mode` | string | Screenshot mode: `"none"`, `"extract"`, `"capture"`, or `"both"` |

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
  "diagram_mermaid": "graph TD\n  A[Request] --> B[Auth Middleware]\n  B --> C{Valid JWT?}\n  C -->|Yes| D[Route Handler]\n  C -->|No| E[401 Response]"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `goal` | string | One-sentence description of what was accomplished |
| `summary` | array of strings | 3-7 bullet points covering the key outcomes |
| `key_files` | array of strings | Most important files that were created or modified |
| `diagram_mermaid` | string | Optional Mermaid/source diagram text showing architecture or flow. The current HTML viewer renders it as inert preformatted text for offline safety. |

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
| `takeaway` | string | One declarative outcome sentence: the broad shape of what happened. The line a reader scans to decide whether this step matters. Distinct from `title` (topic) and `intent` (why). |
| `intent` | string | What the agent was trying to accomplish and why |
| `claims` | array | Individual narrative statements with confidence levels |
| `evidence` | object | Grounded artifacts from the session logs |
| `decisions` | array | Key decisions made during this step |
| `errors_encountered` | array | Problems hit and how they were resolved |

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
5. **Proof** — `evidence` (`diff_hunks`, `commands`, `media`) renders inside a
   collapsed `<details>` with a one-line scent label, expandable on demand.

`takeaway` is optional in the renderer (older walkthroughs omit it), but the
editorial step should always write one.

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
| `diff_hunks` | array | Selected diff hunks (not full diffs) |
| `diff_hunks[].file` | string | File path |
| `diff_hunks[].before` | string | Code before the change |
| `diff_hunks[].after` | string | Code after the change |
| `commands` | array | Shell commands executed |
| `commands[].cmd` | string | The command |
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

## Evidence Rules

The walkthrough schema enforces a clear separation between narrative (claims) and artifacts (evidence):

1. **Claims are the agent's narrative.** Each claim is an individual statement tagged with a confidence level. The agent producing the walkthrough is responsible for honest confidence assessment.

2. **Evidence is deterministic.** The `evidence.*` fields (`files_changed`, `diff_hunks`, `commands`) come from the pipeline scripts, not from LLM inference. They are always grounded by construction and cannot have a confidence level other than factual.

3. **Source refs enable verification.** Every claim can point to specific line ranges in the source session logs, allowing a reader to verify the claim against the raw transcript.

4. **The HTML viewer respects confidence.** Grounded claims render normally. Inferred claims get a subtle visual indicator. Speculative claims get a visible badge so readers know to treat them with appropriate skepticism.

5. **Steps are editorial, not mechanical.** The orchestrator model decides how many steps, what grouping, and what emphasis. 100 agent actions across 5 sessions might become 8-12 steps. The goal is teaching, not transcript replay.
