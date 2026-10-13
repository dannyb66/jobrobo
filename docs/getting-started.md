# Getting started

This tutorial takes a new checkout through a local resume-optimizer run before starting the application bot.

## 1. Install and inspect

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python --version
git status --short
python -m unittest discover -s tests -v
```

The current dependency list includes macOS packages (`pyobjc` and `py2app`). Other platforms may need a separate dependency setup. DOCX conversion requires LibreOffice, installed separately from Python dependencies. Set `LIBREOFFICE_PATH` to its executable if discovery through `PATH` or the macOS application path does not find it.

Chrome is required for the browser bot; an optimizer-only run does not need Chrome or ChromeDriver. See the root [README](../README.md#troubleshooting) when setting up the browser later.

## 2. Configure a local resume run

Use a copy of the source resume, with a clearly named local job ID. The source must have a recognizable `SKILLS` heading or inline `Skills:` section.

```bash
cp "<source-resume>.docx" "<working-resume>.docx"
```

All optimizer modes require `OPENAI_API_KEY` for JD keyword extraction. Use your existing local key configuration or set that environment variable in the active session. Keep credentials out of Git.

The user configuration is stored at:

```text
~/Library/Application Support/jobrobo/config/resume_optimizer_defaults.json
```

The GUI loads repository defaults into missing fields while preserving existing user values. Saving persists the merged configuration. Use the [reference](resume-optimizer-reference.md) to review the mode, bank policies, source path, and expected page count.

## 3. Generate a resume

Start the desktop dashboard:

```bash
python JobRobo.py
```

The **Resume Optimizer** tab accepts a job title, job description, source path, and mode. Opening the dashboard or using this tab does not start the bot. Begin with `skills` to inspect keyword changes with fewer document edits:

| Mode | DOCX behavior |
| --- | --- |
| `skills` | Updates Skills only. |
| `bullets` | Updates Skills and professional-experience/project bullets. |
| `full` | Runs `bullets` and replaces recognized professional-experience titles with the target title. |

`full` does not rewrite the summary. PDF input always uses Skills-only editing, even when another mode was requested.

## 4. Inspect the result

Open the returned PDF, generated DOCX when available, and `.match_report.json`. Outputs go to `temp/` next to the source folder; the function's returned path identifies the accepted PDF.

Check the report's `effective_mode`, `status`, and `format_verification.passed`. A DOCX layout failure may result in a Skills-only fallback, which leaves original bullets and titles intact. Review selected skills and every changed claim, title, date, heading, link, and contact detail. The configured page count defaults to two. A format pass does not establish truthful claims or identical visual layout.

If the run fails, inspect the report and console output before retrying. Do not reuse a PDF from an earlier run as evidence that the current run succeeded.

## 5. Start the browser only after local review

Configure `config/personals.py`, `config/questions.py`, `config/search.py`, and `config/settings.py`. Begin with one search term, `switch_number = 1`, `run_non_stop = False`, `run_in_background = False`, and `pause_before_submit = True`. `switch_number` is a quota per search term, so multiple terms can lead to multiple applications even with non-stop looping disabled.

```bash
python runAiBot.py
```

You can also start it from the dashboard's **Run LinkedIn Bot** tab. Review the job, configured answers, and actual attached resume at the submission pause. Record the source, job context, mode, accepted output path, report, and any manual edits. See the [developer runbook](developer-runbook.md) for repeatable checks when changing code.
