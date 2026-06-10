# Walkthrough Skill — Restructure Plan
Status: **draft for review**. Nothing edited yet. Comment inline (Roughdraft CriticMarkup) and I'll revise before touching any files.
## Goal
Two coordinated changes:

1. **Portable restructures** (Codex's suggestions) — land in `SKILL.md` + scripts + schema. These help **every** runtime (Codex, OpenCode, Claude Code). They are the baseline.
  
2. **Guarded dynamic-workflow branch** — a capability-aware option in `SKILL.md`, sitting alongside the existing `Claude Code → parallel` / `Codex → sequential` branches, that offers to run the fan-out as a dynamic multi-agent workflow **when the runtime supports it and the run is large**. A no-op where workflows don't exist.
  

The two reinforce each other: the **brief** becomes the workflow's contract (`args`), and the **outline gate** is the workflow's interactive boundary. We implement the restructures in a _workflow-ready shape_ so the workflow is a drop-in execution swap — not a fork.

**Design constraint honored throughout:** the skill stays portable and capability-agnostic. The workflow branch is always conditional ("if your runtime supports…"), never a hard dependency. The deterministic Python backbone is identical on every platform; only the orchestration layer of the fan-out steps varies.

* * *
## Part A — Portable restructures (everyone)
### A1. Brief contract — `out/<ns>/brief.json`
After the step-1 scoping dialog, persist the reader frame to a small JSON file **before** discovery, so every downstream stage reads one durable contract instead of re-deriving intent.

```json
{
  "audience": "teammate",
  "detail_level": "both/toggleable",
  "purpose": "review",
  "scope": "auth module rewrite",
  "media_mode": "none",
  "max_steps": 10
}
```

- Lives in the per-walkthrough namespace (respect the existing `out/` clobber gotcha).
  
- Consumed by: relevance gate (A2), editorial assembly (A3/recipes), the quality gate (A5), and `meta` in the final `walkthrough.json`.
  
- **On Claude Code this object is the workflow's** `args` — one contract every stage receives, which directly closes the "the pipeline doesn't enforce the brief" gap.
  
### A2. Relevance gate — select before summarizing
Today the pipeline summarizes every chunk and relies on the editor to cut later → overwhelm at the source. Add explicit relevance scoring against the brief so low-signal material is dropped **before** expensive summarization.

- **This extends what already exists.** Step 2 already has "subagent-assisted discovery" that scores sessions for relevance. We make that scoring **brief-driven** (pass `brief.json`) and add an optional second, finer gate at the chunk level.
  
- **Two altitudes:**
  
  - _Session-level_ (cheap, from `session-cards.json`): drop whole irrelevant sessions before normalize/chunk. Biggest compute saving.
    
  - _Chunk-level_ (optional, finer): score each chunk against the brief and skip full summarization for low-signal chunks. Natural as workflow **stage-0**.
    
- **No silent truncation:** whatever is dropped gets logged and feeds the omissions list (A6). User still confirms the session shortlist (existing step 2).
  
### A3. Outline gate
Before writing `walkthrough.json`, produce a short outline and (for ambiguous / high-stakes runs) confirm it with the user:

- one-sentence **frame** ("for `<audience>`, at `<detail_level>`, to `<purpose>`, covering `<scope>`"),
  
- the **proposed steps** (titles + one-line takeaways, within the recipe's target count),
  
- **what's intentionally omitted** and **why this slice is enough**.
  

This is the interactive boundary: the batch middle (relevance → summarize → synthesize) ends by _proposing_ an outline; the human-in-the-loop confirms; then final assembly runs. On Claude Code, the workflow returns the outline and the main loop owns the gate.
### A4. Purpose recipes
Consolidate the currently-scattered "guidelines by audience / purpose / detail" into one explicit recipe table, keyed primarily by **purpose**, with audience/detail as modifiers. Wire it into the brief and the validator.

| purpose | step target | claim density | evidence depth | emphasis |
| --- | --- | --- | --- | --- |
| **onboard** | 4–7 | low–med | shallow diffs | concept map, ownership boundaries, where to start reading |
| **understand** | 5–10 | medium | medium | final outcomes, pivots, just-enough implementation |
| **review** | 6–10 | high | deep (tests, edge cases) | decisions, risks, test evidence, unresolved questions |
| **self-refresh** | 4–7 | low | shallow | what changed and why; skip obvious context |

Detail level still controls **depth, not breadth** (existing rule). "both/toggleable" keeps the visible skim path high-level and pushes depth into claims/decisions/collapsed evidence — it does **not** double the step count.
### A5. Focus validation — extend `validate_walkthrough_quality.py`
Add brief-conformance + focus checks (optional new inputs: `--brief out/<ns>/brief.json`, `--chunks out/chunks/manifest.json`):

- **require** `meta.audience`, `meta.purpose`, `meta.detail_level`, `meta.scope` (and match `brief.json` when provided) — _fail_
  
- cap **claims per step** — _warn_ > 6, _fail_ > 10 (tunable)
  
- cap **overview.key_files** — _warn_ > 8
  
- **warn** on excessive commands/screenshots per step
  
- "**every chunk became a step**" heuristic: _fail_ if `len(steps) >= 0.8 * num_chunks` (only when `--chunks` provided)
  
- **fail/warn** on file-level or `chunk-NNN` step titles (already partly covered)
  
- step count over the recipe's target → _warn_ (nudge, not hard fail)
  
### A6. Omissions field
Make deliberate omission first-class so the agent feels licensed to cut.

- Schema: add `overview.omissions: string[]` (e.g. `["routine dependency bumps", "a failed Redis experiment", "setup churn"]`).
  
- Populated by synthesis/assembly + fed by what the relevance gate dropped.
  
- Surfaced at the outline gate; rendered **subtly** in the HTML (a small "Intentionally not covered" note in the overview — not a prominent block).
  
### A7. Skim vs technical depth (lowest priority)
Mostly already handled by the End State/Journey toggle + altitude ladder + collapsed evidence. For "both/toggleable," reinforce the convention (depth → claims/decisions/gotchas/collapsed evidence, not more steps). Possible small addition: an optional per-step "deep dive" collapsible. **Candidate to defer** to a follow-up.

* * *
## Part B — Guarded dynamic-workflow branch (SKILL.md)
Add a third, capability-guarded option to **Step 5 (Chunk Summarization)**, next to the existing Claude/Codex branches. Proposed wording (red-line this):

> **Dynamic workflow (only if your runtime supports it).** If your runtime offers dynamic multi-agent orchestration (e.g. Claude Code's `Workflow` tool) **and** the run is large (multiple sessions or ≳8 chunks), consider running steps 2.5–6 (relevance → summarize → synthesize) as one workflow:
> 
> - the brief (`out/<ns>/brief.json`) is the workflow's `args` — one contract every stage receives;
>   
> - each chunk is summarized by a **schema-returning agent**, so the validated summary comes back **in-band** (this removes the "did the subagent actually write the file?" verification dance entirely);
>   
> - sessions **pipeline** into synthesis (session A synthesizes while session B is still summarizing — no global barrier);
>   
> - the workflow returns session summaries **+ a proposed outline** for the gate (A3), then stops. Final editorial assembly stays interactive in the main loop.
>   
> 
> **When to offer vs. just do it:** if a session-level "ultracode" mode is already on, run the workflow by default (it is already opted in). Otherwise _offer_ it to the user first — their "yes" is the opt-in. **Fall back** to the parallel (Claude Code) / sequential (Codex) paths above when workflows are unavailable or the run is small (e.g. the ≈1-chunk meta walkthrough).

Notes:

- "dynamic workflow" ≠ "ultracode": a dynamic workflow is one self-paced orchestration run; ultracode is the session mode that makes workflows the default. The branch keys off _workflows available + run is big enough to pay off_, and treats ultracode-on as "already yes."
  
- The branch names the capability **conditionally**, so Codex/OpenCode simply skip it.
  
- We will **not** ship a canned workflow `.js` asset in this pass (see open decision #6); the branch describes the shape inline.
  

* * *
## File-by-file change list
- `SKILL.md`
  
  - Step 1: write `out/<ns>/brief.json`; add it to the pipeline contract.
    
  - New **Step 2.5 — Relevance gate** (brief-driven; session-level default, optional chunk-level); describe the fan-out substrate-neutrally.
    
  - Step 5: add the guarded **dynamic-workflow** branch; note the schema-return removes the file-write footgun.
    
  - New **Outline gate** before Step 7 assembly.
    
  - Step 7: consume brief + purpose recipe; emit `omissions`.
    
  - Consolidate audience/purpose/detail guidance into the **recipe table** (A4).
    
- `scripts/validate_walkthrough_quality.py` — A5 checks; optional `--brief`, `--chunks`.
  
- `scripts/merge_summaries.py` — carry `omissions` / brief through to the draft.
  
- `references/walkthrough-schema.md` — add `overview.omissions`; document `brief.json`; make `meta.audience/purpose/detail_level/scope` required.
  
- `tests/test_validate_walkthrough_quality.py` — cover new checks; brief roundtrip.
  
- `assets/walkthrough-template.html` **+** `scripts/render_html.py` — render `omissions` subtly (small change).
  

* * *
## Sequencing / build order
1. **Brief contract (A1)** — foundation everything else reads.
  
2. **Recipes (A4) + validator (A5)** — codify the focus rules; tests.
  
3. **Relevance gate (A2)** — extend existing step-2 subagent scoring; add chunk-level option.
  
4. **Outline gate (A3) + omissions (A6)** — incl. small render change.
  
5. **Guarded workflow branch (B)** — once the stages are described substrate-neutrally, this is a tight paragraph.
  
6. **A7 skim/appendix** — only if not deferred.
  

* * *
## Open decisions (your call — please comment)
1. **Relevance altitude:** session-level only (cheap) / session **+** optional chunk-level stage-0 (finer, slightly pricier) / make it configurable. — _I lean: session default, chunk-level optional._
  
2. **Relevance mechanism:** keep it a subagent/agent judgment (extend the existing step-2 scorer) vs. add a small `filter_sessions.py` merge helper. — _I lean: agent judgment, no new script unless merging gets fiddly._
  
3. **Omissions location:** `overview.omissions[]` (renders with the overview) vs. `meta.omissions`. — _I lean:_ `overview`_._
  
4. **Recipes home:** inline table in `SKILL.md` (avoids doc sprawl) vs. new `references/walkthrough-recipes.md`. — _I lean: inline._
  
5. **Validator strictness:** which checks are hard _fail_ vs. _warn_, and the thresholds above. — _Want your tolerance._
  
6. **Ship a workflow script?** Just describe the workflow shape in the guarded branch (this pass) vs. also ship a reference `assets/walkthrough-workflow.js` + dry-run it on a real session set (follow-up). — _I lean: describe now, ship later._
  
7. **Workflow scope:** stop at the outline (assembly stays interactive — my recommendation) vs. let the workflow also draft `walkthrough.json`.
  

* * *
## Non-goals (this pass)
- Live/streaming walkthroughs, the indexed warehouse, interactive Q&A, PR/CI integration — all remain existing "Future Work," untouched.
  
- No major renderer redesign (omissions note is small; skim/appendix is mostly existing behavior).
  
- No change to the deterministic parsing/normalization/chunking scripts.
  
## Risks
- **SKILL.md bloat** (already ~580 lines). Mitigation: recipes _replace_ scattered guidance (net-neutral); keep the workflow branch to one tight paragraph; move recipe detail to a reference only if it grows.
  
- **A third orchestration branch to maintain** — accepted cost of the guarded approach; isolated to Step 5.
  
- **Relevance gating dropping real signal** — mitigation: gate conservatively, log/record drops (no silent truncation), user still confirms the shortlist.
  
- **Test churn** for the validator — expected; covered in sequencing step 2.
