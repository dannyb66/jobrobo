# Resume one-line and blank-output verification

Task 42. Verified 2 November 2026 against the current optimizer and rendered
the corrected resume. No live provider request, browser action or application
submission was performed.

## Answer

Before this task, **no** for reliable end-to-end coverage. The intended
one-line machinery existed and passed 58 focused tests, but three bypasses
remained:

1. A page containing only a period or page number counted as nonblank.
2. Bullet wrapping was only a warning in the ordinary optimizer path.
3. Empty bullet paragraphs were not counted at all.

The strict all-bullets path already rejected any non-single-line rendered
bullet. The ordinary path now does too.

## Defects reproduced first

New tests in `tests/test_resume_blank_and_empty_bullets.py` failed before the
fix:

- a whitespace-only provider bullet was retained, but its diagnostic was vague;
- a page number-only page passed `all_pages_have_text`;
- two trailing empty DOCX paragraphs were invisible;
- a rewritten one-line bullet forced onto two rendered lines passed formatting.

The full-pipeline tests also confirmed that the rejection retries and ultimately
returns no accepted resume, rather than silently publishing the overflowed file.

## Fixes

In `modules/ai/resume_optimizer.py`:

- A rendered page now needs at least 20 alphanumeric characters to count as
  meaningful. Page numbers, markers and punctuation no longer hide a blank page.
- `no_empty_bullets` counts empty `List Paragraph` items and is required.
- `bullet_lines` requires every rendered bullet to occupy exactly one line and is
  now required in the generic verifier, not just the strict path.
- The layout report records `empty_bullets`, `empty_trailing_paragraphs` and the
  line count per bullet.

The response validator already rejected whitespace-only or missing replacement
text and retained the exact source bullet. Its diagnostics now say “empty”
explicitly.

## Verification

- Corrected resume
  `output/resume-corrections/20261102-role700/Danny_Basavaraju_AI_Led_Engineering_corrected.pdf`:
  2 pages, zero empty bullets, zero trailing empty paragraphs, zero wraps, all
  pages meaningful, no clipping.
- New focused suite: **9 passed**.
- Related fit, density, pipeline and preserved-section suite: **97 passed** in
  130.30 seconds, zero failures.

The corrected resume still fails the separate source-relative density contract
because its academic bullets and some widths were shortened. That is a
formatting-style difference, not a wrap or blank-output failure; review it
before submission.

## Limits

- This verifies geometry and empty content, not semantic truth or ATS ranking.
- A source bullet that already wraps must be made single-line by the rewrite or
  rejected; the gate no longer accepts a new wrap.
- LibreOffice rendering is exercised locally. Word/Google Docs rendering remains
  a separate visual check.
