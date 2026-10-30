# Work programme — discovery validation and company-page applications

Updated: 2026-10-14. Branch: `feat/external-company-apply`, isolated from `origin/main` at `9103fd584864baf7114cffc8bc14e6a43884e220`.

Global tracker belongs to the coordinating agent. This report covers tasks 1 and 2 and retains their exact prompt text. The request to track progress was: “track entire list as md too along with the exact prompt added against each bullet, and as progress is updated”.

## Task 1 — discover and verify before search/apply

Exact prompt: “1. run discover n verify steps n validate the outputs before running search n apply”

Status: **DONE — validation reviewed; search and application stages remain held**.

A real standalone CLI discovery run used an isolated SQLite database and JSON exports outside the repository. Budget: three companies per configured source, cumulative maximum 18; public rendering disabled. It discovered 15 company records from a16z, Greylock, Sequoia, YC and HN. Greylock, Sequoia and YC explicitly reported partial public coverage; HiringCafe reported restricted access. The CLI correctly returned exit code 1 while retaining the partial export.

Official careers verification checked up to 12 discovered companies and exported 33 open roles, with zero eligible under unchanged canonical filters. The partial result records nine errors: pagination limits for Databricks, Abnormal AI and NVIDIA; pages requiring rendering for Anduril, 7AI, Polymath Robotics, 0x Labs and Airbnb; and restricted access for OpenAI. Exclusion counts overlap: outside role families 23, unknown posted date 10, excluded workplace type 18, old posted date 17, excluded location 3. No date or location gate was weakened.

A separately labelled manual official-source control set verified Modal, Baseten and Braintrust after confirming their employer careers URLs with successful public GET requests. It returned 174 roles: Modal 42, Baseten 105 and Braintrust 27. Five were eligible, four at Baseten and one at Modal. This control set is distinct from VC/public-feed discovery and does not inflate its company count.

The read-only validator passed portable schemas, unique identities, source/parent provenance, observation times and seven-day freshness, recomputed canonical eligibility, persisted run/set/error parity and absence of LinkedIn/application state. Official verification retains `unverified_preferences` for LinkedIn-only filters; it does not establish those UI preferences. The coordinating agent reviewed both validation exports and the eligible descriptions. Baseten Inference Platform was identified as a standalone resume baseline, not an application submission target. No search, application or submission was started.
Artifacts: `/Users/deepakbasavaraju/Library/Application Support/jobrobo/verification/20261014-work-programme/external-task12-233726/`.

## Task 2 — company-page application support

Exact prompt: “2. currently on easy apply is handled, add support to handle apply on company page too.”

Status: **DONE WITH LIVE-TEST LIMITS — implemented and tested; no live submission**.

The existing external branch previously only opened an employer link and recorded a pending collection. It now supports the basic hosted Greenhouse, Lever and Ashby contracts observed through read-only DOM inspection, behind `external_apply_enabled = False` by default. Known configured fields and an independently verified new PDF attachment are prepared; custom questions remain manual. Exact approved ATS posting identity, visible review, required-question completeness, an unchanged PDF and a durable locked claim precede Submit. Confirmation must retain the same employer/job identity; generic shared-domain thank-you pages remain uncertain.

Confirmed applications retain the existing global submission cap and dated history. Pending handoffs do not count as submissions. A separate ATS ledger protects the posting across alternate LinkedIn IDs, and a unique attempt ID makes the pre-submit claim atomic. The integration preserves source provenance and external outcome metadata. Unsupported/custom/authentication/access-challenge flows remain explicit handoffs. No live applicant information was filled, resume uploaded or application submitted. See [company-page application guide](external-apply.md).

Validation includes hosted field/PDF/review failures, confirmed versus uncertain outcomes, shared-domain confirmation rejection, stale concurrent claim rejection before a second click, duplicate protection, runner metadata/history, global cap and read-only artifact admission tests. Full-suite and patch evidence are recorded in the external verification directory. The coordinating agent's independent review identified and verified the need for atomic ownership and posting-scoped confirmation; both have regression coverage.
Primary references checked: [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html), [Lever Postings API](https://github.com/lever/postings-api), [Ashby public job-posting API](https://developers.ashbyhq.com/docs/public-job-posting-api). Public discovery APIs do not establish a universal browser form contract; live form inspection is recorded separately.
