# Time-to-Grok Judging Rubric

How to judge a rendered walkthrough for the two product metrics: **time to high-level understanding** and **time to grok what was done**. Used by the judge-panel workflow described in `TIME-TO-GROK-WORKFLOW.md`; extends the qualitative protocol in `references/skill-eval-benchmark-template.md` with a loopable panel.

## Judging modes

- **Anchored absolute scoring** (baseline + diagnosis): score 1–5 per criterion against the anchors below. Every score must cite concrete examples from the artifact (step numbers, quoted lines). The justifications are the diagnosis fuel; the numbers only rank where to look.
- **Blind pairwise A/B** (verifying changes): two artifacts under randomized labels; pick a winner per criterion plus overall, with rationale. A candidate ships if it takes the majority on the targeted criteria and majority-loses none.

## First-impression protocol

Agent judges cannot un-read a document, so skimming is enforced structurally:

- **Skim judges** receive *only* the skim slice (goal/summary + step titles + takeaway lines, extracted by `scripts/extract_altitude_slices.py`). They score criteria 1–2.
- **Full judges** receive the full `walkthrough.json` (and rendered HTML path). They score criteria 3–5 and write friction notes.

## Judge lenses

Each judge adopts one of the product's audience modes (PRODUCT.md):

- **me-refresh** — built it, re-learning it; allergic to hand-holding and filler.
- **teammate-cold** — never seen this part of the codebase; needs orientation and navigation.
- **reviewer** — evaluating decisions, tradeoffs, risks; suspicious of unsupported claims.

## Criteria and anchors

### 1. Destination clarity (skim materials only)

*From the skim slice alone, how clear is what the system is now and where the work landed?*

- **1** — Cannot say what now exists; the goal is vague or process-speak ("worked on improvements"); summary lists activities, not outcomes.
- **3** — The headline goal is clear but the shape of the result is fuzzy: you know the area, not the architecture or net effect.
- **5** — From goal + takeaways alone you could explain to a teammate what exists now and where the work landed; components and net effects are named.

### 2. Story coherence (skim materials only)

*Do the takeaway lines alone tell a complete, coherent story of what was done and why?* (The skim test, judged.)

- **1** — Takeaways read as a disconnected activity log; no arc; several restate their titles or describe topics instead of outcomes.
- **3** — A story is discernible but has gaps or redundancy; a few takeaways are topics, not declarative outcomes.
- **5** — The takeaway sequence alone is a complete, coherent summary of the work — each line a declarative outcome, ordered with intent.

### 3. Altitude correctness (full artifact)

*Is each fact at the rung matching its importance?*

- **1** — Load-bearing facts (key decisions, live constraints, pivots) surface only inside collapsed evidence or buried prose; the narrative band is cluttered with trivia.
- **3** — Mostly right, with a few misplacements in either direction.
- **5** — Descending a level always rewards with detail and never surprises with essentials; decisions/gotchas sit in the visible band, proof sits behind scent labels.

### 4. Signal density (full artifact)

*Does every step and claim earn its place?*

- **1** — Transcript residue: chunk-shaped steps, mechanical sequences, steps that exist only because the agent did the work; duplicate or padded claims.
- **3** — Mostly earns its place; some steps or claims could merge or be cut without loss.
- **5** — Nothing can be cut without losing meaning; steps group by concept; the artifact reads as edited, not accumulated.

### 5. Evidence trust (full artifact)

*When you descend, do the claims hold up?*

- **1** — Claims unsupported or mislabeled (speculation tagged grounded); refs missing or dangling; evidence unrelated to the claims above it.
- **3** — Most claims grounded with usable refs; some confidence labels are questionable; evidence is relevant but unselective.
- **5** — Confidence labels are honest; each piece of evidence proves the specific claim it supports; diffs and commands are chosen, not dumped.

## Friction notes (full judges)

For each thing you needed but did not find where it should be: `{looking_for, expected_at (altitude rung), found_at (or "absent")}`. These feed the wasted-descent diagnosis.

## Aggregation

- Median per criterion per artifact across judges; a spread ≥ 2 points routes to one tiebreak judge whose score replaces the outlier-most score.
- **Aggregate score** = unweighted mean of the five criterion medians, averaged across the corpus. This is the loop's stopping metric: a change-set must raise it (and majority-lose no criterion in pairwise mode) to be kept.

## Judge output schema (absolute mode)

```json
{
  "artifact": "fastloop-gcp",
  "lens": "teammate-cold",
  "mode": "skim|full",
  "scores": [
    {"criterion": "destination_clarity", "score": 3,
     "justification": "…", "citations": ["step 4 takeaway: '…'"]}
  ],
  "friction_notes": [
    {"looking_for": "why the executor is Node-pinned", "expected_at": "gotcha callout", "found_at": "collapsed diff in step 7"}
  ]
}
```
