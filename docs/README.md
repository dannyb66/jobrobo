# JobRobo documentation

This folder is the detailed technical and operating documentation for JobRobo. The root [README](../README.md) is the shortest path to installation and a first run; these pages explain the architecture, resume optimizer, ATS strategy, and maintenance workflow in more depth.

## Documentation map

| Page | Type | Use it when |
| --- | --- | --- |
| [Getting started](getting-started.md) | Tutorial | You are setting up the repository or running the first safe test. |
| [Architecture](architecture.md) | Explanation | You need to understand the browser bot, optimizer, files, and control flow. |
| [Resume optimizer reference](resume-optimizer-reference.md) | Reference | You need exact modes, config fields, bank behavior, or report fields. |
| [How to ATS-optimize a resume](how-to-ats-optimize.md) | How-to | You want to tailor a two-page resume to a job description. |
| [Staff/principal positioning](staff-principal-positioning.md) | Explanation + how-to | You are positioning the resume for staff, principal, or senior AI engineering roles. |
| [AI market and ATS guide](ai-market-and-ats-2026.md) | Explanation | You want the current market context and evidence-based keyword guidance. |
| [Developer runbook](developer-runbook.md) | How-to + reference | You are changing code, adding a bullet bank, or diagnosing a local run. |

## How the docs are maintained

- Code behavior is the source of truth for implementation details. When behavior changes, update the reference and runbook pages in the same change.
- Market claims are dated and linked to the original source. The 2026 market page records the last verification date so it can be refreshed without confusing trends with permanent facts.
- Resume examples must reflect verified experience from the supplied resume and bullet banks. Documentation should never encourage invented metrics, employers, technologies, or outcomes.
- ATS guidance describes parser-friendly practices and matching strategy; it does not promise a score or an interview.

## Recommended reading order

1. Follow [Getting started](getting-started.md) once.
2. Read [Architecture](architecture.md) before changing the bot or optimizer.
3. Use the [Resume optimizer reference](resume-optimizer-reference.md) for configuration.
4. Use [How to ATS-optimize a resume](how-to-ats-optimize.md) for each tailored resume.
5. Read [Staff/principal positioning](staff-principal-positioning.md) and the [AI market and ATS guide](ai-market-and-ats-2026.md) when refining role strategy.
