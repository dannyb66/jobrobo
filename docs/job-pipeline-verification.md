# Public adapter smoke — October 13, 2026 (Pacific)

From the repository root, repeat the bounded public reads with:

```sh
python3 scripts/smoke_job_pipeline.py
```

The script discovers up to three companies independently from Greylock, Sequoia, a16z, YC, HN, HiringCafe, Wellfound, and Crunchbase, then verifies Modal, Baseten, and Braintrust against the current `config/search.py`. It uses public GET requests and official ATS job-board feeds. It never imports the Selenium runner, logs into a service, submits applications, or touches application/resume history.

`data/job_pipeline/smoke/adapter-summary.json` records the actual observation timestamp, per-source errors, and role counts. `*-discovery.json` and `*-careers.json` retain the full raw adapter result, including source URLs, cursors, explicit unknown facts, descriptions, verification times, eligibility exclusions, and priority tiers. These are local smoke artifacts; the CLI's versioned stage exports additionally carry run IDs and named-set metadata.

The October 13 observation yielded three companies each from Greylock, Sequoia, a16z, YC, and HN. Wellfound yielded three public names but each profile returned HTTP403, so their websites remained unknown. HiringCafe and Crunchbase returned HTTP403 before usable records. Restricted sources produced explicit errors without invoking a renderer or bypassing access controls. Discovery cursors remained incomplete because the smoke limit leaves more public companies to process.

The official careers reads returned 41 Modal, 105 Baseten, and 27 Braintrust published roles. With the current Bay Area, remote/hybrid, full-time, past-month settings, 1 Modal and 4 Baseten roles were eligible; no Braintrust role met every required filter. These counts can change on subsequent reads. Headcount and funding were left unknown for these three smoke inputs, so no established-company priority was fabricated.

Ashby board names came from links published on employer careers pages, including Modal's public meta-refresh and the public SSR data on Baseten/Braintrust pages. The adapter requests full descriptions through the [Ashby public job-posting API](https://developers.ashbyhq.com/docs/public-job-posting-api), [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html), and [Lever Postings API](https://github.com/lever/postings-api). An inaccessible or malformed board remains unknown; only a complete empty public board or explicit employer-wide no-openings statement can establish that the company is not hiring.

The independently executed CLI stages imported three company records and exported 173 verified roles. Public discovery through the standalone CLI returned 15 company records for Greylock, Sequoia, a16z, YC, and HN. Live LinkedIn collection did not complete: the standalone attempt lost its browser session during login, and the native attempt was stopped at manual authentication. Automated tests verify command parity, collection boundaries, selected IDs, browser recreation, and resume; neither live attempt submitted an application.

Source coverage is explicit: YC public jobs are a rotating sample, with snapshot cursors that preserve a batch across repeated runs. Greylock public HTML exposes part of its declared catalog, and Sequoia public HTML exposes a spotlight subset. These sources report partial coverage until a permitted full directory render or export establishes completeness; exhausting the sampled rows is not treated as complete discovery.
