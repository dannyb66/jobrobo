# How to ATS-optimize a resume for a job description

Use this procedure when the goal is a truthful, parser-friendly, two-page resume tailored to one role. The optimizer combines job-description terms with the checked-in skills and bullet banks, then runs a format verifier. It is not a guarantee of an ATS score or an interview.

## Prerequisites

- Python environment installed from `requirements.txt`.
- A current source resume in DOCX format, plus a PDF copy when possible.
- A complete job title and job description.
- `OPENAI_API_KEY` for JD keyword extraction in every mode.
- LibreOffice for DOCX-to-PDF conversion; use `LIBREOFFICE_PATH` if automatic discovery fails.
- A working copy and a unique local job ID; generated files use a sibling `temp/` directory.

## Step 1: choose the optimization mode

Use the smallest mode that solves the problem:

```text
skills  -> Skills only
bullets -> Skills + ordinary experience rewrites + matching bank bullets
full    -> bullets + recognized professional-experience title replacement
```

Use `skills` when the document already has strong role-specific bullets. Use `bullets` to update Skills and tailor the experience/project evidence while keeping titles. Choose `full` only after deciding that its replacement of past professional-experience titles is accurate. The optimizer does not rewrite the summary. PDF input always uses Skills-only editing.

## Step 2: preserve the source and configure the run

Make a working copy:

```bash
cp "Current Resume.docx" "resume-working.docx"
```

Set the working path and mode in the resume optimizer tab or in the user-level JSON configuration. Review the current fields in the [reference](resume-optimizer-reference.md), especially `skill_bank_path`, `project_bullet_banks`, `expected_page_count`, and `allow_unverified_bank_terms`.

For a conservative initial review, save settings such as:

```json
{
  "optimization_mode": "skills",
  "role_profile": "auto",
  "allow_unverified_bank_terms": false,
  "expected_page_count": 2
}
```

The repository default is `full` with `allow_unverified_bank_terms: true`. Setting that marker flag to `false` filters dagger-marked Skills-bank suggestions; it does not validate every extracted JD term against your work history. Bullet banks separately default to `allow_unverified: false`.

## Step 3: run the optimizer

Run the focused test suite before changing behavior:

```bash
python -m unittest discover -s tests -p 'test_resume_optimizer*.py' -v
```

Then use the GUI:

```bash
python JobRobo.py
```

Open the resume optimizer tab, enter the job title and description, select the mode, confirm the source path, and run. The bot entry point is not required for resume generation.

## Step 4: inspect the output

Review all of the following:

1. The skills section uses the job’s canonical terms without becoming a keyword list detached from evidence.
2. In `bullets`/`full`, the first matching Trek Health entry receives its configured bank selection.
3. Matching Codex, Sohamhamso, and SponsorSkip entries receive their own bank selections. Matching uses company/project names and paragraph structure, not project order.
4. Metrics, employers, technologies, and scale claims have supporting evidence. An unmarked bank entry is not independent proof that the claim is correct.
5. The document remains two pages and its bullets do not wrap into an unusable third line or overflow the template.
6. Section headings, dates, links, contact information, and visual hierarchy match the default resume.

Do not treat a higher keyword score as permission to accept unsupported claims. Human review is mandatory after model-generated text.

## Step 5: verify the report and PDF

The report records the requested/normalized/effective mode, status, attempts, bank selections, keywords, `pre_optimization` / `post_optimization` coverage, output path, and format verification. Check the accepted attempt: a failed `bullets`/`full` DOCX can be retried as `skills-fallback`, leaving the source bullets and titles intact. Rejected attempt details stay in `attempts`. If no attempt passes, fix the content or layout and rerun.

If the PDF is available, a quick page-count check is:

```bash
python - <<'PY'
from pathlib import Path
from PyPDF2 import PdfReader

path = Path("resume-working_optimized.pdf")
print({"path": str(path), "pages": len(PdfReader(str(path)).pages)})
PY
```

The exact generated filename can differ by job ID. Use the path in the report rather than guessing it.

## Adding or updating a bank

1. Add or update the Markdown file under `config/bullets/`.
2. Keep stable IDs and preserve claim metadata where possible.
3. Add or update its `project_bullet_banks` entry and matching `company` name. `required_sections` are categories inside the bank, not resume headings.
4. Set conservative minimum/maximum counts for the intended section.
5. Run the bank parser and selection tests.
6. Run a real optimizer test against a copy of the resume.
7. Open the DOCX and PDF to verify layout.

See [Developer runbook](developer-runbook.md) for the bank contract and test checklist.

## Troubleshooting

### The result has keywords but weak bullets

Use `bullets` or `full`, confirm the matching bank is enabled, and check that the job description includes enough context for role inference. Add only verified bank entries; do not increase keyword count blindly.

### The result exceeds two pages

Reduce redundant skills, remove low-value bullets, shorten the longest selected bullets, or lower per-section bank limits. Rerun the verifier after every layout change.

### The optimizer cannot find a project section

Check the configured company/project paragraph and the following title/list structure in the source DOCX. Replacement may leave the original entry intact when those do not match. Inspect `project_bullet_bank_selections` to see which banks were actually applied.

### The browser run keeps applying to more jobs

Use one search term, `switch_number = 1`, `run_non_stop = False`, and the submission pause. The quota is per search term; disabling non-stop behavior alone does not make a multi-term run stop after one application. See [Architecture](architecture.md).
