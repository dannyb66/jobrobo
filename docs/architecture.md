# Architecture and current behavior

JobRobo has two related workflows:

1. a browser automation workflow that discovers and applies to jobs; and
2. a local resume-optimization workflow that turns a job description into a tailored, verified resume artifact.

The workflows share configuration and job metadata, but the optimizer can be run independently. That separation is important: resume generation can be tested without opening a browser or submitting an application.

## System context

```text
                         +----------------------+
                         | config/ + user JSON  |
                         +----------+-----------+
                                    |
                                    v
+----------------+        +--------+---------+        +-------------------+
| runAiBot.py    |-------> | browser modules |------->| LinkedIn in Chrome |
| orchestration  |        | search/apply    |        | upload/questions   |
+-------+--------+        +--------+---------+        +-------------------+
        |                            |
        |                            v
        |                    CSV history, logs,
        |                    screenshots, resume files
        |
        v
+-------+----------------+
| resume_optimizer.py    |<----- job title/description
| parse -> tailor ->     |
| save -> convert -> QA  |
+-----------+------------+
            ^
            |
   skill bank + Trek bank + project banks
```

## Browser startup and profile behavior

`modules/open_chrome.py` owns WebDriver startup. The relevant settings are:

- `safe_mode`: starts a fresh browser profile and is the best diagnostic path when a reused Chrome profile will not start.
- `chrome_profile_path`: points at the local Chrome profile when login persistence is required.
- `stealth_mode`: selects `undetected-chromedriver`; disabling it uses the standard Selenium driver path.
- `chromedriver_path`: controls the driver binary when the configured path is available.

The code warns about having more than ten tabs because an existing Chrome process or a busy profile can cause ChromeDriver to start and immediately exit. Closing all Chrome windows, checking browser/driver compatibility, and trying `safe_mode = True` are the first diagnostic steps. The bot should be treated as a visible, user-supervised browser process.

## Application flow

The normal `runAiBot.py` path is approximately:

1. Load the relevant `config/` modules and initialize browser settings.
2. Open Chrome and navigate to the configured LinkedIn search page.
3. Discover jobs and apply filters such as title, location, company, and experience.
4. For each eligible job, collect title, description, URL, and application metadata.
5. If `use_AI_for_resume` is enabled, call the optimizer and attach its accepted, job-specific PDF once. A rejected/failed optimization can fall back to an independently format-verified source PDF, attached explicitly.
6. Answer configured questions and pause before submission when configured. If optimized and source-PDF attachment both fail, discard the application before Review/Submit.
7. Write application history, logs, screenshots, and errors to the configured local paths.

`switch_number` is the application quota per search term. `run_non_stop` enables repeated search/filter cycles after the initial run. Disabling non-stop looping does not limit the initial run to one application when several search terms are configured. Use one search term, a quota of one, and the submission pause for a supervised first run.

`modules/resume_upload.py` owns the optimized-upload and source-PDF fallback checks. Optimizer rejection, conversion/API errors, missing output, or an upload exception trigger the source fallback. For DOCX input this is the sibling `.pdf`; for PDF input it is the source itself. The fallback must independently pass the configured page-count/layout verifier. A previously attached LinkedIn resume is not accepted as fallback success.

## Resume optimizer flow

```text
run_resume_optimization(...)
  |
  +--> load runtime defaults and normalize mode
  +--> parse DOCX/PDF source
  +--> infer role profile and extract JD keywords
  +--> load skills and bullet banks
  +--> select bank content by JD relevance and exclusion markers
  +--> update Skills in every mode
  +--> rewrite ordinary experience/apply exact bank bullets in bullets/full
  +--> replace professional-experience titles in full
  +--> save DOCX and convert with LibreOffice, or edit PDF Skills only
  +--> verify rendered bounds, headings, page count, and format signals
  +--> retry failed bullets/full DOCX once with Skills only
  +--> write status, attempts, keyword coverage, and verification report
```

The three modes are intentionally explicit:

| Mode | Behavior |
| --- | --- |
| `skills` | Updates the skills section using JD terms and the configured skills bank. |
| `bullets` | Updates Skills, rewrites ordinary professional experience, and inserts exact bank bullets into matching entries. |
| `full` | Runs `bullets` and replaces recognized professional-experience titles with the target title. It does not rewrite the summary. |

The exact implementation is documented in the [optimizer reference](resume-optimizer-reference.md). The [ATS how-to](how-to-ats-optimize.md) describes the operator workflow.

## Configuration precedence

The optimizer merges bundled defaults with user JSON at `~/Library/Application Support/jobrobo/config/resume_optimizer_defaults.json`; saved user values and unknown settings survive. Loading merges in memory; saving serializes read/merge/write and persists atomically. The GUI saves edited form fields so newer bank changes are preserved. For older files without an explicit mode, legacy flags infer `skills`, `bullets`, or `full`. Missing project-bank lists migrate to the four defaults while preserving legacy Trek choices. Explicit lists, including `[]` to disable banks, stay authoritative. A per-call mode argument overrides the saved mode. Malformed JSON or a non-object config raises an error instead of being silently replaced.

The GUI imports the browser bot only when its Run action is used. Opening the dashboard and running the optimizer do not initialize Chrome. API-key retrieval happens when optimization is requested.

The repository’s `config/` directory contains checked-in bank content and code defaults. Personal resume paths, API keys, browser profiles, and generated artifacts should remain local. Never use a generated resume or application log as the source of truth for credentials.

Bank paths use `modules/config_loader.py:resource_path`, resolving relative paths from the repository during development or bundled resources when packaged. `setup.py` includes the skills guide and all four bullet banks in the py2app resource layout. Packaging does not fetch an API key at build time.

## Main data and output surfaces

| Surface | Purpose |
| --- | --- |
| `config/` | Runtime defaults, secrets integration, skill bank, and bullet banks. |
| `modules/ai/resume_optimizer.py` | Parsing, keyword extraction, bank selection, rewrite, output, and verification. |
| `modules/ai/` | LLM helpers and related AI behavior. |
| `modules/open_chrome.py` | Browser profile and driver startup. |
| `runAiBot.py` | Bot orchestration and application loop. |
| `JobRobo.py` | Tkinter dashboard for bot and optimizer configuration. |
| `modules/resume_upload.py` | Accepted optimized-PDF upload and verified source-PDF fallback. |
| `all excels/` | Applied and failed application-history CSVs. |
| `all resumes/temp/` | Job-specific output artifacts and match reports. |
| `logs/` | Diagnostics and failure screenshots. |
| `docs/` | Detailed operating and engineering documentation. |

## Design decisions and trade-offs

### Exact evidence plus model breadth

The bullet banks provide deterministic, role-specific text for high-value sections. Exact selections retain claim wording; marked bullet claims are excluded by default. The Skills guide has a separate policy: its dagger-marked terms are allowed by default and can be filtered with `allow_unverified_bank_terms = false`. Neither bank selection nor the LLM independently validates career history. The operator reviews the actual evidence behind each claim.

### DOCX source and PDF artifact

DOCX is the editable source because the writer reuses its paragraphs, list styles, and run font/character-spacing properties. Skills prioritize JD guidance and deduplicate recognized full-phrase/acronym aliases within the original entry-count upper bound. PDF is the inspection and upload artifact when conversion and verification succeed. LibreOffice discovery checks `LIBREOFFICE_PATH`, then executable names on `PATH`, then the macOS application path; conversions use isolated profiles and a 60-second timeout. DOCX/PDF consistency requires at least 95% normalized token coverage and every DOCX heading in rendered order. The format verifier is separate from keyword scoring: output with the wrong page count remains rejected even if keyword coverage improves.

### Local browser session

Using a local Chrome profile preserves the user’s login state, but it also makes process/profile conflicts possible. The system keeps browser startup configuration explicit so safe mode can isolate a driver problem from a profile problem.

## Current limitations

- LinkedIn page structure and selectors can change without notice.
- Browser automation can reach a submit action; user supervision remains required.
- PDF parsing is less expressive than DOCX parsing for layout-aware edits.
- LLM output is not a truth validator. The verifier checks rendered/document format signals, not career history, title equivalence, or all visual defects.
- ATS systems differ, so the match report is diagnostic rather than a universal score.
