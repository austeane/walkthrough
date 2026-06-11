# Walkthrough Architectures

Two organizing principles for the editorial assembly step. Same schema, same
quality gate, same altitude ladder, same evidence rules — different step
structure, chosen from the reader frame before any steps are written.

Both were measured with blind judge panels against a five-criterion rubric
(destination clarity, story coherence, altitude correctness, signal density,
evidence trust). The selection rule below follows the measured fault line:
question-led structure swept destination clarity for handoff-shaped readers,
while the narrative arc retained story coherence on drama-heavy work.

## Choosing the architecture

Pick from `meta.purpose` and `meta.audience`, set during the scoping dialog:

| Signal | Architecture |
|---|---|
| `purpose: onboard` — build context to work in the area | **Descent** |
| Handoff / cold teammate / "what exists and can I trust it" | **Descent** |
| Infra, platform, or library work whose reader needs the destination | **Descent** |
| `purpose: review` — evaluate decisions, tradeoffs, risks | **Journey** |
| "Should we standardize on X?" — the artifact exists to relive a decision | **Journey** |
| `audience: me (refresh)` — re-learn what I built and why | **Journey** |
| The session's meaning lives in a dramatic hinge (an audit voiding a result, a forced pivot) | **Journey** |

Tiebreak: ask which question the reader opens with. *"What is here now?"* →
Descent. *"How did this happen / was this right?"* → Journey. Still ambiguous →
Descent (it swept destination clarity in panel testing, and a destination-first
artifact degrades more gracefully for the wrong reader than a chronology does).

State the choice to yourself alongside the editorial frame: "This walkthrough
is for `<audience>`, at `<detail_level>`, to `<purpose>`, covering `<scope>`,
shaped as a `<Descent|Journey>`."

## Shared invariants (both architectures)

Everything in SKILL.md section 7 applies regardless of architecture. In
particular:

- The **altitude ladder** and the **skim test**: takeaway lines read alone form
  a complete summary.
- **Evidence is verbatim or absent**; claims never outrun their evidence.
- **One fact, one rung**; headline facts at most twice per artifact, and
  deduplication never evicts measured numbers from the skim band.
- **Cold-reader rule** in the skim band; a **glossary** carries it below the
  skim band (near-universal: expected in ~every walkthrough).
- A **LikeC4 diagram** for anything multi-component (near-universal):
  `overview.diagram_image`, plus per-step `diagram` where one component
  deserves its own view.
- **Constraints carry the operational truth** and are exempt from the brevity
  bias — proven vs unproven with measured numbers, environment caveats, pinned
  literals, deferred items by name.
- The **two-screen height budget**: any step (and the overview skim band)
  should read in at most ~two laptop screens. The viewer clamps overflow
  behind "Show more", but the clamp is the safety net — the authoring fix is
  splitting the step, demoting detail down a rung, or plain-language concision.
- An optional **hyperframe video** (SKILL.md step 7d) substantially displaces
  text wherever it is attached.
- **Internal fact consistency is non-negotiable.** Before the gate, diff every
  headline number/status across its two permitted occurrences — they must
  agree on the fact even when the wording differs. Stale planning docs in the
  sources describe superseded states; prefer evidence from runs over evidence
  from plans.

## The Journey arc

Steps trace the causal chain of the work: build → harden → pivot → validate.
Group by concept or subsystem; use chronology only when chronology IS the
story. The takeaway sequence reads as a story with no causal holes; integrity
beats (a voided verification, an audit reclassification) always keep a visible
journey beat.

Two elements are required even here — they are the Descent's measured
strengths, grafted back:

- **A proof ledger lives somewhere explicit.** `end_state.constraints` states
  proven-vs-unproven with the measured numbers; if the work earned a
  verification story (a test campaign, an audit), give it a step rather than
  scattering pass/fail facts across the narrative.
- **A where-to-start landing.** The reader leaves knowing the entry-point
  files and what is deferred by name: `end_state.architecture` +
  `overview.key_files`, or a closing orientation step tagged
  `"mode": "end-state"` for onboarding-flavored readers.

## The Descent (question-led, destination-first)

The bet: for handoff-shaped readers, time-to-grok is governed not by narrative
but by how fast the artifact answers, **in order**, the five questions every
reader of an agent-session walkthrough actually has:

1. **What exists now?** — the destination, component by component.
2. **How much can I trust it?** — proven vs unproven, with every measured
   number, environment caveat, and integrity event stated outright.
3. **Why is it shaped this way?** — the load-bearing decisions, each with its
   rejected alternative and the constraint that forced the choice.
4. **What fought back?** — the failures and pivots that taught something
   durable (only those; routine debugging is noise).
5. **Where do I start?** — entry-point files, how to extend, what is named
   and deferred.

### Structural rules

- Steps map to the descent, never to time. Target shape (7–10 steps total):
  - 2–3 **destination tour** steps — one per major component cluster; the
    takeaway states what the component is and its measured net effect. The
    first tour step anchors on the architecture diagram (`overview.
    diagram_image` carries the system view; give a tour step its own `diagram`
    when a component cluster deserves a dedicated LikeC4 view).
  - 1 **proof ledger** step — the verification story in one place: what was
    tested, what passed/partially passed/was never exercised, with numbers.
    Integrity events (voided verifications, audit reclassifications, claims
    that didn't survive scrutiny) live HERE as first-class claims, not buried.
  - 2–3 **decision** steps — grouped by theme; each claim is a decision with
    its alternative and forcing constraint; chronology appears only as the
    minimal causal background ("after X collapsed at N TPS, …").
  - 1–2 **friction** steps — what fought back and the durable lesson; tag
    `"mode": "journey"`.
  - 1 **orientation** step — where to start reading, how to extend, deferred
    items by name; tag `"mode": "end-state"`.
- Takeaways are answers: each step's takeaway answers its question
  declaratively, with measured numbers where they exist. The takeaway
  sequence read alone = the five answers in order. That IS the story.
- `overview.goal`: one sentence naming what was built and its proven envelope.
  `overview.summary`: the answer digest — one bullet per question (≤5
  bullets). `end_state`: full destination framing, unchanged from schema norms.
- **Narrative momentum inside the descent.** When the work contains a genuine
  dramatic hinge (an audit voiding the headline result, a forced pivot), the
  descent must carry its causal chain, not just its facts: the proof-ledger
  step states WHAT was reclassified, and the "what fought back" step tells the
  hinge as a connected sequence (discovery → consequence → rebuild) with
  explicit back-references ("the stub the plan review had already flagged").
  The reader should be able to reconstruct when the hinge happened relative to
  the deliverables without leaving the takeaway sequence.
- Where the Descent conflicts with the Journey arc's narrative guidance
  (skim-test-as-story, chronological connective tissue), the Descent wins.
  The gate's structural requirements always hold.

### When the Descent is the wrong call

Skim readers punish the absence of a causal arc when the work's meaning is a
decision or a drama: an artifact whose stated goal is "decide whether…" or
whose center of gravity is a hinge event reads better as a Journey. The panel
result that set this boundary: the Descent swept destination clarity and won
infrastructure handoffs decisively, while the Journey kept story coherence on
the drama-heavy artifact. Use the table above; don't force one shape onto
every session.
