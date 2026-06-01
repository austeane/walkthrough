# DESIGN.md

The visual system already lives in `assets/walkthrough-template.html` and is
described in `references/walkthrough-template-reference.md` §6. This file is the
canonical summary for design work.

## Aesthetic

"Distinctive editorial." A warm, authored, magazine-like reading instrument,
not a tool-chrome dashboard. Offline and self-contained. Light + dark, both
warm (no cold gray UI). The reading view is the product; the present/deck view
is the same data at a higher altitude.

## Color

Warm tinted neutrals, never `#000`/`#fff`. Strategy is **restrained**: tinted
ink/paper surfaces carry the page; a single jewel **teal** accent does the
signalling and stays under ~10% of the surface.

- Accent (teal): `#3fbfae` dark / `#0f766e` light. The only brand hue. Used for
  eyebrows, the active TOC item, links, the takeaway marker, scent labels.
- Status hues, kept distinct from the accent so they read as status, not brand:
  - diff add: green; diff del: red
  - `inferred`: amber
  - `speculative`: crimson
- New color should prefer OKLCH and keep these roles distinct. Do not introduce
  a second brand hue.

## Typography

System stacks only (no webfonts, for offline + test constraints):

- `--font-display`: serif — `"Iowan Old Style","Palatino Linotype",Palatino,
  "Book Antiqua",Georgia,ui-serif,serif`. Titles, hero, the takeaway lead.
- `--font-body`: humanist sans — `system-ui,-apple-system,...`. Intent, claims,
  body copy.
- `--font-mono`: `"JetBrains Mono",ui-monospace,"SF Mono",Menlo,Consolas,
  monospace`. Code, diffs, commands, scent labels, step numbers.

Hierarchy is carried by scale + weight + the serif/sans/mono split, not by color
alone. Body measure capped ~64ch; narrative lines ~58-65ch.

## Elevation & texture

Hairline rules (`--hairline`) separate most things; cards are used sparingly and
never nested. Atmosphere is a layered radial-gradient wash plus a faint inline
SVG grain on the overview hero **only**. Everywhere else stays calm so the
diffs and prose read.

## Motion

Reveal-on-scroll (opacity + translate, ease-out), disabled under
`prefers-reduced-motion`. No animating layout properties. No bounce/elastic.

## Component conventions

- **View toggle (End State / Journey)**: a segmented control in the topbar (teal fill
  on the active segment, matching the accent system). It is the most significant piece
  of chrome — it reshapes *what* the reader sees, not just how — so it reads as two
  explicit named states, not a single icon-button like theme/present. End State is the
  default first impression (scannable destination); Journey is one click away. Content
  that does not belong to the active view is removed cleanly (`display:none`), and
  container bands (callouts, reasoning maps) collapse rather than leave an empty frame.
- **Takeaway**: a serif lead line under the title, full-strength text color,
  larger than intent. The "broad shape" altitude. (No colored side-stripe.)
- **Overview**: desktop uses a two-column editorial header so the long goal does
  not push the summary, stats, and step grid too far below the fold. The step
  grid comes before key-file chips because the work arc is the first-pass scan.
  Jump cards include compact decision/gotcha counts so readers can pick drill-down
  targets from the work arc. Mobile stays single-column.
- **Claims**: editorial paragraphs; confidence shown via a small pill, not via a
  thick colored side border.
- **Decisions / Gotchas**: callouts in the always-visible narrative band (they
  are reasoning, not raw artifacts).
- **Evidence (diffs / commands / screenshots)**: a `<details>` collapsed by
  default, with a mono scent label (e.g. `4 files · 2 diffs · 1 cmd · 1 shot`)
  so the reader knows what is inside before opening. "Expand all" in the header
  and the print path force every block open.
- **Diffs**: Pygments Monokai tokens on the warm surface; per-file +/- counts
  and Copy actions are JS-driven from the embedded `DATA`.

## Hard constraints (enforced by tests)

See `references/walkthrough-template-reference.md` §2. Notably: no
`fonts.googleapis.com` / `cdn.jsdelivr.net`; overview diagrams render from
embedded LikeC4 image exports first, with sanitized SVG/Mermaid only as fallback;
evidence scent label emits as `>{{ step._evidence_summary }}<` with no adjacent
whitespace; all user/agent text stays autoescaped; diff hunks render from
`hunk.rendered_html | safe`. The full `uv run pytest` suite must stay green.
