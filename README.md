# LinkedIn AI Auto Job Applier 🤖
This is a web scraping bot that automates the process of job applications on LinkedIn. It searches for jobs relevant to you, answers application questions from your configured profile, customizes the resume using job information, and can submit Easy Apply applications. The bot can process many applications quickly, but it should be run with a submission pause enabled until the answers and resume output have been reviewed.


## 📽️ See it in Action
Click on above image to watch the demo or use this link https://youtu.be/gMbB1fWZDHw


## ✨ Content
- [Introduction](#linkedin-ai-auto-job-applier-)
- [Demo Video](#-see-it-in-action)
- [Index](#-content)
- [Install](#-how-to-install)
- [Current workflow](#current-workflow)
- [Repository map](#repository-map)
- [Run commands](#run-commands)
- [Job discovery pipeline](#job-discovery-pipeline)
- [Configure](#-how-to-configure)
- [Resume ATS optimizer](#resume-ats-optimizer)
- [Detailed documentation](docs/README.md)
- [Troubleshooting](#troubleshooting)
- [Dynamic Search Profiles](#dynamic-search-profiles)
- [Contributor Guidelines](#-contributor-guidelines)
- [Features](#-feature-list)
- [My letter for YOU ❤️](#-my-heartfelt-letter-to-you-)
- [Updates](#major-updates-history)
- [Disclaimer](#-disclaimer)
- [Terms and Conditions](#-terms-and-conditions)
- [License](#-license)
- [Socials](#-socials)
- [Support and Discussions](#community-support-and-discussions)

<br>

## Current workflow

The repository has two related workflows:

1. `runAiBot.py` drives the LinkedIn browser session. It searches using the values in `config/search.py`, filters jobs, reads the job and company information, answers Easy Apply questions from `config/questions.py` and `config/personals.py`, uploads the configured resume, and records the result in the CSV history files and `logs/`.
2. `JobRobo.py` opens the desktop dashboard. The **Run LinkedIn Bot** action loads and starts the browser automation. The **Resume Optimizer** tab saves optimizer settings and runs the ATS pipeline without starting Chrome.

For the ordinary DOCX path in `bullets` or `full` mode, the optimizer follows this sequence:

```text
Job description
      ↓
Existing keyword extraction + skills-bank guidance
      ↓
Skills section update
      ↓
JD-aware bullet rewrite for ordinary professional experience
      ↓
Exact, curated bullet-bank selection for Trek Health and the first three projects
      ↓
Optional job-title alignment (`full` mode)
      ↓
DOCX → PDF conversion → configured page-count/layout verification
      ↓
Accepted PDF + `.match_report.json` (or failure report)
```

With `rewrite_all_bullets=true`, a separate path inventories every eligible source bullet, rewrites ordered batches, updates Skills and optionally professional titles, then verifies the assembled PDF. Academic Distinctions stays unchanged. Failed bullet rewrites may retain their original text when `rewrite_source_fallback_enabled=true`; this is reported separately from a complete rewrite. See the [current Task 11 options](docs/TASK11-README.md#current-optimizer-options).

The optimizer can also run separately from the LinkedIn bot. You can generate and inspect a resume without starting Chrome, and you can use a static resume by running the bot without enabling resume optimization. A browser run can submit applications, so keep `pause_before_submit = True` while validating a new configuration.

## Repository map

| Path | Responsibility |
| --- | --- |
| `runAiBot.py` | Main LinkedIn automation entry point. |
| `JobRobo.py` | Tkinter dashboard for browser automation and resume optimization. |
| `config/search.py` | Search terms, location, filters, quotas, and skip rules. |
| `config/questions.py` | Application answers, resume paths, pause behavior, salary, visa, and profile inputs. |
| `config/personals.py` | Personal information used in application forms. |
| `config/settings.py` | Browser, timing, safe mode, stealth mode, logging, and legacy resume flags. |
| `config/resume_optimizer_defaults.json` | Bundled optimizer defaults; existing saved user JSON overrides matching fields. |
| `config/prompts/resume_bullets.txt` | Canonical bullet generation prompt, pinned per run with policy overrides. |
| `config/resume_company_context.json` | Company/project domain catalogue for all-bullets generation. |
| `modules/resume_all_bullets.py` | Parallel all-bullets generation, coverage, Skills/title assembly, review and binding checks. |
| `modules/ai/resume_optimizer.py` | Keyword guidance, skills optimization, bullet rewriting, bank selection, PDF/DOCX handling, and format verification. |
| `modules/resume_upload.py` | Optimized-PDF attachment and independently verified source-PDF fallback. |
| `config/skills/` | ATS vocabulary and role-profile guidance. |
| `config/bullets/` | Fact-preserving bullet banks for specific companies and projects. |
| `all resumes/default/` | Default DOCX/PDF resume uploaded by the bot. |
| `all resumes/temp/` | Generated, job-specific resumes and match reports. |
| `all excels/` | Applied and failed application history CSVs. |
| `logs/` | Runtime logs and failure screenshots. |
| `tests/` | Automated tests for the resume optimizer and format contract. |
| `docs/` | In-depth architecture, optimizer reference, ATS guidance, role positioning, and developer runbook. |

See the [documentation index](docs/README.md) for the tutorial, architecture explanation, configuration reference, ATS workflow, staff/principal positioning guide, current market notes, and maintenance runbook.

## Run commands

The command choices below use the current working-tree implementation. Configuration values are a dated snapshot, not universal defaults.

| Goal | Command / guide |
| --- | --- |
| Fresh configured LinkedIn search and apply | `python runAiBot.py --configured-search-and-apply --fresh` |
| Resume an unfinished LinkedIn search | `python runAiBot.py --configured-search-and-apply` |
| Inspect searches without application forms | `python runAiBot.py --diagnose-search --limit 5 --output /tmp/jobrobo-search-check.json` |
| Test ten forms/uploads with Submit disabled | `python runAiBot.py --configured-search-and-apply --fresh --prepare-only --limit 10` |
| Discover → verify → rank → search → apply | [Job discovery pipeline](#job-discovery-pipeline) |
| Prepare or submit employer URLs | [Direct job URL applications](#direct-job-url-applications) |
| Optimize a resume independently | [Task 11 commands and options](docs/TASK11-README.md#current-standalone-commands) |

From the repository root, create an isolated environment and install the dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate              # macOS/Linux
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Run the automated checks before changing the live application configuration:

```bash
python -m pip install -r requirements-dev.txt
python -m py_compile modules/ai/resume_optimizer.py modules/config_loader.py JobRobo.py
python -m json.tool config/resume_optimizer_defaults.json >/dev/null
python -m unittest discover -s tests -v
```

Start the browser automation only after Chrome is closed or the dedicated JobRobo profile is configured:

```bash
python runAiBot.py
```

Open the dashboard when you want to configure and run the optimizer interactively:

```bash
python JobRobo.py
```

DOCX optimization requires LibreOffice in addition to Python dependencies. The converter checks `LIBREOFFICE_PATH`, `soffice` / `libreoffice` on `PATH`, and the macOS application path. All optimizer modes require an OpenAI API key for JD keyword extraction.

The optimizer can also be called from Python without opening the dashboard. Repository defaults fill missing fields in the saved user configuration at `~/Library/Application Support/jobrobo/config/resume_optimizer_defaults.json`; existing user choices remain authoritative:

```python
from modules.ai.resume_optimizer import run_resume_optimization

output_path = run_resume_optimization(
    job_description="Staff AI platform engineer building secure LLM inference systems",
    resume_path="all resumes/default/resume.docx",
    job_id="local-smoke-test",
    job_title="Staff AI Platform Engineer",
    first_name="first",
    last_name="last",
    optimization_mode="skills",
)
print(output_path)
```

Use `optimization_mode="skills"` to update Skills only, `"bullets"` to update Skills and bullets, or `"full"` to also replace recognized professional-experience titles with the target title. `full` does not rewrite the summary or validate title equivalence. Use a distinct local job ID and inspect the returned PDF and report before an application run.

## Resume optimization from one file

Use [`optimize_resume.py`](optimize_resume.py) for an original resume plus complete JD text/file or a supported public JobPosting JSON-LD URL. It reuses the existing engine, supports `--mode full|bullets|skills`, independent `--replace-title` / `--no-replace-title`, opt-in `--rewrite-all-bullets`, and a new `--output` review directory. `--preflight` makes no OpenAI call. See [Task 11 commands, dependencies, mode/title semantics and limitations](docs/TASK11-README.md). Paid runs require an already configured local credential and separate authorization; this workflow never uploads or submits applications.

## Search and apply on LinkedIn without stage inputs

The configured bot searches LinkedIn directly from `config/search.py` and
`config/search_profile.py`, then processes matching jobs in the same session.
It does **not** require `verified_roles.json`, `linkedin_jobs.json`, a named
pipeline set, or the discovery pipeline below.

From the repository root, first inspect the configured search without entering
application forms:

```bash
python runAiBot.py --diagnose-search --limit 5 --output /tmp/jobrobo-search-check.json
```

After reviewing filters, profile answers and resume selection, start a fresh
configured search followed by application processing:

```bash
python runAiBot.py --configured-search-and-apply --fresh
```

This second command can fill/upload application data and reach submission.
Keep `pause_before_submit = True`, `pause_at_failed_question = True` in
`config/questions.py` and `run_in_background = False` in `config/settings.py`
while reviewing applications. Confirm each employer, answers and attachment.
Never treat a provisional first-option answer as a verified fact.

`--fresh` creates a new search manifest for this invocation; existing submission
history, duplicate protection and uncertain-submission checkpoints are preserved.
It temporarily disables unfinished-search resume without editing saved config.
Without `--fresh`, the explicit configured command honors
`resume_search_enabled`. The original `python runAiBot.py` shortcut still works.

Filters and the overall submission cap come from `config/search.py`:
`search_location`, `date_posted`, `job_type`, `experience_level`, `on_site`,
`easy_apply_only`, and `max_applications_per_run` (currently `50`).
`switch_number = 10` is the per-query quota; explicit search quotas take precedence.
These are different limits: an individual manual lane can still have `quota = 1`.
Use the exact `San Francisco Bay Area` location when selecting that native
suggestion. Remote/Hybrid intent and unavailable filter controls must be checked
in the actual results; a requested filter is not proof it was applied.
With `easy_apply_only = True`, company navigation is blocked even on result
layouts without pagination. Otherwise company Apply links can be collected;
an external link is not an application success.

Test the form and optimized attachment without submitting:

```bash
python runAiBot.py --configured-search-and-apply --fresh --prepare-only --limit 10
```

This fills supported forms through the enabled Submit screen, saves validation
evidence, and discards the drafts. The report can contain blockers; `--limit 10`
is a test budget, not a promise that ten forms passed.

The configured command accepts `--fresh` and `--prepare-only [--limit N]`;
`--limit` is rejected for a submitting configured run. Set its submission cap
in `config/search.py`. Pipeline `--mode`, `--input`, `--set`, `--db`, `--refresh`
and `--output` belong to the separate staged commands. The diagnostic's
`--limit` limits collected metadata, not confirmed submissions.
See the [configured LinkedIn run guide](docs/linkedin-configured-run.md) for
configuration, resume behavior, stopping and verification limits.

## Direct job URL applications

`direct_apply.py prepare` fills supported employer forms and uploads an optimized
resume with **submission permanently disabled**. `direct_apply.py submit` uses
the same preparation flow and defaults to **manual Submit on each employer tab**.
Run these commands from the repository root. Local Chrome is the default browser;
Kernel cloud browsing is optional.

### Choose the input

For this programme, use Task 1's current Phase 2 shortlist. The generated
`remaining` file excludes jobs recorded as submitted, duplicate or possibly
submitted across saved runs:

```bash
roles="$HOME/Documents/Codex/2026-10-14/task/task1-location-fix/phase2/phase2-engineering-ranked-remaining.json"
```

The original `phase2-engineering-ranked.json` retains the full 191-role shortlist;
`phase2-engineering-ranked-with-submissions.json` adds run histories to all roles.
The older `verification-tiers/90-engineering-ranked.json` is a broad inventory,
not the current geographically filtered shortlist. Earlier runs sourced the
Stockholm role from that old file. Application preference exclusions in a supplied
inventory are currently **warnings**, so choosing the current filtered input
matters. Explicit URLs and the old inventory are not automatically geographically
filtered by `submit`.

Both `prepare` and `submit` accept one `--url`, a `--urls-file`, or repeated
`--input` files. Inputs support one URL per TXT line, URL-array/simple job JSON,
saved verified/ranked `verified_roles` JSON, and legacy queues. An existing
verified-role set name can be supplied with `--input NAME --db PATH`.
`jobs.txt` is the preparation pilot list; `jobs-untested.txt` is the separate
untested list. Neither filename changes submission behaviour. Shell variable
names are case-sensitive: use lowercase `"$roles"` consistently.

For the final ten-job cross-provider sample (nine Task 1 remaining roles plus
the approved generic replacement), use [`jobs-validation.txt`](jobs-validation.txt) or the local
`jobs-validation.json` metadata file. The metadata JSON is kept private because
it contains original scraped descriptions and source data. The ten-case sample covers
Ashby, Lever, Greenhouse and one generic entry. See the
[manual validation commands, coverage limits and feedback plan](docs/manual-validation-run.md).

### Prepare without submitting

```bash
python3 direct_apply.py prepare --url 'https://employer.example/careers/job' --leave-open
python3 direct_apply.py prepare --urls-file jobs.txt
python3 direct_apply.py prepare --urls-file jobs-untested.txt
python3 direct_apply.py prepare --input "$roles" --limit 2
```

Preparation saves evidence, prints blockers, and normally closes its browser.
`--leave-open` keeps the final draft visible. `--url` is unnecessary when a file
is supplied. `--grounded-resume` is deprecated and unnecessary: both direct and
LinkedIn flows read the same saved resume optimizer JSON.

### Manual review or automatic Submit

```bash
# Default: fill a new tab per job, continue the batch, then monitor manual Submit.
python3 direct_apply.py submit --input "$roles" --limit 2

# The same default workflow with an untested TXT list.
python3 direct_apply.py submit --urls-file jobs-untested.txt --limit 2

# Pause only for unknown/defaulted answers or required corrections.
python3 direct_apply.py submit --input "$roles" --pause-before-submit unknown --limit 2

# Explicit automatic final Submit, using local Chrome.
python3 direct_apply.py submit --input "$roles" --pause-before-submit never --limit 2
```

| Pause mode | Final action |
| --- | --- |
| `always` | Default. Review/edit and click Submit manually on the employer tabs. |
| `unknown` | Manual tabs for AI/defaulted answers, recovered labels or required corrections; other jobs submit automatically. |
| `never` | Automatically click Submit after the required form, identity, attachment and tracking checks pass. |

There is no separate review window or required PDF review gate. Keep the process
running while submitting manually; it observes outcomes across retained tabs.
Ctrl-C saves progress. A fresh command creates a new run ID and directory and
can attempt previously submitted URLs again. The status-filtered input is an
optional way to avoid repeats; cross-run reporting does not block fresh runs.

Parallel batches are opt-in and use isolated Kernel browser sessions per worker:

```bash
python3 direct_apply.py submit --input "$roles" --browser kernel \
  --workers 3 --pause-before-submit always
```

`--workers` accepts 1–4 and defaults to 1. Values above 1 require `--browser
kernel`; local Chrome uses one profile and remains sequential. With the default
`always` mode, workers prepare jobs concurrently in separate sessions, then
leave their job tabs open for manual review. Each worker reuses its own session
for subsequent URLs. `never` explicitly allows concurrent automatic
submissions. Every job’s worker, tab, and status are checkpointed in the run,
so `--resume` can reconnect unresolved worker sessions. The configured
application cap still applies across all workers.

### Kernel cloud browser and CAPTCHA handling

Install the optional dependencies and configure `KERNEL_API_KEY` in the ignored
local `.env` or environment; never put the actual key in a README or run report.

```bash
python3 -m pip install -r requirements-kernel.txt
python3 direct_apply.py prepare --input "$roles" --browser kernel --limit 2
python3 direct_apply.py submit --input "$roles" --browser kernel --limit 2
python3 direct_apply.py submit --input "$roles" --browser kernel --pause-before-submit never --limit 2
```

Manual Kernel runs open a private live view for reviewing the tabs. Kernel can
solve supported CAPTCHA challenges; the runner waits within its configured
budget and checks the employer page afterwards. CAPTCHA success alone does not
mean an application was submitted. Employer confirmation, including Ashby's
success banner, establishes `applied`. An unconfirmed possible activation stays
`submission_uncertain` without an automatic second click.

Some portals complete a solved challenge by clicking a hidden submit control or
calling the native form method. That single continuation is allowed only for the
original validated form, with a response token and unchanged application answers.
A second final activation remains blocked. Solver readiness and employer
submission confirmation are tracked separately.

A third-party application service may accept a request into its own queue and
promise to submit later. The run records `external_submission_pending` under
`submission_uncertain`, protects that attempt on resume, and waits for evidence
of employer submission before treating it as applied.

`config/browser_runtime.json` controls backend, stealth/headless settings,
challenge/session timeouts and optional Kernel profile/proxy settings. Use
`--browser-config PATH` for another file. `--chrome-profile` applies to local
Chrome and cannot be combined with Kernel. See the
[Kernel setup, retention and limitations](docs/generic-url-preparation.md#optional-kernel-cloud-browser).

### Status, resume, retries and reconciliation

No `RUN_DIR` or run ID is required for a fresh run. To inspect or continue one
specific run, copy the actual directory printed by that command:

```bash
RUN_DIR='/absolute/path/printed/by/the/run'
python3 direct_apply.py status --run "$RUN_DIR"
python3 direct_apply.py submit --resume "$RUN_DIR"

# Retry only eligible failures proven to have occurred before Submit, in that run.
python3 direct_apply.py submit --resume "$RUN_DIR" --retry-failed

# Start a fresh run from that run's retry inventory.
python3 direct_apply.py submit --input "$RUN_DIR/retry.json" --pause-before-submit always

# Record an inspected outcome locally; this command never submits a form.
python3 direct_apply.py reconcile --run "$RUN_DIR" --role 'role:EXACT_ID' \
  --outcome applied --reason 'Employer confirmation inspected'
```

`--resume` requires a directory and takes its saved selection; do not combine it
with `--input`, `--run-dir`, `--role` or `--limit`. It reconnects retained review
tabs and continues pending work, preserving the browser backend. Applied or
uncertain jobs in that same run are not automatically submitted again. Use
`--outcome not-submitted` only after inspecting a failed/rejected outcome; this
adds it to the retry inventory. Reconciliation does not open a browser.

Each run saves `progress.json`, `events.jsonl`, `applications.json`, its own
ledger/state database, preparation reports, `retry.json`/`retry.txt`,
`needs-review.json` and manual-review files. `applied` means confirmed;
`awaiting_manual_submit` needs your click; `awaiting_correction` needs edits;
`awaiting_email_verification` retains the original tab for your emailed code;
`submission_uncertain` needs outcome inspection. Failed pre-submit work is kept
for retry. `--run-dir` optionally selects a destination; an existing destination
gets a unique sibling rather than being overwritten.

Email verification is separate from CAPTCHA solving. Automatic mode continues
other jobs and retains verification tabs without replaying Submit. Explicit
resume reconnects those tabs. `--retry-failed` requires `--resume` and leaves
confirmed and possibly submitted attempts protected.

### Task 1 tracking, profile answers and resume settings

Every submit checkpoint updates the cross-run report at
`logs/direct_submit_tracking/runs.html`. Task 1's role review links each run and
its submitted, uncertain, manual and other statuses. Reload it and use
**Application status** to hide submitted/uncertain jobs or inspect specific
outcomes. Earlier uncertain attempts remain visible even after another run
confirms submission. Remaining JSON/TXT inputs are regenerated beside the
original shortlist; the original verification data is preserved.

`config/submission_tracking.json` selects run roots, output location and linked
role reviews. To backfill or refresh saved records without browser actions:

```bash
python3 -m modules.submission_tracking
```

Profile inputs come from `config/personals.py`, `config/questions.py` and the
private file selected by `external_questions_config_path` or `--questions`.
GPA uses explicit `candidate.gpa` (configured locally as `"3.8"`). Website/GitHub
and discovery source come from their configured fields. The configured
first-option fallback handles otherwise unanswered choices; DEI questions use
the last available refusal/None option. AI drafts descriptive answers when
enabled; missing free-text personal facts remain unresolved. `unknown` mode flags
first-option and AI answers for manual review.

Job-URL submissions can additionally read a private JSON profile from
`~/.jobrobo/direct-submit-profile.json`, selected by
`direct_submit_profile_path` in `config/settings.py`. Supported keys are `email`
and `signature_date_policy`. An explicit email override replaces older resume
autofill for this workflow. With `"signature_date_policy": "completion_date"`,
recognized application signature dates use the machine's local completion date
(ISO for date controls, MM/DD/YYYY for text controls). Birth, employment and
unidentified dates still require their own answers. The same date policy can
be set in the private question JSON for both `prepare` and `submit`; it is
configured there locally too. These submit-profile overrides apply to
new preparation within `submit`, including resumed pending jobs; they do not
change LinkedIn settings, historical submissions or pending verification emails.

After resume upload, the runner waits within a bounded budget for parsing and
preserves valid populated fields. It rechecks fields before writing and verifies
committed autocomplete choices after selection. Changed posting identities stop
before applicant data is entered. Kernel diagnostics store bounded error
categories and sanitized request paths, excluding request bodies and query strings.
Location controls use country context when they describe eligible countries;
phone readback accepts formatting while preserving the supplied digits. Resume
analysis can take up to the bounded processing budget; a service error is saved
as a pre-submit failure rather than an accepted attachment or application.

Direct applications share LinkedIn's optimizer JSON at
`~/Library/Application Support/jobrobo/config/resume_optimizer_defaults.json`,
with repository defaults as fallback. Verified PDFs are cached by original
resume, JD and optimizer settings. Logs show generation stages, API waits,
bullet progress, cache reuse and upload. The uploaded copy has a readable
`Name_Resume_Company_Role__identifier-contenthash.pdf` filename. Resume integrity
and attachment checks remain active without a manual PDF approval requirement.

| Additional option | Purpose |
| --- | --- |
| `--role 'role:ID'` | Select an exact saved role; repeat for several roles. |
| `--limit N` | Select the first N deduplicated input jobs. |
| `--max-applications N` (submit) | Restrict the configured submit cap; outstanding manual tabs count toward it. |
| `--config-dir PATH` | Use another profile configuration directory. Include its tracking config for automatic tracker updates. |
| `--questions PATH` | Use a private question/candidate override JSON. |
| `--discovery-source 'Web'` | Override the actual referral/discovery source for this run. |
| `--output-dir PATH` | Select the shared preparation/resume cache location. |
| `--db PATH --set NAME --output PATH` (submit) | Add pipeline database/set tracking and an application JSON export. |

`submit` replaces the older queue-execution command for this workflow; legacy
`plan`, `run --queue ... --execute` and `export --queue ...` remain available.
For detailed input contracts, troubleshooting and tested coverage, see the
[direct preparation and submission guide](docs/generic-url-preparation.md).

## Job discovery pipeline

The pipeline separates company discovery, verification against official careers pages, LinkedIn collection, and selected-job application. Each stage saves cumulative records in SQLite and can export a portable, versioned JSON set for the next stage.

```bash
python -m job_pipeline discover companies --set ai-companies --limit 25
python -m job_pipeline verify careers --input ai-companies --set hiring-roles --limit 25
python -m job_pipeline rank careers --input hiring-roles --set ranked-roles
python -m job_pipeline search linkedin --input ranked-roles --set linkedin-candidates --limit 25
python -m job_pipeline apply linkedin --input linkedin-candidates --set reviewed-applications --limit 1
```

Discovery and verification have independent budgets in `config/job_pipeline.py`: `discovery_limit_per_source`, `discovery_source_limits`, `discovery_target_companies`, `verification_limit_companies`, refresh/render flags, and established-company priority. Defaults currently allow 50 companies per source, 250 cumulative companies and 25 company verifications. CLI overrides include `--source`, `--target-companies` (`0` disables the target), `--refresh` / `--no-refresh`, `--render-public` / `--no-render-public`, and verification's `--prioritize-established` / `--no-prioritize-established`. Repeated runs preserve sets and checkpoints. Ranking prioritizes established Staff/Principal roles ahead of early teams; it does not apply.

`search linkedin` only collects jobs and never opens application forms or submits applications. `apply linkedin` revisits the selected IDs, revalidates them, and uses the existing Easy Apply flow with a visible final review pause, including background configurations. `run linkedin` combines search and application. The default database is `data/job_pipeline/pipeline.sqlite3`; repeat `--input` to merge compatible sets, use `--output` to export a stage, and use `--db` to select a database.

The same LinkedIn backend is available through `python runAiBot.py --mode search`, `--mode apply`, or `--mode search-and-apply`, with the same input, set, export, limit, and database options. `python runAiBot.py` preserves the existing bot workflow. Importing either frontend or displaying pipeline help does not start Chrome or load credentials.

See the [job pipeline guide](docs/job-pipeline.md) for input contracts, official-careers verification, role priorities, resume behavior, and source-access limitations. Application verification uses mocks; no live applications are submitted by the automated tests.

## ⚙️ How to install
1. [Python 3.10](https://www.python.org/) or above. Visit https://www.python.org/downloads/ to download and install Python, or for windows you could visit Microsoft Store and search for "Python". **Please make sure Python is added to Path in System Environment Variables**.
2. Install the pinned Python dependencies from `requirements.txt`. After Python is installed, open a console/terminal or shell and use the [pip](https://pip.pypa.io/en/stable) command-line tool:
  ```
  python -m pip install -r requirements.txt
  ```
3. Download and install latest version of [Google Chrome](https://www.google.com/chrome) in it's default location, visit https://www.google.com/chrome to download it's installer.
4. Clone the current git repo or download it as a zip file, then run commands from the repository root.
5. If `stealth_mode = False`, install the ChromeDriver build matching your Chrome major version. See [Chrome for Testing](https://googlechromelabs.github.io/chrome-for-testing/) for downloads. If `stealth_mode = True`, `undetected-chromedriver` downloads a driver at runtime, but startup is less predictable and requires network access.
  <br> <br>
  ***OR*** 
  <br> <br>
  If you are using Windows, click on `windows-setup.bat` available in the `/setup` folder, this will install the latest chromedriver automatically.
6. If you have questions or need help setting it up or to talk in general, join the github server: https://discord.gg/fFp7uUzWCY

[back to index](#-content)

<br>

## 🔧 How to configure
1. Open `personals.py` file in `/config` folder and enter your details like name, phone number, address, etc. Whatever you want to fill in your applications.
2. Open `questions.py` file in `/config` folder and enter your answers for application questions, configure wether you want the bot to pause before submission or pause if it can't answer unknown questions.
3. Open `search.py` file in `/config` folder and enter your search preferences, job filters, configure the bot as per your needs (these settings decide which jobs to apply for or skip). Configure role lanes, skills, and manual searches in `search_profile.py`; location and filter values remain in `search.py`. See [Dynamic Search Profiles](docs/dynamic-search.md).
4. Prefer environment variables or a local, uncommitted secrets configuration for LinkedIn/OpenAI credentials. Credentials are optional: if no LinkedIn username/password is supplied, the bot uses the configured Chrome profile and asks for manual login when needed. Never commit real credentials to `config/secrets.py`.
5. Open `settings.py` file in `/config` folder to configure the bot settings like, keep screen awake, click intervals (click intervals are randomized to seem like human behavior), run in background, stealth mode (to avoid bot detection), etc. as per your needs.
6. Add the default resume paths in `config/questions.py`: `default_resume_path` for a static upload and `default_resume_docx_path` for DOCX optimization. Keep a matching sibling PDF beside the DOCX. Ordinary optimization can use an independently verified source-PDF fallback. All-bullets mode requires a verified generated artifact; its optional per-bullet source retention is different from uploading the entire original PDF. If no verified attachment is available, the application is retained for retry.
7. Run `runAiBot.py` and see the magic happen.
8. If you have questions or need help setting it up or to talk in general, join the github server: https://discord.gg/fFp7uUzWCY

### Configuration reference

| File or setting | What it controls | Typical first-run value |
| --- | --- | --- |
| `config/search.py:search_terms` | LinkedIn search queries. | `['Senior Software Engineer']` |
| `config/search.py:search_location` | Location entered into LinkedIn search. | `'California, United States'` |
| `config/search.py:switch_number` | Per-query application/external-link quota, unless a SearchSpec has its own quota. | Currently `10`; use `1` for a smoke test |
| `config/search.py:max_applications_per_run` | Confirmed submissions across all queries/cycles in the command. | Currently `50`; use `1` for a smoke test; `None` disables the cap |
| `config/settings.py:run_in_background` | Whether Chrome is visible. | `False` while debugging |
| `config/settings.py:safe_mode` | Opens a clean Guest-style browser profile when normal Chrome startup fails. | `True` for startup troubleshooting |
| `config/settings.py:chrome_profile_path` | Dedicated Chrome user-data directory used by JobRobo. | Defaults to `~/.jobrobo/chrome-profile`; an empty value uses the same default |
| `config/questions.py:pause_before_submit` | Pauses before the final submit action. | Currently `False`; use `True` for manual review |
| `config/questions.py:pause_at_failed_question` | Legacy failed-question setting; current Easy Apply recovery records unresolved required fields for retry without a Help Needed popup. | Inspect retry reasons and configured answers |
| `config/questions.py:default_resume_path` | PDF uploaded to LinkedIn. | `all resumes/default/resume.pdf` |
| `config/questions.py:default_resume_docx_path` | DOCX source used when resume optimization is enabled. | `all resumes/default/resume.docx` |
| `config/resume_optimizer_defaults.json:optimization_mode` | Resume rewrite scope. | `skills`, `bullets`, or `full` |

Keep secrets out of commits. Use environment variables or the repository's existing key-loader flow for OpenAI credentials, and do not paste real passwords into documentation, issues, or screenshots. If a credential has ever been committed, rotate it before continuing.

### Safe first run

Use this sequence before allowing unattended applications:

1. Set `max_applications_per_run = 1`, use one search term, and set `switch_number = 1`, `run_non_stop = False`, `run_in_background = False`, `pause_before_submit = True`, and `pause_at_failed_question = True`. The quota is per search term, not per run.
2. Close extra Chrome windows and tabs. A large number of open tabs can cause ChromeDriver to start a browser without reaching the job page.
3. Run the test suite and inspect the configured resume paths.
4. Start `python runAiBot.py`, review the job, answers, attached resume, and final submission screen.
5. Stop the run manually if it proceeds to another job unexpectedly. Multiple search terms can each process their quota even with non-stop looping disabled. Increase quotas or enable repeated cycling only after the one-job path is understood.

### Resume ATS optimizer

The following bank-selection details describe the ordinary path when
`rewrite_all_bullets=false`. The current saved all-bullets path has separate
[policy, Skills-width, source-retention and attachment rules](docs/TASK11-README.md#current-optimizer-options).

The optimizer keeps the existing job-description keyword extraction flow and adds
curated vocabulary guidance from
`config/skills/Skills_Keyword_Bank_Staff_Principal_2026-10.md`. The job description
is still authoritative: bank suggestions must match JD vocabulary, while the selected
role profile helps rank those matches.

Configure the mode in the GUI or saved user JSON. The bundled `config/resume_optimizer_defaults.json` supplies defaults for missing fields:

```json
"optimization_mode": "full"
```

Valid modes are:

| Mode | Changes | Use when |
| --- | --- | --- |
| `skills` | Reorders and replaces the Skills section only. | Existing bullets already fit the role, or the source is a PDF. |
| `bullets` | Updates Skills, rewrites ordinary experience, and inserts exact bank bullets into matching entries. | You want JD alignment while preserving titles. |
| `full` | Runs `bullets` plus recognized professional-experience title replacement. | You have reviewed the accuracy of the title changes. |

Bullet and title operations require DOCX. PDF input always uses Skills-only editing
and records `effective_mode: "skills-pdf"`. The optimizer
does not rewrite the summary or change project titles.

#### Skill guidance and JD context

The flow extracts keywords from the JD, infers a role profile such as Staff / Principal
AI Platform or Healthcare AI, and combines those results with the existing Skills
section. The same selected skills and JD-guided phrases are passed to the bullet
rewrite prompt. The model is instructed to preserve facts, but the implementation
does not independently validate work history. Skills-bank terms marked `†` are allowed
by default; set `allow_unverified_bank_terms` to `false` to filter those bank suggestions.
Extracted JD terms still require human review for evidence.

Skills selection prioritizes JD guidance and deduplicates recognized full-phrase/acronym
pairs such as `Model Context Protocol (MCP)` and `MCP`. The original number of entries
is an upper bound; duplicates can shrink the result. DOCX edits reuse source runs and
their font/character spacing to preserve compact template formatting.

#### Curated bullet banks

Configured project bullet banks in `config/bullets/` provide exact, JD-ranked bullets
for the first matching company entry. The default configuration covers:

| Resume entry | Bank | Default selection |
| --- | --- | ---: |
| `TREK HEALTH` | `Trek_Health_Bullet_Bank.md` | 7 bullets, including platform and leadership sections |
| `CODEX SELF-HOSTED` | `Codex_SelfHosted_Bullet_Bank.md` | 3–5 bullets, always including Platform |
| `SOHAMHAMSO` | `Sohamhamso_Bullet_Bank.md` | 2–4 bullets, always including Overview |
| `SPONSORSKIP` | `SponsorSkip_Bullet_Bank.md` | 1–2 bullets, always including Overview |

The three project banks target named entries under `ENTREPRENEURIAL VENTURES & PROJECTS`;
matching uses company/project text and the expected paragraph structure, not project order.
For each bank, the selector scores preset references, JD lookup phrases, direct JD
word overlap, and preferred character length. It applies maximum counts, category
targets, metric/verb deduplication, and marker exclusions. Minimum counts and required
categories can be unmet when too few eligible candidates remain. Bullets marked `†` or `‡` are
excluded by default because they require candidate proof or confirmation. Set a bank's
`allow_unverified` value to `true` only after reviewing its evidence. Unmarked bank
text is not independently fact-checked by the optimizer.

The exact bank bullet replaces the first matching entry's existing list paragraphs.
All other professional-experience entries continue through the existing JD-aware LLM
rewrite path. A `skills` run does not rewrite bullets or apply bullet banks.

Example project-bank configuration:

```json
"project_bullet_banks": [
  {
    "path": "config/bullets/Codex_SelfHosted_Bullet_Bank.md",
    "company": "CODEX SELF-HOSTED",
    "min_bullets": 3,
    "max_bullets": 5,
    "required_sections": ["A"],
    "allow_unverified": false
  }
]
```

#### Output and verification

Generated files are written under the resume's sibling `temp/` directory with a
job-specific filename. The optimizer also writes a `.match_report.json` beside the
intended PDF containing requested/normalized/effective modes, status, attempt history,
keywords, bank IDs, `pre_optimization` / `post_optimization` keyword coverage, and
format-verification results. Keyword coverage is a local diagnostic, not an ATS vendor score.

The post-conversion verifier rejects output when it does not meet the configured
contract. The default expects two pages, extractable text, horizontal/vertical text
bounds, source-relative sections and rendered headings, no new orphaned headings,
stable bullet counts, and similar margins/body font sizes. DOCX/PDF consistency also
requires at least 95% normalized token coverage and every DOCX section heading in
rendered order. Wrapping details remain inspection
signals; a pass does not establish identical appearance or truthful claims.

A failed `bullets`/`full` DOCX verification receives one Skills-only retry from the source.
If accepted, it records `effective_mode: "skills-fallback"`, with empty top-level bank
selections; rejected choices and checks remain in `attempts`. If no optimized artifact is
accepted, the bot can attach an independently verified source PDF. If both upload paths
fail, the application is discarded before Review/Submit. A previous LinkedIn attachment
is not accepted as fallback success. See the [reference](docs/resume-optimizer-reference.md)
for the complete configuration and report contract.

[back to index](#-content)

<br>

## Troubleshooting

### Chrome opens and immediately exits

This usually means ChromeDriver cannot create a compatible session, Chrome is
already holding the selected profile, or the browser profile has stale startup
state. Try these checks in order:

1. Close every Chrome window and confirm no Chrome process is still running.
2. Check that Chrome and ChromeDriver major versions match. Update Chrome and use
   the matching driver from [Chrome for Testing](https://googlechromelabs.github.io/chrome-for-testing/).
3. Set `safe_mode = True` in `config/settings.py` and retry. Safe mode uses a clean
   profile rather than the everyday Chrome profile.
4. If `stealth_mode = True`, reinstall the package in the active environment:

   ```bash
   python -m pip uninstall undetected-chromedriver
   python -m pip install undetected-chromedriver
   ```

5. Keep the browser visible with `run_in_background = False` while diagnosing. Do
   not debug startup failures with a large batch or unattended submission enabled.

### The browser starts but does not reach the job

Close excess tabs before starting. The bot expects to control the active JobRobo
profile and can appear idle when Chrome opens with another profile or too many tabs.
Check `chrome_profile_path`, confirm LinkedIn is logged in to that profile, and run
with `pause_after_filters = True` if you need to inspect the search state.

### The bot continues to another job

`switch_number` controls the quota for each search term. For a one-job smoke test,
set `max_applications_per_run = 1`; optionally use one term and
`switch_number = 1`. Keep `run_non_stop = False`, and leave
`pause_before_submit = True`. If a run has already
submitted the expected application, stop it manually before changing the quota or
cycling settings.

### Resume optimization fails or produces the wrong output

Check that the DOCX and PDF source paths exist, the DOCX contains a standalone
`SKILLS` heading or an inline `Skills:` section, and the OpenAI key is available to
the active Python environment. Run the unit tests before retrying. Then inspect the
generated `.match_report.json`; it records keyword coverage, selected bank IDs, and
the attempt and format check that failed. Early API or conversion errors can produce
failure reports without an accepted PDF. Check the returned path and `status` before
using any artifact from the output folder.

### Generated resume is not two pages

The default verifier expects two pages because the current resume template is a
two-page document. Use `skills` mode first, reduce the configured skill count, or
shorten unsupported source content. Do not bypass the verifier merely to submit a
longer document: the bot's upload path is intended to use a verified PDF.

[back to index](#-content)

<br>

## Dynamic Search Profiles

Searches combine enabled manual queries from `config/search_profile.py`, existing `search_terms`, and queries generated from your role lanes and skills. Each query uses the current location, filters, and exclusion settings in `config/search.py`. The existing San Francisco Bay Area, full-time, remote/hybrid preferences and Staff/Principal search terms are preserved. Duplicate queries keep the first definition, with manual searches taking precedence.

`dynamic_search_enabled = True` and `ai_query_refinement_enabled = True` are enabled by default. Search refinement uses OpenAI independently of resume optimization and `use_AI`; missing credentials or invalid responses fall back to deterministic role queries. The configured `switch_number = 10` is a per-search quota, overridden by `quota = 1` for the supplied manual search; `max_applications_per_run = 50` currently caps confirmed submissions across the command. The current local `pause_before_submit = False` allows submission; set it to `True` for review or use `--prepare-only` to disable Submit entirely.

The runner attempts LinkedIn's natural-language search, records the actual search mode and any fallback or filter warnings, and saves query checkpoints under `logs/search_runs/`. A matching interrupted run resumes automatically; completed searches and previously submitted jobs are skipped. Submission checkpoints across all saved runs also protect fresh runs when CSV logging failed; uncertain submissions remain skipped for manual inspection. Applied and failed CSV records include the run, query, mode, profile, and source. Existing CSV rows are preserved during header migration.

See the [configuration, resume behavior, and verification guide](docs/dynamic-search.md) for manual-search examples, safe query previews, read-only search diagnostics, verified modern filters, and the limits of the classic keyword fallback. Fresh search-and-apply was also manually tested. Live evidence has confirmed optimized uploads and submissions; those observations do not guarantee every future LinkedIn layout or employer form. See the [latest recovery behavior and evidence](docs/TASK11-README.md#current-linkedin-integration-and-recovery).

[back to index](#-content)

<br>


## 🧑‍💻 Contributor Guidelines
Thank you for your efforts and being a part of the community. All contributions are appreciated no matter how small or big. Once you contribute to the code base, your work will be remembered forever.

NOTE: Only Pull request to `community-version` branch will be accepted. Any other requests will be declined by default, especially to main branch.
Once your code is tested, your changes will be merged to the `main` branch in next cycle.

### Code Guidelines
  #### Functions:
  1. All functions or methods are named lower case and snake case
  2. Must have explanation of their purpose. Write explanation surrounded in `''' Explanation '''` under the definition `def function() -> None:`. Example:
      ```python
      def function() -> None:
        '''
        This function does nothing, it's just an example for explanation placement!
        '''
      ```
  4. The Types `(str, list, int, list[str], int | float)` for the parameters and returns must be given. Example:
      ```python
      def function(param1: str, param2: list[str], param3: int) -> str:
      ```
  5. Putting all that together some valid examples for function or method declarations would be as follows.
      ```python
      def function_name_in_camel_case(parameter1: driver, parameter2: str) -> list[str] | ValueError:
        '''
        This function is an example for code guidelines
        '''
        return [parameter2, parameter2.lower()]
      ```
  6. The hashtag comments on top of functions are optional, which are intended for developers `# Comments for developers`.
      ```python
      # Enter input text function
      def text_input_by_ID(driver: WebDriver, id: str, value: str, time: float=5.0) -> None | Exception:
          '''
          Enters `value` into the input field with the given `id` if found, else throws NotFoundException.
          - `time` is the max time to wait for the element to be found.
          '''
          username_field = WebDriverWait(driver, time).until(EC.presence_of_element_located((By.ID, id)))
          username_field.send_keys(Keys.CONTROL + "a")
          username_field.send_keys(value)
      
      ```
   
  #### Variables
  1. All variables must start with lower case, must be in explainable full words. If someone reads the variable name, it should be easy to understand what the variable stores.
  2. All local variables are camel case. Examples:
      ```python
      jobListingsElement = None
      ```
      ```python
      localBufferTime = 5.5
      ```
  3. All global variables are snake case. Example:
      ```
      total_runs = 1
      ```
  4. Mentioning types are optional.
      ```python
      localBufferTime: float | int = 5.5
      ```
  
  #### Configuration variables
  1. All config variables are treated as global variables. They have some extra guidelines.
  2. Must have variable setting explanation, and examples of valid values. Examples:
      ```python
      # Explanation of what this setting will do, and instructions to enter it correctly
      config_variable = "value1"    #  <Valid values examples, and NOTES> "value1", "value2", etc. Don't forget quotes ("")
      ```
      ```python
      # Do you want to randomize the search order for search_terms?
      randomize_search_order = False     # True of False, Note: True or False are case-sensitive
      ```
      ```python
      # Avoid applying to jobs if their required experience is above your current_experience. (Set value as -1 if you want to apply to all ignoring their required experience...)
      current_experience = 5             # Integers > -2 (Ex: -1, 0, 1, 2, 3, 4...)
      ```
      ```python
      # Search location, this will be filled in "City, state, or zip code" search box. If left empty as "", tool will not fill it.
      search_location = "United States"               # Some valid examples: "", "United States", "India", "Chicago, Illinois, United States", "90001, Los Angeles, California, United States", "Bengaluru, Karnataka, India", etc.

      ```
  4. Add the config variable in appropriate `/config/file`.
  5. Every config variable must be validated. Go to `/modules/validator.py` and add it over there. Example:
      For config variable `search_location = ""` found in `/config/search.py`, string validation is added in file `/modules/validator.py` under the method `def validate_search()`.
      ```python
      def validate_search() -> None | ValueError | TypeError:
          '''
          Validates all variables in the `/config/search.py` file.
          '''
          check_string(search_location, "search_location")
      ```

  [back to index](#-content)
  
  ### Attestation
  1. All contributions require proper attestion. Format for attestation:
  ```python
  ##> ------ <Your full name> : <github id> OR <email> - <Type of change> ------
      print("My contributions 😍") # Your code
  ##<
  ```
  2. Examples for proper attestation:
  New feature example
  ```python
  def alert_box(title: str, message: str) -> None:
    '''
    Shows an alert box with the given `title` and `message`.
    '''
    from pyautogui import alert
    return alert(title, message)

  ##<
  ```
  
  Bug fix example
  ```python
  def alert_box(title: str, message: str) -> None:
    '''
    Shows an alert box with the given `title` and `message`.
    '''
    from pyautogui import alert

    return alert(message, title)
  ##<
  ```

[back to index](#-content)

<br>

## 🤩 Feature List
The list below separates the working browser/application path from experimental or
legacy paths. Some LinkedIn page changes can still require manual intervention.

#### General Features 🚀:

- Opens Chrome with a dedicated or configured JobRobo profile; log in there on first use (Yet to test with browsers having multiple profiles)
- **Auto Login**: If configured or already saved in browser (not saved passwords)
- Apply filters (Salary, Companies, Experience Level,... ) Must config
- Region specific searches
- Opens job search and searches key words
- Easy applies
- Auto Answers questions answered in config
- Collects urls of career page if have to Apply externally
- Collects HR Info
- Collects skills required (In Development)
- Collects experience required and skips if not applicable to you, must be configured
- Auto Filters jobs based on your experience and black list key words
- Skips blacklisted jobs
- Can be configured to skip jobs requiring Security Clearance
- You can add exceptions to blacklist key words
- Only applies to filtered jobs
- Auto selects next pages until it hits the quota you configured
- Selects your default resume
- Auto Submits
- Saves all the info of applied jobs, failed to apply jobs in excels and logs
- Takes screenshot of questions answered to fail, for future debugging
- Saves info of all questions, it's options, previous answer and current answer in application
- Option to overwrite previous answers
- Continuous applications non stop (beta)
- No need for fear of missing out, Goes through all possible filters and sorts combinations with each cycle if configured (Most Recent, Most Relevant, Newest First, Past 24 Hrs, Past Month, Past Week etc)
- Option to randomize the search order
- Run in background, headless browser
- Auto collects a looooooooooooooooooot of info about your jobs, check applied-jobs.excel and failed_jobs.excel for info after each run.
- Optional pause before submit application.
- Optional pause if stuck at a question.
- Configurable resume optimization with `skills`, `bullets`, and `full` modes, plus the all-bullets path.
- Per-job AI cover letters and descriptive answers with saved draft artifacts.
- Independent discovery, official-careers verification, ranking, LinkedIn search/application, and direct employer preparation/submission.
- Durable search manifests, deferred jobs and submission confirmation evidence.
- JD-guided skill selection from the Staff / Principal keyword bank.
- Curated, fact-preserving bullet banks for Trek Health, Codex Self-Hosted, Sohamhamso, and SponsorSkip.
- Post-conversion resume verification for page count, text extraction, section order, clipping, and layout similarity.
- JSON match reports with keyword coverage, verification results, and failed/accepted attempt history.




#### Stealth features 🥸🤫:  
- Optional undetected ChromeDriver integration. Chrome and ChromeDriver major versions must remain compatible.
- Click intervals can be randomized and increased to avoid suspicions
- Smooth Scrolls the elements into view before click

#### Upcoming Features or currently in development 🤖🛠️:
- Humanize clicks and mouse movements for stealth 
- Auto send personalized messages to HR that accept messages
- Broader resume generation beyond the current DOCX/PDF optimizer
- Additional browser-supported application question strategies

#### Currently Broken 🥲😭: 
- Legacy browser-based ChatGPT login and resume chat-window integration. The current
  optimizer uses the configured OpenAI API/key-loader path instead.
      
[back to index](#-content)

<br>




## ✉️ My Heartfelt letter to you ❤️...

My Dear User,

Thank you for using the job application tool! Your support means everything to me. 

As you continue your job search, I hope this tool has provided you with valuable assistance and streamlined your efforts.

To continue improving and maintaining this tool, I rely on the support of users like you. If you believe in its mission and want to contribute, you can support me by sharing about this project with your peers and network.

By doing so, you can empower others in their job hunt, just as you've been empowered.. Every contribution, big or small, makes a significant impact!

As an independent developer, I pour my heart and soul into creating tools like this, driven by the genuine desire to make a positive impact. Your support, whether through donations or simply spreading the word, means the world to me and helps keep this project alive and thriving.

You can connect and reach me out at:
- LinkedIn  :  https://www.linkedin.com/in/dannybasavaraju/
- Email     :  danny.basavaraju@gmail.com

<br>

Thank you for being part of this journey, and remember that together, we can make a real difference in the lives of job seekers worldwide.

With heartfelt appreciation, <br>

<br>
<br>

[back to index](#-content)

<br>

## Major Updates History

### October 21, 2026
- Added a command chooser for configured LinkedIn, preparation-only tests, staged discovery/verification/ranking, and direct employer applications.
- Documented shared optimizer JSON, content policies, company context, Skills width packing, Luna configuration, API pacing, and explicit original-bullet fallback.
- Updated configured quotas to 10 per query and 50 confirmed submissions per invocation; manual lane quotas still override the query default.
- Documented current Easy Apply navigation, Continue applying reminders, stale-field/upload recovery, Not now profile-promotion dismissal, confirmation handling, and retained retry evidence.
- Refreshed the [Task 11 operating guide](docs/TASK11-README.md) while retaining dated experiments separately.

### October 12, 2026
- Added configurable ATS optimization modes: Skills-only, bullet rewrite, and full title alignment.
- Added JD-guided skill-bank vocabulary and shared JD context for bullet rewriting.
- Added exact, safe-claim bullet-bank selection for Trek Health and the first three entrepreneurial projects.
- Added two-page/layout verification and JSON match reports before optimized resumes are accepted.
- Added documentation and tests for Chrome profile troubleshooting, resume output verification, and project-bank configuration.

### Nov 28, 2024
- Patched to work for latest changes in Linkedin.
- Users can now select to follow or not follow companies when submitting application.
- Frameworks for future AI Developments have been added.
- AI can now be used to extract skills from job description. 

### Oct 16, 2024
- Framework for OpenAI API and Local LLMs
- Framework for RAG

### Sep 09, 2024
- Smarter Auto-fill for salaries and notice periods
- Robust Search location filter, will work in window mode (No need for full screen)
- Better logic for Select and Radio type questions
- Proper functioning of Decline to answer questions in Equal Employment opportunity questions
- Checkbox questions select fail bug fixed
- Annotations are clearer in instructions for setup

### Sep 07, 2024
- Annotations for developers
- Robust input validations
- Restructured config file
- Fixed pagination bug

### Aug 21, 2024
- Performance improvements (skip clicking on applied jobs and blacklisted companies)
- Stop when easy apply application limit is reached
- Added ability to discard from pause at submission dialogue box
- Added support for address input
- Bug fixed radio questions, added support for physical disability questions
- Added framework for future config file updates

### June 19, 2024
- Major Bug fixes (Text Area type questions)
- Made uploading default resume as not required

### May 15, 2024
- Added functionality for textarea type questions `summary`, `cover_letter`(Summary, Cover letter); checkbox type questions (acknowledgements)
- Added feature to skip irrelevant jobs based on `bad_words` 
- Improved performance for answering questions
- Logic change for masters students skipping
- Change variable names `blacklist_exceptions` -> `about_company_good_words` and `blacklist_words` -> `about_company_bad_words`
- Added session summary for logs
- Added option to turn off "Pause before Submit" until next run

### May 05, 2024
- For questions similar to "What is your current location?", City posted in Job description will be posted as the answer if `current_city` is left empty in the configuration
- Added option to over write previously saved answers for a question `overwrite_previous_answers`
- Tool will now save previous answer of a question
- Tool will now collect all available options for a Radio type or Select type question
- Major update in answering logic for Easy Apply Application questions
- Added Safe mode option for quick stable launches `safe_mode`

### May 04, 2024
- Added option to fill in "City, state, or zip code" search box `search_location`
- Bug fixes in answering City or location question


[back to index](#-content)

<br>

## 🧩 Access challenges (CAPTCHA)

The `apply` lane can clear a vendor challenge on the employer page instead of
handing the tab back. It is opt-in and needs a hosted CaptchaKraken key:

```sh
CAPTCHA_KRAKEN_API_KEY=...   # and CAPTCHA_KRAKEN_BASE_URL (or VLLM_BASE_URL)
./scripts/setup_captcha_solver.sh   # builds the 3.11 sidecar venv

python3 direct_apply.py submit --urls-file jobs.txt \
  --captcha-solver --pause-before-submit never --limit 5
```

`--captcha-solver` is the opt-in; `CAPTCHA_SOLVER=1` in `.env` also turns it on
ambiently. Without the flag the lane hands challenges back for manual work, and
it fails fast rather than half-arming if the sidecar or key is missing.

The solver runs in a Python 3.11 sidecar because `captchakraken` needs 3.11
while the app stays on 3.10. It attaches to the already-open tab over CDP and
never clicks Submit. It is bounded to five vendor responses and reports rungs
separately: `detected`, `model_response`, `token_present`, `challenge_cleared`.

Outcomes are reported honestly and separately: `cleared`, `rejected`,
`unsupported`, `no_challenge`, `timeout`, `blocked`, `error`. A cleared
challenge is never counted as a confirmed submission; a page that then refuses
the application is reported as an employer rejection, not a solver failure.

Two ATS-specific behaviours are handled:

- Invisible reCAPTCHA (Ashby) keeps an empty challenge frame until Submit runs
  the widget, so Submit is clicked first, then the board is solved, then Submit
  is clicked again.
- Ashby overlays the filled form and Lever draws its own radio labels, so a DOM
  click is used when the native one is intercepted or is a silent no-op.

Known limits: Greenhouse renders its required questions as react-select
comboboxes, which stay manual. Ashby may flag a submission as possible spam
after a clean solve; that is the employer's call, not the solver's.

See `logs/captcha-eval/` for a dated live run across Ashby, Lever and Greenhouse.

[back to index](#-content)

<br>

## 📜 Disclaimer

**This program is for educational purposes only. By downloading, using, copying, replicating, or interacting with this program or its code, you acknowledge and agree to abide by all the Terms, Conditions, Policies, and Licenses mentioned, which are subject to modification without prior notice. The responsibility of staying informed of any changes or updates bears upon yourself. Additionally, kindly adhere to and comply with LinkedIn's terms of service and policies pertaining to web scraping. Usage is at your own risk. The creators and contributors of this program emphasize that they bear no responsibility or liability for any misuse, damages, or legal consequences resulting from its usage.**


## 🏛️ Terms and Conditions

Please consider the following:

- **LinkedIn Policies**: LinkedIn has specific policies regarding web scraping and data collection. The responsibility to review and comply with these policies before engaging, interacting, or undertaking any actions with this program bears upon yourself. Be aware of the limitations and restrictions imposed by LinkedIn to avoid any potential violation(s).

- **No Warranties or Guarantees**: This program is provided as-is, without any warranties or guarantees of any kind. The accuracy, reliability, and effectiveness of the program cannot be guaranteed. Use it at your own risk.

- **Disclaimer of Liability**: The creators and contributors of this program shall not be held responsible or liable for any damages or consequences arising from the direct or indirect use, interaction, or actions performed with this program. This includes but is not limited to any legal issues, loss of data, or other damages incurred.

- **Use at Your Own Risk**: It is important to exercise caution and ensure that your usage, interactions, and actions with this program comply with the applicable laws and regulations. Understand the potential risks and consequences associated with web scraping and data collection activities.

- **Chrome Driver**: This program utilizes the Chrome Driver for web scraping. Please review and comply with the terms and conditions specified for [Chrome Driver](https://chromedriver.chromium.org/home).


## ⚖️ License

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

See [AGPLv3 LICENSE](LICENSE) for more info.


<br>

[back to index](#-content)

<br>

## Community support and discussions

Use the [GitHub repository](https://github.com/deepakb66/jobrobo) for reproducible
bugs, configuration questions, and patches. Include your operating system, Python
version, Chrome version, ChromeDriver mode, optimization mode, and the relevant
sanitized log excerpt. Never include LinkedIn credentials, API keys, application
answers containing personal data, or full screenshots with private information.

For setup discussion and community help, join the project's Discord server:
https://discord.gg/fFp7uUzWCY

[back to index](#-content)

<br>

## 🐧 Socials
- **LinkedIn** : https://www.linkedin.com/in/dannybasavaraju/
- **Email**    : danny.basavaraju@gmail.com
- **X/Twitter**: https://x.com/deepakcool3


#### ℹ️ Version: [0.1.3.0](VERSION)

---

[back to the top](#linkedin-ai-auto-job-applier-)
