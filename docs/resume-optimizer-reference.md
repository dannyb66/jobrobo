# Resume optimizer reference

This page describes the implemented optimizer contract. See [How to ATS-optimize a resume](how-to-ats-optimize.md) for a walkthrough and [Architecture](architecture.md) for the system flow. The mode tables and bank-selection behavior below describe the ordinary path. With `rewrite_all_bullets=true`, use the [complete bullet rewrite contract](resume-all-bullets.md); see [PDF formatting and verified reuse](resume-formatting.md) for fullness targets, PDF title metadata and upload-cache behavior.

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
)
```

The function returns a PDF path when generation and verification succeed, or `None` on a handled failure. It requires `OPENAI_API_KEY` in every mode because keyword extraction uses the OpenAI API. Model credentials, network errors, and an unavailable converter can prevent a complete run.

## Optimization modes

| Mode | DOCX changes | Typical use |
| --- | --- | --- |
| `skills` | Updates Skills only. | Existing bullets and titles already fit the role. |
| `bullets` | Updates Skills, rewrites ordinary professional-experience bullets, and replaces matching company/project bullets from configured banks. | Tailor terminology and evidence while preserving titles. |
| `full` | Runs `bullets` and replaces recognized dated experience titles with the requested job title. | Title replacement has been deliberately reviewed. |

`full` does not rewrite the summary or validate whether the requested title accurately describes each previous job. Review title changes before using the result. Skills selection prioritizes JD guidance, caps the result at both `max_skills` and the original entry count, and deduplicates recognized full-phrase/acronym pairs. For example, `Model Context Protocol (MCP)` and `MCP` become one entry, preferring the expanded display. Parenthetical context such as `Infrastructure (AWS)` remains distinct from `AWS`. The result can contain fewer entries after deduplication; longer replacement terms can still change wrapping.

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
| `replace_job_title` / `rewrite_bullets` | Legacy flags used to infer a mode when migrating a config without `optimization_mode`: both true gives `full`, only rewriting gives `bullets`, otherwise `skills`. An explicit mode controls the writer. |
| `skill_bank_path` | `config/skills/Skills_Keyword_Bank_Staff_Principal_2026-10.md`. |
| `bullet_bank_path` / `bullet_bank_company` | Legacy single-bank settings, normally Trek Health. |
| `max_bank_bullets` / `allow_unverified_bullet_terms` | Legacy bullet count and marker policy; defaults are `7` and `false`. |
| `project_bullet_banks` | Company/project bank specifications used for exact bullet replacement. |
| `role_profile` | `auto`, or an explicit profile name from the skills guide. |
| `allow_unverified_bank_terms` | `true`; allows dagger-marked skills-bank vocabulary into keyword guidance. `false` filters those bank suggestions. |
| `max_skills` | `65`; ordinary-path upper limit on Skills entries, also bounded by the original entry count. With all-bullets Skills expansion enabled, it is the priority-pool size; see the complete bullet rewrite contract. |
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

Keyword responses must contain a list of strings. Experience responses must preserve the source entry identities, entry count, and bullet count; each bullet must be nonempty and stay within its source bullet's length limit. Invalid responses preserve the source experience or continue without model-extracted keywords, recording `api_warnings`. These structural checks do not establish factual accuracy.

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
format_verification
output_path
```

`pre_optimization` and `post_optimization` each contain `score`, `matched`, `missing`, and `total`. The score is weighted keyword coverage: skills-bank Core terms count twice and other terms once; normalized phrases and parenthetical/acronym variants are matched against extracted text. This diagnostic is not an ATS vendor score or a hiring prediction.

`requested_mode` records the original input and `normalized_mode` records the supported mode used after validation. `unverified_terms` lists guided keywords carrying the skills bank's dagger marker. It is not a complete list of unsupported claims. `format_verification` contains `passed`, `checks`, and `warnings`, with layout details; inspect it even if the keyword score rises.

`attempts` retains each DOCX attempt's mode, output paths, conversion result, verification, and selected bank IDs. PDF editing records its mode, path, and verification without a DOCX conversion step. After a successful Skills-only fallback, top-level bank selections are empty because those bullets are absent from the accepted artifact; the rejected attempt retains its selections in `attempts`.

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
