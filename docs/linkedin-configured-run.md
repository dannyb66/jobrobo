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
required reference answer; normal runs can request manual correction, while
preparation-only runs record the missing data. Existing filled text is preserved
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

`easy_apply_only=True` blocks company navigation regardless of pagination.
With False, the ordinary configured runner can collect company Apply URLs,
including modern company anchors scoped to the current job. A closed destination
is a closed target, not a completed application. Hosted form preparation is a
separate capability and is not introduced by this command.

The configured source paths are `default_resume_path` (PDF) and
`default_resume_docx_path` (DOCX). Review the exact pair and attachment on each
application. `use_AI_for_resume=False` selects the static-resume path;
enabling optimization uses a separate optimizer/key path and can incur API cost.
Changing optimizer defaults alone does not enable resume optimization. Keep
local credentials out of chat, screenshots, commits and command arguments.

Use `pause_before_submit=True`, `pause_at_failed_question=True`,
`run_in_background=False` and `run_non_stop=False` for a reviewed finite test.
`max_applications_per_run` caps confirmed submissions across all queries/cycles;
the default is one. A cap permits that many submissions, so it is not a no-submit
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

## Saved-job validation evidence (2026-10-15)

A submission-disabled replay tested 23 unique saved URLs: 22 reached enabled
Submit and discarded cleanly. The initial batch had 18 ready and five failures;
a failed-only follow-up recovered four. One direct posting lacked the employer
identity hook required by the bounded modern reader and was blocked before
form entry. Application history remained unchanged and no applications were
submitted. This does not establish that live submission succeeded.

The isolated publishing suite passed 817 offline tests. It covers later-job
resume attachment for AI prose and verified cleanup after normal form failures.
Private per-job evidence and retry URLs remain under ignored `logs/` paths.

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
