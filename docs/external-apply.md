# Company-page applications

For arbitrary job URLs with submission disabled, see
[Generic URL preparation](generic-url-preparation.md). This separate command
reuses configured profiles, AI drafting and per-job résumé generation, and
records preparation evidence without entering the submission workflow.

Company-page support is disabled by default. Enable `external_apply_enabled = True` in `config/settings.py` and set `easy_apply_only = False` in `config/search.py` when you want employer links included. Existing date, geography, work arrangement and role eligibility gates remain active. Pipeline application mode still accepts only selected LinkedIn records and retains their verified-role provenance.

The supported preparation contracts are native input, textarea, select, radio, checkbox and multiple-selection controls on hosted Greenhouse, Lever and Ashby applications. Known identity fields use configured values. Additional questions use the typed local JSON described below. A PDF must independently pass the resume verifier and its new attachment must be confirmed. Custom JavaScript comboboxes, embedded flows and ambiguous question/option labels stay manual.

The employer posting must match an approved official role URL, or exact hosted company/title evidence for a legacy run. Unsupported hosts, embedded custom flows, ambiguous uploads, changed posting identities, visible access challenges and incomplete required questions produce an explicit handoff or failure. Preparation does not mean the application was submitted.

The scrollable private review shows each answer, control name/type, source and unresolved question, then offers **Submit application**, **Leave open**, or **Discard application**. Do not click Submit separately in the browser during this review. Choosing **Submit application** authorizes the bot's website Submit click; the review is always required, regardless of `run_non_stop`, `pause_before_submit`, background settings or AI flags. `run_non_stop = False` stops continuous runs; it is not the review guard. A unique Submit control, unchanged verified resume and durable submission checkpoint are required before the automated click. Invalid or incomplete required fields prevent that click.

A confirmed submission requires a new success heading on the same ATS employer/posting identity, including a success route that retains both the board and job ID. A generic thank-you page on a shared ATS domain cannot confirm the application. Interrupted clicks, missing confirmation and unsupported confirmation routes remain `submitting`, protected from automatic retry and further submissions under the configured cap.

Confirmed company-page applications use the existing `max_applications_per_run` budget and dated applied history. Prepared/manual handoffs retain pending history and do not count as confirmed submissions. Outcome metadata includes ATS provider, posting ID, attachment filename/hash, filled field names, manual question labels and attempt ID; it omits the applicant's field values.

## Configure additional answers

1. Copy `config/external_questions.example.json` to `~/.jobrobo/external-questions.json`. The checked-in file contains synthetic values: replace them before using it. Do not copy personal answers or API keys into Git.
2. Edit that private JSON. `external_questions_config_path` in `config/settings.py` can point to another local file. Missing files leave custom questions manual; malformed files produce a visible review warning. `version` must be `1`.
3. Add candidate values under `candidate`, or exact question entries under `answers`. An answer entry needs `question`, `type`, and `answer`; optional `provider` is `greenhouse`, `lever`, `ashby`, or `*`, and optional `name` is the control name shown in review. Repeated labels need that name to disambiguate them. Conflicting entries stay manual.
4. Review the actual form and private answer preview on every application. Unsupported controls and unavailable facts can be completed in the browser while the review remains open.

Answer precedence is an explicit matching question entry, then an explicit candidate value, then optional grounded AI. Existing operator/browser answers are preserved unless a question entry explicitly overrides them; they do not trigger unnecessary AI calls. Candidate JSON values override the existing candidate configuration for this feature. Ordinary question matching normalizes Unicode, case, whitespace, punctuation and a trailing required/optional marker; it does not use fuzzy or substring matching.

| Live control | JSON `type` | JSON `answer` |
| --- | --- | --- |
| Single-line input | `text` | String |
| Long answer | `textarea` | String |
| Numeric input | `number` | Number or numeric string within live bounds |
| Date input | `date` | `YYYY-MM-DD` string |
| Dropdown | `select` | One exact displayed option label |
| Radio group | `radio` | One exact displayed option label |
| Single checkbox | `checkbox` | JSON `true` or `false` |
| Native multi-select or explicit checkbox group | `multiselect` | List of exact displayed option labels |

Candidate fields include identity/contact/address fields, `github`, `summary`, `cover_letter`, `years_of_experience`, `current_employer`, `desired_salary`, `notice_period`, `citizenship`, `require_visa`, `work_authorization` and explicit demographic choices. Only recognized question labels use these values. For unfamiliar or qualified wording, add an exact per-question answer; work authorization is never derived from citizenship or sponsorship. For example, authorization to work with confidential data is a different question from legal authorization to work in the United States.

No unknown citizenship, work authorization, sponsorship, clearance, demographic/disability/veteran, criminal-history, salary, availability, education or employment fact is invented by AI. Leave missing facts unresolved. A consent/attestation checkbox is checked only when a user-authored per-question entry contains a JSON boolean and matches the **entire displayed label exactly**, including case and punctuation; ordinary normalized matching and candidate defaults cannot authorize it. Otherwise consent remains manual. A signature needs an explicit private `candidate.legal_signature` value. All configured consents/signatures still appear in the required human review.

## Optional local-key AI drafts

Question AI is independent of the global `use_AI` and `use_AI_for_resume` flags. It is disabled in the example. To enable it, set `ai.enabled` to `true`, choose a supported `ai.model` and an OpenAI-compatible `ai.base_url`, then supply your own local key. No shared cloud-key service is called by this adapter.

The safe default key name is `JOBROBO_EXTERNAL_AI_API_KEY` in your launch environment. Your existing local OpenAI key can also be used with:

```json
"ai": {
  "enabled": true,
  "model": "gpt-4o-mini",
  "base_url": "https://api.openai.com/v1",
  "api_key_env": "OPENAI_API_KEY",
  "dotenv_file": "/absolute/path/to/your/private/.env",
  "max_questions": 6
}
```

The explicit dotenv file supplies the named local key. Alternatively, an `OPENAI_API_KEY` already present before runtime initialization is captured in memory before the legacy shared-key loader can replace it. A key installed later by that loader is not accepted as this feature's local key. Keys are never stored in the question JSON, answer metadata or logs. The model shown above follows the existing project configuration; endpoint/model access and structured-JSON support must be available on your account.

When AI is enabled and a local key is available, the selected local resume DOCX, existing candidate information/summary and current JD provide bounded source text. This text is sent to the configured provider, so enable it only for material you intend to share there. Each answer is a typed JSON result with source IDs. Candidate history/qualification claims must match an exact candidate-source sentence or clause; citing a real source ID alone is insufficient. Technical-choice claims require candidate evidence, not a desired JD skill. Nonfactual, source-relevant motivation and explicitly hypothetical approaches may use generated prose. Unsupported claims, negation changes, new numbers, invalid options, uncertainty or provider errors produce a manual handoff rather than a guessed answer. This conservative check can reject a truthful paraphrase.

Defaults bound calls to six questions per application (configurable from zero to twenty), twenty seconds per request, no retries and 650 completion tokens; accepted text is at most 1,500 characters and must also fit the live control. Unsupported API parameters/models, missing local keys, malformed JSON and failed requests leave questions manual. Preparation and AI drafts never authorize a submission.

An additional ATS posting ledger lives at `<search_state_dir>/external/applications.json`. Its locked pre-submit claim permits one attempt to own a posting even if LinkedIn presents another ID for the same employer job. Confirmed and uncertain owners cannot be replaced by later drafts or other attempts. Keep this ledger with search/application manifests. An uncertain outcome requires inspection before an operator resolves its tracking state; do not delete protected records to force a retry.

## Evidence and limits

On October 14, 2026, read-only DOM inspection covered a Greenhouse Anduril form, a Lever Instrumentl form and the Ashby Baseten Inference Platform form. Their custom fields were recorded as manual questions. No live applicant information was filled, resume uploaded or application submitted. The Anduril and Instrumentl forms were inspected as contracts, not approved application targets.

Automated tests use synthetic fields/documents, fake AI responses and the real runner loop. They cover typed answers and option validation, precedence, ambiguous/repeated labels, separate radio/checkbox requirements, exact configured consent, unknown personal facts, grounded/failed AI drafts, private review/value-free metadata, local-key provenance, review/attachment gates, strict identity, stale concurrent claims, confirmed and uncertain outcomes, pending history, duplicate protection and the global submission cap. Live server confirmation and employer-specific custom controls remain subject to an authorized selected-target test; this release does not claim every site or every ATS form is automated.
