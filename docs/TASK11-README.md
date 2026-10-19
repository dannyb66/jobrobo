# Task 11 README — resume optimization and full-rewrite workflow

### Latest checkpoint: configured rewrite and Skills layout

The current implementation supports complete per-JD rewrites, protected Academic
Distinctions, source-check configuration, exact job/config-bound PDF uploads and
resume progress logs. A live configured optimized upload completed through a
confirmed LinkedIn submission; the user also reported manual validation. The
Skills width change was subsequently checked with saved generation responses
and actual two-page rendering: 13 original Skills lines, each filling 95.6–99.7%
of available width. This was a layout replay, not a new employer submission.

The saved local all-bullets model is now `gpt-6-luna` with reasoning `none`, four
experience workers and four requested bullets per call. A small live API smoke
test passed; a full Luna rewrite quality benchmark remains pending. Saved local
configuration and generated personal artifacts are not committed. See
[the current configuration and concurrency reference](resume-all-bullets.md).

The dated implementation checkpoints below preserve earlier evidence and
limitations; their references to pending live uploads and older model settings
are historical. Programme status is maintained separately by the tracker owner.


**Current status, 18 October 2026: Task 11 remains In Progress.** The all-bullets path now combines source-supported Skills ranking, every-source-bullet rewriting and independently requested professional-title replacements. A new offline test verifies all three together with actual DOCX/PDF rendering; genuine complete-run and LinkedIn optimized-upload validation remain pending. The historical second Baseten run requested/responded to 54 bullets, with **42 changed unchecked proposals and 12 retained source bullets**. Its PDF has **three pages versus two required**, fails strict layout and is **not application-eligible**. Changed or received wording is not accepted rewriting. Do not upload that historical draft as an eligible result. Task 2/Baseten remains parked; new validation uses a saved non-Baseten JD.

This is the single current Task 11 README. It consolidates the command guide, handbook, approved full-rewrite plan and useful rewrite-flow reference. Historical files and original run artifacts are preserved; obsolete “not implemented yet” statements in those dated sources do not override this README. Consolidating these documents made no paid API request, commit, push or application action.

### 18 October implementation checkpoint

LinkedIn now uses one immutable optimizer configuration snapshot per job for generation and attachment verification. `source_checks_enabled` is a boolean in optimizer JSON (repository default `true`; saved runtime values override defaults). `true` uses grounded source-retention checks; `false` requires `rewrite_all_bullets=true` and selects the production `jd_rewrite` policy. That policy uses original bullets and numeric hints as optional drafting context, freely aligns wording to the JD, and skips source-content validation. It still requires every eligible bullet, exact job/JD/source/config binding, actual provider output, protected Academic Distinctions, and successful formatting before upload. Synthetic/manual previews cannot become production attachments. No original, partial or previous-job PDF fallback is allowed for this configured all-bullets path. A failed rewrite/upload stops that application before submission. Exact attached path, PDF hash and policy are retained even when cover-letter/question drafting is disabled.

Current active settings are in `/Users/deepakbasavaraju/Library/Application Support/jobrobo/config/resume_optimizer_defaults.json`: `source_checks_enabled=false`, `rewrite_all_bullets=true`, `optimization_mode="full"`, `replace_job_title=true`, concurrency4, batches4, `gpt-5.4`/low. `use_AI_for_resume=true` is set in `config/secrets.py`. Academic Distinctions is always preserved, and original numeric metrics are soft drafting/ranking preferences rather than validation gates. CLI `--source-checks` / `--no-source-checks` overrides the saved flag for standalone runs. The normal application flow optimizes once for each JD, uploads that exact PDF, completes the remaining form, and follows the existing Review/Submit pause, confirmation and quota logic. The current `config/search.py` cap is2 confirmed submissions per invocation; per-query quota is10 with explicit search quotas taking precedence. These settings enable the next user-run invocation; this implementation verification does not submit applications.

Use `python runAiBot.py --configured-search-and-apply --fresh --prepare-only --limit 2` to verify forms/uploads with Submit disabled. Use `python runAiBot.py --configured-search-and-apply --fresh` for the configured search-and-apply run, or `python runAiBot.py` for the existing entrypoint. Both reach the same optimizer/upload function; the shared job-pipeline LinkedIn runner delegates to it too.

Configured validation live19 completed47/47 eligible rewrites with all7 Academic Distinctions unchanged,57/70 original numeric expressions retained and two-page formatting verified. Its exact source/JD/job/config binding and source-checks-disabled production attachment policy independently passed verification. Both page images were inspected and the PDF/comparison opened. The body-only fixed-list keyword coverage was30.0%; the stronger numeric/context preference trades off some of the unconstrained synthetic test's77.5% literal coverage. These are local lexical diagnostics, not employer ATS scores or factual verification. Full factual review is still required when source checks are disabled. Unique upload PDF/DOCX names per job/run were added after this standalone process started and independently verified with actual-render artifact tests, avoiding repeated `optimized.pdf` UI selections. The final repository suite passed all1,169 tests in188.124 seconds. Ten dedicated LinkedIn integration cases verify config isolation, no stale/source fallback, once-per-job uploads across pages, artifact provenance and existing pause/Submit/receipt/quota flow using mocks. No live LinkedIn optimized upload or submission was performed; that browser test remains separate. Evidence: `/Users/deepakbasavaraju/Documents/Codex/2026-10-18/task11-full-tailoring/live19-configured-rewrite-receipt.json`. Preliminary live18 was cancelled after discovering leftover synthetic wording in two production payload fields; those fields were fixed before live19. Live17's earlier numeric-hint experiment was partial45/47 with17/69 numeric expressions retained among accepted bullets; it is not the final configured result.

Academic Distinctions is now preserved verbatim in every rewrite mode: ordinary, strict grounded/review, synthetic JD testing, and unchecked saved-result exports. Its heading, text and run formatting are checked before acceptance. It is excluded from model requests and rewrite coverage; this original resume now has47 eligible bullets and7 preserved Academic Distinctions. Original paragraph/ordinal-based IDs remain stable for other sections. A network-blocked replay reused live15's saved text for47/47 eligible bullets, preserved all7 distinctions exactly, and passed the two-page layout check; this was not a new AI generation. Synthetic generation also now receives optional original numbers with nearby unit/metric context, preferring useful quantified results without restoring numeric-retention or source-fidelity validation gates.

The explicit standalone `--synthetic-jd-test --rewrite-all-bullets` experiment removes source-content restrictions to measure unconstrained JD alignment. It sends only the complete JD, target role, routing IDs/hashes and measured bullet-slot geometry; original bullet/company/experience text and fact anchors are omitted. Its final prompt override permits fictional JD-derived accomplishments, response validation bypasses source fact/technology/ownership/metric/word-retention gates, and Skills are replaced with JD terms. Routing identity, response syntax, clean text, actual one-line fit, page/format/link checks and artifact integrity remain. Synthetic Skills may occupy a different width but retain source line count and page placement. The mode is mutually exclusive with `--review-draft`, requires all-bullets mode, labels its comparison/report as synthetic, and can never return an application attachment. Normal policy defaults and application settings remain unchanged. This experiment does not establish a faithful applicant resume or completion of the grounded optimization work.

Live15 completed the requested unconstrained test:54/54 bullet slots rewritten,0 originals retained,54 distinct sentences,86 JD-derived Skills entries and six professional-title changes. Artifact binding and all format checks passed; both pages were visually inspected, and the PDF/comparison opened. With the same fixed80-concept list from live14, bullet-only lexical coverage was13.8% original,16.2% constrained draft,77.5% synthetic draft. This comparison excludes Skills/titles; the synthetic run's separate100% whole-document lexical figure includes its JD-derived Skills and uses a different extracted list. These are textual-coverage measures, not ATS scores or applicant evidence. The synthetic output includes invented technologies/ownership/authorization, repeated responsibility patterns, engineering bullets in academic slots, and job attributes in Skills. All267 resume regression tests passed in194.112 seconds, including six new synthetic tests and actual rendering. No original changed, no upload occurred, and strict attachment verification rejected the synthetic PDF as intended. Evidence: `/Users/deepakbasavaraju/Documents/Codex/2026-10-18/task11-full-tailoring/live15-synthetic-receipt.json` and `live15-fixed-keyword-comparison.json`.

Latest requested rerun, live14, used the saved prompt verbatim (SHA256 `d4fa2ce7076b90a91aaf8f54ca7cc44225b5791ebbf4bb5f1018a8929d4d6b62`), the same immutable original resume and complete Sela JD. All54 bullets were requested/responded;34 rewrites passed local checks and20 originals were retained. Skills retained105 logical entries and six professional titles changed. Two-page layout and artifact binding passed; both rendered pages were visually inspected. The within-run lexical estimate was27.2-to29.6, with a newly extracted keyword denominator, so it cannot be compared directly to earlier run percentages. Spot checks still find meaning/detail concerns, including release-gate wording becoming evaluation-harness wording and MoE/task-compatibility detail disappearing. Full manual content review remains pending. Four focused prompt tests passed using unittest discovery. The partial review draft remains ineligible for automatic attachment; PDF and comparison opened for review. No application/upload occurred. Evidence: `/Users/deepakbasavaraju/Documents/Codex/2026-10-18/task11-full-tailoring/live14-user-prompt-receipt.json`.

The user-edited JD-first generation prompt is now canonical at [`config/prompts/resume_bullets.txt`](../config/prompts/resume_bullets.txt). Fresh Python processes load it verbatim; the shared optimizer adapter and default provider send that same pinned text. Each run saves its exact prompt and SHA256. The old clause-rotation/passive references were removed from request payloads, and the alternative order now follows JD-first, engineering-first, impact-first. Review-only request wording permits selecting and condensing peripheral details, while existing local guards still decide acceptance. Live12 began with the first user edit, then was cancelled when the user updated the canonical file again. Live13 finished using the newest saved prompt (SHA256 ddcfd8d55dadc9e20025b15d329318fce8ea59fbcbd0325c7aa60a7ab4a5ae21):35/54 rewritten,19 originals retained,2-page layout passed. Its frozen keyword estimate was36.4-to38.6; new globally matched phrases were “Data and AI” (title-associated) and “agentic systems”. Both pages were inspected visually and artifact hashes verified; full manual content review is pending. The strict attachment verifier correctly rejects this review-only draft. PDF and comparison opened for user review. No application/upload occurred. Editing an earlier run's prompt file does not change runtime; edit the canonical file for future runs. The original live11 prompt was recovered from the captured source snapshot and verified against its recorded SHA without replacing the user's edited file.

The requested JD-alignment update adds explicit same-experience supported JD targets to bullet requests and candidate ranking, including narrow capability wording equivalents with quoted source evidence. Excluded JD terms are checked against returned candidates as well as named in the prompt; unsupported tools cannot gain priority merely by matching the JD. Source facts and measured fit remain mandatory. Each bullet records readable added JD keywords for review. The comparison puts every raw JSON block in collapsed diagnostics at the bottom, after the original/draft/JD panes and bullet table.

Skills parsing now keeps parenthesized commas together and separates distinct paragraphs. Relevance-preserving layout recovery can wrap existing spaces, hyphens and slashes while retaining logical entries, original fonts and source format. An actual-source local probe preserved105 logical entries, including “Snowflake (Snowpark, Cortex AI)”, and passed13-to13-line density. The previous106 count split that compound entry incorrectly. Live10 finished17/54 accepted with2-page layout passing; keyword estimate38.8-to40.0 came from titles and no accepted bullet added a tracked JD term. Its17 selected pairs were reviewed:14 without a clear major issue and3 needing clarification. All five archived candidate JD gains exceeded the estimated line budget. This did not meet the bullet-keyword alignment goal. No application/upload action is included.

A separate explicit `--review-draft --rewrite-all-bullets` standalone mode now permits concise accurate paraphrases instead of requiring every original content word. It retains numeric, known-technology, metric, scope, ownership, excluded-JD-term and layout checks; missing source words are recorded for human review. Supported JD wording gains count as meaningful edits, and each bullet receives its own evidence-backed opportunities. ReAct reasoning is distinguished from React UI experience. These checks are bounded heuristics, not semantic verification. Review drafts carry `source-facts-manual-review-v1`, remain ineligible for strict attachment even when all bullets render, and never change normal application settings. Default grounded behavior retains strict term protection. Live11 finished with31 rewritten and23 original bullets. Four bullets added evaluation/reliability wording locally, but both terms already occur elsewhere in the source; the only new globally matched phrase was “Data and AI” from title replacement. Its36.9-to38.1 keyword estimate is therefore title-associated lexical gain, not demonstrated bullet-driven ATS improvement. Independent review found10 meaning/scope concerns among31 selected pairs. Both rendered pages were visually inspected, five JSON blocks were verified after the panes/coverage table, artifact hashes passed, and the strict attachment verifier rejected the review-only PDF. The exact JD, PDF and comparison were opened for user review. No complete faithful54/54 result or optimized application upload has been established. Full manual source/JD/output review remains necessary. Use `--review-draft` only with `--rewrite-all-bullets`; `--preflight` still makes no provider call.


Work is on `fix/resume-full-tailoring`; unrelated existing workspace changes are preserved. New genuine tests use immutable original DOCX/PDF copies and the complete saved Sela JD. No generated result has been uploaded, and no employer actions have occurred. Normal application settings remain unchanged; Task2/Baseten remains parked.

| Genuine run | Automatic acceptance | Manual selected-output review | Layout |
| --- | --- | --- | --- |
| live05 | 50/54 | 29 clear material omissions,7 further concerns,14 without clear loss observed | Passed |
| live07 | 32/54 after stronger source checks | 21 without clear material/major grammar issue observed;11 needing correction/clarification | Passed |
| live08 | 33/54 | 25 without clear material/major grammar issue observed;8 needing correction/clarification | Passed |
| live09 | 29/54 | 21 without clear major issue;8 needing correction/clarification | Passed |
| live10 | 17/54 | 14 without clear major issue;3 needing clarification; no accepted bullet JD-keyword gain | Passed |
| live11 review-only | 31/54 | 21 without clear major issue;10 needing meaning/scope clarification | Passed |

These are partial diagnostics, not faithful complete resumes. In particular, live08's accepted ordinal48 ended with the cut-off name “Institute Awa”; another occurrence of “award” hid the loss from set-based recall. The new incomplete-word regression rejects that case. Every selected pair in these three runs was manually reviewed; both live07/live08 rendered pages were inspected. Reports and hash-bound manual reviews are under `/Users/deepakbasavaraju/Documents/Codex/2026-10-18/task11-full-tailoring`.

The combined path records actual source-supported Skills changes, every-source-bullet coverage and professional-title changes. It binds response IDs/hashes to each request, preserves successful siblings, evaluates up to three structural candidates and recovers Skills layout without dropping terms or shrinking fonts. Skills remain grounded even under `review_draft`. Same-experience technical evidence may support terminology, but cannot excuse dropping original bullet facts or transferring sibling metrics. Inexact JD quotes are discarded without evidence credit. Source/JD/draft strings remain untrusted data.

The conservative `source-content-retention-v1` safeguard protects content terms, known technical identities, ownership/scope/modality, negation/intent phrases, selected quantity/timeframe relationships, engineering activity, delimiters and incomplete words. Normal grammatical inflections are allowed. Source-only clause/passive references help draft compact alternatives; no reference is automatically accepted. These lexical checks are **not semantic proof**. Complete manual content and page review remains necessary before upload; older artifacts lacking the retention contract cannot pass the verifier.

An exact source-character cap caused cut-off words and private-use padding. The schema now bounds runaway generation while actual measured glyph/PDF width remains the mandatory one-line/two-page gate. The source-derived soft character guide accounts for measured available width. Private-use/control additions are rejected. The JD parser also recognizes role headings after ignored company text, preventing the earlier empty matching denominator. Local rendering has its own60-second allowance; provider deadlines and explicit cancellation still govern completion.

`rewrite_bullets_per_request` supports1–12 (default12) with complete experience/JD context. Optional `rewrite_token_estimation="tiktoken"` estimates model-tokenized payload/schema plus overhead for rate pacing; default `byte_upper_bound` remains unchanged. Cost/context reservations retain byte upper bounds. Reported token usage exceeding the rate estimate stops new dispatch. Caps are unchanged. A targeted probe on two formerly blocked bullets now passes2/2 after correcting a real clause-relocation false rejection involving plural inflections. Live09 completed with2-bullet batches/concurrency4 and the same300-second/45-second/$2-estimate/rate bounds: all54 requested/responded,29 accepted automatically and25 originals retained. Its two rendered pages were inspected; the format checks passed, Skills changed and six professional titles changed. Known usage estimate is $1.1534875; incomplete/unknown request usage is not an invoice. Independent review has already found ownership/action-object problems in selected outputs. Skills sorting also separates comma-containing parenthesized entries, such as Snowflake (Snowpark, Cortex AI), so term preservation alone does not establish usable Skills prose. Neither the partial draft nor its automatic count establishes faithful completion.

The current code passed all1,140 repository tests in203.019 seconds. All4 focused prompt tests also passed, including a packaging/frozen-resource loader test added after full-suite discovery. Actual DOCX/PDF rendering is covered. Synthetic complete fixtures do not establish genuine54/54 success; older canned fixtures are now correctly tested as partial under stronger fidelity checks.

Next: obtain one genuinely faithful complete standalone result, inspect every bullet/Skills/title diff and every rendered page, then test one optimized upload and the ten-job loop through the existing LinkedIn runner. Both browser tests must use `--prepare-only`; final Submit is disabled. Optimization failure must not upload the original or a previous job's PDF. No complete polished54/54 result or optimized upload has been established.

## Read this workflow in order

1. Prepare your original DOCX and matching PDF, plus the complete selected JD.
2. Choose ordinary `full` / `bullets` / `skills`, or explicitly opt into strict all-bullets behavior. Choose target-title input independently from historical-title replacement.
3. Run a provider-free preflight. A pending AI title is a declared next paid stage, not a fabricated title or an extraction failure.
4. Authorize a new paid run separately if needed. Every output goes to a new directory with source/JD/title/provider provenance.
5. Verify the exact artifacts, every page and per-bullet coverage in the original / draft / exact-JD comparison. A partial or unchecked draft is not an accepted attachment; this standalone workflow never submits an application.

[`optimize_resume.py`](../optimize_resume.py) is the executable entrypoint. It takes an original resume, a complete job description, a mode and an optional title override, then saves the optimized resume and review evidence in a **new output directory**. It calls JobRobo's existing engine; it is not a standalone replacement for the repository. No application upload or submission is included.

## Dependencies and working directory

On Danny's Mac, the verified interpreter is `/opt/homebrew/anaconda3/bin/python3`; the repo is `/Users/deepakbasavaraju/Documents/GitHub/jobrobo`. This runner uses the installed repository dependencies, including `python-docx`, `pdfplumber`, `openai`, `python-dotenv`, `requests`, the existing `modules/` code and `config/` skill/bullet banks. DOCX conversion requires LibreOffice; the verified path is `/Applications/LibreOffice.app/Contents/MacOS/soffice` (or configured `LIBREOFFICE_PATH`). The optional tokenizer estimator additionally uses pinned `tiktoken==0.12.0` (now in `requirements.txt`); it was installed in the verified interpreter without dependency upgrades. First encoding initialization downloads a public vocabulary; prewarm with `python -c 'import tiktoken; tiktoken.get_encoding("o200k_base")'` before offline/tokenizer tests. Ordinary/default byte estimation needs no tokenizer initialization. No virtual environment creation is needed for these verified commands.

Use an original editable `.docx` plus its matching original `.pdf` in the same directory with the same filename stem. The paired PDF provides actual page count and layout measurements. Source files are copied and preserved. PDF-only input supports **Skills editing only**, with title replacement disabled; the runner rejects PDF bullet/title requests instead of silently downgrading them.

```sh
cd /Users/deepakbasavaraju/Documents/GitHub/jobrobo
/opt/homebrew/anaconda3/bin/python3 optimize_resume.py --help
```

## Actual mode and title behavior

| `--mode` | Ordinary DOCX scope | Default title behavior in this runner |
| --- | --- | --- |
| `skills` | Updates Skills using existing grounding/ranking/layout rules; retains bullets. | Preserves dated professional titles. |
| `bullets` | Updates Skills; rewrites ordinary professional bullets and applies matching configured company/project banks. This is not every source bullet. | Preserves dated professional titles. |
| `full` | Runs the ordinary `bullets` scope above. | Also replaces recognized dated professional titles with the resolved target title. |

`--replace-title` independently enables recognized dated professional title replacement in **any DOCX mode**, including `skills`. `--no-replace-title` preserves those titles even in `full`. Aliases `--replace-job-title` / `--no-replace-job-title` are accepted. If neither is supplied, the runner explicitly uses the mode defaults in the table; it does not inherit a conflicting saved title setting. Replacements preserve dates/punctuation; summary and project titles remain unchanged. A requested replacement does not establish that the new title is historically accurate: review the title changes before use.

## Target title: automatic resolution and explicit override

`--job-title` chooses the **target role for optimization/matching**. It does not itself edit past employment titles. `--replace-title` / `--no-replace-title` independently enable/preserve **historical professional titles**, with the [mode defaults above](#actual-mode-and-title-behavior). The target title is optional on the command line. Resolution uses this order:

1. A nonblank explicit `--job-title` wins, even if structured metadata names a different role.
2. Otherwise use the title of the single unambiguous structured `JobPosting` selected from `--jd-url`.
3. If that title is missing, blank or ambiguous—or the JD came from `--jd-file` / `--jd-text`—execution makes **one AI title-extraction call using the full exact JD**, then continues optimization automatically.

Blank explicit values are treated as absent. The AI must return strict JSON with a supported target role and exact JD evidence quotes. It cannot add seniority/role terms absent from its quoted evidence; singular/plural normalization is allowed. It does not derive a title from generic HTML `<title>`, applicant history or a fabricated role. Unsupported/ambiguous JD content, invalid JSON/evidence or provider errors produce an honest actionable error; pass a verified explicit title to bypass extraction. These lexical checks constrain the output but do not prove semantic correctness, so review the resolved title.

`job_title` and `job_title_source` (`explicit_job_title`, `structured_jobposting`, `ai_extraction`) are saved in input provenance and run summary. `title-extraction.json` retains the AI stage's response/ID, evidence, model, usage, timing and configured-cost estimate without credential/transport headers. The engine receives that resolved title. `--job-title` selects optimization context; it remains separate from `--replace-title`, which controls editing historical titles.

**Preflight never makes the AI call.** When free sources cannot resolve a title, it exits 0 with `status: preflight_requires_ai_title`, `job_title: null`, `job_title_source: ai_extraction_required`, `title_extraction_needed: true` and a conservative configured-rate extraction estimate. It reads no key, creates no output directory and does not continue to paid optimization. Supply `--job-title` to fully resolve a free preflight, or run normally to permit the already-documented paid extraction/optimization workflow.

A page with multiple JobPosting objects is still rejected before provider work, even with an explicit title: choosing the correct **description** is a separate ambiguity. Save only the selected complete JD in a text file; title extraction can then run from that file. No unrelated posting is silently selected.

The separate `--rewrite-all-bullets` flag defaults **off**. It selects Task 11's strict source-inventory path for DOCX `full` or `bullets`: every experience/project/academic bullet, stable IDs/count/order, full exact JD plus whole original experience per worker, bounded retries and one rendered line per accepted bullet. It also runs the existing source-supported Skills ranking/updater while preserving Skills formatting and measured space. Target-title replacement remains independent. It rejects `skills` mode. `--rewrite-experience-concurrency 1..4` (default 2) controls this strict path; it does not enable it or change ordinary-mode scope. Reports identify this combined behavior as `all-bullets-skills-titles-v1`; older all-bullets-only artifacts cannot satisfy the new attachment contract.

The runner selects grounded content policy explicitly. It does not expose an unchecked mode or relax source, numeric, ownership or layout checks. The complete strict contract, implementation map and original acceptance plan are consolidated below.

## Choose the job-description input

Exactly one is required:

- `--jd-file /absolute/path/complete-jd.txt`: UTF-8 text, preserved exactly including whitespace. Recommended for a browser-copied full JD.
- `--jd-text 'Complete job description text'`: full inline text, not just a link. Shell history may retain the text.
- `--jd-url 'https://public.example/jobs/123'`: uses the existing bounded public GET client (12-second request timeout, redirect/access/private-host checks, 2 MB response ceiling) and requires exactly **one unambiguous `JobPosting` JSON-LD description**. HTML markup in that complete structured description is converted to plain text; no model summary or truncation occurs. The source URL, page hash, posting title and exact extracted JD hash are saved.

URL support is intentionally specific. JavaScript-only, login/challenge, malformed or multiple-job pages fail with instructions to use `--jd-file`; the runner does not guess that page navigation text is the JD, bypass challenges, or claim every ATS URL works. View the actual job link in your browser, copy its complete responsibilities/requirements/preferred qualifications into a text file, and compare it against the page when structured extraction is unavailable. A page can publish incomplete structured data, so review the extracted text before authorizing a paid run.

## Preflight without an OpenAI call

`--preflight` validates options, original/paired files, page count and exact JD, then prints the plan, including whether title extraction would be needed. It creates no output directory and reads no credential. A URL preflight performs public GETs; a text/file preflight has no network activity. Use a new, not-yet-existing output directory even for preflight.

```sh
/opt/homebrew/anaconda3/bin/python3 optimize_resume.py \
  --resume "/absolute/path/original.docx" \
  --jd-file "/absolute/path/complete-jd.txt" \
  --job-title "Exact target job title" \
  --mode full --no-replace-title \
  --output "/absolute/path/new-review-run" --preflight
```

## Baseten reference examples: with and without an explicit title

Exact Task 11 posting: [Baseten — Software Engineer - Inference Platform](https://jobs.ashbyhq.com/baseten/14c4a663-0b1f-4c11-93ff-1359741ee456). The read-only URL preflight on 16 October 2026 resolved that title from JobPosting metadata with **zero OpenAI calls**. A future page change can affect extraction. The saved JD below is the original Task 11 input; it is not silently replaced with a newly fetched description.

Run this setup once in the same terminal. These existing paths refer to Danny's Mac; substitute your original DOCX/paired PDF and complete JD file for another job:

```sh
cd /Users/deepakbasavaraju/Documents/GitHub/jobrobo
TASK11_PY=/opt/homebrew/anaconda3/bin/python3
TASK11_RESUME="/Users/deepakbasavaraju/Documents/Codex/2026-10-14/task-2/evidence/baseline/source/resume.docx"
TASK11_BASETEN_URL="https://jobs.ashbyhq.com/baseten/14c4a663-0b1f-4c11-93ff-1359741ee456"
TASK11_JD_FILE="/Users/deepakbasavaraju/Documents/Codex/2026-10-15/task-2/evidence/task11-live-manual/20261015T212421-09109bcfbf/exact-jd.txt"
TASK11_JD_TEXT="$(cat "$TASK11_JD_FILE")"
```

All four examples below are **provider-free preflights**, preserve historical titles and create no output directory. URL examples may fetch the public page. Each output must remain a new directory. Removing `--preflight` starts paid optimization and, when required, AI title extraction; doing so needs authorization for that new run.

URL with automatic structured/AI target-title resolution (no `--job-title`):

```sh
"$TASK11_PY" optimize_resume.py \
  --resume "$TASK11_RESUME" --jd-url "$TASK11_BASETEN_URL" \
  --mode full --no-replace-title \
  --output "/tmp/task11-baseten-url-auto-reference" --preflight
```

URL with an explicit target title that takes precedence over metadata:

```sh
"$TASK11_PY" optimize_resume.py \
  --resume "$TASK11_RESUME" --jd-url "$TASK11_BASETEN_URL" \
  --job-title "Software Engineer - Inference Platform" \
  --mode full --no-replace-title \
  --output "/tmp/task11-baseten-url-explicit-reference" --preflight
```

Saved complete JD file with automatic AI extraction deferred until a normal run:

```sh
"$TASK11_PY" optimize_resume.py \
  --resume "$TASK11_RESUME" --jd-file "$TASK11_JD_FILE" \
  --mode bullets --no-replace-title \
  --output "/tmp/task11-baseten-file-auto-reference" --preflight
```

Complete JD supplied as text, with an explicit title to avoid the extraction stage:

```sh
"$TASK11_PY" optimize_resume.py \
  --resume "$TASK11_RESUME" --jd-text "$TASK11_JD_TEXT" \
  --job-title "Software Engineer - Inference Platform" \
  --mode skills --no-replace-title \
  --output "/tmp/task11-baseten-text-explicit-reference" --preflight
```

The text example loads the complete saved JD into an argument, not a URL or summary. Shell command substitution removes trailing newlines; use `--jd-file` when preserving the stored text byte-for-byte matters. Inline text may remain in shell/process history. For strict all-bullets behavior, add `--rewrite-all-bullets --rewrite-experience-concurrency 2` to a DOCX `full`/`bullets` example; it remains incompatible with `skills` and PDF-only input.

## Run and save an optimized resume

These commands call OpenAI and disclose original resume content and the complete JD. They are manual templates for a separately authorized paid run; **no new paid run was made while implementing this runner**. Replace placeholders and choose a fresh output directory for each run. `--output` is a run directory, not a PDF filename; existing files/directories are never overwritten.

Full ordinary scope with historical titles preserved:

```sh
/opt/homebrew/anaconda3/bin/python3 optimize_resume.py \
  --resume "/absolute/path/original.docx" --jd-file "/absolute/path/complete-jd.txt" \
  --job-title "Staff Software Engineer" --mode full --no-replace-title \
  --output "/absolute/path/new-full-review"
```

Ordinary bullets plus Skills, with explicit title replacement:

```sh
/opt/homebrew/anaconda3/bin/python3 optimize_resume.py \
  --resume "/absolute/path/original.docx" --jd-text 'Complete exact job description goes here' \
  --job-title "Staff Software Engineer" --mode bullets --replace-title \
  --output "/absolute/path/new-bullets-review"
```

Skills only (DOCX or original PDF), titles preserved:

```sh
/opt/homebrew/anaconda3/bin/python3 optimize_resume.py \
  --resume "/absolute/path/original.pdf" --jd-file "/absolute/path/complete-jd.txt" \
  --job-title "Staff Software Engineer" --mode skills --no-replace-title \
  --output "/absolute/path/new-skills-review"
```

Strict all-bullets, two parallel experience workers, supported structured URL **without `--job-title`** (structured title first, AI fallback if needed):

```sh
/opt/homebrew/anaconda3/bin/python3 optimize_resume.py \
  --resume "/absolute/path/original.docx" --jd-url 'https://public.example/jobs/123' \
  --mode bullets --no-replace-title \
  --rewrite-all-bullets --rewrite-experience-concurrency 2 \
  --output "/absolute/path/new-strict-review"
```

Title extraction is at most one request, with a 45-second-or-shorter timeout, 700 output-token ceiling, strict JSON schema and no SDK hidden retries. Full JD context is never truncated. A context/budget overflow stops before the title request. Its estimate uses the same configured token rates, not a current provider billing quote. For strict all-bullets runs, reported usage (or the conservative reservation when usage is unknown), one request and elapsed extraction time are subtracted from the configured total allowance before optimization. An exhausted allowance blocks further calls. The strict path applies its configured context/request/rate/time/estimated-cost budgets. The default configured $2 token-cost estimate is **not a provider invoice or hard billing cap**. One keyword request plus up to twice the actual experience sub-batch count bounds strict optimization attempts, plus at most one optional title-extraction request within the configured total request allowance; queue/backoff consumes the 300-second default deadline, each request has a 45-second default timeout, and SDK hidden retries are disabled. Ordinary modes retain their existing engine limits and retry behavior; do not assume the strict run-wide budget governs them. Cancellation stops new strict dispatch; calls already sent may remain charged.

## Secure local credential loading

The runner uses an already configured `OPENAI_API_KEY`, or privately loads the repository `.env` only inside its process. A fallback `.env` must be a regular non-symlink file, permission `0600`, Git-ignored and untracked. It is never created or edited by this runner. The loaded key goes directly to the existing OpenAI client and is not printed, persisted, put in command arguments or added to the environment. The injected engine client avoids its normal dotenv loader. Do not paste keys into this file, terminal commands, chat or fixtures; do not open credential files during code review.

Per-call mode/config/client/output injection is backward compatible; normal existing callers keep their behavior. The CLI copies configuration in memory, forces its explicit options and original PDF page count for that call, and never saves shared/runtime configuration.

## Output, success and review

A new run directory contains:

- `inputs/original.docx` and matching PDF (or the original PDF alone), exact byte copies.
- `exact-jd.txt` and `input-provenance.json`, binding source/JD hashes, URL provenance, selected mode/title/strict settings.
- `review/` containing engine PDF/DOCX, reports and any partial/fit-retry artifacts. Ordinary successful output normally starts as `review/optimized.pdf`; retries can have another filename. Always use the actual path in the summary.
- `run-summary.json`, with resolved title/source, title-stage/total provider counts, `optimized_pdf` only for eligible generation, `preview_pdf` for a retained diagnostic artifact, `engine_status`, `effective_mode`, `rewrite_completed`, coverage and `generated_attachment_eligible`.

Exit 0 means the requested production run passed the runner's acceptance checks. Exit 2 means invalid input, blocked/partial generation or a failed check; a preview may still exist. Ctrl-C returns 130. For ordinary `full`/`bullets`, a format-only or Skills fallback without a completed rewrite cannot be promoted to success. Strict all-bullets also requires source/JD artifact binding and every-bullet completion. Offline test collaborators stay labeled fixtures and never become application attachments.

Open the actual reported PDF/DOCX for review; no opening command makes another API call:

```sh
open "/absolute/path/new-review-run/review/optimized.pdf"
```

Strict runs additionally supply the original / draft / full exact JD three-pane `review/comparison.html`, per-ID coverage, archived provider responses and artifact hashes. Ordinary modes retain their existing detailed match/change reports; this wrapper does not fabricate a strict coverage manifest for them. Before/after scores remain **local heuristic match estimates, not employer ATS rankings, verified qualifications or hiring probability**.

## Existing Baseten evidence is still partial

The first genuine strict run accepted **1/54** bullets. The second genuine **unchecked** run made 18 calls and produced **42 changed / 12 retained** bullets, with all 54 requested/responded. It rendered **three pages**, failed global two-page/one-line layout, and remains ineligible. The corrected saved-response replay made zero additional API calls and preserves those draft pages. This new CLI does not claim that draft passed or reuse it as an accepted output.

The pinned original, corrected comparison and actual draft links are in the review section below. Application automation belongs to Task 13 and has separate data/answer/Submit review gates.

## Offline verification

```sh
/opt/homebrew/anaconda3/bin/python3 -m py_compile optimize_resume.py modules/ai/resume_optimizer.py
/opt/homebrew/anaconda3/bin/python3 -m unittest discover -s tests -p 'test_resume_cli.py' -v
```

The tests block sockets and never load real credentials. Title tests cover explicit/structured/AI precedence for all JD input types, blank and ambiguous titles, provider-free pending preflight, successful automatic continuation with full-JD payload, exact evidence and unsupported-seniority rejection, malformed output/provider errors, cancellation attribution and strict budget debit. They run the existing engine for all three DOCX modes with both title overrides, assert source preservation/output placement, test strict client injection, exact file/inline JD, structured-URL extraction with mocked public responses, private/restricted/ambiguous URL rejection, harmless preflight, no overwrite and explicit partial status. They are fixture verification, not proof of a new genuine paid run.

## Full rewrite contract and original approved plan

This section retains the useful requirements of the approved full-rewrite plan in one place. The implementation exists, but these are still the acceptance requirements; the existing real draft has not satisfied them. The old plan's proposed-only status and historical test baselines are not current implementation claims.

### 1. Immutable source inventory and complete experience context

Inventory all rendered source bullet paragraphs before any curated-bank substitution, including professional, project, academic and bank-backed sections. Skills, headings and plain prose are not bullets. Styled lists/explicit markers and ambiguous or unmapped paragraphs need explicit accounting; do not silently exclude difficult IDs. Stable IDs bind the source DOCX hash, paragraph index and ordinal, with section/experience/title/date context, exact source text and baseline PDF page/line/width measurements. The Baseten inventory has 54 bullets in 12 groups; another resume must be inventoried dynamically.

Every experience worker receives the **full exact JD and its complete immutable original experience context**, even when retrying only a subset. Do not truncate context, borrow facts from another employer, or treat generated wording as source evidence. Curated banks may guide strict rewriting but cannot silently substitute or exclude bullets. Treat resume/JD content as data, not instructions. The requested transformation should change meaningful action/context/outcome while preserving facts; punctuation, case, whitespace and trivial verb swaps do not establish substantive completion.

### 2. Parallel generation, budgets and deterministic assembly

Strict experience concurrency defaults to 2, accepts 1–4, and never enables the all-bullets flag or raises the request/cost allowance by itself. Independent worker results are keyed by immutable experience/bullet IDs. Merge only in original section/experience/bullet order, regardless of completion order; reject missing, duplicate, stale or cross-experience IDs. Workers never write shared DOCX/PDF/report files. Assemble one copied DOCX, then run global rendering and validation.

Each requested sub-batch contains at most12 bullet IDs and retains its experience's full original context. `rewrite_bullets_per_request` accepts1–12 and defaults12; smaller per-run batches do not truncate context or increase time/cost limits. Let `B = sum(ceil(experience bullet count / rewrite_bullets_per_request))`. The strict plan bounds optimization by one keyword request plus at most `2B` rewrite attempts, subject to stricter configured caps; optional title extraction also consumes the wrapper's total allowance. Retry failed/unchanged IDs with feedback and preserve successful siblings. Cache validated responses for layout recovery instead of treating a rendering retry as another paid rewrite.

| Control | Recorded default/pinned behavior; inspect the current run summary |
| --- | --- |
| Provider model | Existing `gpt-4o` client; never infer it from unrelated connection settings. |
| Concurrency | Default 2, supported 1–4; 1 is the sequential fixture reference. |
| Strict pinned request ceiling | 25 for the 54-bullet/12-group Baseten setup before any tighter wrapper budget. General limits still depend on inventory and configuration. |
| Per-request / whole-run provider time | 45 seconds / 300 seconds, including queue/backoff; title extraction time is debited by the wrapper. |
| Completion/context estimates | At most 6,000 completion tokens per rewrite request; 120,000 estimated context tokens. Full-context overflow blocks rather than truncates. |
| Shared rate defaults | 60 requests/minute, 120,000 estimated tokens/minute. |
| Estimated cost | Configured $2 allowance using $2.50/M input and $10/M output rates; **not a current price quote, invoice or hard billing cap**. |

Reserve request/estimated-cost capacity atomically before dispatch. Settle known usage without losing the record of gross reservations; unknown usage/failure keeps conservative reservation. Shared 429 cooldown, `Retry-After`, bounded exponential backoff and SDK retry disabling prevent uncounted retries. Auth/permission errors stop queued work. Cancellation stops new dispatch/retries, rejects late merges and records pending IDs as incomplete; it cannot refund already-sent requests. Local rendering may require additional time after provider work. Do not silently raise limits to turn a partial run into a success claim.

### 3. Response protocol, truth constraints and final layout

Require strict JSON with experience identity and one owned record per requested bullet: stable ID, source-text hash, rewritten/unchanged/blocked status, proposed text and up to two structural alternatives, exact relevant JD spans, preserved fact anchors, change reason and blocked reason. A provider's “rewritten” label is provisional. Each alternative is checked independently; only a factual fitting candidate can be selected. Invalid quoted spans are discarded with a diagnostic, never credited as JD evidence; source facts are checked against actual candidate text rather than trusting the model's declared anchor list. Null/invalid proposals need explicit retained/blocked reasons; transport coverage must come from actual dispatch/response evidence, not just the subset of parsed usable wording.

Preserve source identity, count/order, numeric claims and metric subjects; block unsupported qualifiers, filler, invented skills/achievements and cross-experience borrowing. These are conservative checks, not semantic truth certification. Broader review-policy suggestions must remain separate from an eligible grounded resume. Content policy, target role, title replacement and rewrite scope are independent controls.

Strict fit requires **exactly one nonempty rendered line per accepted rewritten bullet**, with no clipping/overflow. Measure actual source font, indent, bullet marker and usable width. Shorter truthful lines are allowed; do not impose a minimum width or pad with filler. Preserve fonts, margins, spacing and section order, Skills space/format and clickable links. Skills wording/order may change through source-supported ranking; the report records original/output Skills and actual title changes. Do not drop facts or shrink formatting to fit. If meaningful facts cannot fit one line, report the bullet blocked/source-retained and keep it out of accepted coverage.

Ordinary modes retain their existing source-density safeguards: baseline line/page placement and approximate occupied-width bands, with bounded source restoration/cached recovery. Those ordinary 92–108% / final-line 90–110% density bands are not the strict all-bullets minimum-fill contract. One-time paragraph restoration or Skills-only recovery cannot masquerade as completed full rewriting. For Baseten, the required final output remains two pages, 13 Skills lines and eight clickable links; pagination conflicts must be exposed, not hidden with spacing tricks.

### 4. Attempted is not completed; attachment safety

Coverage separates **inventoried, requested, response received, substantively changed, accepted, retained source and failed** counts, with one final reason per stable ID. Fixtures and saved-response replays identify their execution kind separately. Every source ID in a request establishes attempted coverage only; received coverage does not prove usable or accepted output.

Strict completion requires every inventoried bullet to be substantively rewritten, one-line fit and all source/content/format/link checks. Retained originals, missing IDs, budget/provider failures, unchanged wording or failed global rendering are partial/failure outcomes. A 13/54 or 53/54 case cannot become completion. No accepted attachment may be returned by substituting a Skills-only/original/source-restored fallback when strict generation fails. Even an eligible artifact still needs human content review; manual application/Submit authorization is separate.

### 5. Frozen before/after diagnostics and original plan acceptance

Freeze the exact full JD/hash, keyword/concept set, bank hash, method versions and weights before generation. Score actual source and final artifact text using identical denominators and extraction rules; do not score a model response instead of the delivered PDF. Require DOCX/PDF text consistency or label comparisons unavailable. If the JD or keyword universe changes, create a new comparison rather than calling the delta an improvement.

| Diagnostic | Meaning and required evidence |
| --- | --- |
| Required/preferred/context | Existing `jd-requirement-evidence-v1` heuristics, default weights 2/1/1; explicit JD spans only. Show matched/missing IDs and weight denominator. Empty components are N/A. |
| Bounded keyword coverage | Existing `bounded-unique-concept-coverage-v1`; bounded unique concepts, verified acronym expansion, no substring credit, Core bank concepts weighted 2 versus 1 otherwise. |
| Before/after provenance | Retained/introduced/removed/missing mentions, exact source/output evidence and separate target/historical-title diagnostics. Output-only mentions do not retroactively establish source qualifications. |

Negation, optional/OR requirements and company/benefits sections are bounded heuristics requiring review. Label all percentages **local heuristic match estimates — not employer ATS rankings, verified qualifications or hiring probability**. No universal combined ATS score, required score increase or 100% target is justified. Higher scores cannot approve invented claims or layout failure.

The original acceptance plan requires immutable inputs and exact IDs/order, all accepted substantive rewrites, one-line/no-overflow geometry, preserved typography/Skills/links, bound original/draft/exact-JD review and reproducible same-JD scoring. Test default-off compatibility, title/content-policy independence, invalid input/modes, ownership/protocol errors, numeric/metric changes, retries/cache/budget limits, missing credentials, cancellation and attachment refusal. Concurrency-1 versus concurrency-2 fixture results must preserve deterministic ordering/coverage, not promise identical stochastic live prose.

Real-render deterministic fixtures have exercised complete 54/54 and deliberate 53/54 partial behavior; they are offline evidence, not proof of genuine full rewriting. The historical initial plan baseline of 107 tests and Task 3's 13 raw / 8 source-guarded rewrites are different earlier scopes, not Task 11 strict success.

### 6. Ordinary flow, configuration boundaries and original implementation map

The earlier flow reference describes this ordinary path: exact JD + original DOCX/paired PDF → provider keyword extraction → source-evidenced Skills ranking plus curated banks/ordinary professional rewrites → copied DOCX → isolated-profile LibreOffice export → content/layout/link diagnostics → explicitly selected artifact. Projects/academic/bank-backed content were not all genuine model rewrites in the ordinary scope; the strict opt-in inventory path exists to cover every source bullet instead. Count original/source-restored wording honestly in either path.

The 15 October flow snapshot recorded repository defaults `full`, independent title replacement true and Skills priority cap65. Those historical defaults are distinct from this CLI's explicit per-call mode/title resolution. A priority cap is not an instruction to inject65Skills or to change the rendered source Skills inventory. Saved-user settings can override repository defaults; the wrapper applies its selected settings in memory without rewriting shared config. The core model is not chosen by unrelated application-connection configuration.

| Component / original plan touchpoint | Responsibility and verification boundary |
| --- | --- |
| `optimize_resume.py` | Selected original/JD acquisition, target-title precedence, secure per-process client, preflight, mode/title overrides, unique output and truthful exit/eligibility summary. |
| `modules/ai/resume_optimizer.py` | Shared engine, ordinary Skills/bank/professional rewrite path, copied DOCX rendering/recovery; per-call overrides must preserve existing callers. |
| `modules/resume_all_bullets.py` | Ordered source inventory, experience batching/concurrency, immutable context, bounded scheduling, owned JSON protocol, deterministic single assembly, coverage/scoring/review artifact binding. |
| `modules/resume_review_draft.py` | Separate explicit unchecked export and attribution diagnostics; never accepted strict output. |
| `modules/resume_layout.py`, `modules/resume_links.py` | Actual glyph/line/width and clickable-link validation; strict one-line semantics remain separate from ordinary source-density behavior. |
| `config/resume_optimizer_defaults.json`, `modules/config_loader.py`, `JobRobo.py` | Original plan covers default-off/persistence/per-call precedence plus a strict-rewrite toggle, bounded concurrency, cancellation and per-experience/total progress/cost. This README does not certify an unverified GUI state or silently change defaults. |
| `direct_apply.py`, `modules/direct_careers_apply.py`, `runAiBot.py`, `modules/resume_upload.py` | Propagate strict selection and independently verify source/JD/job/output identity before attachment; no original/Skills fallback may label a failed strict generation successful. Submission authorization remains separate. |
| CLI/core/layout/GUI/E2E tests | Preserve default-mode behavior; cover every-ID ownership, protocol/mode/flag errors, numeric/metric safeguards, context limits, bounded retries/cache/rate/budget, cancellation, partial results and ineligible attachment refusal. |

Original E2E acceptance includes actual local DOCX assembly, LibreOffice/PDF geometry and links, not mocked final rendering. Fixtures must verify source/JD hashes, all source IDs, concurrency1/2 deterministic merge, meaningful54/54 accepted changes, one-line fit, original typography/Skills/links, same-JD scores and a bound three-pane comparison. Deliberate53/54, duplicate/missing IDs, overflow, budget/provider failure and changed artifact/JD hashes must remain visibly partial/ineligible. Missing dependencies or zero discovered tests cannot count as a pass. A future genuine version must preserve these checks and capture real response IDs/usage rather than relabeling fixtures or Task3 evidence as live strict success.

## Review workflow, pinned inputs and actual artifacts

### Pinned Baseten identity

| Artifact | Preserved source and identity |
| --- | --- |
| Original DOCX | `/Users/deepakbasavaraju/Documents/Codex/2026-10-14/task-2/evidence/baseline/source/resume.docx`; SHA256 `1a20e99ac92d1d56512accad2179b1e90c138283612f89843d5344ac93b5c968` |
| Original PDF | Same source directory, `resume.pdf`; SHA256 `9731bc76c1a85199cfac2254fd1590af0b5545763ab05e9f31eabfa4b5791981` |
| Saved exact JD | `evidence/baseline/target-job.json` under the 14 October task-2 workspace, `description`; SHA256 `50258a5b9ba4efd1cb30f1722d6e890bb2025130972bb3fb3148e9fa5929bacf` |
| Baseline contract | 54 bullets, 12 experience/project/academic groups, two pages, 13 Skills lines, eight links; verify the actual source, do not reuse these counts for every resume. |

The live structured-URL extraction check has its own current-page/JD hash; it does not silently replace the saved Baseten JD above. Title metadata and full-description selection are separate ambiguities.

### Review each result before any use

1. Read the actual `run-summary.json`, coverage and execution kind; distinguish production eligibility from a retained preview. Ordinary and strict paths have different coverage requirements.
2. Verify source DOCX/PDF hashes, exact JD/hash/role, inventory, output paths/hashes and run identity in the artifact manifest. Never choose the newest PDF by modification time.
3. For strict engine artifacts, the local binding verifier is `python -m modules.resume_all_bullets --verify-review /absolute/path/to/run-directory`. It verifies files; it does not run optimization. A browser `file://` fetch/hash status can remain unverified; do not treat that as a successful browser binding check.
4. Inspect original / draft / **full exact JD** together, every page PNG/PDF and per-ID before/after changes. Check factual meaning, all coverage reasons, one-line fit, Skills, fonts/margins, links and page count. Inspect historical-title proposals separately.
5. A partial, unchecked, mismatched or failed-layout artifact is not application-eligible. Source or generated attachments need independent verification and explicit selection in their own application workflow. This README grants no upload/Submit permission.

| Saved evidence | Current interpretation |
| --- | --- |
| [Corrected three-pane comparison](/Users/deepakbasavaraju/Documents/Codex/2026-10-15/task-2/evidence/task11-unchecked-replay/saved-20261015T222824/comparison.html) | Original / unchecked draft / full exact JD; corrected 54 requested/54 received attribution. |
| [Actual unchecked PDF](/Users/deepakbasavaraju/Documents/Codex/2026-10-15/task-2/evidence/task11-unchecked-replay/saved-20261015T222824/optimized.pdf) · [editable DOCX](/Users/deepakbasavaraju/Documents/Codex/2026-10-15/task-2/evidence/task11-unchecked-replay/saved-20261015T222824/optimized.docx) | Three-page diagnostic draft, 42 changed unchecked proposals / 12 retained, accepted 0; not eligible. |
| [Match report](/Users/deepakbasavaraju/Documents/Codex/2026-10-15/task-2/evidence/task11-unchecked-replay/saved-20261015T222824/match-report.json) · [per-bullet coverage](/Users/deepakbasavaraju/Documents/Codex/2026-10-15/task-2/evidence/task11-unchecked-replay/saved-20261015T222824/rewrite-coverage.json) | Inspect exact failure/retention reasons, not only the PDF. |
| [Saved-response replay receipt](/Users/deepakbasavaraju/Documents/Codex/2026-10-15/task-2/evidence/task11-unchecked-replay-receipt.json) | Reused 18 genuine saved responses; zero new calls, original snapshot retained. |
| [Title-resolution receipt](/Users/deepakbasavaraju/Documents/Codex/2026-10-15/task-2/evidence/task11-title-resolution-delivery.json) · [Baseten URL preflight](/Users/deepakbasavaraju/Documents/Codex/2026-10-15/task-2/evidence/task11-title-baseten-url-preflight.json) | Latest implemented precedence and genuine provider-free structured extraction check. |
| [Command/reference validation](/Users/deepakbasavaraju/Documents/Codex/2026-10-15/task-2/evidence/task11-readme-reference-validation.json) | 13 shell blocks and four Baseten examples checked; example URL responses in parser tests are mocked. |

The first genuine strict run made 15 requests but accepted only 1/54; global layout alone did not establish completion. The existing second unchecked run made 18 genuine calls, requested/responded to 54/54, changed 42 and retained 12, but remains three-page/failed-layout/ineligible. Saved same-JD requirement and bounded-keyword diagnostics were unchanged (41.0→41.0 and 47.1→47.1); no verified qualification/ATS improvement is implied. No new paid run was made for this consolidation or the title/CLI documentation update.

The separate unchecked export route is explicit review-only behavior, not the generic wrapper's grounded mode or its ordinary `review_draft` content policy. It keeps provisional model wording with flags while requiring protocol/source ownership; its `unchecked:true`, `rewrite_completed:false`, `accepted:0`, `strict_attachment_eligible:false` remain false/zero for acceptance even if some geometry passes. It is not exposed as a generic unchecked CLI flag.

## Verification matrix and maintenance

| Latest recorded check | Evidence and honest scope |
| --- | --- |
| Current branch checkpoints | All1,137 repository tests passed, including the new JD/draft and comparison-layout cases. Genuine full-run validation remains pending. |
| Historical235 resume/GUI regression tests | Earlier title-resolution update, including real-render fixtures; not a new genuine full-rewrite success. |
| 20 focused CLI tests | Explicit/structured/AI title precedence, all JD input types, full-JD evidence validation, no-key preflight, mode/title combinations, error/cancellation/budget attribution, output protection and partial eligibility. AI extraction is mock-tested only. |
| Live Baseten structured extraction | Read-only public URL preflight resolved Software Engineer - Inference Platform with zero provider calls and no credential read; it was not a paid rewrite. |
| 13 shell blocks / four Baseten examples | Existing command/reference validation; four examples cover URL automatic/explicit title, file automatic pending-AI, and text explicit title. A mocked URL parser case is not another live URL test. |
| Earlier strict fixtures | Historical tests reported54/54 complete and53/54 partial. The stronger source-retention gate now rejects those canned rewrites as partial; real rendering/concurrency1/2/provenance checks remain, with no model requests. |
| Prior parser/report repair | Explicit retained reasons for null/invalid proposals and transport coverage derived from events; corrected saved replay made zero calls. |

The null blocked-text parser repair prevented diagnostics from discarding valid siblings. Settlement of known token usage prevented conservative upper reservations from starving dispatch. The first genuine run did not archive rejected raw bodies; saved IDs/usage cannot reconstruct them. Newer runs retain attributable response evidence. Keep these limits when interpreting older receipts rather than fabricating an improved historical run.

The canonical CLI uses `run_resume_optimization()` with per-call mode/config/client/output injection, preserving saved settings. The strict core is `modules/resume_all_bullets.py`; unchecked exports use `modules/resume_review_draft.py`; rendering/layout and links use `modules/resume_layout.py` and `modules/resume_links.py`. GUI/config and application callers are separate entrypoints. Legacy module CLI uses saved resume/JD settings and does not accept the wrapper's arbitrary resume/JD-URL flags; prefer `optimize_resume.py` for the commands above. Application behavior is documented by Task 13's own owner.

Useful local verification references, requiring a separately chosen test action: the existing `test_resume_cli.py`, `test_resume_all_bullets.py`, `test_resume_review_draft.py` and `test_resume_all_bullets_e2e.py` suites. Real-render E2E output needs a writable `TASK11_OUTPUT_ROOT`; missing renderer/output permissions are failures or unavailable checks, never manufactured passes. A socket-blocked fixture or saved-response replay must preserve its non-provider execution label.

### Troubleshooting without silent fallback

| Symptom | Action / limit |
| --- | --- |
| Imports fail | Use the repository cwd and verified interpreter above; dedicated historical launchers have a different pinned workspace. Do not invent a virtualenv activation path. |
| Structured URL unavailable/ambiguous | Copy the selected full JD into a UTF-8 file; do not scrape page navigation, select a random posting, truncate it or bypass access challenges. |
| Target title unresolved | Provider-free preflight can honestly declare AI extraction needed. Use a verified explicit title or separately authorize the normal paid path. Review the resolved title/evidence. |
| Key/auth/rate/budget failure | Stop and inspect non-secret attempt evidence. Do not disclose a key, automatically repeat paid work, silently increase a cap or relax content checks. Preflight does not test authentication. |
| Rendering/output failure | Preserve source/reports; check local LibreOffice and writable unique output path. Missing rendering is not layout success. |
| Source restoration or incomplete rewrite | Inspect every stable-ID reason. Retained source is incomplete under strict scope. A plausible PDF or higher heuristic score cannot override rejection. |
| Hash/JD/source binding mismatch | Do not use the artifact or rewrite its manifest to conceal the mismatch. Keep the evidence and investigate. |
| User wants to view a previous run | Open its existing comparison/PDF; do not rerun a provider launcher merely to inspect it. |

### Historical sources preserved, not competing current guides

The original source files remain unchanged at their existing paths; a hash-pinned pre-consolidation copy and tracker section are in `/Users/deepakbasavaraju/Documents/Codex/2026-10-14/task/task-progress/task11-doc-consolidation/archive/`. They are historical evidence, not additional Task 11 README entries:

- `Task11HANDBOOK.md` — previous combined handbook, run history and legacy API recipe.
- `PLAN-REWRITE-ALL-BULLETS.md` — original approved inventory/generation/coverage/scoring/review/E2E plan; its proposed-only statements are dated history.
- `RESUME-REWRITE-FLOW.md` — earlier ordinary-mode/Task 3 behavior snapshot, including density, attribution and attachment distinctions.
- `TASK11-README.before.md` — exact previous command guide; the 13 shell blocks are preserved verbatim in this README.

The consolidation inventory records source paths/hashes, retained command blocks and contract coverage. Current tracker entrypoints intentionally expose this README only; original documents and checkpoint JSONL remain available for audit. Do not restore obsolete competing README links during future log rendering. No commit/push, runtime configuration change, provider call or application action is part of this documentation consolidation.
