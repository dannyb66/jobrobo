# Prepare an application from a job URL

Run from the repository root:

```sh
python direct_apply.py prepare \
  --url 'https://employer.example/careers/job' \
  --discovery-source 'Web search'
```

By default this opens a dedicated visible local Chrome session, reads the posting, generates a
job-specific résumé, fills supported fields and stops at final review. It has
no submission option. Saved pause/background settings cannot enable submission.
The owned local browser closes after evidence is saved. `--leave-open` keeps the last
draft visible; close that dedicated window before reusing its profile.
The browser blocks final application clicks, Enter submission, submit events
and native form submission methods. Non-final navigation is restricted to
observed application-entry and Next/Continue/Review controls.

`config/questions.py` saves the actual discovery source in `application_source`
(currently `"Web"`). `--discovery-source` overrides it for a particular run,
including a candidate override from the private question file. Referral-source
questions select an exact matching option or Other with the supplied description.
Leave the setting empty when unknown.

## Configuration and AI

Candidate values come from existing `config/personals.py` and
`config/questions.py`; optional private per-question overrides use
`external_questions_config_path` or `--questions`. Original résumé hyperlinks
and explicit current-employment records supply absent profile values. Existing
filled answers are preserved unless an explicit question override is supplied.

The existing `ai_cover_letter_enabled` and `ai_descriptive_answers_enabled`
settings control shared LinkedIn-style drafting. Original profile evidence,
the selected PDF, JD and exact question supply context. Drafts and their input
hashes are cached privately. Missing legal, demographic, consent, reference or
personal facts are not invented by AI. The user-selected
`unanswered_choice_policy = "first_option"` in `config/questions.py` chooses the
first non-placeholder option for otherwise unanswered native or accessible custom
selection fields, including factual questions. A single unanswered checkbox is
selected. These answers are recorded as `user_policy:first_option`, not verified
profile facts. Configured answers take priority; invalid explicit overrides,
ambiguous controls and unsupported widgets still need attention. Use `"manual"`
to disable this fallback. Free-text fields without a supplied fact remain unresolved.
`dei_choice_policy = "prefer_not_to_answer"` overrides the profile and first-choice
rule for DEI/demographic selections (ethnicity, communities, gender, age,
disability and veteran status). It selects the last refusal option such as
Prefer not to answer or Decline to disclose, otherwise None/None of the above.
If no explicit opt-out is offered, it leaves the question unresolved.
The configured `years_of_experience` also answers supported minimum engineering
experience checks; it is not treated as experience in a specific technology.
Configured city/country can answer current-location questions, while office
attendance remains a separate commitment.
Qualified sponsorship text may repeat the explicit configured sponsorship
answer; a visa label alone never establishes sponsorship or work authorization.

AI can recover an inaccessible question label only when its proposed label is
an actual substring of the observed nearby text. It cannot generate browser
code, arbitrary clicks or new answer facts through label recovery.

The local environment or `.env` supplies the optimizer key. Drafting can also
use the configured local provider key. The legacy shared-key service is not
called. Real generation/drafting may incur provider charges. Keys and provider
errors are excluded from preparation reports.

## Résumé generation and upload

Preparation reads the same effective JSON configuration as LinkedIn through
`peek_runtime_config()`. The saved file is
`~/Library/Application Support/jobrobo/config/resume_optimizer_defaults.json`;
missing options come from the repository's `config/resume_optimizer_defaults.json`.
Before the saved file exists, the repository defaults apply.

The configured optimization mode, content policy, source-check setting,
all-bullets setting, title replacement, bullet banks, model and concurrency are
passed unchanged to the shared `run_resume_optimization` entry point. The shared
optimizer selects its regular or strict all-bullets path. Preparation no longer
injects a separate per-entry optimizer or forces grounded settings. It never
edits either JSON file.

`--grounded-resume` remains accepted as a deprecated compatibility flag and
prints a notice; it no longer overrides the JSON. Omit it in new commands.
Choose grounded or other supported settings in the same optimizer JSON used by
LinkedIn. Strict outputs use LinkedIn's `verify_strict_attachment` check, bound
to the JD, job ID, source DOCX and exact configuration, before becoming upload
artifacts. Partial, stale or otherwise ineligible strict output is rejected.

Original DOCX/PDF bytes, JD and effective settings bind the generated result.
Generation failure has no original-résumé fallback. A completed result is reused
only when its input/output hashes match its prior independent format acceptance.
Strict cached artifacts also repeat the shared attachment verification. The
shared-engine cache version prevents reusing artifacts from the former
preparation-specific optimizer path. Changing JSON settings changes the cache
identity and requires a fresh generated PDF.
Generation is protected by a process lock. Abandoned or interrupted attempts are
archived in `resume/attempt-history`; retries use a separate output directory and
preserve prior artifacts. A live owner is never restarted. Recovering an attempt
may make new paid API calls; an interrupted request may already have been charged.

Accepted generated PDFs proceed directly to upload and form filling; no manual
PDF review is required. Previously cached, verified PDFs also proceed without
a review marker, so repeat the same prepare command after upgrading.
The CLI prints optimization stages, bullet progress and a 15-second heartbeat
while generation is running. Cache reuse, upload, form filling and any final
blockers are also printed; progress messages omit résumé and JD text.
Heartbeats include the number and age of active requests. Timeouts are reported
separately from connection failures; a timed-out bullet batch is split on its
existing retry, within the same request/cost/deadline limits. Width failures pass
a shorter numeric target to the next rewrite request without changing PDF checks.
The report provides `resume.pdf` and `resume.pdf_sha256`. For an optional visual
inspection record, the compatibility command remains available:

```sh
python direct_apply.py record-resume-review \
  --report /absolute/path/to/report.json \
  --pdf-sha256 SHA256_OF_THE_PDF_YOU_INSPECTED
```

The generated or cached PDF is uploaded
under a filename containing its job identity and content hash. The browser
hashes the selected file bytes before the site can clear its native file input.
Success requires that hash plus either the native attachment or the exact
visible filename receipt. Changing the PDF invalidates its cached hash binding
and requires verification again. Optional visual review establishes layout inspection, not an
independent verification of every candidate claim. AI prose follows the shared
LinkedIn drafting contract: usable prose is required, but source citations and
review flags are advisory, not a semantic proof of factual correctness.

The employer-facing upload filename uses
`Name_Resume_Company_Role__job-identifier-contenthash.pdf`. It retains the existing
job identifier and 12-character PDF hash. Only the upload copy is renamed; cached
optimizer artifacts and their content hashes stay unchanged.

## Several URLs and evidence

Two lists are included at the repository root: `jobs.txt` contains the ten URLs
that passed preparation through final review, and `jobs-untested.txt` contains
ten fresh postings whose application forms have not been tested by this task.
Only public posting metadata was checked for the untested list.

```sh
python3 direct_apply.py prepare --urls-file jobs.txt
python3 direct_apply.py prepare --urls-file jobs-untested.txt
```

To reuse previously generated and verified artifacts, supply the same
`--output-dir` used for that earlier run. A different output directory starts a
new resume cache and generates new PDFs.

Use one URL per line, with optional `#` comment lines:

```sh
python direct_apply.py prepare --urls-file /private/path/jobs.txt \
  --output-dir /private/path/preparation-evidence
```

The output directory defaults to `logs/url_preparations`. Each posting has a
JD snapshot, résumé binding, cached drafts, final screenshot, field-source
metadata, browser action history, current `report.json` and append-only attempt
history. `summary.json` describes the current invocation, including its exact
attempt count and prepared count. It does not change application history or
record any application as submitted. Existing protected ATS ledger entries are
respected. Treat all screenshots, drafts and evidence as private applicant data.

A `prepared` result requires all visible required fields to be valid, a verified
attachment and an identified enabled final submission control. Exit 0 means all
selected URLs prepared; exit 1 means at least one closed, blocked or failed;
exit 2 means command/configuration validation failed. A successful browser run
does not prove server-side acceptance because no application was submitted.
Unanswered optional questions are listed separately in the console and in
`report.json` under `optional_unanswered`; they do not prevent `prepared` status.
Custom menus that expose no matching option get one bounded reopen using a
fresh control reference. Supplied profile facts are not replaced by a different
first option when the matching configured option is temporarily unavailable.

Supported discovery includes native inputs, grouped choices, native selects,
accessible ARIA comboboxes, conditional fields, safe multi-step navigation,
embedded frames and open shadow roots. Custom controls without accessible
options, closed shadow roots, ambiguous posting/field identity, challenges,
account creation and missing facts remain explicit blockers. Any public job
URL can be inspected; universal automatic completion is not claimed.

Required labels expressed through supported field-wrapper styles and hidden
Yes/No proxies are inspected as well as native required attributes. Unrecognized
required wrappers block preparation. Unresolved autocomplete menus are dismissed
before the remaining form is inspected. Location autocompletes use the configured
city and state; a city name must match exactly, so San Francisco Bay Area is not
treated as San Francisco.

Custom phone-country controls verify both the observed country flag and dialing
code when only a calling code is displayed. A shared calling code alone does
not establish the selected country. Qualified work-authorization choices use
exact supported wording and explicit configured eligibility; ambiguous future
sponsorship choices remain unresolved.

LinkedIn's configured preparation-only run routes employer Apply links through
this engine when `external_apply_enabled=True` and `easy_apply_only=False`.
It uses a separate dedicated browser so its submission guard does not interfere
with LinkedIn navigation. Ordinary Easy Apply behavior remains separate.

Local browser regression (synthetic forms, no employer traffic):

```sh
JOBROBO_BROWSER_TESTS=1 PYTHONPATH=tests:. \
  python -m unittest test_generic_prepare_browser
```


## Submit using the same preparation flow

Every normal `submit` invocation starts a new independent run. It generates a
`run_id`, creates a directory under `logs/direct_submit`, and prints both. Run
from the repository root; no run ID, `RUN_DIR` variable or resume flag is needed:

```sh
roles="$HOME/Documents/Codex/2026-10-14/task/task1-location-fix/phase2/phase2-engineering-ranked-remaining.json"
python3 direct_apply.py submit --input "$roles" \
  --pause-before-submit always --limit 2
```

The generated `remaining` input reflects Task 1's geographically filtered
shortlist with submitted/duplicate/possibly submitted jobs removed. It refreshes
after submit checkpoints. Use the original `phase2-engineering-ranked.json`
instead when you intentionally want the complete shortlist, including repeats.
If the remaining file has not been generated yet, run
`python3 -m modules.submission_tracking` first.

Parallel workers are opt-in, bounded to four, and require the Kernel backend so
each worker owns an isolated browser session. A worker reuses that session for
its URLs, opening a separate tab per job. Local Chrome stays sequential because
its profile cannot be shared safely across workers:

```sh
python3 direct_apply.py submit --input "$roles" --browser kernel \
  --workers 3 --pause-before-submit always
```

The default worker count remains 1. With `always`, several jobs can be filled
at once in separate retained worker sessions, while the final Submit stays
manual. `--pause-before-submit never` also runs the final Submit concurrently.
Each URL still has an independent checkpoint, worker ID, and tab reference in
the run, and `--resume` reconnects unresolved worker sessions. The configured
application cap counts reservations across workers, preventing parallel jobs
from exceeding the run limit.

Repeat the same command to start another independent run. Previously applied,
failed or uncertain jobs can be attempted again when selected through the
original input or explicit URLs; the refreshed remaining input omits submitted
and uncertain jobs. A portal can
accept another application or report an existing one. Explicit fresh duplicate
messages after submission are recorded as `duplicate` with stage
`portal_duplicate`; processing continues to the next job.

`prepare` permanently disables submission. `submit` uses the same profile,
question policies, optimizer JSON, resume integrity and upload checks. Each job
opens in a new tab. The default final action is your manual Submit on that tab.

### Inputs and review modes

```sh
python3 direct_apply.py submit --urls-file jobs.txt --pause-before-submit always
python3 direct_apply.py submit --urls-file jobs-untested.txt --pause-before-submit always
python3 direct_apply.py submit --input /path/to/jobs.json --pause-before-submit unknown
python3 direct_apply.py submit --url 'https://employer.example/careers/job' --pause-before-submit always
```

Simple JSON may be an array of URLs or
`{"jobs": [{"url": "https://employer.example/careers/job"}]}`. Repeat `--input`
to merge files. Native saved `verified_roles` artifacts, including ranked JSON,
and legacy `direct-careers-queue-v1` files are also supported. Input order,
role/company IDs, original verification run, ranking run and source hashes are
retained. Old execution statuses in these files are historical context; fresh
runs check the current posting again. Inventory admission still applies, with
candidate preference exclusions displayed as warnings. A `companies` artifact
must first pass through `verify careers`; LinkedIn job artifacts belong to the
LinkedIn lane.

The older `verification-tiers/90-engineering-ranked.json` is broad engineering
inventory. Its Stockholm Modal role has `application_eligible=false` and
`location_excluded`, but this runner reports those application-preference fields
as warnings. All six earlier saved two-role runs used that older file, as
verified from their input paths and matching artifact hashes on 21 October 2026.
Stockholm is absent from the current Task 1 Phase 2 shortlist and its remaining
export. Selecting an input does not add geographic enforcement to explicit URLs.

`--limit 2` selects the first two deduplicated jobs. Use repeated `--role
'role:EXACT_ID'` to select saved roles explicitly. Within a run, duplicate URLs
and aliases do not cause another Submit action.

| Pause mode | Behavior |
| --- | --- |
| `always` | Default. Fill every selected job in its own retained tab; review/edit and Submit manually on the employer pages. |
| `unknown` | Hand off tabs with AI answers, first-option defaults, unverified values, recovered labels or required corrections. Other jobs submit automatically. |
| `never` | Submit automatically after required form, identity, resume and tracking checks pass. |

There is no separate review window. Once a tab is filled and its attachment
verified, the runner leaves it open and prepares the next job without waiting
for submission. It never clicks Submit in `always` mode. You can edit the form
and click its own Submit button; manual edits do not silently disable that click.
Tabs with required unanswered fields are marked `awaiting_correction`, not ready.
Optional blanks alone and AI resume optimization alone do not trigger `unknown`.
Explicit DEI opt-outs and configured facts are known sources. The removed PDF
review gate remains removed.

After filling, the process stays open to monitor employer outcomes across tabs,
without repeatedly switching your selected tab. Keep the terminal running while
you review. A confirmed employer success marks `applied`; a portal duplicate
marks `duplicate`; a known validation rejection stays open for correction and
another manual click. An unconfirmed activation becomes `submission_uncertain`,
and monitoring can still recognize a delayed confirmation. Closing a tab is not
proof of submission. Automatic retry never clicks a possibly submitted form.

Press **Ctrl-C** to save and leave Chrome tabs open. Use the printed explicit
resume command to reconnect to those live tabs and continue monitoring. Chrome
also stays open after confirmed manual outcomes. You close it when finished.
Failures are recorded and later jobs continue; useful failed tabs remain open
in the default manual mode.

The latest saved Task 1 Phase 2 shortlist contains **191 retained roles** (73
reconfirmed Phase 1 plus 118 new), verified on 15 October. The older 90-role
ranked file predates the location follow-up. `all-current-verified-roles.json`
contains 1,093 audit rows including excluded roles; use the ranked shortlist
above as application input. Saved verification is not a fresh live check today.

### Independent tracking and cached resumes

A run owns `state.sqlite3`, `input.json`, `progress.json`, `events.jsonl`,
`applications-ledger.json`, `applications.json`, `retry.json`, `retry.txt`,
`needs-review.json`, `manual-review.json`, `manual-review.txt` and its
`preparations/` reports/screenshots. Progress and
application exports include the run ID. Pipeline application identities include
both run and posting identity, so a later attempt does not replace an earlier
run's outcome.

Fresh runs do not read the old shared application ledger to decide eligibility.
The old ledger and earlier runs remain intact. The submit command's former
`--ledger` argument is deprecated; each run always uses its own ledger. The
legacy `run --queue ... --execute` and LinkedIn interfaces retain their existing
ledger behavior.

Hash-verified resume artifacts may be reused from `logs/url_preparations`
(or `--output-dir`). Reuse still checks the source, live JD, configuration and
output hashes. Sharing verified artifacts does not share application state.
New runs use dedicated Chrome profiles unless explicitly overridden.

`--run-dir` is optional. If its requested directory does not exist, that exact
path is used. If it already exists, a uniquely named sibling is created and
printed. It never silently resumes or overwrites an older run. Always use the
printed actual directory for status or explicit resume.

A canonical `applications.json` is kept in every run. `--output` adds an export
copy; when the requested file exists on a fresh run, the new copy gets a run-ID
suffix. Pipeline SQLite tracking retains separate records for each run.

### Submission history in the Task 1 review

`config/submission_tracking.json` links saved submit runs to the Task 1 Phase 2
role review. Each checkpoint automatically refreshes a reporting index and
`logs/direct_submit_tracking/runs.html`, with links to each run's progress,
uncertain outcomes, events and available preparation reports. Custom run
directories are registered too. Browser credentials and profile answers are
excluded from this index. A reporting failure leaves the application checkpoint
intact and prints a refresh warning.

Reload the role review to see the saved updates. Its **Application status**
filter defaults to hiding confirmed, duplicate and possibly submitted jobs.
Choose **All statuses**, the uncertain/manual groups, or an individual status
to inspect earlier outcomes. A confirmed submission takes precedence over later
failed/pending runs; every run's own status remains visible in its history.
An uncertain attempt is never labelled confirmed without confirmation evidence.

The original ranked JSON and verification timestamps stay unchanged. Beside it,
`*-with-submissions.json` includes the status history, while `*-remaining.json`
and `*-remaining.txt` exclude submitted/duplicate/uncertain jobs. You can use
either remaining file as `submit --input`; using the original input still
permits independent repeat applications as before. These filters do not change
the submit runner's admission or duplicate policies.

To backfill saved runs or refresh after changing the configured review paths:

```bash
python3 -m modules.submission_tracking
```

The configured `run_roots` are scanned for saved production progress; private
fixture hosts are omitted. There is no browser polling or employer action in
this refresh. Keep `submission_tracking.json` in any alternate `--config-dir`
where automatic tracker updates are wanted.

### Explicit resume, status and retries

Resume is optional and means continuing one existing run. It requires a path;
`--resume` alone is invalid. To start afresh, repeat the normal input command.
For recovery, use the actual directory printed by the run:

```sh
RUN_DIR='/absolute/path/printed/by/the/run'
python3 direct_apply.py status --run "$RUN_DIR"
python3 direct_apply.py submit --resume "$RUN_DIR"
```

Explicit resume keeps the selected jobs/order, configuration paths, pause policy
and cumulative cap. It reconnects live manual-review tabs rather than refilling
them. Applied and uncertain jobs are never automatically clicked again. Pending
pre-submit work can be reopened and revalidated. If the old browser/tab has been
lost, its manual outcome cannot be inferred: it enters `needs-review.json`
instead of being silently refilled. Unstarted jobs can continue in a new browser.
`--max-applications N` restricts the configured cap; outstanding manual tabs count
toward that cap. The cap resets on a fresh invocation.

Legacy run directories can be explicitly resumed. Only their owned attempt
claims are copied into a run-local ledger; unrelated shared history is ignored.
The source shared ledger is left unchanged.

`retry.json` includes failures and their recorded reasons; `retry.txt` contains
safe pre-submit retry links. A retry invocation is independent and preserves
its source run unchanged:

```sh
python3 direct_apply.py submit --input "$RUN_DIR/retry.json" --pause-before-submit unknown
```

`needs-review.json` keeps uncertain outcomes separately. Select the original
URL or role in a fresh run if you want another attempt; historical uncertainty
does not block it. For an inspected outcome, the optional `reconcile` command
updates local tracking in that specific run:

```sh
python3 direct_apply.py reconcile --run "$RUN_DIR" --role 'role:EXACT_ID' \
  --outcome applied --reason 'Employer confirmation inspected'
```

`--outcome not-submitted` records an inspected rejection/no-submission outcome
and adds that job to the run's explicit retry inventory. Close its old browser
before reconciling. Reconciliation is not required to start a fresh run.

### Pipeline alias

The official-careers pipeline alias uses this same independent-run engine:

```sh
python3 job_pipeline.py apply careers --input "$roles" \
  --set direct-applications --output logs/direct-applications.json \
  --pause-before-submit always --limit 2
```

Use `--db /path/to/pipeline.sqlite3` to select the pipeline store. Existing saved
verified-role set names are accepted with their database. The direct command
can also opt into pipeline tracking with `--db`, `--set` and `--output`.


## Optional Kernel cloud browser

Install the optional dependencies once:

```sh
python3 -m pip install -r requirements-kernel.txt
```

Set `KERNEL_API_KEY` in the environment or the ignored local `.env`. Keep the key
out of commands, JSON configuration and shared logs. The existing OpenAI settings
and shared resume optimizer JSON still apply; resume generation runs locally.
Kernel receives the job pages and selected PDF bytes.

Prepare without enabling Submit:

```sh
python3 direct_apply.py prepare --urls-file jobs.txt --browser kernel
```

The default submission command still fills one tab per job and waits for manual
Submit. Kernel opens the session's private live view for reviewing those tabs:

```sh
python3 direct_apply.py submit --input "$roles" --browser kernel --limit 2
```

To explicitly enable automatic final Submit with bounded CAPTCHA waiting:

```sh
python3 direct_apply.py submit --input "$roles" --browser kernel \
  --pause-before-submit never --limit 2
```

TXT, JSON, saved verified/ranked roles, role selection and `apply careers` use the
same backend. A fresh invocation creates its own run ID. Resume one saved run
using its printed directory; backend, cloud session ID and tab IDs are recovered:

```sh
python3 direct_apply.py submit --resume /absolute/path/to/printed/run-directory
```

`config/browser_runtime.json` keeps `local` as the default backend. Override its
path with `--browser-config`. Kernel defaults to headful stealth, one active job,
a 120-second CAPTCHA wait and a 900-second inactivity timeout (the smaller of
`timeout_seconds` and `failed_session_retention_seconds`). Locale/timezone and
proxy overrides are omitted by default; some require account features. Local
`--chrome-profile` cannot be used with Kernel. Optional `kernel.profile_id` uses
a separate existing cloud profile without saving new changes.

Only session/target IDs and redacted telemetry are persisted. Solver events
without page scope are saved as session diagnostics and never mark a job applied. Signed connection
and live-view URLs are reacquired from Kernel and stay out of reports. Completed
sessions are deleted. Manual/failed sessions disconnect and expire after the
configured inactivity budget. An open live view or reconnected CDP client counts
as activity and can extend their lifetime; close the view or delete the session
in Kernel when finished. A browser profile cannot restore a lost file input.

The solver operates supported CAPTCHA frames while the employer Submit guard
remains active. A solver success event alone never records an application.
Posting-scoped employer confirmation is required. Before-Submit CAPTCHA timeouts
enter the retry list; after a possible Submit, timeouts/disconnects remain
uncertain and receive no automatic second click. An explicit required-field
rejection is recorded for correction and a later retry. Login, OTP and email
verification remain separate manual-access outcomes. GPA uses explicit
`candidate.gpa` in the private question JSON or an exact per-question answer;
multiple GPAs in the source resume are not resolved by generating prose. `never` records unresolved
jobs and continues the batch without opening a mandatory review pause.

Kernel's [stealth documentation](https://www.kernel.sh/docs/browsers/bot-detection/stealth)
describes its managed solver; hCaptcha support is beta and account-dependent.
Supported generic form layouts and solver results are empirical, rather than a
guarantee that every portal will work.
