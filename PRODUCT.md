# PRODUCT.md

## Register

product

The walkthrough HTML viewer is a reading and reviewing tool. Its design serves
comprehension of the content, not self-expression. It is editorial in *voice*
(a written, authored narrative) but it is a tool in *purpose*: the reader came
to understand code an agent wrote, and every design choice is judged by how
fast and how honestly it delivers that understanding.

## Product purpose

Generate evidence-backed walkthroughs from AI-agent session histories so a
developer can understand what an agent built, why, and how, without replaying
the transcript. The output is a single, self-contained, offline HTML document
(dual-view: a scrollable Reading view and a 1920x1080 Present/deck view), also
designed to export cleanly to PDF via the browser print path.

The reader chooses their altitude on a second axis too: an **End State** view
(just where the work landed) or a **Journey** view (how we got there). The same
evidence base serves both — the end state is the destination; the journey is the
path with its pivots and dead-ends. Both must pass the skim test on their own.

The prime directive: the walkthrough teaches the developer their own codebase.
It is compression and editorial judgment over chronology. 100 agent actions
across 5 sessions might become 8 to 20 steps.

## Users

Developers reviewing agent-written work, in three audience modes:

- **Me (refresh)** — built it, needs to re-learn it. Wants "what changed and
  why", no hand-holding.
- **Teammate** — unfamiliar with this part of the codebase. Needs architectural
  context and enough to navigate.
- **Reviewer** — PR/code-review context. Wants decisions, tradeoffs, error
  handling, anything that deserves scrutiny.

All three scan first and decide where to spend attention. None of them want to
read everything top to bottom.

## Core UX principle: scannable surface, depth on demand

Each step is an **altitude ladder**. The reader descends only as far as they
care to:

1. **Title** — the topic (TOC / scan layer).
2. **Takeaway** — one declarative outcome sentence: the broad shape of what
   happened. The line a reader uses to decide "do I care about this step?"
3. **Intent** — why / context.
4. **Narrative (claims + decisions + gotchas)** — the reasoning, with honest
   confidence tags. Always visible.
5. **Proof (diffs, commands, screenshots)** — collapsed by default behind a
   scent label that says what is inside. The verification layer.
6. **Source refs** — jump to the raw transcript lines.

**The skim test:** the sequence of takeaway lines read alone should form a
complete, coherent summary of the whole session. If it does not, the narrative
failed.

## Tone

Editorial, precise, and honest. Confidence is first-class: claims are tagged
`grounded` / `inferred` / `speculative` and the UI shows it, so a reader always
knows how much to trust a statement. No hype, no filler, every word earns its
place.

## Strategic principles

- Scannable first; depth never forced on the reader, always one interaction away.
- Evidence is verifiable: every claim can point to source lines.
- Offline and self-contained: no CDN fonts, no runtime network fetches, editor
  links resolve locally. The artifact must work on a plane and a year from now.
- Honest confidence over false certainty.

## Anti-references (what this must never feel like)

- A transcript replay or a raw log dump.
- A generic AI-generated "documentation dashboard" with hero metrics, gradient
  accents, and identical icon+heading+text card grids.
- A SaaS marketing page. This is a reading instrument, not a pitch.
- An overwhelming wall of diffs presented with no narrative altitude.
