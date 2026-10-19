# Complete bullet rewrites (Task11)

Company context is optional: set `company_context_enabled: true` and
`company_context_path: "config/resume_company_context.json"` in the optimizer
configuration. The shared all-bullets path reads the catalogue once per job,
matches original company headings through explicit aliases, and sends only the
matching profile with that group's bullet requests, including retries. Unmatched
groups proceed without company context and are listed in the match report.
The exact catalogue is saved as `company-context.json` in the run directory and
covered by the artifact manifest; the report records its hash and group matches.
This adds business context to drafting without changing source-check settings,
Academic Distinctions preservation, or attachment eligibility. Relative catalogue paths resolve from
the repository/application resource root, independently of the launch directory.

To use synthetic rewriting in the normal LinkedIn upload flow, set
`content_policy: "synthetic_jd_test"`, `source_checks_enabled: false`,
`rewrite_all_bullets: true`, and `optimization_mode: "full"` in the saved optimizer
JSON. With resume AI enabled, run
`python runAiBot.py --configured-search-and-apply --fresh`. Each job uses the same
generation, verified PDF upload, Next/Review/Submit, receipt and quota flow as
`jd_rewrite`; existing pause settings still apply. The report retains its synthetic
label: content is JD-generated and is not verified applicant evidence. Complete
coverage, formatting, Academic Distinctions and per-job/config binding remain
required. An explicit synthetic preview requested under a different runtime
policy, or an offline/saved-response fixture, cannot become an upload attachment.

`rewrite_all_bullets` defaults to **false**, independently of content policy,
optimization mode, title replacement and concurrency. Enable it only with
`bullets` or `full`. The dashboard exposes the flag and concurrency (1–4,
default 2), background progress and cancellation. The optimizer CLI accepts
`--rewrite-all-bullets`, `--no-rewrite-all-bullets`, and
`--rewrite-experience-concurrency {1,2,3,4}`. Explicit call options override
saved configuration without modifying saved values.

The separate strict path inventories the original DOCX before curated-bank
substitution. Each bounded worker receives the complete exact JD and the
policy-specific context. Grounded and review-draft workers receive the immutable
original experience; JD-only policies use the references or metric hints described
by their generation policy.
Academic Distinctions is always preserved verbatim, excluded from rewrite
requests and reported separately from eligible bullet coverage. Its text and
run formatting are checked in the final document. This exclusion also applies
to synthetic JD experiments and unchecked exports using older inventories.
Ordered sub-batches contain at most 12 requested IDs. IDs bind
the source hash, paragraph and ordinal. Retries request failed IDs only and
retain successful siblings. Grounded and review-draft source-content checks are
conservative heuristics and still require human content review. `jd_rewrite` and
`synthetic_jd_test` bypass those source-content gates; artifact verification does
not establish the truth of their claims or require a minimum keyword score.

The configured LinkedIn run logs resume preparation, keyword requests, bullet
candidate counts, retries, rendering, verification and upload. While optimization
is waiting, a heartbeat reports the current stage and elapsed time every 15
seconds. Candidate counts are provisional until final PDF checks pass. Progress
messages omit JD/resume text and provider response bodies; they do not alter
timeouts, request budgets, upload eligibility or submission settings.

For JD-led policies, enable `skills_expand_to_fill: true` to preserve the original
Skills line count and fill the measured usable width. The existing keyword call
returns direct JD scoring targets separately from broader `skill_candidates`:
named technologies, engineering practices and closely implied capabilities.
Candidates rank direct JD first, expanded JD next, then relevant original Skills
and configured-bank entries. Titles, years, eligibility and logistics are removed;
aliases are deduplicated. Older keyword responses without the new array remain
usable through the source/bank fallback pool.

`skills_target_fill_ratio` defaults to `0.97`; `skills_min_fill_ratio` defaults to
`0.92`. Whole terms are packed into the source line slots using the original
font's measured widths. Final PDF checks require the original line count, no
overflow and the minimum fill on every Skills line, while preserving original
fonts, margins, spacing and page count. Expanded candidates never enlarge the JD
scoring denominator. With this explicit flag, `max_skills` is the priority-pool
size rather than a hard final count: extra candidates can fill the source block,
and the report records the actual count, provenance and expansion beyond that
limit. The default flag is off; saved user settings enable it for subsequent runs.

Every actual dispatch reserves estimated input/output capacity atomically.
The per-run ceiling is one keyword request plus twice the sum of
`ceil(group_bullets / rewrite_bullets_per_request)`, subject to stricter request/cost/experience limits.
SDK hidden retries are disabled. Shared rate limits and 429 cooldown honor
Retry-After; waits, in-flight timeouts and backoff consume the wall deadline.
Costs are conservative reservations, not a claim of actual billed cost.
Provider response IDs and usage are retained when supplied. Auth/permission
failures cancel undispatched work. Cancellation rejects late results and
cannot reverse previously incurred provider charges.

Workers return data only. A single writer assembles a copied DOCX in original
order, replacing Skills as configured and preserving paragraph/run formatting
and links. Actual PDF
geometry requires every accepted bullet on exactly one nonempty line inside
its original usable width. A glyph-width estimate guides bounded retries;
final rendered geometry decides acceptance. There is no minimum fill in this
mode; existing default-mode and Skills density checks remain. Pagination
changes are reported; one-line compression may leave whitespace.

Runs have unique directories under `temp/task11/`, with original/optimized
DOCX/PDF, exact JD text, source inventory, coverage, scoring manifest, report,
artifact manifest and an escaped original/draft/JD comparison. Original source
files remain unchanged. `verify_binding(run_directory)` verifies source and
output hashes before review. The same JD, keyword universe, bank hash, methods
and weights score actual before/after artifact text. All scores are **local
heuristic match estimates, not employer ATS rankings, verified qualifications
or hiring probabilities**. Inspect required/preferred/context and bounded
keyword evidence separately, including missing and removed terms.

Only every-bullet substantive acceptance plus global format checks can set
`rewrite_completed`. By default, missing, unchanged, source-retained, failed,
cancelled or budget-blocked IDs produce explicit partial/blocked reports. Such
previews return no accepted PDF and cannot fall back to Skills-only success.

Set `rewrite_source_fallback_enabled: true` in the saved optimizer JSON to retain
an individual bullet's exact original text after its bounded rewrite attempts
fail. Successful sibling rewrites remain in the document. A mixed result keeps
`rewrite_completed: false`, but may set `document_complete: true` and
`completion_mode: "source_fallback"` when every slot is accounted for and all
global PDF, Skills, preserved-section and artifact-binding checks pass. Coverage
reports distinguish accepted rewrites, source fallbacks and unresolved slots,
and retain each failed rewrite's reason. This flag defaults to false.

Mixed-result uploads require the current configuration to explicitly enable the
flag, at least one accepted rewrite and a real provider response. Cancelled,
wholly failed, offline and invalid-layout runs remain ineligible. The upload
helper never substitutes the entire source resume for an incomplete strict run.
Application routing integrations must honor completion and artifact binding;
the offline test workflow never uploads or submits an application.

LinkedIn uploads reacquire the current job's application dialog after generation
and while confirming the selected attachment. Stale controls receive up to three
attempts using the same verified PDF; this does not restart generation. If the
selected job changes, attachment stops. A recognized fit-warning dialog clicks
Continue applying once before form navigation. Cleanup closes that warning
without continuing it, and opening failures retain a screenshot before cleanup.

## Reproduce offline checks

```
python3 -m unittest discover -s tests -p 'test_resume_all_bullets.py' -v
TASK11_INPUT_ROOT=/path/to/pinned/evidence/baseline \
TASK11_OUTPUT_ROOT=/path/to/new/task11-e2e \
python3 tests/test_resume_all_bullets_e2e.py -v
```

The E2E harness verifies the plan's exact source/JD hashes, blocks socket
connections, uses historical canned fixtures with out-of-order
completion, and uses actual DOCX assembly, LibreOffice PDF conversion,
geometry, Skills/link checks, matching and artifact binding. It compares
concurrency 1 and 2. The newer source-content retention gate rejects these
older fixture rewrites as partial because they omit source details; their old
54/54 and 53/54 acceptance counts are historical, not current fidelity proof.
The focused combined-tailoring tests separately verify complete synthetic
Skills/bullet/title assembly with real rendering. Missing inputs
or rendering dependencies mean unavailable, never a claimed E2E pass.

Live execution uses only an already configured local environment/.env key
through the existing OpenAI client, with no remote credential provisioning.
Do not put keys in fixtures, reports, source files or commands. A live run may
still be partial; fixture validation and genuine provider responses are
reported distinctly. Every draft requires content and visual review.

## Configured model and parallel API calls

The all-bullets path uses `rewrite_model` and `rewrite_reasoning_effort` for
keyword extraction and bullet generation. Standalone automatic title extraction
uses the same model options. For GPT-6 Luna use:

```json
{
  "rewrite_model": "gpt-6-luna",
  "rewrite_reasoning_effort": "none",
  "rewrite_token_estimation": "byte_upper_bound",
  "rewrite_experience_concurrency": 4,
  "rewrite_bullets_per_request": 4,
  "rewrite_requests_per_minute": 60,
  "rewrite_tokens_per_minute": 240000,
  "rewrite_input_usd_per_million": 0.1,
  "rewrite_output_usd_per_million": 0.5
}
```

These are saved-user overrides, not bundled defaults. Use byte estimation when
the installed tokenizer cannot resolve the model. Admission uses conservative
estimates and spaces request starts; four workers do not guarantee four
requests overlap. Each experience processes its own batches sequentially.
Keyword extraction precedes rewriting, and PDF assembly/rendering follows it.
Limits apply to one optimizer run; multiple bot processes do not share a limiter.
LinkedIn processes jobs sequentially. The supported worker range is 1–4.

The model-switch check verified one small structured-output request with zero
reasoning tokens. It did not evaluate a complete Luna resume rewrite's quality.
