# Developer and operator runbook

This runbook covers routine changes to JobRobo, resume-bank maintenance, and local diagnostics. Do not commit personal resumes, browser profiles, API keys, or generated application data.

## Repository setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

The dependency file is UTF-16 encoded, but pip can parse it. If a package install fails, capture the package and Python version before changing dependency pins.

The current dependency list includes macOS packages. DOCX conversion also requires a separate LibreOffice installation. The converter checks `LIBREOFFICE_PATH`, then `soffice` / `libreoffice` on `PATH`, then the macOS application path. It uses isolated temporary profiles/output and rejects stale or invalid PDFs; conversions time out after 60 seconds.

## Before changing optimizer behavior

Read:

1. `modules/ai/resume_optimizer.py`;
2. `config/resume_optimizer_defaults.json` and the user-level merged defaults;
3. the relevant bank under `config/bullets/`;
4. [Architecture](architecture.md) and the [optimizer reference](resume-optimizer-reference.md);
5. the focused tests in `tests/test_resume_optimizer.py`.

Preserve existing user changes in application CSVs, resume artifacts, logs, screenshots, and local configuration. Use a new working copy for generated documents. Application histories, logs/screenshots, Python caches, Finder metadata, local backup folders, and virtual environments are ignored by Git. Back up application histories and logs before updating a checkout that still tracks them; restore the local data afterward. New checkouts create their own histories as applications are recorded. Personal config and resume changes may still appear in `git status`; keep them out of shared commits.

## Test loop

Run the narrowest useful check first:

```bash
python -m unittest discover -s tests -p 'test_resume_optimizer*.py' -v
```

Then run all tests:

```bash
python -m unittest discover -s tests -v
```

For documentation and Markdown-only changes:

```bash
git diff --check
```

Also verify every new relative link under `docs/` resolves to a file in the repository. Open generated DOCX/PDF artifacts manually when layout behavior changed; unit tests cannot detect every font, conversion, or line-wrap issue.

Tests with controlled model responses establish parser, writer, verification, and fallback behavior without a live model request. A real LibreOffice smoke run establishes conversion behavior in the tested environment. Neither alone establishes successful live API generation; record whether a smoke run used controlled responses or actual API calls.

## Adding a bullet bank

Use this sequence:

1. Copy the source Markdown into `config/bullets/` with a stable filename.
2. Keep a stable ID for each bullet and preserve the original claim text.
3. Follow a checked-in bank's Markdown table format. Preserve category letters, metric IDs, lead verbs, and `†` / `‡` markers where the parser supports them.
4. Add a matching `project_bullet_banks` entry with `company`, bank path, minimum/maximum count targets, and `required_sections` category letters from the bank. Replacement matches names and list structure rather than project order.
5. Set `allow_unverified` conservatively; default to false.
6. Add parser/selector assertions for the new bank.
7. Run the optimizer on a copy of the current resume.
8. Confirm section placement, selected count, claim fidelity, two-page layout, and verifier output.

For the current project mapping, see the [reference table](resume-optimizer-reference.md). Do not use a project bank to fill an unrelated section merely because its keywords score well.

## Changing keyword or mode behavior

When changing `skills`, `bullets`, or `full`:

- keep mode behavior explicit and mutually understandable;
- test keyword/model failures; all modes require a key for JD extraction, and ordinary experience rewriting can fail independently;
- check that a source document is never overwritten;
- preserve the selected bank IDs per attempt; accepted Skills fallback must not report rejected bullets as present;
- test invalid configuration and missing bank paths;
- verify that format failure remains visible even when keyword matching improves.

When changing role inference, add examples for at least the platform, agents/applied AI, evaluation/safety, and backend/full-stack lanes. Avoid hard-coding one employer’s vocabulary as a universal role profile.

## Chrome and ChromeDriver diagnostics

JobRobo defaults to the dedicated `~/.jobrobo/chrome-profile` data directory; an empty `chrome_profile_path` selects that same directory. Set an explicit dedicated path to reuse a JobRobo login, such as `~/Library/Application Support/JobRobo/ChromeProfile` on macOS. Chrome 136 and newer block remote debugging of the everyday default data directory, so use a separate automation profile. See [Chrome’s debugging-profile guidance](https://developer.chrome.com/blog/remote-debugging-port).

When `runAiBot.py` reports `session not created: Chrome instance exited`:

1. Close every Chrome window and stop any leftover Chrome/ChromeDriver process using normal OS tools.
2. Confirm browser and driver major versions are compatible.
3. Confirm the configured profile path exists and is not locked.
4. Try `safe_mode = True` to isolate profile reuse from driver startup.
5. If safe mode works, inspect the profile path and login strategy before restoring it.
6. If stealth startup fails, test the standard Selenium path or reinstall the pinned compatible package in the virtual environment.
7. Re-run with a small, supervised search and keep submission paused.

Do not debug a driver failure by launching repeated live application runs. Browser selectors and LinkedIn behavior can change independently of the local code.

## Output verification

For every meaningful optimizer change, inspect:

- generated DOCX;
- generated PDF when conversion succeeds;
- optimization report;
- actual page count;
- longest bullets and section boundaries;
- bank IDs and project-section placement;
- pre/post match signals;
- warnings and failure fields.

LibreOffice may be unavailable or unstable in a restricted environment. Treat conversion failure as a reportable condition and inspect the DOCX directly; do not silently label an unverified PDF as valid.

Check `status`, `error`, `api_warnings`, `attempts`, `effective_mode`, and `format_verification` in the match report. Nonfatal model warnings can coexist with accepted format output. `pre_optimization` and `post_optimization` describe local weighted keyword coverage. A `skills-fallback` output has no applied bank selections at the top level; rejected selections remain in its attempt history. For DOCX output, require `docx_pdf_content_consistent`, at least 95% `details.docx_pdf_token_coverage`, all rendered headings present, and `rendered_section_order_preserved`. Static checks do not establish full visual equivalence or the truth of claims.

When changing packaging, confirm `setup.py` includes the skills guide and four bullet banks at their configured relative resource paths. Bank loading must work from a different working directory and through the `resource_path` bundle layout. API-key retrieval belongs to optimizer execution rather than setup/build execution.

For the upload path, cover optimizer rejection, missing output, API/conversion/upload exceptions, a valid source PDF, and failure of both attachments. The source PDF is independently verified and explicitly uploaded. When neither upload succeeds, the application is discarded before Review/Submit. Once a resume is attached, later Next steps must not trigger repeated optimization.

## Security and privacy

- Keep secrets in local environment/config integration; never add them to docs or examples.
- Redact API keys, cookies, personal contact data, and browser profile paths from issue reports.
- Treat application logs and screenshots as personal data.
- Do not upload a generated resume to a third-party checker without reviewing its privacy terms.
- Keep the browser visible and supervised when the flow can submit an application.
