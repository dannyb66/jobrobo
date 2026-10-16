# Changelog

## Unreleased

### Added

- Discover startup companies from public investment and hiring boards, and verify roles against official careers pages and Ashby, Greenhouse, or Lever listings.
- Run discovery, career verification, LinkedIn collection, and selected-job applications independently with cumulative SQLite sets and portable JSON exports.
- Use matching LinkedIn search and application modes from both `python -m job_pipeline` and `runAiBot.py`, with durable provenance, checkpoints, and application history.
- Configure discovery and verification budgets, cumulative company targets, per-source limits, refresh, freshness, established-company priority, and optional bounded public-page rendering independently.

### Changed

- Expand engineering searches with Modal systems, inference, platform, SDK, and storage role families; prioritize established Staff and Principal roles before early teams.
- Keep LinkedIn collection separate from application state, revalidate selected job IDs before applying, and retain the final review pause and verified-resume requirement.
- Report inaccessible sources and incomplete career checks explicitly while preserving previously observed records.

### Fixed

- Cap confirmed submissions across every query and nonstop cycle in one command with `max_applications_per_run = 1` by default, including pipeline application modes; keep capped runs resumable and retain review and verified-resume checks.
- Verify LinkedIn's committed classic-search location and check each job against the canonical location policy before opening an application form, preventing out-of-area hybrid jobs from passing a Bay Area search while retaining eligible remote jobs.

## [0.1.3.0] - 2026-10-14

### Fixed

- Search LinkedIn's current prompt interface with verified location and inline filters, including pages that omit tracking attributes; reuse validated search URLs for subsequent queries.
- Read complete job and employer descriptions from modern results and job pages while preserving application review, eligibility checks, and duplicate protection.

### Added

- Diagnose a configured LinkedIn search with `--diagnose-search`, recording filter outcomes, sampled jobs, and screenshots without starting applications or changing application history.

## [0.1.2.0] - 2026-10-13

### Fixed

- Run Chrome with a dedicated or explicitly configured profile, including expanded macOS paths, while keeping guest-profile behavior in safe mode.

### Changed

- Keep application histories, logs, screenshots, Python caches, and Finder metadata local instead of tracking them in Git. New checkouts create their own runtime histories.

## [0.1.1.0] - 2026-10-13

### Fixed

- Preserve clickable website and email links when rebuilding an optimized resume from PDF input; reject rewrites when existing links cannot be retained.
- Require generated resume PDFs and DOCX companion fallbacks to preserve external link targets and usable click areas before upload, and report missing links for diagnosis.

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
