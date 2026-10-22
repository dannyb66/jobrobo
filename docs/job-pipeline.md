# Job discovery pipeline

The pipeline keeps discovery separate from application. Discover companies, verify open engineering roles on their official careers pages, collect matching LinkedIn jobs, then apply to selected LinkedIn IDs. Each command saves cumulative records in a local SQLite database and returns a versioned JSON result that can be exported and passed to another command.

## How to run the stages

From the repository root, use a named set for each stage:

```bash
python -m job_pipeline discover companies --set ai-companies
python -m job_pipeline verify careers --input ai-companies --set hiring-roles \
  --output data/job_pipeline/hiring-roles.json
python -m job_pipeline search linkedin --input hiring-roles --set linkedin-candidates --limit 25 \
  --output data/job_pipeline/linkedin-candidates.json
```

The third command opens LinkedIn using the existing bot's browser, login, query planner, compatible filters, and job-description gates. It collects matching jobs without opening application forms, uploading a resume, or clicking Submit.

Review the collected jobs. To apply to a subset, create a reviewed artifact with the selected IDs and retain each record's provenance. Replace the example ID with an ID from your exported records:

```python
from uuid import uuid4
from modules.job_pipeline.models import StageResult, read_artifact, write_artifact

source = read_artifact("data/job_pipeline/linkedin-candidates.json", "linkedin_jobs")
selected_ids = {"1234567890"}
selected = [
    record for record in source.records
    if str(record.get("linkedin_id") or record.get("job_id") or record["id"]) in selected_ids
]
if not selected:
    raise ValueError("No selected IDs were found in the exported jobs")
reviewed = StageResult.create(
    "linkedin_jobs", "reviewed-linkedin", str(uuid4()), selected,
    delta=selected, input_set_ids=[f"linkedin_jobs:{source.set_name}"],
)
write_artifact(reviewed, "data/job_pipeline/reviewed-linkedin.json")
```

Pass that selected artifact to application mode:

```bash
python -m job_pipeline apply linkedin \
  --input data/job_pipeline/reviewed-linkedin.json \
  --set reviewed-applications \
  --limit 1 \
  --output data/job_pipeline/reviewed-applications.json
```

Application mode revisits the selected job IDs and revalidates company, role, and configured eligibility before entering the existing Easy Apply flow. It retains resume verification and enables a visible final review pause. It does not fill an application quota with unrelated search results. Existing per-search application quotas still apply; `--limit` is an upper bound on selected candidate work, not a promise of that many submissions. The default `max_applications_per_run = 1` in `config/search.py` also limits the whole command to one confirmed submission, so `--limit 5` can still submit at most one application.

For a combined LinkedIn search and application run, provide a verified-role set:

```bash
python -m job_pipeline run linkedin \
  --input hiring-roles \
  --set hiring-applications \
  --limit 1
```

Bare `python -m job_pipeline` and `python -m job_pipeline --help` print help without starting a browser or loading credential services. Importing `job_pipeline` and `runAiBot` is also safe; runtime browser and credential setup happens only when a requested LinkedIn run starts.

## Direct official-careers applications

`python3 job_pipeline.py apply careers --input /path/to/ranked.json --pause-before-submit always` consumes the saved verified-role order directly, fills each job in a new retained tab using the shared preparation/resume engine, and defaults to manual Submit on the employer pages. It continues filling without a separate review window and tracks confirmed outcomes in the applications stage. Every invocation creates a new run automatically, including repeated URLs from previous runs. Its printed path can be used with `python3 job_pipeline.py apply careers --resume /path/to/that/run` for explicit recovery. See [independent runs and retry examples](generic-url-preparation.md#submit-using-the-same-preparation-flow). Company discovery and verification remain separate steps; the existing LinkedIn lane is unchanged.

## Commands and input contracts

| Command | Input stage | Output stage | Limit applies to |
| --- | --- | --- | --- |
| `discover companies` | Optional company sets/imports | `companies` | Companies per source in the discovery run. |
| `verify careers` | `companies` | `verified_roles` | Companies checked in the verification run. |
| `rank careers` | `verified_roles` | `verified_roles` | All saved records; offline ordering never applies a limit. |
| `search linkedin` | `verified_roles` | `linkedin_jobs` | LinkedIn collection work for the run. |
| `apply linkedin` | `linkedin_jobs` | `applications` | Selected application work for the run. |
| `apply careers` | `verified_roles`, TXT/JSON or legacy direct queue | `applications` | Selected direct jobs; durable run cap also applies. |
| `run linkedin` | `verified_roles` | `applications` | Combined LinkedIn work for the run. |

The default set is `startup-companies`, and the default database is `data/job_pipeline/pipeline.sqlite3`. LinkedIn commands retain the `default_limit = 25` budget. Discovery and verification use their stage settings described below. Use `--set` to name the output set. `--input` accepts a JSON artifact path or a named set in the selected database; repeat it to combine multiple inputs of the required stage. Wrong-stage or malformed artifacts fail validation before browser startup. `--output` writes the returned result as JSON. Changing an output filename does not change the saved work's identity.

Successful commands return exit status `0`. A result with errors returns `1` while still printing and exporting its partial records. Invalid input or an I/O failure returns `2`. Inspect `errors` even when a partial result contains useful records.

Use `--refresh` on discovery, verification, search, or combined runs when you intend to restart that stage's scan. Discovery and verification also accept `--no-refresh` to override a configured refresh default. Discovery refresh resets its source cursor; verification otherwise uses its configured freshness window. `--source` may be repeated for discovery to restrict the configured sources. Discovery and verification accept `--render-public` and `--no-render-public`; these options are separate from LinkedIn browser and application settings.

The existing bot provides the same LinkedIn modes:

```bash
python runAiBot.py --mode search --input hiring-roles --set linkedin-candidates
python runAiBot.py --mode apply --input linkedin-candidates --set reviewed-applications --limit 1
python runAiBot.py --mode search-and-apply --input hiring-roles --set hiring-applications --limit 1
```

Both frontends use `runAiBot.run_pipeline(request)` and the same database, stage contracts, checkpoints, and history. The standalone `run linkedin` command maps to the same `search-and-apply` request mode as `runAiBot.py --mode search-and-apply`. Running `python runAiBot.py` without arguments retains the existing configured bot workflow, including application behavior.

## Configure discovery and verification

Edit [`config/job_pipeline.py`](../config/job_pipeline.py) to change stage budgets and behavior without adding command-line flags. These controls do not change application preferences, LinkedIn limits, resume settings, or submission pauses; those retain their existing configuration files.

| Discovery setting | Default | Behavior |
| --- | --- | --- |
| `discovery_limit_per_source` | `50` | Maximum company records requested from each source in one run. Positive integer. |
| `discovery_target_companies` | `250` | Stop further discovery once the cumulative output set reaches this target. Set `None` to disable the target. Existing and imported companies are retained. |
| `discovery_source_limits` | `{}` | Optional per-source budgets, for example `{"a16z": 100, "hn": 25}`. Values must be positive integers. |
| `discovery_refresh` | `False` | Restart source cursors when `True`; otherwise continue saved progress. |
| `discovery_render_enabled` | `False` | Enable bounded rendering of ordinary public JavaScript pages when needed. |

| Verification setting | Default | Behavior |
| --- | --- | --- |
| `verification_limit_companies` | `25` | Maximum companies checked in one run. Positive integer. |
| `verification_refresh` | `False` | Recheck companies even when their verification cache is fresh. |
| `verification_render_enabled` | `False` | Enable bounded public-page rendering when HTTP results require it. |
| `verification_prioritize_established` | `True` | Check companies with established-company evidence before early-stage and unknown companies. Ordering is stable within each group. |
| `verification_freshness_days` | `7` | Freshness window for cached verification and verified roles used by LinkedIn. Positive integer. |

| Shared setting | Default | Behavior |
| --- | --- | --- |
| `established_min_employees` | `50` | Explicit employee-count threshold for established-company evidence. Positive integer; count ranges use their lower bound. |
| `established_funding_stages` | Series B through Z, IPO, Public | Funding stages that establish company maturity without a known employee count. List of nonempty names. |
| `public_render_max_pages` | `5` | Maximum public pages rendered in a discovery or verification run. Positive integer. |
| `public_render_timeout_seconds` | `15` | Timeout for each rendered public page. Finite positive number. |

The existing `db_path`, `default_set`, `sources`, and `source_config` remain supported. `source_config` stores per-source adapter options such as permitted public URLs. `default_limit = 25` remains the LinkedIn default and supplies a stage budget for older configuration files that lack the corresponding new field.

Explicit discovery and verification CLI flags override their stage configuration. Discovery budget precedence is `--limit`, then `discovery_source_limits[source]`, then `discovery_limit_per_source`. Omitting `--limit` preserves source-specific budgets. `--target-companies N` overrides the cumulative target; `--target-companies 0` disables it for that run. Raising or disabling a reached target allows discovery to continue; a refresh does not remove existing companies from the set.

`--refresh`/`--no-refresh` and `--render-public`/`--no-render-public` override their stage defaults. Verification additionally accepts `--prioritize-established`/`--no-prioritize-established`. For example:

```bash
python -m job_pipeline discover companies --set ai-companies \
  --limit 100 --target-companies 500 --no-refresh
python -m job_pipeline verify careers --input ai-companies --set hiring-roles \
  --limit 40 --no-prioritize-established --no-render-public
```

Rendering is disabled by default. Enabling it starts the public-page renderer only when a supported adapter needs ordinary page rendering, within the page and timeout budgets. Access challenges and restricted responses remain recorded errors. Help and bare CLI imports do not start a renderer or load Chrome/OpenAI services, even when rendering is enabled in configuration. Invalid stage settings fail validation before discovery or verification work starts.

## Company discovery and source limitations

Discovery uses the enabled sources in `config/job_pipeline.py`. The public-source adapters cover Greylock, Sequoia, a16z, Y Combinator, Hacker News hiring threads, and HiringCafe where public data is available. Sources carry their observations into company records, including employee-count and funding-stage evidence when available.

Source availability is part of the result: a blocked page, inaccessible endpoint, unsupported import, or missing public data is recorded as an error or restriction rather than treated as a successful crawl. Wellfound and Crunchbase can be selected explicitly for permitted public-page discovery or supplied through authorized imports; neither is enabled in the default six-source list. Profile enrichment can fail even when a public company listing succeeds. The pipeline does not claim to bypass login or access restrictions. A partial result can still contain useful companies from other sources.

Discovery deduplicates company records and preserves source observations. Its saved source cursor allows later runs to continue adding companies instead of repeating the first page. The default budget is 50 companies per source per run, with a cumulative target of 250 companies; configure source overrides or disable the target when needed.

To import a permitted company export without crawling discovery sources, use:

```bash
python -m job_pipeline discover companies \
  --source import --input data/job_pipeline/company-export.json --set ai-companies
```

## Verification against official careers pages

Verification reads each company's official careers URL and follows the supported Ashby, Greenhouse, Lever, or generic structured HTML/JSON careers adapter. Python callers can supply a public-page renderer through the service's `render` argument. The CLI uses public HTTP requests by default and reports pages that need rendering; configure `verification_render_enabled = True` or pass `--render-public` to allow the bounded renderer. A LinkedIn search result alone does not establish that the company has an open official role.

Verification builds a broad inventory of official open engineering and related technical roles. It includes software, AI, data, hardware, security, reliability/SRE, support, forward-deployed work, and engineering management across seniority levels. Technical science/research and engineering-adjacent occupations such as solutions engineering and technical product/program management remain visible with review metadata. A technical department or company description alone does not turn recruiting, sales-account, marketing, or administrative occupations into engineering roles.

In `verified_roles`, `eligible` and `verification_eligible` mean open engineering-inventory inclusion. The configured `config/search.py` `search_location` gates inventory inclusion; mismatched and unknown locations remain in the full audit export with `location_excluded` or `unknown_location`, but stay out of the eligible shortlist. The shared geography matcher also permits explicitly supported US/California/global remote roles for the Bay Area and does not infer geography from an unqualified “Remote” label. Other candidate constraints no longer hide these postings: `application_eligible` and `application_exclusion_reasons` record the separate evaluation against current `config/search.py` location, work arrangement, employment type, date, company, exclusion-term, clearance, and experience settings. `review_notes` exposes these concerns and adjacent/research review; `role_classification` records the family, confidence, evidence, and review flag. Missing full descriptions remain visible for official open postings but block application and leave the crawl incomplete. Closed, unlisted, prospect, unknown-availability, and nonengineering postings do not become eligible engineering vacancies.

Records retain the title, description, official URL, company identity, department/team when supplied, locations, workplace and employment types, sources, verification time, and `verification_policy_version`. Fresh cached records are reevaluated under this policy without changing their observation timestamp or verification run. Refresh is still required to obtain new source evidence.

### Group and order verified roles for review

Verification exports every saved record in review order. Add the original resume to compare its existing vocabulary with each posting:

```bash
python -m job_pipeline verify careers --input ai-companies --set hiring-roles \
  --resume "all resumes/default/resume.docx" --output data/job_pipeline/hiring-roles.json
```

To reorder an existing verification artifact without fetching careers pages, launching Chrome, changing the source database, or applying to jobs:

```bash
python -m job_pipeline rank careers --input data/job_pipeline/hiring-roles.json \
  --resume "all resumes/default/resume.docx" --set ranked-roles \
  --output data/job_pipeline/ranked-roles.json
```

`--input` also accepts an existing saved verified-role set; repeat it to combine sets. Conflicting versions of the same role ID must be reconciled first. `rank careers` has no processing limit: all 90 open engineering roles in a 174-record verification remain present, as do the other 84 records for audit. `--set` labels this offline export; it does not create a new saved set. To reproduce a snapshot, add an explicit timezone-aware cutoff such as `--as-of 2026-10-15T12:00:00Z`. Normal execution uses the current UTC time. Ranking never makes an old source verification fresh; search/application still require their existing freshness and candidate checks.

Each record has separate `review_priority` metadata. Existing company `priority_tier`, source `verified_at`/`verification_run_id`, inventory inclusion, and application eligibility remain unchanged. Ranking metadata is derived when exporting, rather than persisted as a new careers observation. Legacy consumers may ignore it; LinkedIn query grouping and its company priority policy retain their existing behavior.

Posting age uses the source `published_at` value: at most 24 hours, at most seven days, at most 30 days, older, or unknown. Boundaries are inclusive. Future, invalid, missing, date-only, and timezone-free values have explicit unknown reasons; verification time is never substituted for posting time.

Optional resume affinity is a bounded lexical heuristic for choosing what to review first. It is **not an ATS score, a probability of selection, or proof of qualification**. It recognizes a fixed technical vocabulary with token boundaries and explicit aliases, avoiding Java/JavaScript and RAG/storage substring matches. Terms in the job title count twice; other recognized job-description terms count once. With a recognized title family, the numeric index is `80 × matched term weight / job term weight + 20 × matched title families / title families`. Without a recognized title family, it is `100 × matched term weight / job term weight`. High means at least 65, medium at least 35, and low below 35. Missing resume, missing description, and unrecognized job vocabulary produce unknown affinity, not zero.

The metadata reports the index, band, matched/missing terms, matched title families, reason, method version, cutoff, and SHA-256 of the original resume bytes. It does not save the resume text, path, contact details, or evidence excerpts. DOCX, PDF (with installed `pdfplumber`), UTF-8 text, and Markdown are supported. Use an original reviewed resume; this stage does not optimize it. Lexical matches can come from general or negated mentions and employer boilerplate, and the vocabulary is incomplete, so review the evidence rather than interpreting the index as validated experience.

| Review tier | Open engineering inventory conditions |
| --- | --- |
| 1 | Posted within seven days with medium or high resume affinity. |
| 2 | Any other posting within seven days; a posting within 30 days with medium/high affinity; or an older posting with high affinity. |
| 3 | Remaining open engineering inventory, including unknown posting dates. |
| 4 | Records outside open engineering inventory, retained for audit. |

Without `--resume`, affinity is unknown and review ordering uses posting recency: recent postings enter tier 2, others tier 3. Within a tier, sorting uses recency bucket, descending affinity index (unknown last), newest exact posting time, then company name, title, and stable role ID. This ordering groups roles without dropping any. It has no model/API calls and no dependency on the resume optimizer or its scoring implementation. Integrating a separately validated resume/JD scoring model is a future enhancement.

Only a successful complete careers crawl can mark an absent old role as closed. An inaccessible or incomplete crawl cannot establish current availability and preserves existing role data; the company's current hiring check can be recorded as unknown. Importing an older artifact does not revive a role already known to be closed. This distinction prevents an outage or blocked page from erasing valid discovery work.

### Role priorities

The version 2 search profile includes Staff/Principal infrastructure, platform, systems, inference, and SDK lanes, plus Member of Technical Staff variants for Systems, Inference Runtime, Machines, ML Performance, Platform Engineering, Product Backend, SDK, and Storage. Verification and LinkedIn preparation rank eligible roles in four tiers:

| Tier | Role/company evidence |
| --- | --- |
| 1 | Established companies with explicit Staff or Principal roles. |
| 2 | Established companies with relevant generic engineering roles, including Modal-style Member of Technical Staff, Systems, Inference, SDK, Infrastructure, Backend, Storage, Machines, ML, or performance work. |
| 3 | Early-stage companies and founding roles. |
| 4 | Companies whose scale or stage is unknown. |

With the default maturity settings, established-company evidence means a sourced employee count of at least 50 or a sourced Series B or later funding stage, IPO, or public-company status. The shared settings above control those thresholds. Unknown evidence remains unknown. Inventory includes engineering roles at all seniority levels. Later LinkedIn matching retains its junior-role and explicit seniority-downgrade guards. The profile holds semantic role intent, while application filters remain in `config/search.py`.

## LinkedIn matching and application boundaries

Search-target preparation retains fresh open engineering inventory even when candidate preferences require later review. Query snapshots still carry the configured filters; actual LinkedIn collection continues to apply those filters and its description, company, and seniority checks. This does not promise that every official posting will appear in a filtered LinkedIn result set.

Selected application preparation recomputes current candidate requirements independently, including in the combined search-and-apply flow. Imported `eligible` or `application_eligible` flags cannot authorize an application. Closed/prospect/stale or inconsistent parents, missing descriptions, and current candidate exclusions stop selection. The application runner also retains its live job/company/eligibility checks before forms.

LinkedIn collection uses the existing natural-language query planner and classic keyword fallback. It applies available UI filters and the existing post-discovery description gates. Matching checks company identity against the verified company and configured aliases; a loose partial name match is insufficient. A relevant related engineering title can match an official role family even if LinkedIn's wording differs.

Search mode saves a separate collection ledger. Collecting a job does not create a submitted application, consume application quota, or place the job in the applied history. Application mode accepts only IDs from the selected `linkedin_jobs` inputs and revisits those IDs for current validation. Missing, closed, changed, ineligible, or already-applied jobs are recorded with their outcome rather than replaced with unrelated results.

An application retains its source company and verified-role identity, selected LinkedIn ID, query identity, actual search mode, and historical search metadata. Collected records carry a full `search_spec` plus flattened query fields. Application records preserve the collected origin as `discovery_run_id`, alongside the application's `search_run_id`. Current canonical filters and verified parents govern revalidation while historical query wording, source, and profile identifiers remain traceable. Search and application use separate checkpoints so a search-only run cannot make later application mode believe that the collected job was submitted.

Pipeline applications set `pause_before_submit = True` before entering the existing application flow, retaining a visible final review even when background settings normally disable pauses. Verified-resume requirements and the user-configured `use_AI_for_resume` value are honored. Reviewing exports does not submit applications; the `apply` and combined `run` commands can submit after their application checks and review pause. Bare legacy bot runs retain their existing configuration behavior.

`max_applications_per_run` in `config/search.py` caps confirmed submissions across all queries in one command, including explicit `apply` and combined modes from either frontend. Its default is `1`; use a positive integer to change it or `None` to disable it. Failed or skipped applications and collected external application links do not consume this budget. `switch_number` remains a per-query application/external-link collection quota. `--limit` remains a candidate-work ceiling and does not override the submission cap. Search-only mode is unaffected. Bare bot runs share one submission budget across any nonstop cycles.

`chrome_profile_path` in `config/settings.py` selects a dedicated Chrome user-data directory; the default and an empty value use `~/.jobrobo/chrome-profile`. Safe mode uses a temporary browser profile. Search can use the configured background mode. Pipeline application runs use a visible browser, recreating a cached headless or invalid session when needed.

## Saved state and resume

The default SQLite database stores stage entities, source observations, named-set memberships, run records, and cursors. Repeated upserts are idempotent: importing or discovering the same entity updates its known record without adding duplicate applications or duplicate set members.

Each stage result contains the cumulative set and a separate delta of records added or changed in that run. A run that adds no new records still returns the previously saved set. Errors remain visible alongside partial progress.

LinkedIn resume identity uses the effective inputs and configuration, not the frontend command spelling or JSON output filename. Switching from `python -m job_pipeline` to `runAiBot.py --mode ...` can continue the same matching work when both use the same database, stage, set, inputs, and configuration. Search collection state and application manifests remain separate.

Reaching the submission cap stops the application manifest with `application_limit_reached` and leaves unfinished work resumable. A subsequent invocation starts a new command budget and resumes remaining work while retaining per-query counts and skipping protected job IDs.

With a submission cap enabled, an uncertain submission pauses further applications until its LinkedIn outcome is verified; it does not count as a confirmed submission.

Preserve the database and existing search/application manifests to retain resume and duplicate protection. Successful applications and uncertain submissions remain protected across entrypoints; an interrupted submission requires inspection on LinkedIn before a manual retry. A collection-only checkpoint can resume scanning without treating collected jobs as applied.

## Portable JSON contracts

All stage exports use `schema_version: 1` and these top-level fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Artifact contract version, currently integer `1`. |
| `stage` | `companies`, `verified_roles`, `linkedin_jobs`, or `applications`. |
| `set_name` | Name of the cumulative output set. |
| `run_id` | Run that produced this export. |
| `created_at` | ISO-formatted creation timestamp. |
| `input_set_ids` | Provenance identifiers for input sets. |
| `records` | Cumulative records in the output set. |
| `delta` | Records added or changed by this run. |
| `errors` | Structured errors and source restrictions. |

`StageResult` is both a dataclass and a mapping; Python callers can use attributes or dictionary-style keys. The canonical LinkedIn request is:

```python
from modules.job_pipeline.models import LinkedInRunRequest, read_artifact
from runAiBot import run_pipeline

verified = read_artifact("data/job_pipeline/hiring-roles.json", "verified_roles")
result = run_pipeline(LinkedInRunRequest(
    mode="search",
    input_sets=[verified.to_dict()],
    set_name="linkedin-candidates",
    output_path="data/job_pipeline/linkedin-candidates.json",
    limit=25,
    db_path="data/job_pipeline/pipeline.sqlite3",
))
print(result["stage"], len(result.records), len(result.delta))
```

Company records identify the company by ID, name, domain, website, careers URL, aliases, source evidence, employee count, and funding stage. Verified-role records add company ID and nested company details, title, description, careers URL, department/team, locations, workplace and employment types, separate inventory/application decisions and reasons, classification/review metadata, status (`open`, `closed`, or `unknown`), verification time, priority tier, and sources. LinkedIn and application records retain their upstream company/role references for traceability.

The artifact reader rejects unsupported schema versions, missing or unknown top-level fields, wrong-stage input, invalid timestamps, and nonportable JSON values. Exports are replaced atomically so a failed write preserves the previous file.

## Verification and troubleshooting

Run the automated suite from the repository root:

```bash
python -m unittest discover -s tests -v
```

Regression tests use local source fixtures and mocked browser, credential, and application services. Search-mode tests assert that application forms, resume uploads, and Submit are not reached; application tests check selected IDs, metadata, and resume behavior. No live applications are submitted by these tests. Live source accessibility and account-specific LinkedIn selectors must be reported separately from mocked verification.

The [recorded public smoke and CLI verification](job-pipeline-verification.md) lists the observed source restrictions, careers results, and the remaining live LinkedIn authentication limitation.

If an input is rejected, check its `stage`, `schema_version`, and selected `--db`. If a source is blocked, inspect `errors` and import a permitted export or use another available source. If careers verification reports unknown availability, inspect the official URL and retry; an inaccessible crawl is not proof that a job is closed. If a LinkedIn result fails identity matching, verify the company's official identity and aliases rather than weakening the match globally.

See the [dated read-only verification report](job-pipeline-verification.md) for observed source coverage and live LinkedIn limitations, and the [dynamic search guide](dynamic-search.md) for existing filter warnings, classic-search limits, and application-history metadata, and the [documentation index](README.md) for the rest of the workflow.
