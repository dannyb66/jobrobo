# Changelog

## [0.1.0.0] - 2026-10-13

### Added

- Tailor resumes with Skills, Bullets, or Full modes using job-description vocabulary and Staff/Principal role guidance.
- Select exact, job-relevant bullets from configurable Trek Health, Codex SelfHosted, Sohamhamso, and SponsorSkip banks.
- Inspect per-job keyword coverage, selected bank entries, generation attempts, API warnings, and format results in JSON reports.
- Read detailed setup, architecture, optimization, maintenance, and Staff/Principal positioning documentation.

### Changed

- Verify page count, text bounds, document/PDF content agreement, section order, margins, and font-size similarity before accepting generated PDFs.
- Retry rejected full or bullet rewrites with Skills-only changes, then explicitly upload a verified source PDF when optimized output is unavailable.
- Preserve user configuration while adding new defaults and serialize configuration updates to avoid lost settings.

### Fixed

- Correct the optimizer dashboard callback and show failures when no verified PDF is produced.
- Defer browser and credential initialization until the relevant action is started.
- Preserve paragraph and run formatting during text replacement, including compressed character spacing.
- Keep project and academic headings out of professional-experience rewriting and avoid duplicate Skills vocabulary.
- Reject stale or invalid conversion output and stop applications when no verified resume can be attached.
- Include Markdown guidance banks in the macOS application resources and resolve them independently of the working directory.
