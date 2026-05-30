# Walkthrough Template Reference

Reference for agents that need to evaluate, modify, or generate data consumed by `assets/walkthrough-template.html`.

**Template file**: `/Users/austin/dev/walkthrough/assets/walkthrough-template.html`
**Renderer**: `/Users/austin/dev/walkthrough/scripts/render_html.py`

The template is a **dual-view, single-file** document rendered from one
`walkthrough.json`:

- **Reading view** (default) — a scrollable, reading-first page. Each step is an
  **altitude ladder**: title → `takeaway` (the gist) → `intent` (why) → narrative
  (claims + decisions + gotchas, always visible) → **evidence** (diffs, commands,
  screenshots) in a `<details>` that is **collapsed by default** behind a one-line
  scent label, expandable on demand. Decisions/gotchas are reasoning, so they sit
  in the visible band, not inside the collapsed evidence.
- **Present view** (deck) — a true fixed **1920×1080** stage scaled with a single
  CSS transform, one slide at a time, for live walk-throughs and PDF export.

Both views are emitted from the same data into two DOM trees; the active one is
chosen by `data-mode` on `<html>`. There is **no evidence modal** (removed).

---

## 1. Template Engine

**Engine**: Jinja2 with autoescape enabled for `.html`/`.htm`
(`select_autoescape(enabled_extensions=("html","htm"), default=True)`).

All user/agent-authored text (`overview.goal`, `step.title`, `claim.text`,
summary items, file paths, command text, decisions, gotchas) relies on Jinja
**autoescape**. Do **not** add `| safe` to any of those. `| safe` is used only for
trusted, server-produced HTML: `pygments_css`, `data.overview._diagram_svg`, and
each `hunk.rendered_html`.

### Variables Injected by `render_html.py`

| Variable | Type | Description |
|----------|------|-------------|
| `data` | dict | The full walkthrough JSON after `prepare_data()` (adds `_diagram_svg`, `key_file_refs`, per-step `_file_refs`, `_evidence_summary`, and `rendered_html` on each diff hunk) |
| `data_json` | Markup | Safe-serialized JSON embedded verbatim into `<script>const DATA = {{ data_json }};</script>`. Produced by `serialize_script_data()` (escapes `</` → `<\/` and U+2028/U+2029) |
| `pygments_css` | Markup | Monokai token CSS from `HtmlFormatter(style="monokai", cssclass="highlight", nobackground=True)`. Injected into the `<style>` block via `{{ pygments_css }}` |

### Rendering Pipeline

```
walkthrough.json
    |
    v
render_html.py --input X --output Y [--normalized Z] [--captures-manifest M]
    |
    +--> bridge_screenshots_to_media()  # evidence.screenshots[] -> evidence.media[] stubs
    +--> attach_capture_media()         # optional Path-B captures/manifest.json
    +--> resolve_media()                # hydrate media data_uri/thumbnail_uri (Pillow compresses)
    +--> prepare_data()
    |       +--> filter_file_refs()        -> overview.key_file_refs, step._file_refs
    |       +--> render_mermaid_svg()      -> overview._diagram_svg  (sanitized inline SVG)
    |       +--> highlight_diff_hunk()     -> hunk.rendered_html  (Pygments; hunk.html dropped)
    |       +--> summarize_evidence()      -> step._evidence_summary
    +--> get_pygments_css()
    +--> serialize_script_data()        -> data_json
    +--> template.render(data, data_json, pygments_css)
```

---

## 2. Hard Constraints (enforced by `tests/test_render_html.py`)

Any rewrite of the template MUST keep all of these:

1. Contain these literal JS substrings (programmatic-navigation test):
   - `revealStep(step)`
   - `step.classList.add('visible');`
   - `this.scrollToStep(this.steps[idx]);`
2. Contain **no** `fonts.googleapis.com` and **no** `cdn.jsdelivr.net`
   → no CDN webfonts, no runtime Mermaid. Fonts are **system stacks**
   (serif display + humanist body + mono); a future custom display face is a
   one-line base64 `@font-face` swap.
3. Render the overview diagram from `data.overview._diagram_svg | safe`, falling
   back to `<pre>{{ data.overview.diagram_mermaid }}</pre>` **only** when there is
   no SVG. (Tests assert `<svg class="mermaid-svg"` present and `<pre>flowchart LR`
   absent.)
4. Emit the evidence summary as `>{{ step._evidence_summary }}<` with **no adjacent
   whitespace**, so e.g. `>1 cmd · 1 shot<` appears verbatim. Achieved with
   `<span class="ev-summary">{{ step._evidence_summary }}</span>`.
5. Keep autoescape for all user/agent text; embed data only via
   `<script>const DATA = {{ data_json }};</script>`.
6. Render diff hunks from `hunk.rendered_html | safe` — never `hunk.html`
   (dropped by `prepare_data`).

The full suite (`uv run pytest`) must stay green after any change.

---

## 3. Data Contract

Optional fields are noted; absent ones are skipped via `{% if %}` or `| default()`.

### 3.1 Top-Level: `data`

```
data
├── meta
│   ├── repo_root          # string, optional — enables cursor:// / vscode:// links
│   ├── repo               # string, optional — shown in sidebar header
│   └── scope              # string, optional — shown in hero/slide eyebrow
├── overview
│   ├── goal               # string — <title>, header title, hero <h1>, title slide
│   ├── summary            # list[str], optional — hero bullets + first 3 on title slide
│   ├── key_files          # list[str], optional (raw paths after filtering)
│   ├── key_file_refs      # list[FileRef] (added by prepare_data) — hero "Key files" chips
│   ├── diagram_mermaid    # string, optional — Mermaid source (fallback <pre> only)
│   └── _diagram_svg       # string (added by prepare_data) — sanitized inline SVG
└── steps                  # list[Step]
```

### 3.2 `data.meta`

| Field | Used In | Purpose |
|-------|---------|---------|
| `meta.repo_root` | JS `getRepoRoot()`/`normalizeFileRef()` + `prepare_data` link building | Prefix for relative paths to form `cursor://file/...` and `vscode://file/...` |
| `meta.repo` | Jinja2 | Sidebar repo line |
| `meta.scope` | Jinja2 | Eyebrow text on hero and title slide |

### 3.3 `data.overview`

| Field | Type | Required | Template Usage |
|-------|------|----------|----------------|
| `overview.goal` | string | has `default("")` | `<title>`, `.topbar__title`, `.hero__title`, title slide `<h1>` |
| `overview.summary` | list[str] | No | `.hero__summary` (all) and `.slide__summary` (first 3) |
| `overview.key_file_refs` | list[FileRef] | No | `.chip-row` of `.key-file` links in the hero |
| `overview._diagram_svg` | string | No | `.overview-diagram` (inline SVG, `| safe`) |
| `overview.diagram_mermaid` | string | No | `<pre>` fallback only when `_diagram_svg` is empty |

A stat strip in the hero (and the title slide) is computed **in Jinja** with a
`namespace`: `steps = data.steps|length`, plus summed `files` (Σ `step._file_refs`),
`commands` (Σ `step.evidence.commands`), `decisions` (Σ `step.decisions`), and
`fixes` (Σ `step.errors_encountered`). A sixth "min read" stat is filled by JS.
The hero also renders a **jump grid** of cards linking to each step.

### 3.4 `data.steps[]` (Step Object)

| Field | Type | Required | Template Usage |
|-------|------|----------|----------------|
| `step.id` | string | Yes | `id` on the reading `<article>` and overview `<section>`; `#`-anchor in TOC, jump grid, copy-link; `data-step-id`; `id="media-<id>"`; DATA lookups |
| `step.title` | string | Yes | TOC text, jump card title, `.step-title`, `.slide__title` |
| `step.takeaway` | string | No (but author it) | `.step-takeaway` lead (reading), `.slide__takeaway` (deck), and the jump-card subline `.jump-card__d`. The "broad shape" the reader scans first. |
| `step.intent` | string | No | `.step-intent` (reading); `.slide__intent` on the deck **only when there is no `takeaway`** |
| `step.claims` | list[Claim] | No | `.claim` paragraphs (reading); first **4** on the slide, with a "+N more — see Reading" note when capped |
| `step.evidence` | object | No | Collapsed `<details class="evidence">` (closed by default) + one-line scent chip, rendered only when evidence has `diff_hunks`/`commands`/`media` |
| `step.decisions` | list[Decision] | No | `◆ Decision` callouts in the visible `.callouts` band (above the evidence block) |
| `step.errors_encountered` | list[Error] | No | `⚠ Gotcha` callouts in the visible `.callouts` band (above the evidence block) |
| `step._file_refs` | list[FileRef] | added by prepare_data | "Files touched" chips (reading) + `.slide__file` chips (first 5, deck) |
| `step._evidence_summary` | string | added by prepare_data | `<span class="ev-summary">` scent text (the `>…<` constraint); appends `N failed` when any command failed |

`<details class="evidence">` is rendered when `step.evidence` has any of
`diff_hunks`, `commands`, or `media` (a files-only evidence object renders no
collapsible — the files already show as chips). It is **closed by default**;
"Expand all" in the header toggles every one, and `initPrint()` opens them for
`Cmd+P`/PDF then restores. `<details>` works without JS. The `.callouts` band
(decisions + gotchas) is a sibling rendered **before** the evidence block and is
always visible.

### 3.5 `step.claims[]` (Claim Object)

| Field | Type | Required | Usage |
|-------|------|----------|-------|
| `claim.text` | string | Yes | Paragraph body |
| `claim.confidence` | string | No (default `"grounded"`) | CSS modifier + inline pill |

**Confidence rendering** (reading `.claim` / deck `.slide__claim`). Grounded is the
trusted default and gets **no decoration** (a clean paragraph); only the exceptions
are flagged, so a scanning reader spots what to question and trusts the rest. No
side-stripe borders:

| Value | Class modifier | Visual |
|-------|----------------|--------|
| `grounded` | `--grounded` | Plain paragraph, no pill, no tint |
| `inferred` | `--inferred` | Amber **"inferred"** pill + subtle amber background tint (`--inferred-bg`) with a hairline `color-mix` border |
| `speculative` | `--speculative` | Crimson **"speculative"** pill + subtle crimson background tint (`--speculative-bg`) with a hairline `color-mix` border |

The pill text equals the actual confidence (`{{ conf }}`). A compact confidence
**legend** renders in the overview hero (`.legend`) only when the walkthrough
contains any inferred/speculative claims (computed in the Jinja `stats` namespace).

### 3.6 `step.evidence` (Evidence Object)

| Field | Type | Inline rendering |
|-------|------|------------------|
| `evidence.diff_hunks` | list[DiffHunk] | "Diffs" group: per-hunk `.diff` block |
| `evidence.commands` | list[Command] | "Commands" group: terminal-style `.cmd` blocks |
| `evidence.media` | list[MediaItem] | "Screenshots" group: `#media-<id>` container, JS-populated |
| `evidence.files_changed` | list[str] | (raw paths; chips come from `step._file_refs`) |

### 3.7 `evidence.diff_hunks[]` (DiffHunk Object)

| Field | Type | Usage |
|-------|------|-------|
| `diff_hunk.file` | string | `.diff__file` label + per-file +/− aggregation key |
| `diff_hunk.rendered_html` | string (added by render) | Inserted via `{{ hunk.rendered_html | safe }}` into `.diff__body` |
| `diff_hunk.diff` | string | Source for the rendered HTML and for JS +/− counts / copy-diff |
| `diff_hunk.before` / `after` | string | Synthesized into a unified diff if `diff` absent (counts + copy fallback) |
| `diff_hunk.line` | number | Reserved (editor-link line); chips use `_file_refs` |

`render_html.py` drops the untrusted `hunk.html` and produces `hunk.rendered_html`
with `DiffLexer` (`nowrap=False, cssclass="highlight", nobackground=True`).
The template adds, **client-side from `DATA`**, a `+X −Y` count to each diff
header (`[data-counts]`) and a **Copy diff** button. `.diff__body` scrolls when
tall (`max-height`), and prints unbounded.

### 3.8 `evidence.commands[]` (Command Object)

| Field | Type | Usage |
|-------|------|-------|
| `command.cmd` (or `command.command`) | string | `.cmd__text` (`$ `-prefixed), copy-command source |
| `command.status` | string | `.cmd__dot--pass` (green) / `.cmd__dot--fail` (red); default `pass` |
| `command.summary` (or `output_preview`) | string | `.cmd__out` block |

### 3.9 `evidence.media[]` (MediaItem Object)

Unchanged contract. JS `renderMedia()`/`renderThumb()` populate `#media-<id>`:

| Field | Usage |
|-------|-------|
| `media.data_uri` | Full image (lightbox `data-full-src`) and thumbnail fallback |
| `media.thumbnail_uri` | Preferred `<img src>` (300px JPEG from render) |
| `media.caption` | `.media-caption` + lightbox caption |
| `media.group` | Groups items together |
| `media.group_role` | `"before"`/`"after"` → side-by-side `.media-compare` grid |

### 3.10 `step.decisions[]` (Decision Object)

| Field | Usage |
|-------|-------|
| `decision.decision` | `.callout__title` of a `◆ Decision` callout |
| `decision.rationale` | `.callout__body` |
| `decision.alternatives_considered` | `.callout__alts` list (now rendered) |

### 3.11 `step.errors_encountered[]` (Error Object)

| Field | Usage |
|-------|-------|
| `error.error` | `.callout__title` of a `⚠ Gotcha` callout |
| `error.resolution` | `.callout__body` |

### 3.12 FileRef Object (produced by `filter_file_refs`)

`{ raw_path, label_path, abs_path, cursor_href, vscode_href }`. The template uses
`label_path` for display + the `data-file` match key, `cursor_href` for the link,
and `abs_path` in `data-abs-path`.

---

## 4. Layout Structure

```
<html data-theme="dark" data-mode="reading">
<head><style> tokens + chrome + reading + present + shared + {{ pygments_css }} + print </style></head>
<body>
  .progress                          # top progress bar (reading only)
  nav.sidebar#sidebar                 # TOC (overview + steps), shared by both views
    .sidebar__head (kicker + repo)
    ul.toc > li > a.toc-link[data-step]
  header.topbar                       # hamburger, title, search, Expand-all, Mode, Theme
  main.reading-view#readingView
    {# Jinja namespace accumulates stat-strip totals #}
    section.overview.step#overview[data-step="0"]
      .hero (eyebrow, title, summary, .stat-strip, .legend?, key-file chips)
      .overview-diagram (_diagram_svg | safe  OR  <pre> fallback)
      .jump-grid (cards: __n number + __body[ __t title + __d takeaway subline ])
    {% for step %}
    article.step#<id>[data-step][data-step-id]
      .step-eyebrow (Step N + copy-link "#")
      h2.step-title ; p.step-takeaway? (gist) ; p.step-intent? (why)
      .files (file-chip chips, JS +/− counts)
      .claims (claim paragraphs; pill + tint on inferred/speculative, plain grounded)
      .callouts?  (◆ Decision / ⚠ Gotcha callouts — always visible reasoning band)
      details.evidence  (closed by default; only when diff_hunks/commands/media)
        summary > span.evidence__hint "Evidence" + span.ev-summary{{ _evidence_summary }}
        .evidence__body
          Diffs group (.diff: head + counts + Copy diff + body=rendered_html|safe)
          Commands group (.cmd: dot + text + Copy)
          Screenshots group (#media-<id>, JS-populated)
    {% endfor %}
  div.deck-viewport#deckViewport       # PRESENT view (shown only when data-mode=present)
    div.deck-stage#deckStage            # fixed 1920x1080, transform: scale()
      section.slide.slide--title[data-slide="0"]  (eyebrow, hero title, summary, stats)
      {% for step %}section.slide[data-slide]  (eyebrow N/total, title,
          takeaway OR intent, up to 4 claims + "+N more", file chips,
          evidence summary){% endfor %}
    .deck-controls (#deckPrev, #deckIndex/#deckTotal, #deckNext)
  div.lightbox#lightbox                # image lightbox (close/prev/next/img/caption)
  <script>const DATA = {{ data_json }};</script>
  <script> WalkthroughViewer + DeckController + App </script>
</body>
```

### View switching

`data-mode` on `<html>` is `reading` (default) or `present`, persisted in
`localStorage['walkthrough-mode']`. CSS shows exactly one container:
`[data-mode="present"] .reading-view { display:none }` and
`.deck-viewport { display:none }` flipped to `display:block` under present.
The present stage is positioned below the header and right of the sidebar; the
scroll-snap model of the old "presentation" layout is gone.

---

## 5. Interactive Behavior (JavaScript)

Three classes, instantiated as `new App()` on `DOMContentLoaded`
(`window.__walkthrough`).

### 5.1 `WalkthroughViewer` (reading)

- `this.steps` = `.reading-view section[data-step], .reading-view article[data-step]`
  (overview is index 0). `this.tocLinks`, `this.currentStep`, `this.progress`.
- `IntersectionObserver` (no-op unless `data-mode==='reading'`) calls
  `revealStep(step)` → `step.classList.add('visible')` + `setCurrentStep(idx)`
  (updates progress width, TOC `.active` + `aria-current`).
- Navigation: `scrollToStep`, `goToStep(idx)` (`this.scrollToStep(this.steps[idx]);`),
  `goRelative(±1)`, `goToBoundary('start'|'end')`, jump cards, initial hash.
- `computeDiffStats()` reads `DATA`, fills each diff `[data-counts]` and each
  `.file-chip__counts` with `+adds −dels` (aggregated per file).
- `computeReadTime()` fills `#readTime` (words / 200 wpm).

### 5.2 `DeckController` (present)

- `this.slides` = `.deck-stage .slide`, `this.index`, `this.total`.
- `scale()` is **fit-to-content**: it measures the active slide's real content
  height (`.slide__inner` `scrollHeight` + padding, in unscaled layout px) and sets
  the `deck-stage` transform to `translate(-50%,-50%) scale(min(vpW/1920,
  vpH/max(1080, contentHeight)))`. A dense slide therefore shrinks to fit instead
  of clipping; normal slides behave as before (`max` resolves to 1080).
- `goToSlide/next/prev` toggle `.slide.active`, update `#deckIndex`, call
  `reading.setCurrentStep(index)` to keep the two views in sync, and re-run
  `scale()` so each slide gets its own best fit. Touch-swipe nav.

### 5.3 `App` (shared chrome)

- **Theme**: `localStorage['walkthrough-theme']`, toggles `data-theme` dark/light,
  ☾/☀ icon.
- **Mode**: toggle button; entering present calls `deck.activate(reading.currentStep)`,
  leaving scrolls reading to `deck.index`.
- **Sidebar/TOC**: hamburger toggles `.open`; TOC click jumps slide (present) or
  scrolls (reading); closes sidebar.
- **Search**: filters reading steps (`display:none`) + TOC (`.search-hidden`).
- **Expand/Collapse all**: toggles every `details.evidence`.
- **Copy**: delegated clicks for `.copy-link` (step URL), and `.copy-btn`
  (`data-copy-kind=diff|cmd`, resolved from `DATA`), with clipboard + textarea
  fallback and a transient "Copied"/"✓" state.
- **Media galleries + lightbox**: `initMediaGalleries()` populates `#media-<id>`;
  lightbox supports zoom-to-full, prev/next, keyboard, click-out, Esc.
- **Keyboard** (single handler, routed by `data-mode`): ←/→/↑/↓/Space/PageUp/PageDown
  move between steps (reading) or slides (present); Home/End jump to ends;
  Esc closes sidebar/lightbox; ignored while typing in inputs.

---

## 6. Styling & Aesthetic

"Distinctive editorial", offline, warm, light + dark.

- **Type**: `--font-display` = serif stack
  (`"Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua",Georgia,ui-serif,serif`);
  `--font-body` = humanist sans (`system-ui,-apple-system,…`);
  `--font-mono` = `"JetBrains Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace`.
  No webfonts (offline + test constraints).
- **Palette**: warm "ink" dark default + warm "paper" light, all via CSS custom
  properties on `:root` / `[data-theme="light"]`. Single jewel **teal** accent
  (`#3fbfae` dark / `#0f766e` light), kept distinct from status hues.
- **Status hues**: diff add green / del red; `inferred` amber; `speculative` crimson.
- **Narrative components** (no side-stripe borders anywhere):
  - `.step-takeaway` / `.slide__takeaway` — a serif **lead** under the title, full
    text color, larger than the muted-sans `.step-intent`. The gist altitude.
  - `.claim` — clean paragraph for grounded; inferred/speculative get a pill + a
    subtle tinted block (full hairline `color-mix` border), so exceptions pop.
  - `.callout` (decision/gotcha) — full tinted border + background wash + leading
    icon label; teal for decisions, the del hue for gotchas, so they scan apart.
  - `.evidence` — collapsed `<details>` with a mono scent chip; the `.evidence__hint`
    "Evidence" label precedes the chip.
  - `.jump-card` — number + title + 2-line clamped `takeaway` subline (skim grid).
- **Atmosphere**: layered radial gradients + a faint inline-SVG grain
  (`--grain`, `feTurbulence`) on the overview hero only; hairline rules elsewhere.
- **Diff highlighting**: `{{ pygments_css }}` (Monokai) + `.diff__body .highlight pre`
  forced transparent so blocks inherit the warm surface.
- **Responsive**: `max-width:860px` collapses the sidebar (hamburger), full-width
  reading, deck viewport spans full width; `max-width:560px` tightens chrome.
- **Reduced motion**: `prefers-reduced-motion` disables reveal/scroll animation.
- **Print** (`@media print`): hides chrome/deck/copy controls, forces the reading
  view + every `.evidence__body` open, removes hero gradients/grain, avoids
  breaking diffs/callouts across pages → clean `Cmd+P` PDF. `initPrint()` also
  opens every collapsed `details.evidence` on `beforeprint`/`matchMedia('print')`
  and restores their state on `afterprint`, so the PDF carries the full proof.

---

## 7. Editor Links

`normalizeFileRef(filePath)` (JS) and `filter_file_refs`/`normalize_file_ref`
(Python) build `cursor://file/<abs>` and `vscode://file/<abs>` from `meta.repo_root`
+ relative path (absolute paths used as-is). Hero key-file chips and per-step
"Files touched" chips link via `cursor_href`; diff +/− counts and copy actions are
JS-driven from `DATA`. If `meta.repo_root` is empty, links fall back to the raw
path (only useful if already absolute).

---

## 8. Embedded Data (`DATA` Global)

```html
<script>const DATA = {{ data_json }};</script>
```

`DATA` is the authoritative source for JS-driven pieces: diff/file +/− counts,
copy-diff/copy-command payloads, media gallery thumbnails, and the lightbox.
Jinja renders the static skeleton and all in-flow evidence text; JS enriches it.

---

## 9. Minimal Valid Data Shape

```json
{ "overview": { "goal": "My Walkthrough" }, "steps": [] }
```

A typical fully-populated step:

```json
{
  "id": "step-1",
  "title": "Set up the project",
  "intent": "Initialize the repository with required dependencies",
  "claims": [
    {"text": "Created package.json with TypeScript config", "confidence": "grounded"},
    {"text": "Likely chose TypeScript for type safety", "confidence": "inferred"}
  ],
  "evidence": {
    "files_changed": ["package.json", "tsconfig.json"],
    "diff_hunks": [
      {"file": "package.json", "line": 1, "diff": "--- a/package.json\n+++ b/package.json\n+{\n+  \"name\": \"my-project\"\n+}"}
    ],
    "commands": [
      {"cmd": "npm init -y", "status": "pass", "summary": "Initialized package.json"}
    ],
    "media": [
      {"data_uri": "data:image/jpeg;base64,…", "thumbnail_uri": "data:image/jpeg;base64,…", "caption": "Terminal output"}
    ]
  },
  "decisions": [
    {"decision": "Use TypeScript", "rationale": "Better IDE support and type safety", "alternatives_considered": ["plain JS"]}
  ],
  "errors_encountered": [
    {"error": "tsc not found", "resolution": "Added typescript to devDependencies"}
  ]
}
```
