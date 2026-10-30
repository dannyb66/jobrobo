# Changelog

## [0.1.7.0] - 2026-10-30

### Fixed

- Continue LinkedIn employer applications after a rejected CAPTCHA using one bounded solve cycle; preserve uncertain attempts for outcome checks.
- Save employer submission checkpoints before Submit and import later confirmations on resume without replaying an application or counting it twice.
- Retain failed employer tabs and diagnostics, keep manual blockers out of automatic retries, and clear stale Easy Apply filters for employer-only searches.
- Match employer titles containing HTML entities and preserve browser ownership when handing off direct applications.

## [0.1.6.0] - 2026-10-28

### Fixed

- Use the candidate name as the optimized PDF title and prefer complete bullet rewrites that fill the original line without shrinking fonts or changing margins.
- Keep safe fitting candidates when a bounded expansion retry fails; preserve Academic Distinctions and report rendered line fullness.
- Cache verified per-job resumes against the source, exact job description, configuration, prompt and optimizer dependencies, avoiding duplicate optimization calls on retries.

### Added

- Shared all-bullets optimization, company context, configurable Skills packing, progress reports and standalone review tooling for the existing LinkedIn upload path.
- Configurable source-bullet fallback and independent layout, coverage and job/config binding verification before attachment.

## [0.1.5.0] - 2026-10-18

### Fixed

- Recognize LinkedIn's job-specific Application status panel after Easy Apply submission, so successful applications are confirmed and counted toward the run limit.
- Compare submitted state with the exact job's pre-submit baseline, retaining protection against stale, hidden and unrelated receipts.
- Dismiss optional success receipts without requiring the older Done button; dismissal errors no longer turn confirmed applications into failures.

## [0.1.4.0] - 2026-10-15

### Added

- Run configured LinkedIn search and application processing with `--configured-search-and-apply --fresh`, without discovery-stage input artifacts; retain existing submission history and duplicate protection.
- Document the direct configured workflow separately from the staged job pipeline.

### Fixed

- Respect Easy Apply-only policy when result pages omit pagination, and recognize modern company Apply anchors scoped to the current job.
- Re-detect modern results after the landing prompt hydrates, so native location and filter verification use the correct adapter.
- Replace ordinary preferred first-name fields exactly after blur, preventing controlled-input concatenation while preserving legal-name and surname fields.

## Unreleased

### Direct job-URL applications

- Prepare or submit TXT URL lists and saved verified-role JSON with the shared resume optimizer configuration and profile answers.
- Review each prepared application in its employer tab by default; opt into Kernel automatic submission with independent run IDs, explicit resume, durable progress and retry exports.
- Preserve valid resume autofill, verify asynchronous location choices and exact phone digits, and support scoped native/server-action Continue steps and uploads that automatically advance the form.
- Permit one delayed CAPTCHA submission continuation for the validated form while keeping answers and form target bound to the original activation.
- Retain email verification without replaying Submit, distinguish a queued application service from employer confirmation, and publish protected submission outcomes to remaining-role views.

### LinkedIn application fixes

- Fill classic and native Easy Apply pages through Next, Review and Submit readiness, with verified attachment paths and explicit submission receipts.
- Test forms without submitting using `--prepare-only`; retain prepared and failed job URLs, descriptions and retry history.
- Draft and cache cover letters and descriptive answers from the selected resume and job description. Keep semantic rewrite checks disabled; handle references from reusable configuration with synthetic data restricted to preparation tests.
- Wait for modern descriptions to hydrate, reattach resumes for drafting on later jobs, and stop if a failed form cannot be discarded cleanly.

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
