# Resume technology/date audit — AI Led Engineering (Role 700)

Audit date: 2 November 2026. Read-only review of the submitted PDF, base
resume, prepared JD and optimizer code. No file was regenerated, no runtime
configuration was changed and no employer action was taken.

## Inputs

- Submitted resume: `/Users/deepakbasavaraju/Downloads/resume-4483849419-20261030T001712-d157cd63f0.pdf`
  — 2 pages, 162,733 bytes, SHA-256
  `b8bc55b0c6275e63f77a84ee03b47ea6cdbf75b36a08e871f7f7c242e8c4393e`.
- Base resume: `all resumes/default/resume.docx`.
- Role 700 brief: `~/Downloads/Four_AI_Roles_Job_Descriptions_671_702_700_701_703_27.10.2026(P).docx`.
- Public posting: `https://www.linkedin.com/jobs/view/4483849419/`.
- Role data: `logs/search_runs/f327d2ff-895c-4be4-8291-aaffca1b1379.json`.

The posting recovered from the URL is the **701** enterprise/platform variant
(“AI Led Engineering – Enterprise AI, Cloud and Platform Transformation”), not
the 700 prompt/agent variant. The downloaded resume filename carries the
LinkedIn job ID, not a Role 700 ID. Role IDs are recruiter references and do
not appear in the PDF.

## Verdict

The technology pairings are real date errors, not just wording. Fixing only
the prompt would leave the same defect reachable.

| Resume claim | Role period | Technology availability | Finding |
| --- | --- | --- | --- |
| “Used Kiro to govern secure retail engagement cloud platforms” — Chill Panda | Jan 2022 – May 2023 | Kiro preview 14 Jul 2025; GA 17 Nov 2025 | About two years too early |
| “Connected Bedrock and SageMaker to MCP-enabled AI agents” — Quantgro | May 2023 – Jan 2024 | MCP open-sourced 25 Nov 2024; Bedrock GA 28 Sep 2023 | MCP is about 10 months too early; Bedrock is possible only from late Sep 2023 |
| “Engineered Prometheus and OpenTelemetry pipelines” — Rivigo | Jan 2016 – Jan 2018 | OpenTelemetry formed May 2019; first SDK releases Oct–Nov 2019 | OpenTelemetry is about two years too early; Prometheus is possible but not proved by the base resume |
| “Instrumented Ariceum’s platform with OpenTelemetry and Prometheus” — Ariceum | Jan–May 2022 | Prometheus predates the period; OpenTelemetry does not | OpenTelemetry is about three years too early; Prometheus is possible but not proved by the base resume |
| “Instrumented GenAI sales assistants with OpenTelemetry” — Sybill | Jan 2024 – Jun 2025 | Available, depending on month | Plausible but unproven by the base resume |
| Kiro under Codex Self-Hosted | Sep 2026 – present | Available | Plausible, but unproven by the base resume |

Primary release evidence:

- Kiro preview: [Introducing Kiro, 14 July 2025](https://kiro.dev/blog/introducing-kiro/).
  General availability: [17 November 2025](https://kiro.dev/blog/general-availability/).
- MCP: [Anthropic announcement, 25 November 2024](https://www.anthropic.com/news/model-context-protocol).
- Bedrock: [AWS general availability, 28 September 2023](https://aws.amazon.com/about-aws/whats-new/2023/09/amazon-bedrock-generally-available/).
- OpenTelemetry: [CNCF/OpenCensus merger, May 2019](https://www.cncf.io/blog/2021/08/26/opentelemetry-becomes-a-cncf-incubating-project/).

## Dates that should not be changed without candidate confirmation

- **Chill Panda Jan 2022 – May 2023 is internally credible.** The base resume
  describes OpenAI GPT/NLP personalization, multi-tenant SaaS, React/Next.js and
  a three-month prototype. OpenAI’s API was available from 2020. Keep the dates;
  replace the Kiro claim with the actual tools and evidence.
- **Rivigo Jan 2016 – Jan 2018 is an ordinary employment range.** OpenTelemetry
  had not launched. Prometheus and OpenTracing did exist, but the base resume
  proves neither. Keep the dates; use the original dashboard/tracking evidence
  and add only tools the candidate actually used.
- **Quantgro May 2023 – Jan 2024** remains candidate-supplied. A public company
  page says “Founded 2024”, and a company-registry record says the LLP was
  incorporated on 5 October 2023. Neither proves the candidate’s start date, so
  do not silently move it. MCP specifically must move to Sybill or later unless
  the candidate confirms a post-November-2024 MCP project at Quantgro.

## What the optimizer did wrong

1. **No availability model.** The rewrite payload carries company context and
   `historical_title_dates`, but neither is checked against a technology’s
   first-release date.
2. **Same-role vocabulary counts as per-bullet proof.**
   `validate_response()` builds `technology_context` from the whole experience
   group, so one supported mention allows the term in every bullet of that job.
   Quantgro’s skill list mentioned MCP, and Sybill’s skill list mentioned
   OpenTelemetry; the rewrite then converted both into “implemented” claims.
3. **The term bank cannot catch Kiro or OpenTelemetry.** `Kiro` is absent from
   `config/skills/Skills_Keyword_Bank_Staff_Principal_2026-10.md`. The only
   OpenTelemetry row is `OpenTelemetry (OTel) for LLM Tracing`, which does not
   exact-match the string “OpenTelemetry”. `source_claim_issue()` therefore
   returns `None` for the Kiro and Rivigo OpenTelemetry bullets in a direct
   reproduction.
4. **No technology/project identity.** “Used Kiro to govern…” and “Instrumented
   … with OpenTelemetry” are tool-participation claims. A Skills-section mention
   is weaker evidence than a project bullet and should render differently.
5. **The earlier resume was cleaner.** The prior submitted variant in
   `task2-live/upload-independent-format-verification.json` has no anachronistic
   tool claims in Chill Panda, Quantgro or Rivigo. This is a regression from
   aggressive tailoring, not a long-standing baseline.

The original generation directory is not retained, so the exact prompt payload,
provider response and selected candidates cannot be replayed. The PDF,
validator behavior and source documents are sufficient to establish the defect;
they are not sufficient to quote the original model response.

## Other quality problems visible in the submitted PDF

- All eight roles use the same title, **“AI Led Engineering”**. This deletes job
  titles (Product Manager, Senior Software Engineer, CPTO) and the progression
  from engineer to architect. The JD asks for evidence of senior technical
  leadership; flattening titles weakens it.
- Chill Panda and Rivigo have no product/project identity, only tool names.
  Recruiters cannot see what was built, for whom, or what the candidate owned.
- The 701 variant asks for 12+ years, enterprise platform design, 3+ years of
  AI and 3+ years of AIOps. Yet Rivigo and Byju’s were rewritten with
  GenAI/cloud vocabulary that postdates them, instead of using their genuine
  scale, reliability and commerce evidence.
- “Faster feature releases by 50%” under Chill Panda becomes “accelerating
  feature releases by 50%” without the original “modular distributed systems”
  context, so the mechanism disappears.
- Ariceum says “Terraform-managed Kubernetes and Docker” although the base
  resume supports only “AWS, React and Django”; the mechanism needs confirmation.
- Kiro is credited with “govern[ing] secure… cloud platforms”. Kiro is an IDE,
  so “governed with Kiro” is more precise than “used Kiro to govern”.

## Recommended resume correction before resubmission

Keep the date ranges. Replace the four false pairings with role-appropriate,
evidence-bearing lines:

**Chill Panda — Jan 2022 – May 2023**

- Deployed a multi-tenant SaaS platform with 99.9% uptime, launching a working
  prototype in three months and onboarding 10 enterprise clients.
- Integrated OpenAI GPT and NLP into personalized customer interactions,
  improving retention 25% and reducing support queries 40%.
- Built real-time order processing for $1M+ in transactions and React/Next.js
  engagement surfaces, accelerating releases 50% through modular services.

**Quantgro — May 2023 – Jan 2024**

- Built real-time financial data and analytics pipelines for trading research,
  cutting analysis latency 50%.
- Developed AI/ML predictive models and backend services for fund management,
  improving decision quality 35% and operating efficiency 40%.
- Led five engineers and built internal automation, shortening release cycles
  30% and reducing manual effort 45%.

**Rivigo — Jan 2016 – Jan 2018**

- Built the core Pickups module as sole developer, supporting 300,000+ pickups
  across 100+ cities.
- Created real-time shipment and analytics dashboards for 100+ clients and led
  three engineers.
- Kept the original monitoring evidence as dashboards and tracking. Add
  “Prometheus-era monitoring” only if the candidate confirms Prometheus was
  actually used; never use OpenTelemetry for this period.

**Ariceum — Jan–May 2022**

- Led five developers to ship an AWS, React and Django MVP in two months.
  Use OpenTelemetry only if the instrumentation was added during the CPTO term;
  otherwise move it to the Sybill or Codex project where the dates permit it.

## Reply to the recruiter

> Thanks for catching this — the dates are right, but the tool attributions are
> not. The resume was tailored too aggressively and pulled some technology
> names into earlier roles.
>
> The concrete corrections:
>
> - **Chill Panda (Jan 2022–May 2023):** Kiro did not exist yet. The real work
>   there was multi-tenant SaaS, real-time order processing, and OpenAI
>   GPT/NLP personalization.
> - **Quantgro (May 2023–Jan 2024):** MCP was not public until November 2024.
>   The role used AI/ML models, real-time financial pipelines and backend
>   services. The MCP implementation belongs under Sybill (2024–25) and the
>   Codex project.
> - **Rivigo (Jan 2016–Jan 2018):** OpenTelemetry launched in 2019. Rivigo used
>   operational dashboards and real-time tracking; OpenTelemetry belongs later.
> - **Ariceum (Jan–May 2022):** OpenTelemetry was also not available yet. The
>   supported work is the AWS, React and Django MVP; the Prometheus claim still
>   needs confirmation.
>
> I’m correcting the resume rather than moving dates. For the 701 remit, the
> strongest truthful evidence is platform design and reliability at scale:
> multi-tenant SaaS with 99.9% uptime at Chill Panda; real-time financial
> pipelines at Quantgro; and 300,000+ pickups plus client dashboards at
> Rivigo. The 2025–present Trek work carries the current agent, MCP, Bedrock and
> observability stack.
>
> I’ll send a corrected PDF with the dates unchanged and the tool claims mapped
> to the roles that can support them.

## Fix plan

### P0 — block the current failure class

1. **Correct the submitted source.** Apply the replacement bullets above, verify
   dates against the base resume, and regenerate with dates preserved. Do not
   resubmit until every technology has a supporting role period.
2. **Add a versioned technology timeline catalogue** at
   `config/technology_timeline.json`. Small JSON keyed by
   canonical term with aliases, first-public date, evidence grade and source.
   Seed at least Kiro, MCP, Bedrock, OpenTelemetry, LangGraph, AutoGen, CrewAI,
   Terraform and Kubernetes. Unknown terms are allowed but marked unchecked.
3. **Check the role end date.** Reject a technology first released after the
   role ended. For a term released during a role, require a candidate-confirmed
   adoption date before treating it as implemented.
4. **Separate the three grades.** Store `used`, `evaluated` and
   `skills-only`. Only `used` may produce “built/instrumented/integrated with”;
   `evaluated` must say so; `skills-only` must not become a project bullet.
5. **Fix term matching before adding more rules.** Add exact canonical terms and
   aliases for Kiro and OpenTelemetry; stop using the descriptive bank label as
   the matching key.

### P1 — make the payload honest

6. Pass only technologies valid for that role plus undated source-supported
   terms. Do not pass the full JD tool list to every experience group.
7. Add a compact prompt rule: “A tool is usable only if it existed during this
   role and has evidence in this experience. Do not convert Skills-section
   exposure into implementation.”
8. Keep the candidate’s real title in every role. Preserve product identity,
   the action, the mechanism and the metric subject when rewriting.
9. Put the technology audit in the review report: term, role period,
   availability, grade and decision. Make a late-release term a visible warning,
   and make a confirmed contradiction a strict-attachment blocker.

### P2 — prevent silent regressions

10. Add golden fixtures for the four bad pairings and one valid pairing per
    technology. Test term aliases, dates at boundaries, undated adoption, and
    “mentions in Skills but not in the project”.
11. Add a reviewer-facing timeline view and a one-click “move claim to an
    eligible role” action. Preserve the original dates.
12. Record the generation directory or a durable copy of the prompt payload and
    selected candidates with the uploaded PDF. The current run cannot be audited
    beyond the rendered text.

### Acceptance criteria

- No role claims a technology first released after its end date.
- An in-period technology still needs per-role evidence and a grade.
- Skills exposure alone cannot produce an implementation verb.
- The four known pairings fail a regression test until corrected.
- Dates and job titles are byte-identical to the confirmed base resume.
- A valid 2025+ MCP/Bedrock claim still passes.

## Scope note

This audit does not establish that every remaining resume claim is true.
Company-Skills mentions, the Terraform/Kubernetes wording at Ariceum, and the
degree of Kiro use all still need candidate confirmation. It also does not
authorize resubmission or contact with the employer.
