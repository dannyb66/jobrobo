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
Review existing saved browser answers too. Unknown required or consequential
answers need a real answer before submission, not a first-option placeholder.

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
`--fresh`; read filters and application caps from configuration. The separate
`--mode search/apply/search-and-apply` commands belong to the staged pipeline
and retain its input/set contracts.

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

These CLI routing, fresh-state restoration, filter-transition, preferred-name
replacement and company-route guards have offline regression tests. They do not
prove current live employer acceptance or authorize an application run. Modern
Easy Apply form changes can still require manual handling; the ordinary runner's
legacy modal lookup is not a fully verified unattended modern-form solution.

Stop on unknown factual/consent answers, wrong attachments, unverified location,
closed roles or unexpected destinations. Preserve logs under `logs/search_runs`
and the configured CSV history. Do not infer submission from entering a form or
reaching its review screen.
