# Dynamic search profiles

Dynamic searches turn your role intent and existing search preferences into natural-language LinkedIn queries. Configure roles, skills, and manual searches in [`config/search_profile.py`](../config/search_profile.py). Keep locations, filters, and job exclusion rules in [`config/search.py`](../config/search.py); the planner reads them when a run starts.

## Profile settings

| Setting | Default | Effect |
| --- | --- | --- |
| `profile_name` | `"staff-principal-ai-platform"` | Identifies the profile in manifests and CSV history. |
| `profile_version` | `"2"` | Identifies the profile revision. Use a nonempty string. |
| `dynamic_search_enabled` | `True` | Generates queries from `role_lanes`. Manual and legacy searches still run when disabled. |
| `ai_query_refinement_enabled` | `True` | Attempts OpenAI role-query refinement for generated searches. |
| `role_lanes` | 22 configured engineering lanes | Nonempty strings describing roles. At least one is required when dynamic search is enabled. |
| `skills` | AI, platform, and infrastructure skills | Nonempty strings added to each natural-language query. |
| `manual_searches` | One enabled Staff AI Platform Engineer search | Explicit queries with stable IDs and optional quota overrides. |
| `resume_search_enabled` | `True` | Automatically resumes the latest matching unfinished run. |
| `search_state_dir` | `"logs/search_runs"` | Stores run manifests and the runner lock. |

Boolean settings must be `True` or `False`. `role_lanes` and `skills` must be lists; their entries are limited to 200 characters. Profile name, version, and state directory must be nonempty strings. An invalid profile stops the run rather than silently changing its meaning.

The supplied role lanes cover Staff/Principal software, AI, machine learning, backend, infrastructure, platform, systems, inference, and SDK work; Member of Technical Staff variants for systems, inference runtime, machines, ML performance, platform, backend, SDK, and storage; related generic engineering titles; and Founding Engineer. See `config/search_profile.py` for the complete list. Edit those lanes and the skill list to match your goals.

## How to add or disable a manual search

Edit `manual_searches` in `config/search_profile.py`:

```python
manual_searches = [
    {
        "id": "staff-ai-platform",
        "query": "Staff AI Platform Engineer",
        "enabled": True,
        "quota": 1,
        "role_label": "Staff AI Platform Engineer",
        "notes": "Keep this role as an explicit search lane.",
    },
    {
        "id": "principal-backend",
        "query": "Principal Backend Engineer",
        "enabled": False,
    },
]
```

| Field | Required? | Behavior |
| --- | --- | --- |
| `id` | Yes | Unique within the profile, at most 100 characters. Start with a letter or digit; subsequent characters may also include `.`, `_`, or `-`. The resulting ID is `manual:<id>`. Keep it stable when editing the query. |
| `query` | Yes | Nonempty natural-language text, at most 4,000 characters. Canonical search preferences are added to it. |
| `enabled` | No | Defaults to `True`. Set `False` to omit the search. |
| `quota` | No | Positive integer; defaults to `switch_number` from `config/search.py`. |
| `role_label` | No | Optional nonempty text used as the shorter classic keyword fallback query. Defaults to the manual query. |
| `notes` | No | Optional nonempty text for configuration notes; does not change the query. |

Unknown fields, duplicate IDs, empty queries, or invalid quotas fail validation. Disabled definitions must still be valid. At least one enabled manual, legacy, or generated search must remain.

## Canonical search preferences

The existing preferences are preserved: San Francisco Bay Area, full-time, remote or hybrid, jobs posted within the past month, Easy Apply, and most-recent ordering when available. Legacy `search_terms` retain Staff and Principal Software Engineer and AI Engineer searches, Staff Machine Learning Engineer, AI Platform Engineer, Staff Backend Engineer, and Founding Engineer. Change those values in `config/search.py`; the profile does not copy them.

The planner snapshots these values from `config/search.py`:

| Purpose | Settings |
| --- | --- |
| Search intent | `search_location`, `date_posted`, `salary`, `easy_apply_only`, `experience_level`, `job_type`, `on_site`, `companies`, `location`, `industry`, `job_function`, `job_titles`, `benefits`, `commitments`, `under_10_applicants`, `in_your_network`, `fair_chance_employer` |
| UI ordering | `sort_by` |
| Post-discovery gates | `about_company_bad_words`, `about_company_good_words`, `bad_words`, `security_clearance`, `did_masters`, `current_experience` |

Application budgets also live in `config/search.py`: `switch_number = 10` sets the default per-query quota, and `max_applications_per_run = 1` caps confirmed submissions for the whole command. Set the latter to a positive integer or `None` to disable the command-wide cap. A manual search's `quota` overrides only its per-query quota.

Each role query includes the applicable location, employment type, work arrangement, experience level, company, industry, date, salary, and applicant preferences, plus profile skills. Exclusion and experience hints also appear in the natural-language query. Existing checks on company and job descriptions still apply after discovery, including company exceptions and the configured master's-degree experience allowance. `current_experience = -1` disables the experience ceiling.

The runner also checks each job's location and work arrangement before opening an application form, using the query's canonical filter snapshot. With the configured San Francisco Bay Area preference, hybrid and on-site jobs must be in the Bay Area; US-eligible remote jobs remain allowed under the existing location policy. Missing or incompatible location evidence causes the job to be skipped. Official careers verification retains broad open engineering listings and records this location policy as application-readiness metadata. Selected application preparation and live LinkedIn checks enforce it, without a separate location setting in the profile.

`sort_by` is attempted through the UI and recorded in the snapshot. Search wording expresses intent; LinkedIn controls ranking and may return results outside that intent. This feature does not introduce a local job-fit score.

## Query generation and OpenAI fallback

The planner adds enabled manual searches first, legacy `search_terms` second, and generated role lanes third. It deduplicates the rendered queries after Unicode normalization, case folding, and whitespace normalization. The first query retains its source, ID, and quota. With `randomize_search_order = True`, execution order is shuffled after planning; deduplication precedence remains the same.

Manual IDs come from their configured `id`. Legacy, generated, and AI-refined IDs are derived from their source and normalized role wording. Sources are `manual`, `legacy`, `generated`, or `ai_refined`. AI-refined lanes replace the deterministic generated lanes when refinement succeeds; manual and legacy definitions remain available.

Refinement proposes distinct role variants ranked by profile coverage. The response is validated before use, and accepted titles go through the same canonical preference renderer. Invalid, empty, duplicate, unsupported, or failed responses trigger a warning and deterministic queries. If dynamic generation fails after manual or legacy queries have been planned, those queries can continue.

Search refinement reads `OPENAI_API_KEY` or the existing `llm_api_key`, plus `llm_api_url` and `llm_model`. It uses a separate client with a bounded timeout, independently of `use_AI` and `use_AI_for_resume`. No available key produces a warning and deterministic search; search refinement does not require resume optimization to be enabled.

`use_AI_for_resume = True` in `config/secrets.py` is configured for the next run as requested. Resume optimization uses its existing credentials and upload flow. The submission pause in `config/questions.py` remains `pause_before_submit = True`.

## How to preview the deterministic plan

From the repository root, run this preview before launching the browser:

```bash
python3 - <<'PY'
from config import search, search_profile
from modules.search_planner import build_search_plan

profile = {
    key: value for key, value in vars(search_profile).items()
    if not key.startswith("_")
}
profile["ai_query_refinement_enabled"] = False
for spec in build_search_plan(profile, search):
    print(f"{spec.query_id} | {spec.source} | quota={spec.quota}")
    print(spec.query_text)
    print(f"Classic fallback: {spec.classic_query}\n")
PY
```

This prints the planned queries without connecting to OpenAI, opening LinkedIn, creating a manifest, or submitting applications. If validation fails, fix the named profile value and rerun the preview.

To inspect the signed-in search experience without applying, run:

```bash
python3 runAiBot.py --diagnose-search --limit 5 \
  --output logs/search-diagnostic.json
```

The diagnostic uses a configured query, opens LinkedIn, and collects up to five job-card records and search screenshots. Its report includes query transport, the detected UI variant, location confirmation, filter outcomes, sanitized result URLs, and job metadata. It does not open application forms, upload resumes, submit applications, or create application/collection ledgers. It closes the browser it creates. Only `--limit` and `--output` can accompany `--diagnose-search`; pipeline inputs and modes are unnecessary. The diagnostic limit defaults to five.

Run the configured bot with `python3 runAiBot.py`. The default `max_applications_per_run = 1` allows at most one confirmed submission across all queries in that command. The same budget spans any nonstop cycles; it resets when you invoke the command again. Failed or skipped jobs and collected external application links do not consume this submission budget.

The per-query quota remains separate: successful Easy Apply submissions and collected external application links count toward `switch_number` or a manual `quota` when external applications are enabled. Failed and skipped jobs do not consume that quota. External links remain marked as pending rather than submitted applications. Disabling the command-wide cap with `None` still leaves per-query quotas in effect. Final review and verified-resume checks remain in place.

## Search modes and filter warnings

For each query, the runner detects the current LinkedIn search interface. In the modern experience, it submits the rendered natural-language query through the visible prompt and applies supported inline filters below the search. Modern cards and pagination feed the existing application flow. Search completion uses recognized results or an explicit empty state; it does not require card elements to become stale, because LinkedIn can reuse them across searches.

After a native search verifies its rendered filters and location, the adapter can reuse the observed URL state for later queries in the same browser session. Each replay must verify the new query, filters, location, and results again. A rejected replay is discarded and rebuilt through the native controls. These session recipes use observed parameters; they do not hardcode geography IDs or assume that a URL alone proves filter selection.

The classic keyword route is used only when a native classic interface is positively detected. A modern-search failure is recorded for diagnosis instead of assuming that a constructed classic URL restores the older UI. Search diagnostics distinguish the submitted query, transport, detected interface, location confirmation, and verified, unavailable, or failed filters alongside actual mode (`ai` or `classic`), fallback reason, and warnings.

Location confirmation follows the detected interface. Classic search selects the matching autocomplete option and verifies its committed geography and label. Modern search verifies rendered location confirmation; typed text alone is insufficient. The configured Easy Apply requirement must also be verified before application work proceeds. Every job still passes the existing location check before application, regardless of search mode or result ranking.

Other unavailable controls leave their intent in the natural-language query and produce a warning; existing description and eligibility checks remain active. Most-recent ordering is best effort when its control is absent. Remote and Hybrid retain their configured OR meaning: the runner does not select a Remote-only control that would remove requested hybrid jobs. Contextual suggestion chips are not automatically treated as configured filters.

Modern job details are tied to the selected job ID before company, location, and description checks run. The readers use scoped job/company sections and the full description DOM, including text hidden by a collapsed preview, so exclusion terms below the visible excerpt remain checked. Missing modern description evidence stops that job before the application form. The existing resume, review, quota, and submission checks follow these readers.

LinkedIn documents Date posted, Company, Experience level, Employment type, Remote, Easy Apply, In my network, and Under 10 applicants as available results-page filters. Its current help lists sorting and Hybrid/On-site as forthcoming and classic search as being retired. Suggested chips below the search bar adapt to each query. See [LinkedIn's AI-powered job search help](https://www.linkedin.com/help/linkedin/answer/a6889044/). Account-specific controls are detected at runtime; public help does not establish their DOM or URL contracts.

## How to resume an interrupted run

Leave `resume_search_enabled = True` and rerun `python3 runAiBot.py`. The runner resumes the newest unfinished manifest matching the effective deterministic plan and refinement setting. It reuses the saved query list, including any prior AI-refined wording, without requesting new refinement. A changed effective plan starts a new run.

A run stopped by the command-wide submission cap records `application_limit_reached`. Any unfinished queries remain resumable; the next invocation gets a fresh submission budget and continues that work, preserving per-query counts and duplicate protection. With a submission cap enabled, an uncertain submission pauses further applications until its LinkedIn outcome is verified.

On resume:

1. Completed queries are omitted.
2. The incomplete query restarts at page one, retaining its prior counts.
3. Previously processed terminal outcomes are skipped across all queries in the run.
4. Jobs recorded only as `in_progress` before submission may be retried.
5. Jobs checkpointed as `submitting` remain protected even if the browser reports a submit error. Their query stops with `submission_uncertain` until you verify the application status on LinkedIn. Other queries can continue.
6. Previously submitted jobs in the applied CSV and jobs recorded as `applied` or uncertain `submitting` in any saved manifest are skipped, including across new runs.
7. Pagination continues until the remaining quota is met or results are exhausted, then the next incomplete query runs.

Set `resume_search_enabled = False` to start a new run with current settings. Successful and uncertain submissions are still skipped using CSV history and all manifests in `search_state_dir`, even when configuration changes or a submission was followed by failed CSV logging. Keep the manifests to retain that protection. Failed and skipped jobs from an old run can be considered again in a new run; their previous audit records remain intact.

Each `logs/search_runs/<run_id>.json` manifest stores run and profile identifiers, configuration identity, timestamps, status, current query, and stop reason. Query records contain the search specification, status, actual mode, executed text, fallback reason, warnings, applied and collected counts, processed IDs, job outcomes and reasons, last page, and last job ID. The saved last page is audit information; resume restarts at page one to avoid missing shifted results.

Checkpoints are written atomically, and a runner lock prevents simultaneous search runners from sharing state. A corrupt manifest is reported rather than silently overwritten.

After verifying an uncertain application's status on LinkedIn, resolve its checkpoint locally. Copy the run ID, query ID, and job ID from the manifest; choose `"applied"` only if submission is confirmed, or `"failed"` if it was not submitted:

```python
import json
from pathlib import Path
from modules.search_history import file_lock
from modules.search_state import SearchManifest

path = Path("logs/search_runs/<run_id>.json")
with file_lock(path.parent / ".runner.lock"):
    manifest = SearchManifest(path, json.loads(path.read_text()))
    manifest.resolve_submission("<query_id>", "<job_id>", "applied")
```

This updates the manifest and its applied count; existing CSV audit records remain intact. Rerun the bot to continue the remaining work. A verified failure remains skipped within that run and may be reconsidered in a new run.

## Application history and migration

Applied and failed CSV rows gain these fields:

- `Search Run ID`
- `Search Query ID`
- `Search Query`
- `Search Mode`
- `Search Profile`
- `Search Source`

`Search Query` records the executed text, including the shorter query when classic fallback runs. `Search Profile` contains `<profile_name>@<profile_version>`. Use `Search Run ID` and `Search Query ID` to locate the matching manifest, filter snapshot, and job outcome.

When a record is first written to an older CSV, the writer creates `<filename>.bak`, retains existing columns and rows, and atomically replaces the file with an extended header before appending. Old rows have blank search metadata because their exact queries were not tracked. An existing backup is preserved. Unrecognized headers or malformed rows stop migration and preserve the original file.

If an older applied-history schema has no `Date Applied` column, migration labels those dates `Unknown (legacy applied history)` so its previously protected job IDs remain protected without inventing application dates.

Applied-job IDs are loaded by the `Job ID` header rather than a column position, excluding the header itself and pending external links. They are combined with `applied` and uncertain `submitting` job IDs from every manifest in `search_state_dir`. This preserves duplicate protection across overlapping queries, resumed runs, fresh runs, and changed configurations, including when CSV logging failed after submission. Inspect uncertain submissions on LinkedIn before a manual retry.

## Verification and troubleshooting

Run the automated tests from the repository root:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
```

Tests cover planning, refinement validation and fallback, modern prompt/filter transport, committed location selection, job-location gates, full modern detail readers, resumable state, per-query quotas and command-wide submission caps, CSV migration, and application metadata using local fixtures and mocked browser interactions. Search diagnostics verify the signed-in search and card interface; they do not verify live application forms. No live LinkedIn applications were submitted during implementation verification.

If refinement warns that credentials are unavailable, deterministic queries still run. If a filter warning appears, inspect the saved query and current LinkedIn filter controls. If a run resumes an older query list, its manifest matches the current effective plan; disable automatic resume to start a new run. If a job remains `submitting` after interruption, verify it on LinkedIn before any manual retry.

If the location input shows San Francisco Bay Area while the results header still shows United States, the typed value has not established the intended search geography. Inspect the recorded location warning or query failure and the selected LinkedIn location. The job-location gate remains active, so an out-of-area hybrid result must be skipped before an application form opens. Final review, resume verification, and the command-wide submission cap continue to apply.

See the [README configuration instructions](../README.md#-how-to-configure) for the existing login, resume, and application-question settings.
