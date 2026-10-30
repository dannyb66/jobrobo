# Diverse ATS manual-validation run

The final sample contains ten distinct URLs: nine roles from Task 1's current
`phase2-engineering-ranked-remaining.json` and one approved replacement for a
retired generic listing. Coverage is five Ashby employers, two Lever employers,
two Greenhouse roles and one generic job-site entry. The sample has been run;
form and submission outcomes are summarized below and in the saved outcome file.

Use [jobs-validation.txt](../jobs-validation.txt) for the URL list, or the local
`jobs-validation.json` to retain role IDs, JDs and verification metadata. Both
load the same final URLs in the same order. The approved Ondo Finance replacement
records its separate live evidence and replacement approval. The raw metadata JSON remains private. [The manifest](../jobs-validation-manifest.json)
records the source file hash, selected cases, warning details, saved outcomes
and validation focus.

| Case | Provider / entry | Company | Role | Saved preference warnings |
| --- | --- | --- | --- | --- |
| 1 | Lever | Instrumentl | Senior Backend Engineer | Unknown posting date |
| 2 | Greenhouse | Baton | Software Engineer - Data Platform | Unknown posting date |
| 3 | Ashby | DuckDuckGo | Senior Privacy Engineer | None |
| 4 | Generic entry | Ondo Finance via CareerJumpShip | Infrastructure Engineer (DevOps) | None; employer delivery pending |
| 5 | Ashby | Namespace | Infrastructure Software Engineer | None |
| 6 | Lever | Shield AI | Engineer, Software - open level (R5285) | Unknown employment type and posting date |
| 7 | Greenhouse | Baton | Staff Software Engineer - Infrastructure, Data Platform | Unknown posting date |
| 8 | Ashby | Solace Health | Senior Backend Engineer | None |
| 9 | Ashby | Modal | Member of Technical Staff - Inference Runtime | None; San Francisco role |
| 10 | Ashby | Baseten | Software Engineer - Inference Platform | None; different from the submitted Storage manager role |

The earlier Stockholm role and previously submitted/uncertain posting URLs are
excluded. Original role fields and verification dates are preserved. Four cases
have the warnings shown above; the runner currently displays these as warnings.
All Greenhouse listings in this shortlist belong to Baton, so the two Greenhouse
cases may have identical forms. Workday, SmartRecruiters, iCIMS and other absent
providers are outside this sample. The generic listing may require an outbound
handoff or expose a separate access/navigation gap.

## Commands

Case 4 now uses the approved Ondo Finance Infrastructure Engineer (DevOps)
listing. The retired IT Engineer input is preserved in the ignored audit copy at
`logs/direct_submit_validation/20261022/audit-inputs/`. The application service
accepted the replacement application and queued employer delivery; this does not
count as an employer-confirmed submission. See the [implementation and
live-validation record](direct-validation-fixes-plan.md).

Run from the repository root. For the manual Kernel batch:

```bash
python3 direct_apply.py submit --input jobs-validation.json \
  --browser kernel --pause-before-submit always --limit 10
```

Each run keeps live counts in `progress.json` and writes final totals to
`summary.json`; confirmed success counts include only employer-confirmed
`applied` outcomes.

Equivalent URL-only input:

```bash
python3 direct_apply.py submit --urls-file jobs-validation.txt \
  --browser kernel --pause-before-submit always --limit 10
```

For local Chrome, omit `--browser kernel`:

```bash
python3 direct_apply.py submit --input jobs-validation.json \
  --pause-before-submit always --limit 10
```

Choose one batch command; running all three creates three independent runs.
`always` fills a new tab per job and leaves final Submit to you. Keep the process
running while reviewing or manually submitting so confirmation can be observed.
Review actual values, including first-option defaults, before deciding which
applications to submit. Filled fields and an uploaded resume alone do not mean
submission succeeded. The configured application cap must allow the batch size;
`--limit` selects jobs and does not raise that cap.

Optional preparation-only pilot covering the three identifiable providers:

```bash
python3 direct_apply.py prepare --input jobs-validation.json \
  --browser kernel --limit 3
```

This pilot permanently disables Submit and saves evidence; it does not retain
one review tab per job. It also does not establish coverage of the generic
entry. Use the full manual batch for that.

If interrupted, copy the actual printed run directory:

```bash
RUN_DIR='/absolute/path/printed/by/the/run'
python3 direct_apply.py status --run "$RUN_DIR"
python3 direct_apply.py submit --resume "$RUN_DIR"
```

The final sample remains a ten-job regression input after applications; fresh
commands can attempt the same jobs again. For recovery of an existing
review session, use its explicit resume command. To retry pre-submit failures
in a fresh run, use its `retry.json`. Inspect uncertain outcomes before deciding
whether a new attempt is appropriate.

## Review and feedback loop

1. **Record the run directory and case outcome.** Note whether the employer
   form opened or an access/handoff/closed-job result appeared. Do not count a
   closed role as an input-control defect.
2. **Inspect the filled form and resume.** Check visible values, selected
   choices, conditional required fields, DEI opt-outs, the uploaded filename and
   whether the displayed attachment is the correct tailored PDF.
3. **Inspect any manual submission separately.** Record validation errors,
   CAPTCHA behaviour and the employer's success or duplicate message. Confirm
   the saved status agrees with the page. The original run remains linked in
   the Task 1 review and submission-run dashboard.
4. **Report each gap with its evidence.** Use the template below. The run's
   `progress.json`, `events.jsonl`, `preparations/*/report.json` and screenshots
   provide application-stage evidence; Kernel session IDs and redacted CAPTCHA
   events provide cloud-session evidence. Do not include API keys or signed
   connection/live-view URLs.
5. **Fix and retest the smallest failing case.** Reproduce the issue in a local
   regression, implement the root-cause fix, then repeat that case in prepare
   or manual-review mode. Rerun the ten-case matrix after the case passes.
   Changes to shared field reading, upload, navigation or confirmation handling
   need checks across the other providers too.

Feedback template:

```text
Run directory:
Case number / job URL:
Stage: navigation / resume / upload / fields / review / CAPTCHA / confirmation / tracking
Expected behaviour:
Observed behaviour and exact field/question:
Manual Submit clicked: yes / no
Employer page outcome:
Saved status:
Relevant report/screenshot or Kernel session ID:
```

The first iteration is complete when all ten cases have an observed result and
each gap has evidence or a local passing regression. A blocked generic handoff,
closed posting or unresolved required fact remains explicit; it is not counted
as a successful filled application. Actual widget diversity and live posting
availability can only be established by this manual run.


Current follow-up validation: six employer confirmations, two unconfirmed
hCaptcha attempts, one email-verification hold and one queued intermediary
handoff. The shared fixes have local regression coverage; this is not a blanket
ten-job submission success claim. The detailed implementation report records
which external gates remain.

## Saved validation outcomes

The original ten-case audit, as of 2026-10-22T03:17:55Z, records six employer-confirmed
submissions, one Greenhouse email-verification hold, two Lever hCaptcha cases
without employer confirmation, and one CareerJumpShip service queue awaiting
employer delivery. The service-queued case is not counted as submitted. See
[`validation-outcomes.json`](../logs/direct_submit_validation/20261021/fixes/validation-outcomes.json)
for per-job statuses.

The later independent run `804fd765-3131-4df0-b05e-b2d44157c467` (2026-10-23)
confirmed 3/10 submissions (30%). Its other outcomes are two uncertain
submissions, one email-verification hold, three blocked applications, and one
failure before submit; no jobs were left unattempted. These are per-run counts;
the three confirmations repeat jobs confirmed in the earlier cohort. The local
run's `summary.json` records the full counts and elapsed time.
