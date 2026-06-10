# Time-to-Grok Optimization Workflow — Plan
Status: **draft for review, rev 2**. Rev 1's knowledge-quiz fitness function is replaced by a holistic judge panel (quiz grading measures the reader-agent's recall as much as the artifact, and agent attention profiles don't match human skimming). Comment inline (Roughdraft CriticMarkup) and I'll revise, then launch.
## What "optimize it" means here
Assumption stated up front: **"it" is the walkthrough product** — the pipeline + editorial rules + renderer that produce `walkthrough.html`. The two metrics are properties of the _reader experience_ of the artifacts it produces:

- **Time to high-level understanding** — how fast a cold reader gets "what is this system / where did the work land?" This is the product's **End State view + overview + skim test** territory.
  
- **Time to grok what was done** — how fast a reader can reconstruct what changed, why, the key decisions and gotchas. This is **Journey view + takeaway ladder** territory.
  

The product docs already name these as the core UX principles (altitude ladder, skim test, scannable-first). What the repo does **not** have is a way to _measure_ them — and you can't set a workflow loose to optimize an unmeasured target. It will hill-climb on its own opinions.
## What already exists (and what's missing)
The repo has three quality mechanisms today, none of which measures reader experience in a loopable way:

| Mechanism | What it checks | What it can't tell you |
| --- | --- | --- |
| `validate_walkthrough_quality.py` | Structural lint: step count ≤ 12, takeaways present, grounded claims, no `chunk-NNN` titles | Whether a reader gets the picture faster |
| `references/skill-eval-benchmark-template.md` | Qualitative blind A/B review protocol (human + 2 agents) | Manual and slow; not invocable by a workflow |
| The "skim test" | An _instruction_ to the editorial agent | Never verified against an actual reading |

There is also a real corpus already on disk to measure against: `out/solstice-form-behavior-*`, `out/fastloop-gcp`, `out/feb-sprint`, `out/meta`, `out/process-walkthrough`, `out/security-hardening`, plus the frozen `.eval/solstice-form-behavior/` benchmark package with its session lists and normalized source data.
## Core proposal: build the fitness function first, then loop
The workflow is a **measure → diagnose → improve → re-measure** loop. The novel piece — and the thing worth most of the budget — is the measurement harness.
### The fitness function: a holistic judge panel
A panel of independent model judges scores each artifact on a small set of subjective, anchored criteria. Two judging modes, used at different points in the loop:

**Mode 1 — Anchored absolute scoring (baseline + diagnosis).** Each judge scores 1–5 per criterion against written anchors (what a 1 looks like, what a 5 looks like), and every score must cite concrete examples from the artifact ("step 4's takeaway restates the title", "the constraint about Node pinning only surfaces inside a collapsed diff"). Aggregate by median; a spread ≥ 2 points routes to a tiebreak judge instead of being averaged away. The justifications, not the numbers, are the diagnosis fuel.

**Mode 2 — Blind pairwise A/B (verifying changes).** After changes, judges see baseline vs candidate with randomized labels and pick a winner per criterion plus overall, with rationale. Pairwise preference is far more reliable than absolute-score deltas, and it directly extends the blind A/B protocol the repo's benchmark template already defines — this just makes it workflow-invocable.

**Proposed criteria (5).** Each maps to one of the two target metrics or guards against gaming them:

| Criterion | What the judge asks | Serves |
| --- | --- | --- |
| Destination clarity | From the skim materials alone, how clear is what the system is now and where the work landed? | Time to high-level understanding |
| Story coherence | Do the takeaway lines alone tell a complete, coherent story of what was done and why? (the skim test, judged) | Time to grok what was done |
| Altitude correctness | Is each fact at the right rung — nothing load-bearing buried in collapsed evidence, nothing trivial clogging the narrative band? | Both (wasted-descent guard) |
| Signal density | Does every step and claim earn its place — no filler, no transcript residue, no "the agent did work so it gets a step"? | Both (brevity bias) |
| Evidence trust | When you do descend, do claims hold up — grounded tags honest, refs resolvable, diffs relevant? | Guard against hollow polish |

**First-impression discipline.** To approximate human skimming despite agent attention profiles: judges receive the **skim slice** first (end-state goal/summary + titles + takeaways, extracted deterministically) and must commit their Destination-clarity and Story-coherence scores before seeing the full artifact. The full artifact then informs the other three criteria and may add notes — but not revise the committed first-impression scores. The altitude slicer survives from rev 1 as materials prep, not as a quiz constraint.

**Panel composition.** 3–5 judges per artifact with deliberately distinct lenses — and the product already defines them: the three audience modes (me-refresh, teammate-cold, reviewer). Optionally add non-Claude judges (Gemini Flash via the `agy` CLI, Codex) to match the benchmark template's multi-reviewer spirit and de-correlate the panel; see open decisions.

A change "wins" if it takes the pairwise majority on the targeted criteria and loses none — improvement without regression, judged blind.
### Why this beats letting critics loose directly
A pure critic fan-out ("audit the template", "audit SKILL.md") produces plausible opinions with no way to rank them or detect regressions. With the panel, every proposal gets tagged with the criterion it claims to move, and the blind pairwise re-measure settles the argument. The panel also operationally validates (or falsifies) the bets already in flight in `RESTRUCTURE-PLAN.md` — brevity ceiling, relevance gate, recipes, omissions — instead of taking them on faith.
## The loop: three chained workflows, with you at the gates
One monolithic workflow would run for a very long time and make code changes you haven't seen. Chaining keeps each run one well-scoped fan-out, and matches the interactive-boundary philosophy the restructure plan already adopts (the outline gate). All eval outputs go to `.eval/ttg/<artifact>/…` — never `out/` (the clobber gotcha; `out/walkthrough.json` is also a test fixture).
### Workflow 1 — Measure + Diagnose (read-only, launch first)
- **Phase A — Materials.** Pick 3 corpus artifacts for diversity (recommend: `solstice-form-behavior` UI feature, `fastloop-gcp` infra, `meta` dogfood). Extract skim slices deterministically. Script work, ~0 agents.
  
- **Phase B — Judge panel.** Pipeline per artifact: 4 judges (3 audience lenses + 1 floater), anchored absolute scoring with first-impression discipline, structured output (scores + cited justifications + descent-friction notes). Artifacts flow independently, no barrier. ~12 agents.
  
- **Phase C — Diagnosis.** Parallel critics, each fed the panel's scores and justifications plus their target surface: skim-test/End-State auditor, information-scent/IA auditor (titles, scent labels, above-the-fold), editorial-guidance critic (SKILL.md step 7 + recipes), validator-gap critic ("which judge-cited failures does the quality gate not catch?"). ~4 agents.
  
- **Phase D — Synthesis.** One agent merges everything into: baseline scorecard per artifact + ranked proposals, each tagged `{criterion_moved, layer, effort, risk, restructure_plan_item_it_validates}`. ~1 agent.
  

Returns the scorecard and ranked proposals. **Gate: you pick which proposals proceed.** Roughly 17 agents, no file mutations.
### Workflow 2 — Implement + Verify
- Implement approved proposals, grouped by layer (worktree isolation only if layers collide on files). Run `uv run pytest` + the quality gate.
  
- Re-produce the corpus artifacts: template/renderer changes need only a re-render (cheap, deterministic); editorial-rule changes need re-assembly from the existing cached summaries (moderate); nothing re-runs normalization.
  
- Re-measure with **blind pairwise A/B**: fresh judges (judges ≠ implementers), randomized labels, per-criterion verdicts. Keep wins, revert losses, flag splits as noise.
  
### Workflow 3+ — Iterate or institutionalize
Repeat the panel + implement cycle on the next proposal batch, or stop and bank the harness. The pairwise panel can also become a standing check: any future SKILL/template change re-runs it on the frozen corpus.
## Levers the workflow may pull
Three layers produce the reader experience; proposals must declare which they touch. This list is also the blast-radius contract for W2:

| Layer | Files | Typical moves |
| --- | --- | --- |
| Editorial rules | `SKILL.md` step 7, recipes; `references/walkthrough-schema.md` | Takeaway phrasing rules, end_state.architecture usage, omissions, step ordering |
| Renderer / template | `assets/walkthrough-template.html`, `scripts/render_html.py` | Above-the-fold layout, End State default, scent labels, jump cards |
| Quality gate | `scripts/validate_walkthrough_quality.py` + tests | Codify whatever judges actually cited — locks the gains in |

Deterministic pipeline scripts (normalize/project/chunk) are explicitly **out of scope** — they don't touch reader experience (this matches the restructure plan's non-goals).
## Durable assets this leaves behind
The point isn't one optimization pass; it's that the repo gains a reusable fitness function:

- The **judging rubric** (criteria + anchors + first-impression protocol) as a reference doc, extending `references/skill-eval-benchmark-template.md`'s qualitative protocol with a loopable panel.
  
- `scripts/extract_altitude_slices.py` — the deterministic skim-slice extractor used for judging materials.
  
- `.eval/ttg/` — baseline scorecards and pairwise verdicts per corpus artifact, so future runs are comparable.
  
- The panel workflow script itself, saved under `.claude/workflows/` so "re-measure" is one invocation.
  
## Decisions (resolved 2026-06-10)
1. **Criteria set** — the 5 above, as proposed.
  
2. **Panel composition** — Claude Fable is the main judge pool; Codex 5.5 xhigh may be added (most valuable in the W2 blind pairwise verdicts, where panel de-correlation matters most).
  
3. **Corpus** — the 3 recommended, plus an agent scans `~/.cc-history` to surface a couple more completed walkthrough artifacts (process-walkthrough and security-hardening in `out/` are leading candidates).
  
4. **Restructure-plan coupling** — RESTRUCTURE-PLAN stays its own track; this workflow only _validates_ its bets.
  
5. **Uncommitted work** — commit before W1 so the baseline measures a known revision.

**Stopping rule (session goal):** keep running improve → re-measure cycles; stop when a proposed change set fails to improve the judges' aggregate score.
