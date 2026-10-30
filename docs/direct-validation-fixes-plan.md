# Current validation audit and implementation plan

Status: **shared fixes verified; six employer confirmations and four external gates**. The original audits
below remain historical evidence. Subsequent user-authorized implementation and
submission recovery are recorded separately here.

## Implementation update, 22 October 2026

The shared engine now preserves valid resume autofill, rereads fields before
writing, checks committed asynchronous location selections, maps GitHub/legal-name
variants, reports exact required blockers, and stops initial posting identity
changes before applicant data is entered. Intermediate native POST/React
Continue steps receive a single form-bound permission; final Submit remains
separately guarded. Named referrals require supplied facts rather than AI prose.
Live follow-up also identified country-only location semantics, formatted phone
readback, a missing “Your full name” alias, and a resume-analysis service failure.
Country context and phone formatting now resolve through shared rules rather
than employer-specific answers. Resume analysis has a bounded wait and surfaces
HTTP failures without claiming that an unverified file was accepted.

The Lever follow-up uses the same Kernel stealth/solver configuration as the
successful Ashby cases. The user confirmed hCaptcha beta is already enabled.
Lever's public client invokes a hidden native submit after its asynchronous
hCaptcha callback; a retained Shield AI guard also recorded a blocked
`form.submit`. A local delayed-callback fixture reproduced that incompatibility.
The final guard now permits one solver continuation for the original validated
form, with an actual response token and unchanged non-CAPTCHA answers. It does
not issue a second automated final click or infer application success from a
solver event. Changed answers, another form and preparation mode stay blocked.

The verified generic replacement now completes its form and reaches the
service's same-application success route. The uploaded bytes were observed in
the multipart request and acknowledged with HTTP 200 after auto-advance. Its
actual message is “You're in the queue” and promises employer submission within
24 hours. That remains `submission_uncertain` with stage
`external_submission_pending`; it is not counted as employer-confirmed applied,
and is not replayed on resume. The shared detector distinguishes a queued
intermediary handoff from an employer success message.

Email verification has a durable `awaiting_email_verification` state. Resume
reconnects the existing tab without replaying its original Submit. Automatic
mode continues the remaining batch and retains the verification tab. Explicit
`--retry-failed` retries only eligible pre-submit failures within a saved run.
Kernel cursors use API-provided offsets; bounded diagnostics omit query strings,
request bodies and raw error messages. Retained-tab reconnect avoids installing
a binding across every existing frame.
Fresh declared application-success containers are recognized even when an
employer customizes its wording. Pre-existing messages and upload-only success
labels cannot establish a new application. Retained uncertain attempts are
inspected again at batch end without replaying Submit.

The six independently confirmed applications are preserved and skipped. The
Baton Data Platform verification remains pending by explicit user direction.
The mismatched CareerJumpShip IT Engineer case is retired before Submit with its
original input/history preserved. A separately verified Ondo Finance DevOps
posting replaces it with user approval. There are ten active cases plus the
retired audit row; `active_total` and `active_counts` distinguish these.

Future URL-submit preparation reads optional private profile overrides. The
latest contact override applies only to this workflow. The user also explicitly
approved `signature_date_policy=completion_date`: signature dates use the local
completion date, while birth, employment and unidentified dates remain separate.
DEI opt-out policy is unchanged. Historical submissions and verification emails
are not rewritten.

Final checks: the fresh full suite passed **1,493 tests, 61 skipped**; the
focused provider/submission/browser matrix passed **117 tests, 18 skipped**;
**36 final confirmation contracts** passed after the last reporting changes.
These checks cover delayed autofill, location commitment, phone formatting,
scoped Continue, matching upload responses, delayed CAPTCHA callbacks, unchanged
form bindings, OTP recovery and stale-message rejection.

The ten active live cases now have observed outcomes: **six employer-confirmed,
two unconfirmed Lever hCaptcha attempts, one Baton email-verification hold and
one intermediary queued handoff**. Both Lever cases were retried with the same
Kernel stealth/solver settings used for the working Ashby cases. Their challenge
UI closed without a response token or employer confirmation; the new continuation
was armed and not consumed. Instrumentl had no blocked guard actions. Shield's
native-method block was already present during filling, before final activation;
it does not establish that a post-activation continuation was blocked.
The hCaptcha beta is enabled per the user; no missing-account-setup conclusion
is drawn. CAPTCHA/system queries returned no events and Chromium logs were
unavailable, so provider-side success or failure cannot be independently inferred.

The approved generic replacement reached a service queue that promises submission
within 24 hours, not a confirmed employer receipt. It remains protected pending.
The Baton OTP remains untouched by explicit user direction. No repeat final click
was made for an uncertain attempt. Private `validation-outcomes.json`, refreshed
`already-applied.txt`, `remaining-cases.txt` and a factual Kernel evidence note
are under `logs/direct_submit_validation/20261021/fixes/`. The remaining-case list
is for inspection; run-owned `retry.txt` excludes these protected outcomes.
There is **no claim of ten successful employer submissions**.

## Historical audit

Run: `8afd5714-14e2-442f-a65d-9413428932e4`.
Kernel session: `njgykc7g2g41t2mpz3ig38ly`.
The saved policy is **`pause=never`**, so this run is automatic submission mode.
Rechecked at **01:31–01:32 UTC on 22 October 2026 (18:31–18:32 PDT on
21 October)**. All ten jobs now have terminal batch statuses: **four applied,
five blocked, one submission uncertain**. The saved progress was last updated
at 01:28:46 UTC. The retained Kernel session was still available at recheck.

The earlier 01:17–01:19 UTC snapshot had no confirmed applications yet; that
was an intermediate observation, superseded by the completed batch below.

## Observed results

| Case | Observed result | Evidence / implication |
| --- | --- | --- |
| Instrumentl | Blocked; required Current location is empty in the live form despite a prepared field record | Non-ARIA `location-input` autocomplete reports no location found/loading. Filling text alone did not produce a persistent valid location. |
| Baton Data Platform | `submission_uncertain` after a Submit activation | Live page requests an emailed 8-character security code. CAPTCHA is clear; there is no employer success confirmation. |
| DuckDuckGo | Blocked on required Location | Accessible custom autocomplete returned zero observed options; field remains unselected. |
| CareerJumpShip | Blocked after two Continue attempts | POST server-action form remains on `who-you-are`; guard recorded `next-handler` twice. |
| Namespace | Blocked on required GitHub profile | Exact label is missing from the candidate alias mapping even though `candidate.github` is configured. |
| Shield AI | Blocked | Final report includes an unresolved required full legal name and disability signature Date. Generic final-validation wording hides the useful field-level detail. Optional missing facts must remain distinct from required blockers. |
| Baton Staff Infrastructure / Data Platform | Applied | Report has `confirmation_verified=true`; retained tab is on this job's `/confirmation` page with a success message. Confirmed at 01:19:41 UTC. This is a different role from the Baton OTP case. |
| Solace Health Senior Backend | Applied | Report and retained Ashby success container confirm receipt. Confirmed at 01:22:55 UTC. |
| Modal Inference Runtime | Applied | Report and retained page confirm success. Confirmed at 01:25:31 UTC. This is the selected SF role, not the earlier Stockholm role. |
| Baseten Inference Platform | Applied | Report and retained page confirm success. Confirmed at 01:28:38 UTC. This is a different role from the earlier Storage manager application. |

### Updated bug register

The following was the **proposed** bug register at audit time. Implementation
and rerun status are described above. Priority does not imply that another
application was submitted during the audit.

| ID / priority | Bug and evidence | Proposed fix | Required verification |
| --- | --- | --- | --- |
| B01 / P0 | CareerJumpShip expected IT Engineer but observed Infrastructure Engineer (DevOps), with a different posting/application ID. The cause of the changed page remains unproven. | Bind saved input identity to the initial posting before resume generation or private form work; recheck after every transition. Stop as `posting_identity_changed`. | Mismatched ID/title stops before resume, upload or answers; legitimate same-job apply routes work. |
| B02 / P1 | Resume parsing can populate a field after the fill snapshot but before its write. Local reproduction confirmed an overwrite; attachment verification does not await parsing. | Bounded parser settling plus a fresh read before resolution and immediately before writing. Preserve meaningful valid values and skip unnecessary AI. | Delayed parsing and autofill during AI resolution produce no overwrite or clear/type operation. |
| B03 / P1 | Custom dropdowns do not preserve existing committed selections. | Detect a committed selected value, distinguish it from search text/placeholders, reacquire after rerender and preserve it. Flag explicit profile/DEI conflicts for review. | Existing native/custom/radio choices remain intact; placeholders and unselected static radio values are still filled. |
| B04 / P1 | Instrumentl Current location is still empty and invalid despite a prepared record. DuckDuckGo Location remains unresolved with no observed options. Exact cause of the Lever value clearing is not yet proven. | Support related asynchronous and non-ARIA location menus, select a configured matching location, and verify persistence after blur/rerender. | Lever and Ashby autocomplete fixtures, delayed/no results, clear-on-blur and post-selection readback. |
| B05 / P1 | Namespace's required GitHub profile remains empty/invalid; its exact label is absent from aliases despite configured GitHub. | Add normalized GitHub profile aliases using the existing candidate value. | Exact live label and URL input resolve from configuration; no AI URL generation. |
| B06 / P1 | Shield AI's required full legal name remains empty/invalid; label variant is unmapped. Its required disability signature Date is also empty/invalid. | Map the legal-name variant to explicit identity. Keep signature/date/attestation separate; require applicable explicit configuration or manual completion. | Required-marker variants map correctly; generic dates never receive an invented attestation. |
| B07 / P1 | Baton Data Platform remains on email verification with eight empty `security-input-*` fields and no success; current state only says uncertain. | Add durable `awaiting_email_verification` before/after Submit, retain the tab and attempt, continue the batch, and reconnect without replaying submission. | OTP wrong/expired/success, restart/closed-tab handling, no guessed/logged code and no duplicate activation. |
| B08 / P1 | CareerJumpShip Continue is a POST server-action form; current guard prevents its default action. Reproduction: zero POSTs with guard, one POST and next screen without it. Live tab is still on `who-you-are`. | One scoped intermediate-transition permit bound to control, form, action, method and verified posting. Await the actual transition; preserve final-submit protection. | Native POST, React server action and client Next; rejection/slow transition; final Submit still protected. |
| B09 / P1 | Final validation replaces useful field blockers with `Required answers or access challenge remain`; a prepared record can outlive an empty live field. | Merge specific blockers and verify required fields after parsing/conditional changes. Separate optional missing facts, access challenges and field failures. | Reports identify exact required controls and readback failures instead of only a generic reason. |
| B10 / P1 | Solace's required named-referral/connection question was recorded as `source=ai_draft`. Its draft has no source IDs. This proves a routing/provenance gap, not that a referral was fabricated. | Classify named referrals and relationships as supplied facts. Use an explicit referrer/no-referral answer, otherwise hand off. Preserve configured web discovery for questions it actually answers. | Referral wording variants never call prose AI without explicit relationship facts; motivation questions still work. |
| B11 / P2 | Telemetry code derives cursor offsets from event counts despite API pagination using opaque offsets. Current diagnostics also cannot capture network/console detail. | Persist returned API cursors, distinguish unavailable from empty logs, and add opt-in redacted page/request diagnostics for future sessions. | Filtered empty pages, opaque offsets, pagination/restart, unavailable log source, and payload/credential redaction. |

### Kernel recheck

The same retained session was reachable and all ten job tabs were inspectable.
The first Baton's email verification screen is still present; its uncertain
outcome must not be promoted to applied. All four applied jobs were independently
checked against retained employer success pages/messages.

The refreshed 100-event unfiltered sample contained **97 CDP command events,
one connect and two disconnect events**, with older pages available. This is a
bounded sample, not a total event count. Read-only audit attachments contribute
to these events; disconnects alone do not establish browser crashes.
The CAPTCHA/system query over the preceding 45 minutes returned zero events
with no next page. That absence does not prove solver success or failure.

The documented `chromium` supervisor process source again returned
**`logs source not available`**. Browser network, console and page telemetry are
unset in this session. No request failure, provider-side OTP cause or engine
health conclusion can be established from those unavailable sources. No
diagnostic settings or active tabs were changed to obtain this recheck.

Fresh evidence is in
`logs/direct_submit_validation/20261021/live-validation-audit/recheck-20261022T013135Z/`:
`progress-snapshot.json`, `reports-summary.json`, `kernel-recheck.json`,
`referral-routing-evidence.json` and `receipt.json`. Original audit evidence
below remains unchanged.

### CareerJumpShip identity issue

The selected input is **IT Engineer**, URL ending `c1bb7b74`. The first observed
posting was **Infrastructure Engineer (DevOps)** at Ondo Finance, URL ending
`8257c5e6`, and the application uses that different job ID. The generated resume
was bound to the observed different role. Generic navigation verifies the
observed title after it has selected a job, but does not adequately compare the
initial observed job against the saved input's expected posting.

This is verified identity drift, not a proven server redirect: an independent
read-only request to the original public URL returned a Vercel 429 checkpoint,
so it could not establish why the live tab reached a different posting. Stop
this case as `posting_identity_changed` until the input is reverified; do not
silently accept another job at the same company.

### Autofill finding

Ordinary native fields already have an existing-value preservation branch.
However, that branch reads a snapshot before answer resolution. If ATS resume
parsing completes during answer resolution, the subsequent write can overwrite
the newly populated field. A local synthetic reproduction confirmed this:
the ATS-filled `Resume parsed name` became `Configured name` under the current
`fill_fields` implementation.

Custom dropdowns have no equivalent existing-selection guard. Upload acceptance
also returns once file integrity/attachment is verified; it does not wait for
the employer's asynchronous resume parsing to settle. The live pages alone do
not establish the exact order of every overwrite in this run; the local race
reproduction establishes the implementation gap independently.

### Continue finding

CareerJumpShip's form uses `method=post` and a hidden React `$ACTION_ID` input.
The current guard deliberately calls `preventDefault()` on identified Next
submit events. That works for client-side wizards but blocks a native/server
action that requires the POST. A local reproduction recorded zero POSTs and no
navigation with the guard, versus one POST and the next screen without it.
No Continue click was performed on the employer during the audit.

## Implementation order and acceptance checks

### 1. Enforce expected posting identity before private form work

Compare requested/saved job ID, title and company with the first live posting,
before generating a resume or filling/uploading applicant information. Repeat
the comparison after entry-link navigation and every wizard transition. For
generic job sites, bind the posting's stable ID to its application ID; a same-host
or same-company redirect is insufficient.

Tests: changed job ID/title stops before the resume provider, upload or answer
provider is called; legitimate same-job application suffixes remain supported;
unknown/mismatched generic redirects remain explicit handoffs.

### 2. Preserve valid ATS autofill and prevent delayed overwrites

After upload, wait within a bounded budget for observed resume parsing/spinners
and field changes to settle. Do not wait for global network idle or unrelated
analytics. Read current field state before generating an answer and immediately
before writing it; reacquire controls after rerenders.

Preserve nonempty valid text, meaningful selected options, selected radio groups
and committed autocomplete values. Search text, placeholders and a radio input's
static `value` are not evidence of a selection. Do not reopen/reselect a valid
custom dropdown. Avoid an AI call for a field that is already filled. Record
preserved/filled/failed counts without logging answer values.

Surface conflicts with explicit configuration or DEI opt-out policy for review
instead of silently overwriting valid prefilled answers. Recheck required
fields after parsing and after each conditional change.

Tests: initial and delayed autofill, autofill during an AI response, valid custom
selection, placeholder option, partially populated radio groups, parser timeout,
and rerendered inputs. Assert preserved answers receive no clear/type/select
action and need no unnecessary AI request.

### 3. Fix field mappings, location controls and blocker reporting

Add normalized aliases for GitHub profile and full legal name, using supplied
profile facts only. Do not treat a generic Date or signature as permission to
invent or attest a fact. Keep missing consent/signature/fellowship information
manual unless explicit applicable configuration exists.

Also classify named referrals and personal connections before the generic prose
fallback. The Solace report shows a required referral question resolved by
`ai_draft`; this does not establish whether its answer was factually correct.
An explicitly supplied web discovery source answers discovery-source questions,
but does not itself establish a named referrer or a no-referral assertion. Use
an exact configured relationship answer or a manual handoff when required.

Recognize observed location autocompletes even without ARIA roles, including
Lever's location input. Wait for related options, select a matching configured
city/region/country, and verify the committed value persists after blur. Scope
option discovery to the related widget; do not choose an unrelated dropdown.
Apply the same persistence check to native and accessible controls. A typed
value is not automatically a prepared field.

Preserve specific required-field blockers when final validation fails instead
of replacing them with `Required answers or access challenge remain`. Optional
unanswered fields stay separately visible in reports.

Tests: Namespace's exact GitHub label, legal-name label with a required marker,
Lever location selection/clear-on-blur behaviour, DuckDuckGo-style async
location options, missing-option recovery, exact blocker propagation and referral
variants that never fall through to unsupported prose drafting.

### 4. Model email verification as a durable manual continuation

Detect email verification before and after possible Submit, including
Greenhouse's eight separate `security-input-*` controls and its actual message
wording. Use an explicit `awaiting_email_verification` state, preserve the tab,
and checkpoint whether a final activation has already occurred.

Do not generate, guess, read a mailbox for, or log the code. Hand the existing
Kernel live tab to the user even when the rest of the batch uses `never` mode;
continue preparing other jobs. Observe manual verification and subsequent
employer confirmation. If the portal requires another user action after code
entry, treat that as an explicit verification continuation rather than blindly
repeating the original automated Submit.

Resume must reconnect this tab without refilling/reuploading or replaying the
original activation. Loss/expiry of the verification tab remains an unresolved
possibly submitted outcome. Include this state in manual-review views,
needs-review reporting and the Task 1 filter that hides possibly submitted jobs.

Tests: OTP before/after activation, wrong/expired code, verification followed by
success or validation rejection, process restart, closed tab and no automatic
duplicate Submit. Preserve original attempt and run history throughout.

### 5. Support scoped server-action wizard transitions

Keep final submission protection intact. Add a one-transition permission bound
to the identified Next/Continue control, its specific form, method, observed
action endpoint and verified posting. Permit the native/server-action POST only
for that vetted intermediate step; do not globally unblock form submission.

Wait for the request/navigation/step transition to settle before deciding it
repeated a state. Include step route, form action, heading and active-field
structure in progress detection. Preserve same-job binding, required-field
checks and bounded loop limits. A failed or ambiguous transition must not be
blindly clicked again.

Tests: client-side Next, native POST, React server action, slow transition,
server validation rejection, repeated state, unexpected target/job change and
final Submit still blocked in preparation/manual modes.

### 6. Improve diagnostics and validate across providers

This session exposes control/connection telemetry, but the filtered CAPTCHA/
system query returned zero events. No solver success/failure can be inferred
from that absence. Network and console telemetry were not enabled for this
session. The supervisor log endpoint returned `logs source not available`,
including the documented `chromium` source; it did not supply clean browser logs.
See the [official Kernel CLI log and telemetry reference](https://github.com/kernel/cli#browser-logs).

Add bounded, redacted page-error/request-failure and navigation diagnostics for
future runs: target ID, stage, method, host/path, status and error category;
exclude bodies, form values, OTPs, cookies, headers and signed URLs. Distinguish
unavailable logs from an empty successful log read. Persist the API's returned
opaque telemetry cursor; do not derive offsets from filtered event counts or
sequence numbers. Retain session-wide events without misattributing them to a
job.

First run local regressions for each confirmed issue. Then validate the affected
cases individually with preparation or retained manual tabs, followed by the
same ten-case matrix. Required pass conditions: no preserved-value overwrite,
correct role identity, specific blockers, working vetted intermediate navigation,
resumable OTP handoff, and `applied` only after posting-scoped employer success.
The original read-only audit made no employer actions. Subsequent authorized
retries and their actual outcomes are recorded in the implementation update above.

## Evidence

Private audit files are under
`logs/direct_submit_validation/20261021/live-validation-audit/`:
`progress-snapshot.json`, `live-session.json`, `field-details.json`,
`kernel-details.json`, `chromium-logs.json`, `telemetry-summary.json`,
`next-post-reproduction.json` and `autofill-race-reproduction.json`.
Existing run reports and screenshots remain in their original run directory.
