# Job discovery pipeline

The pipeline keeps discovery separate from application. Discover companies, verify open engineering roles on their official careers pages, collect matching LinkedIn jobs, then apply to selected LinkedIn IDs. Each command saves cumulative records in a local SQLite database and returns a versioned JSON result that can be exported and passed to another command.

## How to run the stages

From the repository root, use a named set for each stage:

```bash
python -m job_pipeline discover companies --set ai-companies --limit 25
python -m job_pipeline verify careers --input ai-companies --set hiring-roles --limit 25 \
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

Application mode revisits the selected job IDs and revalidates company, role, and configured eligibility before entering the existing Easy Apply flow. It retains resume verification and enables a visible final review pause. It does not fill an application quota with unrelated search results. Existing per-search application quotas still apply; `--limit` is an upper bound on selected work, not a promise of that many submissions.

For a combined LinkedIn search and application run, provide a verified-role set:

```bash
python -m job_pipeline run linkedin \
  --input hiring-roles \
  --set hiring-applications \
  --limit 1
```

Bare `python -m job_pipeline` and `python -m job_pipeline --help` print help without starting a browser or loading credential services. Importing `job_pipeline` and `runAiBot` is also safe; runtime browser and credential setup happens only when a requested LinkedIn run starts.

## Commands and input contracts

| Command | Input stage | Output stage | Limit applies to |
| --- | --- | --- | --- |
| `discover companies` | Optional company sets/imports | `companies` | Companies per source in the discovery run. |
| `verify careers` | `companies` | `verified_roles` | Companies checked in the verification run. |
| `search linkedin` | `verified_roles` | `linkedin_jobs` | LinkedIn collection work for the run. |
| `apply linkedin` | `linkedin_jobs` | `applications` | Selected application work for the run. |
| `run linkedin` | `verified_roles` | `applications` | Combined LinkedIn work for the run. |

The defaults are `--limit 25`, `--set startup-companies`, and `--db data/job_pipeline/pipeline.sqlite3`. Use `--set` to name the output set. `--input` accepts a JSON artifact path or a named set in the selected database; repeat it to combine multiple inputs of the required stage. Wrong-stage or malformed artifacts fail validation before browser startup. `--output` writes the returned result as JSON. Changing an output filename does not change the saved work's identity.

Successful commands return exit status `0`. A result with errors returns `1` while still printing and exporting its partial records. Invalid input or an I/O failure returns `2`. Inspect `errors` even when a partial result contains useful records.

Use `--refresh` on discovery, verification, search, or combined runs when you intend to restart that stage's scan. Discovery refresh resets its source cursor. Verification otherwise uses a seven-day freshness window. `--source` may be repeated for discovery to restrict the configured sources.

The existing bot provides the same LinkedIn modes:

```bash
python runAiBot.py --mode search --input hiring-roles --set linkedin-candidates
python runAiBot.py --mode apply --input linkedin-candidates --set reviewed-applications --limit 1
python runAiBot.py --mode search-and-apply --input hiring-roles --set hiring-applications --limit 1
```

Both frontends use `runAiBot.run_pipeline(request)` and the same database, stage contracts, checkpoints, and history. The standalone `run linkedin` command maps to the same `search-and-apply` request mode as `runAiBot.py --mode search-and-apply`. Running `python runAiBot.py` without arguments retains the existing configured bot workflow, including application behavior.

## Company discovery and source limitations

Discovery uses the enabled sources in `config/job_pipeline.py`. The public-source adapters cover Greylock, Sequoia, a16z, Y Combinator, Hacker News hiring threads, and HiringCafe where public data is available. Sources carry their observations into company records, including employee-count and funding-stage evidence when available.

Source availability is part of the result: a blocked page, inaccessible endpoint, unsupported import, or missing public data is recorded as an error or restriction rather than treated as a successful crawl. Wellfound and Crunchbase can be selected explicitly for permitted public-page discovery or supplied through authorized imports; neither is enabled in the default six-source list. Profile enrichment can fail even when a public company listing succeeds. The pipeline does not claim to bypass login or access restrictions. A partial result can still contain useful companies from other sources.

Discovery deduplicates company records and preserves source observations. Its saved source cursor allows later runs to continue adding companies instead of repeating the first page. The default cap is 25 companies per source per run.

To import a permitted company export without crawling discovery sources, use:

```bash
python -m job_pipeline discover companies \
  --source import --input data/job_pipeline/company-export.json --set ai-companies
```

## Verification against official careers pages

Verification reads each company's official careers URL and follows the supported Ashby, Greenhouse, Lever, or generic structured HTML/JSON careers adapter. Python callers can supply a public-page renderer through the service's `render` argument for pages that need ordinary JavaScript rendering. The CLI uses public HTTP requests by default and reports pages that need rendering; discovery and verification do not automatically start Chrome. A LinkedIn search result alone does not establish that the company has an open official role.

Verified roles include the full title and job description, official role URL, company identity, locations, workplace arrangement, employment type, sources, verification timestamp, and eligibility outcome. Eligibility reads the existing canonical `config/search.py` settings: location, work arrangement, employment type, exclusion terms, security-clearance rules, and experience gates remain configured once.

Only a successful complete careers crawl can mark an absent old role as closed. An inaccessible or incomplete crawl cannot establish current availability and preserves existing role data; the company's current hiring check can be recorded as unknown. Importing an older artifact does not revive a role already known to be closed. This distinction prevents an outage or blocked page from erasing valid discovery work.

### Role priorities

The version 2 search profile includes Staff/Principal infrastructure, platform, systems, inference, and SDK lanes, plus Member of Technical Staff variants for Systems, Inference Runtime, Machines, ML Performance, Platform Engineering, Product Backend, SDK, and Storage. Verification and LinkedIn preparation rank eligible roles in four tiers:

| Tier | Role/company evidence |
| --- | --- |
| 1 | Established companies with explicit Staff or Principal roles. |
| 2 | Established companies with relevant generic engineering roles, including Modal-style Member of Technical Staff, Systems, Inference, SDK, Infrastructure, Backend, Storage, Machines, ML, or performance work. |
| 3 | Early-stage companies and founding roles. |
| 4 | Companies whose scale or stage is unknown. |

Established-company evidence means a sourced employee count of at least 50 or a sourced Series B or later funding stage. Unknown evidence remains unknown. Related engineering titles can match the configured role families; junior roles or an explicit seniority downgrade are excluded. The profile holds semantic role intent, while location and eligibility filters remain in `config/search.py`.

## LinkedIn matching and application boundaries

LinkedIn collection uses the existing natural-language query planner and classic keyword fallback. It applies available UI filters and the existing post-discovery description gates. Matching checks company identity against the verified company and configured aliases; a loose partial name match is insufficient. A relevant related engineering title can match an official role family even if LinkedIn's wording differs.

Search mode saves a separate collection ledger. Collecting a job does not create a submitted application, consume application quota, or place the job in the applied history. Application mode accepts only IDs from the selected `linkedin_jobs` inputs and revisits those IDs for current validation. Missing, closed, changed, ineligible, or already-applied jobs are recorded with their outcome rather than replaced with unrelated results.

An application retains its source company and verified-role identity, selected LinkedIn ID, query identity, actual search mode, and historical search metadata. Collected records carry a full `search_spec` plus flattened query fields. Application records preserve the collected origin as `discovery_run_id`, alongside the application's `search_run_id`. Current canonical filters and verified parents govern revalidation while historical query wording, source, and profile identifiers remain traceable. Search and application use separate checkpoints so a search-only run cannot make later application mode believe that the collected job was submitted.

Pipeline applications set `pause_before_submit = True` before entering the existing application flow, retaining a visible final review even when background settings normally disable pauses. Verified-resume requirements and the user-configured `use_AI_for_resume` value are honored. Reviewing exports does not submit applications; the `apply` and combined `run` commands can submit after their application checks and review pause. Bare legacy bot runs retain their existing configuration behavior.

`chrome_profile_path` in `config/settings.py` optionally selects a dedicated Chrome user-data directory; an empty value uses the existing default-profile lookup. Search can use the configured background mode. Pipeline application runs use a visible browser, recreating a cached headless or invalid session when needed.

## Saved state and resume

The default SQLite database stores stage entities, source observations, named-set memberships, run records, and cursors. Repeated upserts are idempotent: importing or discovering the same entity updates its known record without adding duplicate applications or duplicate set members.

Each stage result contains the cumulative set and a separate delta of records added or changed in that run. A run that adds no new records still returns the previously saved set. Errors remain visible alongside partial progress.

LinkedIn resume identity uses the effective inputs and configuration, not the frontend command spelling or JSON output filename. Switching from `python -m job_pipeline` to `runAiBot.py --mode ...` can continue the same matching work when both use the same database, stage, set, inputs, and configuration. Search collection state and application manifests remain separate.

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

Company records identify the company by ID, name, domain, website, careers URL, aliases, source evidence, employee count, and funding stage. Verified-role records add company ID and nested company details, title, description, careers URL, locations, workplace and employment types, eligibility and exclusion reasons, status (`open`, `closed`, or `unknown`), verification time, priority tier, and sources. LinkedIn and application records retain their upstream company/role references for traceability.

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
