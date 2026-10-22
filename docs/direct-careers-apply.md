# Apply directly to verified career postings

The shared [`submit` command](generic-url-preparation.md#submit-using-the-same-preparation-flow)
accepts raw URLs, TXT/JSON, verified/ranked artifacts and these legacy queues.
It creates a fresh independent run automatically, with `--pause-before-submit
always|unknown|never`, progress and retry exports, using the same optimizer as
`prepare`. Prior submissions or uncertainty do not block a fresh invocation.
The default fills each job in a separate retained tab and continues the batch.
Review/edit and Submit on the employer pages; no separate review window opens.
Keep the terminal running for outcome tracking, or press Ctrl-C to save and leave
Chrome open. Optional `--resume RUN_DIR` reconnects live tabs in that run.
Use `prepare` when submission must stay disabled.

The queue-specific commands below remain supported as the legacy interface.

`direct_apply.py` consumes a versioned `verified_roles` JSON from discovery/verification/ranking. It skips LinkedIn search: the official application URLs are already present. Importing the module or asking for CLI help opens no browser and loads no credentials.

The queue retains every input record in its supplied priority order. Application preference diagnostics such as date, location or work arrangement remain visible warnings; they do not remove the broadly verified engineering inventory. Unsupported providers, stale/closed/prospect postings, missing JDs/provenance and duplicate ATS identities remain explicit handoffs. Reverify stale postings through `job_pipeline.py verify careers`; a saved open status is rechecked for freshness before execution.

## Start with the original resume

Create a queue without opening employer pages, generating a resume or using an API key:

```bash
python direct_apply.py plan \
  --input /absolute/path/90-engineering-ranked.json \
  --queue /absolute/path/direct/90-original-queue.json \
  --source-docx 'all resumes/default/resume.docx' \
  --source-pdf 'all resumes/default/resume.pdf'

python direct_apply.py status --queue /absolute/path/direct/90-original-queue.json
```

Planning independently checks PDF/DOCX format and hyperlinks, then snapshots the exact document bytes outside the source files. It uses the existing format verifier without constructing an optimizer or making model calls. The default is two pages and seven-day verification freshness; pass explicit `--expected-pages` or `--freshness-days` if your document/workflow needs another value. Existing queues cannot be overwritten; resume the queue or choose a new filename.

Execute a selected row after reviewing the queue:

```bash
python direct_apply.py run \
  --queue /absolute/path/direct/90-original-queue.json \
  --role 'role:YOUR_VERIFIED_ROLE_ID' \
  --execute
```

Omit `--role` to consume the next pending row in the saved order. Repeat it to select several rows. `--max-attempts` defaults to one, and `--max-applications` defaults to one and can only further restrict the existing `config/search.py` cap. Restarting the same queue skips confirmed/discarded records and preserves every prior attempt. An uncertain submission in either this queue or the shared ATS ledger stops execution until an operator investigates it.

The runner opens visible Chrome with a dedicated default profile at `~/Library/Application Support/JobRobo/ChromeProfileDirect`. `--chrome-profile` can select another dedicated directory. It does not import `runAiBot.py`, start LinkedIn, call the legacy shared-key loader or depend on LinkedIn credentials. Chrome/Selenium must be installed and that chosen profile must be available.

The explicit `--execute` command enables this direct runner; it does not change `external_apply_enabled` or other personal flags. Hosted Greenhouse, Lever and Ashby URLs use their native application routes and the same strict ATS employer/job identity checks as external apply. Custom controls, account logins, challenges and employer-specific steps may still require a manual handoff. A closed page encountered after planning is never reported as an application just because its saved status was open.

## Questions and submission review

Existing literal candidate values are read from `config/personals.py`, `config/questions.py` and only recognized identity values in `config/secrets.py`, without executing those files. API keys/passwords are never copied into the candidate profile. Configure additional typed answers in the private JSON described in [external-apply.md](external-apply.md); `--questions` can select a file. Explicit private JSON candidate values override the existing candidate fields.

Question AI stays disabled unless both `--enable-question-ai` and the private JSON's `ai.enabled=true` are present. Original resume mode never generates a resume and never requires an API key. With question AI disabled, it does not construct an AI answerer. If enabled separately, the local-key adapter uses the current JD and selected source context under its existing grounding rules.

Every supported application still requires the private **Submit application / Leave open / Discard application** review. The review includes the exact selected PDF path and, for an optimized artifact, its report path. Open and check the document content before approving. `run_non_stop=False` is not the submission guard; this review is always required. Choosing Submit authorizes the single website Submit click. Do not separately click Submit in the browser during that dialog.

The exact PDF digest, independently accepted format, attachment and ATS identity are checked again before Submit. The shared ledger defaults to `<config/search_profile.py search_state_dir>/external/applications.json`, matching the external/LinkedIn runner. Set `--ledger` only when you intentionally select another shared ledger. The durable ATS claim precedes the Submit click; confirmed and uncertain claims cannot be automatically replaced. Unsupported confirmation routes remain uncertain rather than being counted as applied.

A Leave open/handoff keeps its browser visible and stops the invocation so you can inspect it. A new invocation can reopen a prepared draft; do not manually submit an older browser draft and then restart without reconciling tracking state. Confirmed/failed/discarded sessions created by this runner are closed.

## Use an already validated optimized resume

After Tasks 3–4 produce and review a role-specific optimized PDF/DOCX and accepted match report, create a private selection map. The keys are verified role IDs:

```json
{
  "role:YOUR_VERIFIED_ROLE_ID": {
    "pdf": "/absolute/path/optimized.pdf",
    "docx": "/absolute/path/optimized.docx",
    "report": "/absolute/path/optimized.match_report.json",
    "job_description_sha256": "SHA256_OF_THE_EXACT_VERIFIED_DESCRIPTION_STRING"
  }
}
```

`job_description_sha256` is SHA-256 of `role["description"].encode("utf-8")`. It explicitly binds your selection to that JD snapshot. The selected report must be accepted, have a passing format result, match the original DOCX digest and job title, and name that exact selected PDF. The current optimizer report does not independently attest the JD hash; the selection map is the operator's explicit binding. Planning verifies the selected documents again and snapshots their bytes/report. Manual content review is still required; format acceptance is not factual verification.

```bash
python direct_apply.py plan \
  --input /absolute/path/90-engineering-ranked.json \
  --queue /absolute/path/direct/90-optimized-queue.json \
  --source-docx 'all resumes/default/resume.docx' \
  --source-pdf 'all resumes/default/resume.pdf' \
  --resume-mode optimized \
  --optimized-map /absolute/path/selected-optimized-resumes.json
```

Run that queue with the same explicit selected-row command. All 90 inventory rows remain present; roles without their own optimized selection stay manual handoffs. This selected-artifact mode does not generate a resume or silently fall back to the original. Use the separate generated mode below for lazy per-role generation.

## Generate a role-specific optimized resume automatically

After verifying Tasks 3–4, plan a queue with `--resume-mode generated` using the same input/source arguments. Planning only validates/snapshots the original documents and retains every role; it makes no model calls, reads no API key and does not construct an optimizer. No generated PDF is claimed until a run produces one.

```bash
python direct_apply.py plan \
  --input /absolute/path/90-engineering-ranked.json \
  --queue /absolute/path/direct/90-generated-queue.json \
  --source-docx 'all resumes/default/resume.docx' \
  --source-pdf 'all resumes/default/resume.pdf' \
  --resume-mode generated

python direct_apply.py run \
  --queue /absolute/path/direct/90-generated-queue.json \
  --role 'role:YOUR_VERIFIED_ROLE_ID' \
  --generate-resume --execute
```

Generated mode requires exactly one explicit selected role, one attempt and an application cap of one. The run checks selection, verification freshness, duplicates, source hashes and the shared uncertain-submission ledger before generation. It then calls the reviewed optimizer with that exact JD/title, a unique generation ID and paired copies of the verified original DOCX/PDF in a private generation workspace. The optimizer uses its existing local `OPENAI_API_KEY` environment or local `.env` behavior and saved runtime settings for mode, title replacement and content policy. It never calls the legacy shared-key service. Running this mode may incur API charges and sends the selected resume/JD to the configured optimizer provider. No key is needed for original/selected-artifact modes when question AI is disabled.

Before calling the default optimizer, its runtime `expected_page_count` must match the queue's `--expected-pages` contract. A mismatch/invalid page setting produces a handoff before a model call; align those settings before retrying. The returned PDF/DOCX and accepted report must belong to this generation workspace and match its unique job ID, title and source digest. An independent format/hyperlink check still runs. The runner snapshots the accepted files and records a separate hashed binding containing the exact JD, role/ATS identity, source documents and output/report digests. The normal mandatory review displays the generated PDF/report, and submission rechecks their hashes. Runtime optimizer settings determine the effective mode; accepted shorter/Skills fallbacks are recorded rather than presented as a guaranteed full rewrite.

Generation errors, missing/rejected output or format failures stop with an explicit manual handoff and no original-resume fallback. The generation checkpoint is written before entering the optimizer; an interrupted call is not automatically repeated and requires inspection of its private workspace/checkpoint. A failed completed generation can be retried through another explicit selected run. A successfully generated draft left open for review is reused on restart, so continuing that draft does not make another model call. This mode performs no batch generation for all 90 roles.

## Progress and evidence

The private queue stores ordered role snapshots, JD hashes, candidate filter warnings, resume/report hashes, every attempt, timestamps and invocation stop reasons. Persisted results contain question names/types/sources, not answer values. A confirmed count means a new success heading on the exact ATS employer/posting identity; prepared forms never count as submitted.

```bash
python direct_apply.py export \
  --queue /absolute/path/direct/90-original-queue.json \
  --output /absolute/path/direct/applications.json
```

The export is a versioned `applications` StageResult retaining the verification run, queue, role, employer posting, JD and resume provenance. It is independent of LinkedIn CSV history; keep the shared ATS ledger alongside your normal application state to protect duplicate applications across both entry points.

Unit tests cover original/optimized/generated planning, inventory retention, priority order, explicit selection, cap/restart/dedup, stale or incomplete records, resume changes, generation/report binding, failed/rejected/interrupted generation, reuse without repeated spend, ledger write failure and uncertain outcomes. `scripts/test_direct_careers_browser.py` is a separately invoked real Chrome test: it routes one ATS identity only to a loopback native form inside its test transport, verifies original resume first and the selected optimized artifact second, checks native answer controls, attachment, review, confirmation and exported provenance. Its optional `--exercise-generated` run uses an injected generator with the already validated real AI artifacts to exercise lazy-generation plumbing; it makes no fresh API calls. It never contacts or submits to an employer, and a passing synthetic fixture does not certify every live Ashby/Lever/Greenhouse application.
