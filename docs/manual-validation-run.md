# Diverse ATS manual-validation run

The frozen sample is drawn only from Task 1's current
`phase2-engineering-ranked-remaining.json`. It contains ten distinct URLs:
five Ashby employers, two Lever employers, two Greenhouse roles and one generic
job-site entry. No current form inspection, browser interaction, resume upload
or application submission was performed while compiling it.

Use [jobs-validation.txt](../jobs-validation.txt) for the URL list, or the local
`jobs-validation.json` to retain the verified role IDs,
JDs and original verification metadata. Both load the same URLs in the same
order. The raw metadata JSON remains private. [The manifest](../jobs-validation-manifest.json) records the source file
hash, selected cases, warning details and proposed checks. Validation focuses
are things to inspect, not claims about widgets already observed on these forms.

| Case | Provider / entry | Company | Role | Saved preference warnings |
| --- | --- | --- | --- | --- |
| 1 | Lever | Instrumentl | Senior Backend Engineer | Unknown posting date |
| 2 | Greenhouse | Baton | Software Engineer - Data Platform | Unknown posting date |
| 3 | Ashby | DuckDuckGo | Senior Privacy Engineer | None |
| 4 | Generic entry | CareerJumpShip | IT Engineer | None; downstream employer/ATS unverified |
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

The table records the original frozen sample. During the subsequent authorized
rerun, the unavailable/mismatched IT Engineer case was retired and replaced by
a separately verified Ondo Finance Infrastructure Engineer (DevOps) posting.
That saved run preserves the original input plus the approved replacement and
skips its confirmed applications on resume. See the
[implementation and live-validation record](direct-validation-fixes-plan.md).
The frozen TXT/metadata inputs retain the original case for audit; starting a
fresh run from them does not silently substitute another role.

Run from the repository root. For the manual Kernel batch:

```bash
python3 direct_apply.py submit --input jobs-validation.json \
  --browser kernel --pause-before-submit always --limit 10
```

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

The sample is a fixed regression input. It will not shrink after submissions;
fresh commands can attempt the same jobs again. For recovery of an existing
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
