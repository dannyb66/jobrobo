# Configured LinkedIn search and apply

Run from the repository root with the Python environment that has this project's
dependencies installed. These commands need no `verified_roles` or
`linkedin_jobs` input artifacts.

## Check configuration before applications

```sh
python runAiBot.py --help
python runAiBot.py --diagnose-search --limit 5 --output /tmp/jobrobo-search-check.json
```

Help starts no browser or credential loader. The diagnostic opens its own browser,
collects configured-search metadata and closes it; it does not enter application
forms or upload a resume. Resolve any existing owner of the dedicated browser
profile first. Login/challenges require the user.

| File | Review |
| --- | --- |
| `config/search.py` | Terms, exact location, date, type, seniority, Remote/Hybrid, Easy Apply scope, exclusions, per-query quota and overall submission cap. |
| `config/search_profile.py` | Dynamic/manual lanes, skills, AI refinement, resume behavior and search-state directory. |
| `config/questions.py` | Resume paths, factual application answers, pause before Submit and failed-question pause. |
| `config/personals.py` | Profile facts and optional ordinary `preferred_first_name`; legal-name/surname/signature fields remain separate. |
| `config/settings.py` | Visible dedicated profile, non-stop mode and company-link behavior. |

Keep the credential configuration private. Do not open or commit keys while
reviewing these nonsecret files. A visa label alone does not establish citizenship,
permanent work authorization, future sponsorship or an office-attendance promise.
Review existing saved browser answers too. Required free-text answers need
supplied facts or grounded drafts. Configured radio/dropdown answers take
precedence; otherwise the first enabled non-placeholder option is selected
and reported for review.

`search_terms` is not necessarily the complete query list: enabled manual and
dynamic lanes are deduplicated and ordered by the search planner. AI refinement
can propose wording when enabled; turn it off for a fixed deterministic test.
`experience_level=[]` means no seniority filter even when Staff/Principal appear
in queries. `current_experience=-1` disables the numeric eligibility ceiling;
it does not establish the candidate's years-of-experience answer.

Prefer the native suggestion's exact label, for example `San Francisco Bay Area`.
The runner rechecks the modern interface after landing-prompt hydration. Inspect
committed location/filter evidence and warnings. Prompt-only Remote/Hybrid intent
and unavailable controls are not verified UI filter selections.

The modern JD reader waits up to 15 seconds for description content after the
job header appears. LinkedIn can render Easy Apply while the JD is still loading;
an early header alone does not establish that the description is unavailable.

## Start a fresh configured run

```sh
python runAiBot.py --configured-search-and-apply --fresh
```

**Validated on 18 October 2026:** fresh search-and-apply is working end to end,
including final Submit, LinkedIn confirmation, application-history recording and
stopping at the configured limit. An observed live run submitted and confirmed
two applications and verified their applied status again after reload. The user
also confirmed successful manual testing. Filters and limits still come from
the configuration; this validation does not imply every search result or UI
variation is supported.

This starts the same configured search/application runner as `python runAiBot.py`.
The explicit fresh command creates a new search manifest instead of resuming an
unfinished matching search. It restores the in-process resume setting afterward
and never edits saved config. Submission history, duplicates and uncertain
submissions remain protected; do not delete history to make a fresh test.

To honor saved unfinished-search resume behavior:

```sh
python runAiBot.py --configured-search-and-apply
```

Do not combine this entry with pipeline or diagnostic flags. It accepts only
`--fresh` and the preparation-only options below; read filters and application caps from configuration. The separate
`--mode search/apply/search-and-apply` commands belong to the staged pipeline
and retain its input/set contracts.

To exercise the first ten eligible Easy Apply forms with submission disabled:

```sh
python runAiBot.py --configured-search-and-apply --fresh --prepare-only --limit 10
```

This fills forms through the final enabled Submit screen, captures evidence,
and discards each draft. It never clicks Submit or opens external application
flows. Inspect the printed JSON report under `logs/form_validations`; an exit
code alone does not establish that all ten forms passed. Missing required
personal answers are recorded as blockers and the test continues after cleanup.

Set `references` in `config/personals.py` to your reusable professional-reference
text, including names, relationships and the contact details you want supplied.
Native reference textareas use that value. An empty setting cannot supply a
required reference answer; the current Easy Apply runner retains an unresolved application for retry
without a Help Needed popup; preparation-only runs record the missing data too. Existing filled text is preserved
unless a configured replacement is available and overwriting is enabled.

`test_references` contains clearly labeled synthetic data and is available only
in preparation-only mode. Submitting runs never fall back to this test setting.

`ai_cover_letter_enabled` and `ai_descriptive_answers_enabled` in
`config/questions.py` enable per-job AI prose independently of general AI and
resume optimization. The exact question, selected PDF's extracted text, explicit
candidate information and JD provide the drafting context. References and other
missing personal facts require configured answers. Generated prose is accepted
without local semantic, metric or citation validation. Empty/malformed responses
and API failures still require review.

Drafts are saved as `cover_letter.txt` and `answers.json` in a job-specific folder
beside the optimized resume, or under `all resumes/application_drafts/<job_id>`
for the static default resume. Answers are cached only when their full inputs
match; long text is fitted to field character limits. Existing filled answers are preserved
when overwriting is disabled. `upload_optimized_resume` remains the verified
attachment path, and its selected PDF supplies subsequent drafting evidence.

Preparation-only jobs and failed Easy Apply attempts are retained in
`logs/deferred_applications/retry_jobs.json`, with a compact clickable index in
`retry_jobs.md`. The runner saves the canonical job URL and JD before discarding
a prepared form. The archive deduplicates jobs and retains outcome history and
failure reasons. Historical failures may have uncertain submission state;
check application history before retrying them. Saving an entry does not apply
for the job or mark it applied.

Backfill a day's failed, interrupted and preparation-only jobs from saved logs:

```sh
python scripts/backfill_linkedin_retries.py --date 2026-10-15
```

The default date is today in `America/Los_Angeles`. Existing applied-history IDs
are excluded, and repeated backfills deduplicate source events.

## Application scope and resume

`application_mode` in `config/search.py` selects `external_only` (current),
`easy_apply_only`, or `both`, overriding the legacy `easy_apply_only` flag.
Without that setting, the legacy flag retains its previous behavior. External-only
mode clears the Easy Apply-only filter and skips Easy Apply results.

Employer links use the same preparation and submission engine as `direct_apply.py
submit`, including the shared résumé cache and `direct_submit_profile_path`.
`external_apply_enabled`, `external_apply_captcha_solver`, and
`external_apply_pause_before_submit` in `config/settings.py` control the handoff.
Only confirmed applications close their employer tabs; unresolved tabs remain
open while the search continues. See the [README employer-flow options](../README.md)
for configuration and the local browser regression command.

The configured source paths are `default_resume_path` (PDF) and
`default_resume_docx_path` (DOCX). Review the exact pair and attachment on each
application. `use_AI_for_resume=False` selects the static-resume path;
enabling optimization uses a separate optimizer/key path and can incur API cost.
Changing optimizer defaults alone does not enable resume optimization. Keep
local credentials out of chat, screenshots, commits and command arguments.

The local `pause_before_submit` is currently `False`. For a reviewed run, use
`pause_before_submit=True`, `pause_at_failed_question=True`,
`run_in_background=False` and `run_non_stop=False` for a reviewed finite test.
`max_applications_per_run` caps confirmed submissions across all queries/cycles;
the current `config/search.py` value is `50`. `switch_number=10` is the
per-query quota, overridden by explicit lane quotas such as the manual lane's `quota=1`. A cap permits that many submissions, so it is not a no-submit
guard. The ordinary pause dialog can disable pauses; do not disable it before
answers and attachments have been reviewed. Legacy background mode disables pauses.

## Verification and stopping

Offline tests cover CLI routing, fresh-state restoration, filter transitions,
preferred-name replacement, company-route guards, native/classic Easy Apply
navigation, saved AI drafts and retry retention. Required unsupported fields can
still require manual handling; entering a form is not evidence of submission.

Stop on unknown factual/consent answers, wrong attachments, unverified location,
closed roles or unexpected destinations. Preserve logs under `logs/search_runs`
and the configured CSV history. Do not infer submission from entering a form or
reaching its review screen.

## Optimizer settings and current dialog recovery

The saved optimizer JSON at
`~/Library/Application Support/jobrobo/config/resume_optimizer_defaults.json`
overrides bundled defaults. It is shared with direct employer preparation.
Current saved settings use all-bullets `full` mode, `synthetic_jd_test`, source
checks disabled, original-bullet fallback enabled, `gpt-6-luna` with reasoning
`none`, four workers/four-bullet batches, company context and Skills width packing.
These are dated local choices, not universal defaults. See the
[Task 11 option table and policy distinctions](TASK11-README.md#current-optimizer-options).

The application step optimizes once, verifies that PDF for the current
job/JD/source/config, uploads it, reacquires rerendered controls, and handles
Next pages before Review and Submit. Explicit original-bullet fallback can
qualify a fully verified combined PDF; it does not authorize uploading the
entire original PDF after an all-bullets generation failure. Progress logs show
API waits, provisional bullet counts, rendering, verification and upload, with
a heartbeat every 15 seconds while waiting.

Recognized match warnings use **Continue applying**, including link controls.
After a confirmed submission, the optional resume-to-profile promotion uses
**Not now**, including the variant saying the application is in the Applied tab.
It does not click Update profile. Unknown blocking dialogs remain blockers;
the runner does not blindly select the rightmost action. Recoverable job failures
remain pending/retryable and other work continues only after verified cleanup.

Confirmation is saved before optional dialog cleanup. If cleanup still blocks,
the run can stop with `post_submit_ui_blocked` while the job remains `applied`.
Close the old Exiting popup before starting a resumed command; changing code
cannot restart an application loop that has already exited. An Easy Apply platform daily limit or command cap can stop processing. Employer
uncertainty reserves capacity and remains protected from Submit replay while
other employer jobs continue; post-submit CAPTCHA solving is bounded to two calls. Preserve the manifest and diagnostics when investigating.

## Submission confirmation

The runner recognizes both explicit receipt dialogs and the modern job-specific
**Application status → Application submitted** panel. It compares the observed
state with the selected job's pre-submit baseline, so an existing applied panel
or a changed elapsed-time label cannot count as a new application. Missing
confirmation remains uncertain and blocks automatic resubmission.

An optional receipt can be dismissed after confirmation. Modern panels do not
require a Done button, and receipt-dismissal errors do not change a confirmed
application into a failure. Applied history and the invocation limit are updated
from the confirmed submission.
