# Company-scoped configured LinkedIn searches

Company scoping is opt-in. Existing commands without these flags retain their behavior.

## Inputs and flags

- `--companies-file PATH`: JSON catalog with `companies` entries containing `name` and optional string `aliases`, or a JSON array of names. Relative paths resolve from the working directory.
- `--company NAME`: repeat for multiple companies; inline entries are appended to file entries and deduplicated in first-seen order.
- `--company-batch-size N`: positive integer, default 10. The 292-entry `data/company_names.json` produces 30 batches.
- `--strict-company-filter`: skip missing, ambiguous or unmatched employer names before résumé generation, form preparation or external Apply. Matches the complete supplied list and explicit aliases, including companies in other batches. Uses Unicode/case/whitespace/punctuation and trailing legal-suffix normalization; no fuzzy or substring matching.

All flags require `--configured-search-and-apply`. Batch-size and strict flags require company input. Malformed, missing or empty input is rejected before opening the browser. Metadata/provenance in the catalog does not certify employer eligibility; existing job and application gates still apply.

## Commands

File input, default batch size, prompt targeting only (unrelated search results can still be processed):

```sh
python runAiBot.py --configured-search-and-apply --fresh --single-search \
  --companies-file data/company_names.json
```

Strict filtering and explicit batch size:

```sh
python runAiBot.py --configured-search-and-apply --fresh --single-search \
  --companies-file data/company_names.json \
  --company-batch-size 10 --strict-company-filter
```

Repeat inline names, select base prompt 2 and run two company batches:

```sh
python runAiBot.py --configured-search-and-apply --fresh --single-search 2 \
  --company "ByteDance" --company "Rive" --company "Griting" \
  --company-batch-size 2 --strict-company-filter
```

Combine file entries with inline names (existing names are deduplicated):

```sh
python runAiBot.py --configured-search-and-apply --fresh --single-search \
  --companies-file data/company_names.json \
  --company "ByteDance" --company "Rive" \
  --company-batch-size 10 --strict-company-filter
```

Bounded real-browser verification, with submissions disabled:

```sh
python runAiBot.py --configured-search-and-apply --fresh --single-search \
  --company "ByteDance" --company "Rive" --company "Griting" \
  --company-batch-size 2 --strict-company-filter --prepare-only --limit 3
```

The limit counts preparation attempts across the invocation, not companies or batches. If it is reached before the second batch, verify the remaining company with another bounded invocation:

```sh
python runAiBot.py --configured-search-and-apply --fresh --single-search \
  --company "Griting" --strict-company-filter --prepare-only --limit 1
```

For a compatible unfinished normal run, repeat its command without `--fresh`. Prepare-only runs always create a fresh manifest; prepare-only resume is not supported. `--single-search N` selects the base prompt before expansion, not the Nth company batch. Without it all configured base prompts are expanded. Normal submission caps apply across the entire invocation.

The company restriction is appended after existing AI refinement (or deterministic fallback) and preserved in classic keyword fallback. The manifest snapshots names, aliases, batch membership, size and strict policy. Changed scope cannot resume an incompatible run. Existing native LinkedIn filters also remain in effect.

## Tests and evidence

```sh
PYTHONPATH=tests:. python3 -m pytest -q \
  tests/test_company_search_scope.py tests/test_search_planner.py \
  tests/test_search_runner.py tests/test_linkedin_preparation_report.py
python3 -m unittest discover -s tests
```

Inspect `logs/search_runs/<run-id>.json` for effective query specifications, batch scopes, skips, and job outcomes. Console logs identify each batch and its company-scoped prompt. Prepare-only reports record readiness/failure with `submission_disabled: true`; absence of a confirmed submission alone does not prove a form reached enabled Submit. Check the recorded preparation outcome and diagnostics.
