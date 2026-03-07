# Remediation Baseline

This file records the current pre-remediation baseline for the walkthrough skill.

## Environment

- Walkthrough workspace: `/Users/austin/dev/walkthrough`
- Current state: filesystem checkout only; no `.git` directory is present in this workspace.
- Implication: baseline/candidate comparison should support a filesystem snapshot fallback instead of assuming `git worktree` is always available.

## Primary Benchmark

Use this benchmark first:
- Benchmark name: `solstice-form-behavior`
- Frozen benchmark package: `.eval/solstice-form-behavior/`
- Target repo: `/Users/austin/dev/solstice`
- Audience: `teammate`
- Media mode: `both`

## Current Real-Artifact Validation

### `out/solstice-form-behavior-20260303-214138`
- `normalized.jsonl`: `20/29 passed`, `9 failed`, `1 warning`
- `projected.jsonl`: `6/6 passed`, `0 failed`
- `chunks/manifest.json`: `4/4 passed`, `0 failed`, `1 warning`
- Failure themes:
  - first visible `user_message` starts at `turn_index=2` for some sessions
  - multiple turn-index regressions
  - non-contiguous/interleaved sessions
  - `seq` not strictly increasing

### `out/fastloop-gcp`
- `normalized.jsonl`: `125/179 passed`, `54 failed`, `1 warning`
- `projected.jsonl`: `6/6 passed`, `0 failed`
- `chunks/manifest.json`: `4/4 passed`, `0 failed`, `1 warning`
- Failure themes:
  - first visible `user_message` starts at `turn_index=0` for many sessions
  - multiple turn-index regressions
  - non-contiguous/interleaved sessions
  - `seq` not strictly increasing

## Current Artifact Sizes

### `solstice-form-behavior-20260303-214138`
- `normalized.jsonl`: `19,558,526` bytes
- `projected.jsonl`: `6,438,743` bytes
- `walkthrough.json`: `102,654` bytes
- `walkthrough.html`: `9,952,694` bytes

### `fastloop-gcp`
- `normalized.jsonl`: `63,884,101` bytes
- `projected.jsonl`: `25,194,285` bytes
- `walkthrough.json`: `69,371` bytes
- `walkthrough.html`: `198,102` bytes

## Browser Baseline: Solstice HTML

Reviewed file:
- `file:///Users/austin/dev/walkthrough/.eval/solstice-form-behavior/baseline/walkthrough.html`

### External Requests Observed
Readable output currently depends on runtime external requests:
- `https://fonts.googleapis.com/...`
- `https://fonts.gstatic.com/...`
- `https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js`

### Broken Provenance Links Observed
Overview file links currently render malformed editor URLs with duplicate repo prefixes, for example:
- `cursor://file//Users/austin/dev/solstice//Users/austin/dev/solstice/src/features/events/components/combined-registration-wizard.tsx`

The same duplication appears on multiple overview and step-level file links.

### Qualitative Baseline Notes
- The artifact is rich and useful, but still slide-heavy for long engineering narrative.
- The provenance layer is visibly untrustworthy because of malformed file links.
- The artifact is not offline-clean because of external font and Mermaid requests.
- The baseline package copied into `.eval/solstice-form-behavior/baseline/` should be treated as the before-artifact for the first comparison.

## Immediate Readiness State

Before remediation starts, the following are already prepared:
- frozen benchmark manifest
- frozen session list
- copied baseline walkthrough artifacts
- workspace snapshot checksums
- baseline run report skeleton
- browser review and reviewer templates

Use `.eval/solstice-form-behavior/` as the first execution package.
