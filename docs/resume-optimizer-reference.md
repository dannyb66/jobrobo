# Resume optimizer reference

This page describes the implemented optimizer contract. See [How to ATS-optimize a resume](how-to-ats-optimize.md) for a walkthrough and [Architecture](architecture.md) for the system flow.

## Public entry point

```python
from modules.ai.resume_optimizer import run_resume_optimization

output_path = run_resume_optimization(
    job_description="Complete job description",
    resume_path="all resumes/default/resume.docx",
    job_id="local-review",
    job_title="Staff AI Platform Engineer",
    first_name="first",
    last_name="last",
    optimization_mode="skills",  # optional; otherwise use saved configuration
    content_policy="grounded",  # or explicit "review_draft"
    replace_job_title=False,  # independent optional override
)
```

The function returns a PDF path when generation and verification succeed, or `None` on a handled failure. It requires `OPENAI_API_KEY` in every mode because keyword extraction uses the OpenAI API. Model credentials, network errors, and an unavailable converter can prevent a complete run.

## Optimization modes

| Mode | DOCX changes | Typical use |
| --- | --- | --- |
| `skills` | Updates Skills only. | Existing bullets and titles already fit the role. |
| `bullets` | Updates Skills, rewrites ordinary professional-experience bullets, and replaces matching company/project bullets from configured banks. | Tailor terminology and evidence while preserving titles. |
| `full` | Runs `bullets` and replaces recognized dated experience titles with the requested job title. | Title replacement has been deliberately reviewed. |

The independent `replace_job_title` flag overrides the mode's title behavior: false preserves professional titles even in `full`; true enables replacement in `bullets` or `skills`. When no flag exists, `full` retains its historical title behavior. The GUI checkbox saves this independent override. Replacements preserve title punctuation and dates; they do not establish that the new title accurately describes a previous job. Every title change appears in the review report. Summary and project titles remain unchanged.

Skills selection ranks explicit JD relevance before clipping, then related existing AWS/Docker/Terraform context, then original order. Related-tool relevance is a local presentation heuristic and gives no credit for an unstated JD requirement. Selection caps the result at both `max_skills` and the original entry count and deduplicates proven full-phrase/acronym pairs. Off-JD bank/model vocabulary and terms confined to recognized company-overview/benefits sections do not enter the coverage denominator. The result can contain fewer entries after deduplication; longer terms can change wrapping.

DOCX text replacement retains all source runs and distributes the replacement text across them proportionally, preserving their font properties and character spacing. Skills reuse existing paragraphs and line capacities. This preserves template formatting signals without promising identical rendering.

PDF input always updates Skills only and records `effective_mode: "skills-pdf"`, including when `skills` was requested. PDF editing does not support the DOCX bullet or title operations. Project titles are preserved in every mode.

An invalid mode currently prints a warning and uses `full`. Select one of the supported values explicitly.

## Runtime configuration

Repository defaults live in `config/resume_optimizer_defaults.json`. The user configuration lives at:

```text
~/Library/Application Support/jobrobo/config/resume_optimizer_defaults.json
```

This is the path used by the loader, including when run outside macOS. Current bundled defaults fill missing fields while saved user values, including unknown settings, remain authoritative. Loading an existing file merges in memory. Saving serializes the complete read/merge/write operation and persists atomically; the GUI saves its edited fields so newer bank settings survive. Editing repository defaults alone does not replace existing user choices. Malformed JSON or a non-object configuration raises a configuration error instead of silently overwriting the file. The function argument `optimization_mode` overrides the saved mode for that call.

| Field | Meaning / repository default |
| --- | --- |
| `optimization_mode` | `full`; supported values are `skills`, `bullets`, `full`. |
| `replace_job_title` | Independent boolean override for dated professional title replacement; explicit false is preserved. A call argument overrides the saved flag. |
| `rewrite_bullets` | Legacy mode migration flag. An explicit `optimization_mode` controls bullet rewriting. |
| `content_policy` | `grounded` by default; `review_draft` explicitly permits proposed unsupported Skills and broader role-appropriate AI content. The GUI exposes both choices. |
| `rewrite_length_multiplier` | `1.15`, allowed range 1–1.5; each rewrite may use up to this proportion of source characters, capped at 40 extra characters. Final layout verification remains required. |
| `rewrite_response_attempts` | `2`, allowed 1–2; retry invalid model responses once. A final partially invalid response retains individual source bullets while keeping valid rewrites. |
| `layout_retry` | `true`; retry the requested mode with bank count/length bounded by source bullets before falling back to Skills only. Valid model rewrites are cached for identical inputs. |
| `match_weights` | Optional positive `required`, `preferred`, `context` weights; defaults 2, 1, 1 are local heuristics, not empirical ATS weights. |
| `skill_bank_path` | `config/skills/Skills_Keyword_Bank_Staff_Principal_2026-10.md`. |
| `bullet_bank_path` / `bullet_bank_company` | Legacy single-bank settings, normally Trek Health. |
| `max_bank_bullets` / `allow_unverified_bullet_terms` | Legacy bullet count and marker policy; defaults are `7` and `false`. |
| `project_bullet_banks` | Company/project bank specifications used for exact bullet replacement. |
| `role_profile` | `auto`, or an explicit profile name from the skills guide. |
| `allow_unverified_bank_terms` | `true`; allows dagger-marked skills-bank vocabulary into keyword guidance. `false` filters those bank suggestions. |
| `max_skills` | `50`; upper limit on Skills entries, also bounded by the original entry count. |
| `expected_page_count` | `2`; required number of rendered output pages. |
| `resume_path` | Source DOCX or PDF path used by the GUI/module entry point. |
| `job_id`, `job_title`, `job_description` | Output identifier and target job context. |
| `first_name` / `last_name` | Output filename components. |

The skills marker flag does **not** check whether every extracted JD keyword is supported by the resume. Keyword extraction and model rewriting are not career-fact verification.

When an older file has no `project_bullet_banks`, migration adds the four default banks and carries its legacy Trek path, company, count, and marker policy into the first specification. An explicit saved bank list remains authoritative.

## Bullet-bank targets

| First matching entry | Bank | Default count target | Required category |
| --- | --- | --- | --- |
| `Trek Health` | `Trek_Health_Bullet_Bank.md` | 7 | `A` Platform and `N` Leadership |
| `CODEX SELF-HOSTED` | `Codex_SelfHosted_Bullet_Bank.md` | 3–5 | `A` Platform |
| `SOHAMHAMSO` | `Sohamhamso_Bullet_Bank.md` | 2–4 | `A` Overview |
| `SPONSORSKIP` | `SponsorSkip_Bullet_Bank.md` | 1–2 | `A` Overview |

Replacement matches the configured `company` against a normalized company/project paragraph, then replaces the following list paragraphs after the title line. It does not select a project merely by its ordinal position. If the target or expected paragraph structure is absent, that bank is not applied.

Example specification:

```json
{
  "path": "config/bullets/Codex_SelfHosted_Bullet_Bank.md",
  "company": "CODEX SELF-HOSTED",
  "min_bullets": 3,
  "max_bullets": 5,
  "required_sections": ["A"],
  "allow_unverified": false
}
```

`required_sections` contains categories inside the bank, not headings in the resume. Relative bank paths resolve through `resource_path`: from the repository root in development, the application Resources directory in a py2app bundle, or the extraction directory in a PyInstaller bundle. Absolute custom paths are used directly. Missing or empty bullet banks are skipped. Set `project_bullet_banks: []` to disable curated replacements while retaining ordinary LLM rewriting in `bullets`/`full`. Use `skills` to skip all bullet operations.

## Bank selection and claim limits

The parser reads the checked-in Markdown tables, stable IDs, category letters, preset references, lookup phrases, metric IDs, lead verbs, and `†` / `‡` markers. Selection ranks preset and JD-lookup matches, JD word overlap, required categories, and preferred character lengths. It limits duplicate metric IDs and lead verbs, including across configured banks.

With `allow_unverified: false`, marked bullet entries are excluded. Required categories and minimum counts are selection targets; insufficient eligible candidates or deduplication can yield fewer bullets. The selector does not add an excluded claim to reach a count.

Selected bank text is inserted exactly. Ordinary professional experience follows the existing LLM rewrite path, prompted with the target title, JD, selected skills, and guided keywords. The model is instructed to preserve facts, but the implementation does not independently validate those facts or the bank's source evidence. Review every selected claim and rewritten bullet.

Skills selection retains the existing skills pool and ranks only JD terms with bounded evidence in the original resume, including its experience and projects. A proven acronym expansion may change the display wording. A source mention of `vLLM` does not establish a compound serving stack containing other tools. JD extraction and bank markers provide vocabulary guidance; they cannot establish candidate experience. Unsupported terms stay in the report as gaps instead of being inserted into Skills. Original skill count and configured `max_skills` still bound the selection. A Skills-only fallback uses the same grounded selection.

These source restrictions describe `grounded`. With explicit `content_policy: "review_draft"`, unsupported JD terms may be proposed in Skills and the model may propose relevant responsibilities or technologies beyond source statements. The artifact is labeled `manual_review_draft`, and changes, unsupported terms and provenance require review. This makes an editable draft; it does not verify new qualifications or authorize submission. The source is preserved and page/font/content/hyperlink checks still gate the returned PDF.

Keyword responses must contain a list of strings. Experience responses preserve source identities, entry count and bullet count, with nonempty text within per-bullet fit budgets. The prompt supplies those budgets and JD requirement context. Invalid responses receive a bounded compression retry; after the final attempt, valid bullet edits survive while invalid bullets retain source text. Structural identity/count failures retain the source entries. `rewrite_diagnostics` and `api_warnings` expose these outcomes and numerical length failures without repeating candidate text. These checks do not establish factual accuracy.

## Output and report contract

For source `<parent>/<source-folder>/resume.docx`, output is placed in `<parent>/temp/`. The filename contains normalized first name, last name, target title, and job ID. Use a distinct local job ID for each inspection run. The source file is retained.

The pipeline writes `<output-stem>.match_report.json` alongside the intended PDF, including generation, conversion, and verification failures. Successful DOCX fallback files add `_layout_safe` to the stem. Inspect the returned path and report rather than guessing the filename.

Report fields include:

```text
job_id
job_title
requested_mode
normalized_mode
effective_mode
status
error
attempts
api_warnings
role_profile
skill_bank
bullet_bank
bullet_bank_company
project_bullet_banks
selected_bullet_bank_ids
project_bullet_bank_selections
keywords
unverified_terms
pre_optimization
post_optimization
keyword_scoring_method
keyword_provenance
skills_grounding
content_policy
artifact_kind
review_required
auto_submission_authorized
replace_job_title
title_replacement_applied
source_sha256
changes
discarded_extracted_keywords
rewrite_diagnostics
match_analysis
format_verification
output_path
```

`pre_optimization` and `post_optimization` retain `score`, `matched`, `missing`, and `total`. Coverage counts each unique concept once: skills-bank Core concepts count twice and other concepts once. Matching uses complete normalized tokens/phrases, so Java does not match JavaScript, RAG does not match storage, and C/C++/C# remain distinct. Parenthetical acronyms count as aliases only when they spell the full phrase's initials; contextual parentheses such as `Infrastructure (AWS)` remain part of the phrase. Competing expansions of an acronym are not credited from that ambiguous acronym alone. `keyword_scoring_method` records `bounded-unique-concept-coverage-v1`, since corrected matching and deduplication can change scores from older reports. This is a local lexical diagnostic, not an ATS vendor score, qualification assessment, or hiring probability.

`keyword_provenance` separates `retained_terms`, `introduced_terms`, `removed_terms`, and `absent_terms`, with input terms, weights, and short source/output mention excerpts. An expanded equivalent can retain source provenance from a proven acronym. These are textual mentions, including potentially negated claims, and the report explicitly sets `facts_verified: false`. Introduction signals review rather than proving a falsehood: curated-bank evidence may exist outside the source resume. The diagnostic does not validate work history, durations, employer requirements, or application eligibility, and it does not change the format/hyperlink acceptance gates.

`skills_grounding` records `bounded-source-supported-skills-v1`, the evidence scope, supported/blocked JD terms, and source excerpts or `no_bounded_source_mention` reasons. The full original resume supports pipeline selection; direct `optimize_skills` calls without `source_text` use the supplied current Skills as evidence. All guided terms remain in `keywords`, so blocked Skills terms still count as missing coverage. This guard is lexical source support, not independent factual verification; `facts_verified` remains false. Review negated or historical mentions and all selected bank/rewritten experience claims separately.

In draft policy, `skills_grounding.proposed_keywords` records unsupported proposals; `removed_source_skills` records clipped source terms. `changes` contains paragraph locators and before/after text for review, with `facts_verified: false`. `title_replacement_applied` reports actual title changes, independently of the requested flag. `auto_submission_authorized` is false: the report grants no application-submission authority. Existing application review remains a separate workflow.

`match_analysis` uses `jd-requirement-evidence-v1`. It separates required, preferred and context coverage, source versus output evidence, draft-only mentions, and title-term alignment. Known bare/flattened headings and optional phrases such as “isn't required” influence the heuristic extraction. Repeated requirements do not gain weight; simple OR alternatives count once. Negated-only source mentions are flagged. Weights and title overlap are inspectable local diagnostics, with no vendor-score or qualification claim. Keyword extraction, mixed Boolean clauses, context and negation remain imperfect; inspect the linked JD spans and evidence.

`requested_mode` records the original input and `normalized_mode` records the supported mode used after validation. `unverified_terms` lists guided keywords carrying the skills bank's dagger marker. It is not a complete list of unsupported claims. `format_verification` contains `passed`, `checks`, and `warnings`, with layout details; inspect it even if the keyword score rises.

`attempts` retains each DOCX attempt's mode, output paths, conversion result, verification, and selected bank IDs. PDF editing records its mode, path, and verification without a DOCX conversion step. After a successful Skills-only fallback, top-level bank selections are empty because those bullets are absent from the accepted artifact; the rejected attempt retains its selections in `attempts`.

When compact bank retry succeeds, `effective_mode` adds `-fit-retry` and preserves the requested bullet/title edits. If it fails, the final Skills fallback preserves historical titles. A compact retry reuses identical validated model inputs from memory; changed entry groups can require another bounded model request. With two response attempts, keyword extraction plus both rewrite groups can make up to five requests. Set `rewrite_response_attempts: 1` or `layout_retry: false` to reduce that bound.

`status` is `accepted`, `rejected`, or `failed`. `error` records a handled pipeline failure. `api_warnings` records keyword or bullet-model failures that can allow processing to continue with bank guidance or original experience text. An accepted format result therefore does not prove that every requested model rewrite succeeded.

## Format verification and fallback

The verifier compares rendered PDF text and, for DOCX input, source/output document signatures. It checks the configured page count, nonempty extractable page text, horizontal/vertical text bounds, source-relative section sequence, rendered heading order, new orphaned headings, bullet-count changes, margins, and inherited minimum/maximum/typical body font sizes. Title and heading fonts are excluded from the body-font comparison.

For DOCX output, every DOCX section heading must appear in PDF text in order. The `docx_pdf_content_consistent` check also requires at least 95% coverage of Unicode-normalized DOCX tokens in the rendered PDF, counting repeated tokens. This helps reject stale/unrelated conversion output or missing content; it does not establish identical word order or appearance. The ratio is recorded in `format_verification.details.docx_pdf_token_coverage`.

The `hyperlinks_preserved` check requires each external DOCX link target to appear as a PDF URI annotation with a usable click area. For PDF-only input, source annotations provide the expected targets. Repeated targets retain their occurrence counts; wrapped links may create additional annotations. Export-added trailing slashes are tolerated, while query/fragment changes remain distinct. Counts, missing targets, and invalid click areas are recorded in `format_verification.details.hyperlinks`. This also rejects a linkless companion PDF used as a DOCX source fallback.

PDF-input rewriting recreates clickable links around their visible source labels after reflow, including email links, matching the source row so earlier plain text cannot steal a linked label. It stops rather than silently dropping annotations when a label is absent, ambiguous, or cannot be mapped to the rewritten text, or when the input is rotated or uses an unsupported link type. Use the DOCX path for those cases. Internal DOCX bookmarks are outside the external-URI preservation check. A PDF that already has no annotations cannot supply missing target URLs; regenerate it from its DOCX.

Layout details record source/output wrapping; increased wraps are an inspection signal rather than proof of clipping. Some checks are template-specific. A pass does not establish correct facts or compatibility with every ATS parser. Open the PDF to review wrapping, heading placement, contact information, links, and readability.

When a `bullets` or `full` DOCX output fails verification, the pipeline retries once from the original source using the already selected Skills and no bullet/title operations. An accepted retry records `effective_mode: "skills-fallback"`. Skills-only DOCX and PDF inputs do not receive that retry. Conversion failure prevents acceptance; a verifier rejection returns `None` and leaves its report for diagnosis.

DOCX conversion requires LibreOffice. Discovery checks `LIBREOFFICE_PATH`, then `soffice` / `libreoffice` on `PATH`, then the macOS application path. Each conversion uses an isolated profile and temporary output, validates a fresh PDF, and has a 60-second timeout. A stale PDF is not accepted as a successful new conversion.

The bot's treatment of optimizer failure is described in [Architecture](architecture.md#application-flow). Always review the actual attached resume before submission.

If compact bank selections still fail layout or bullet-count checks, the optimizer retries the requested mode while retaining the original bank-target sections. Validated ordinary rewrites and requested title replacements remain active, and the identical rewrite group uses its cache. The report labels this `bullets-source-banks-retry` or `full-source-banks-retry`; it records no bank IDs because those source sections were retained. All PDF verification gates still apply before any Skills fallback.
