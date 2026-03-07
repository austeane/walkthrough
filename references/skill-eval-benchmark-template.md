# Skill Evaluation Benchmark Template

Use this reference when you need to compare two versions of the walkthrough skill on the same real feature implementation.

This benchmark is for evaluating the skill as an operator workflow, not just validating individual scripts.

## Purpose

The benchmark should answer one question:

> Does the candidate version of the skill produce a meaningfully better final `walkthrough.html` for the same feature work than the baseline version?

Quantitative checks are guardrails. The final decision is primarily qualitative and should come from reviewing the rendered HTML outputs.

## Outputs

Each benchmark run should produce:
- `baseline/walkthrough.html`
- `candidate/walkthrough.html`
- `baseline/run-report.json`
- `candidate/run-report.json`
- `browser-findings.md`
- `comparison.md`

Recommended directory layout:

```text
.eval/
  <benchmark-name>/
    manifest.json
    baseline/
      walkthrough.json
      walkthrough.html
      run-report.json
      ...intermediate artifacts...
    candidate/
      walkthrough.json
      walkthrough.html
      run-report.json
      ...intermediate artifacts...
    review/
      browser-findings.md
      reviewer-you.md
      reviewer-codex.md
      reviewer-claude.md
      comparison.md
```

## Benchmark Manifest Template

Create one manifest per benchmark and reuse it unchanged for baseline and candidate runs.

```json
{
  "benchmark_name": "solstice-form-behavior",
  "description": "Feature walkthrough benchmark for form behavior implementation in Solstice.",
  "feature_repo_root": "/absolute/path/to/target/repo",
  "walkthrough_repo_root": "/absolute/path/to/walkthrough/repo",
  "baseline_source_mode": "git_worktree_or_filesystem_snapshot",
  "scope": {
    "mode": "specific_sessions",
    "sessions_file": ".eval/solstice-form-behavior/sessions.json",
    "session_paths": []
  },
  "audience": "teammate",
  "media_mode": "extract",
  "expected_repo_revision": {
    "branch": "main",
    "commit": "<optional-fixed-target-commit>",
    "compare_range": "<optional-commit-range>"
  },
  "expected_improvements": [
    "No broken or double-prefixed editor links",
    "Readable output without required external network requests",
    "Evidence is easier to inspect in the HTML",
    "Narrative is more clearly tied to the repo and changed files"
  ],
  "hard_gates": {
    "require_validate_pipeline_pass": true,
    "forbid_broken_editor_links": true,
    "forbid_required_external_requests": true,
    "require_html_safe_rendering": true,
    "max_html_size_mb": 12
  },
  "review_protocol": {
    "blind_labels": true,
    "reviewers": ["user", "codex", "claude"],
    "require_independent_first_pass": true
  }
}
```

## Recommended Setup

1. Pick one canonical benchmark first.
2. Freeze the session selection in `sessions.json`.
3. Prefer two walkthrough worktrees when the workspace is a Git checkout:
   - `baseline`: pre-improvement commit
   - `candidate`: current branch
4. If Git metadata is unavailable, use a filesystem snapshot fallback:
   - freeze the baseline artifact and a `workspace-snapshot.json` file
   - run the candidate from the current workspace or a copied candidate directory
5. Run both with the same manifest.
6. Review the final HTML outputs in a browser.

Recommended worktree layout when Git is available:

```bash
git worktree add ../walkthrough-baseline <baseline-commit>
git worktree add ../walkthrough-candidate <candidate-commit-or-branch>
```

Filesystem snapshot fallback when Git is unavailable:

```text
.eval/
  <benchmark-name>/
    baseline/
      walkthrough.html
      walkthrough.json
      run-report.json
      workspace-snapshot.json
    candidate/
      ...
```

## Operator Subagent Prompt Template

Use one operator subagent per checkout.

```text
You are running a benchmark of the walkthrough skill.

Use the local SKILL.md in this checkout as the workflow source of truth.
Use only the benchmark manifest at: <manifest-path>
Write all outputs to: <run-output-dir>

Rules:
- Do not widen or narrow the benchmark scope.
- Use the frozen session selection from the manifest.
- Record any fallbacks, missing data, skipped steps, or deviations in run-report.json.
- Preserve intermediate artifacts needed for later comparison.
- Produce the final walkthrough.json and walkthrough.html.
- If a step cannot be completed, report the exact blocker and stop rather than silently changing scope.
```

## Run Checklist

Use this checklist for both `baseline` and `candidate`.

### 1. Inputs
- Confirm the manifest file is identical for both runs.
- Confirm the same `sessions.json` or explicit session list is used.
- Confirm the same audience and media mode are used.
- Confirm the same target feature repo is used.

### 2. Skill Run
- Run discovery only if required by the manifest.
- Run batch preprocessing or equivalent deterministic steps.
- Run validation on normalized/projected/chunk outputs.
- Produce summaries.
- Produce `draft-walkthrough.json`.
- Produce final `walkthrough.json`.
- Render final `walkthrough.html`.

### 3. Run Report
Each run should record at least:

```json
{
  "benchmark_name": "...",
  "skill_version": {
    "walkthrough_commit": "...",
    "walkthrough_branch": "..."
  },
  "target_repo": {
    "root": "...",
    "branch": "...",
    "commit": "..."
  },
  "inputs": {
    "audience": "...",
    "media_mode": "...",
    "sessions_file": "..."
  },
  "artifacts": {
    "normalized": "...",
    "projected": "...",
    "manifest": "...",
    "walkthrough_json": "...",
    "walkthrough_html": "..."
  },
  "hard_gate_results": {
    "validate_pipeline": "pass|fail",
    "broken_editor_links": "pass|fail",
    "external_requests": "pass|fail",
    "html_safety": "pass|fail"
  },
  "fallbacks_used": [],
  "deviations": [],
  "notes": []
}
```

## Browser Review Checklist

Open both HTML files in the browser.

Check these items for both `A` and `B`:
- Does the page load cleanly?
- Are there unexpected network requests?
- Do editor links look correct?
- Does search behave coherently?
- Does step navigation match visible state?
- Do evidence modals open correctly?
- Do screenshot galleries behave correctly?
- Does the page remain readable if network access is disabled?
- Is the artifact easy to scan as an engineer?

Record browser findings in:
- `review/browser-findings.md`

Suggested structure:

```md
# Browser Findings

## A
- Load behavior:
- Network requests:
- Link correctness:
- Search/navigation:
- Evidence modal/gallery:
- Readability:
- Notable issues:

## B
- Load behavior:
- Network requests:
- Link correctness:
- Search/navigation:
- Evidence modal/gallery:
- Readability:
- Notable issues:
```

## Qualitative Review Rubric

Each reviewer should assess `A` and `B` independently before comparing notes.

### Review Questions
- Which output better explains what changed?
- Which output better explains why it changed?
- Which output is more clearly tied to the actual repo and files?
- Which output makes evidence easier to inspect and trust?
- Which output is easier to navigate and absorb in the browser?
- Which output would you rather hand to a teammate coming in cold?

### Reviewer Template

Create one file per reviewer:
- `review/reviewer-you.md`
- `review/reviewer-codex.md`
- `review/reviewer-claude.md`

```md
# Reviewer: <name>

## First-pass verdict
- Better overall: A | B | Tie

## Dimension-by-dimension
- Repo applicability:
- Provenance trust:
- Developer comprehension:
- Noise reduction:
- Evidence usability:
- Viewer interaction quality:

## Notes on A
- Strengths:
- Weaknesses:

## Notes on B
- Strengths:
- Weaknesses:

## Decisive reasons
- 
```

## Comparison Report Template

After the three independent reviews, synthesize them into `review/comparison.md`.

```md
# Benchmark Comparison

## Benchmark
- Name:
- Feature repo:
- Baseline walkthrough commit:
- Candidate walkthrough commit:
- Audience:
- Media mode:

## Expected Improvements
- 

## Hard Gates
- Pipeline validation:
- Editor link correctness:
- External network dependency:
- HTML safety:
- Size budget:

## Browser Findings
- A:
- B:

## Reviewer Verdicts
- You:
- Codex:
- Claude:

## Areas of Agreement
- 

## Areas of Disagreement
- 

## Final Decision
- Winner: A | B | No clear winner
- Why:
- Regressions still present:
- Follow-up work:
```

## Decision Rule

Use this rule consistently:

1. Candidate must pass the hard gates.
2. Candidate should win the qualitative review on the targeted dimensions.
3. If reviewers disagree sharply, do not overstate the result.
4. If the claimed improvement is mostly editorial, rerun the benchmark 2-3 times before calling it established.

## Starting Recommendation

Use this first benchmark:
- benchmark name: `solstice-form-behavior`
- audience: `teammate`
- media mode: `extract`
- baseline: last known pre-remediation commit
- candidate: current branch

Then add a second benchmark using `fastloop-gcp` after the first benchmark is stable.
