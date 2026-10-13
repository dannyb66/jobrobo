# Trek Health Experience: Bullet Bank for JD-Based Resume Optimization

**Role:** Principal Engineer, Trek Health, San Francisco, CA (June 2025 – Present)
**Sources:** *Contract_Intelligence_Agent_Hub_Principal_Engineer_Brief* plus the current resume (as of Oct 11, 2026)
**Purpose:** A pool of pre-approved, fact-checked, single-line bullets. A resume optimizer, human or AI, can pick 5–7 per JD using the tags and rules below.

---

## 0. Rules for the optimizer (read first)

1. **Line fit:** every bullet is 110–126 characters, so it fits on one line in the current resume template. Do not merge two bullets.
2. **Pick 5–7 bullets.** Always include one from **A (Platform)** and one from **N (Leadership)**. Fill the rest by JD match using the tags.
3. **No number twice.** Each metric appears at most once in the final set. Use the *Metric ID* column (§2) to check.
4. **Vary the lead verbs.** No two picked bullets may start with the same verb.
5. **Tense:** use present tense ("Own", "Mentor", "Lead") only for ongoing responsibilities, and past tense for delivered work. Use at most two present-tense bullets.
6. **Facts only:** never change a number, and never upgrade "fluency" terms such as **MCP**, **A2A** or **OpenTelemetry** into claims that you implemented them. The brief lists them only as market alignment (see §4).
7. **Verification flags:** bullets marked † use numbers that are **not in the brief** (from the resume). Use them only if the candidate has confirmed them.
8. **Mirror the JD's wording:** if the JD writes "LLM-as-a-Judge", "guardrails" or "durable execution", prefer the variant that uses the same term.

**Tag legend:**
- `PLAT` AI platform / infra
- `AGENT` applied agents
- `SEC` AI security / safety
- `EVAL` evals / quality
- `OPS` reliability / SRE
- `DATA` data engineering
- `HC` healthcare
- `FS` full-stack / backend
- `LEAD` Staff/Principal leadership
- `COST` cost/FinOps

---

## 1. Default set (general Staff/Principal AI roles)

- Architected 0→1 multi-tenant agentic AI platform for healthcare contract intelligence, serving 100+ clients on 5TB+ of data †
- Own cross-cutting agent architecture: ReAct orchestration, subagents, plan mode, memory, observability and per-query cost caps
- Designed auditable agent control plane: tool registry, JIT discovery and allowlists for 20+ tools, 40+ skill playbooks
- Hardened tool-using LLMs with 11 sequential tool gates, prompt-injection defense, tenant isolation and org-level kill switches
- Defined release quality bar for agentic AI: 150-case replay harness, L1–L3 tiers, golden-path tests; 25/25 routing, 14/14 E2E
- Led delivery of 158 API routes, 442 Snowflake procedures and ~870K LOC (TypeScript, SQL), authoring ~48% of 4,700+ commits
- Mentor 10+ engineers and set the technical roadmap; built paved-road patterns, runbooks and reference agent implementations †

---

## 2. Metric registry (single source of truth)

| ID | Metric | Source | Status |
|---|---|---|---|
| M1 | 100+ clients | Resume | † confirm |
| M2 | 5TB+ data (transparency / contract data) | Resume | † confirm |
| M3 | 10+ engineers mentored | Resume | † confirm |
| M4 | 22 tools → "20+ tools" | Brief | ✅ |
| M5 | 10 active skills; 44 skill playbooks → "40+ skill playbooks" | Brief | ✅ |
| M6 | 6 seeded operational scopes | Brief | ✅ |
| M7 | 3-stage scope classifier (keyword, inherited thread, low-cost model) | Brief | ✅ |
| M8 | 3 rollout modes (off, log-only, enforce) | Brief | ✅ |
| M9 | 11 sequential tool gates | Brief | ✅ |
| M10 | 150-case replay harness | Brief | ✅ |
| M11 | 25/25 routing queries (hospital & Medicare-rate workflows only) | Brief | ✅ scope-limited |
| M12 | 14/14 end-to-end security/reliability suite | Brief | ✅ |
| M13 | L1/L2/L3 testing tiers | Brief | ✅ |
| M14 | 30-second bounded Python execution | Brief | ✅ |
| M15 | 50KB bounded result payloads | Brief | ✅ |
| M16 | 80-way parallel ingestion | Brief | ✅ |
| M17 | Subagent gets ½ remaining iteration/token budget + parent deadline | Brief | ✅ |
| M18 | 158 API routes (Contract Intelligence) | Brief | ✅ |
| M19 | 442 procedure files (Contract Intelligence) | Brief | ✅ |
| M20 | 163 stored procedures, 89 seed scripts (Agent Hub) | Brief | ✅ |
| M21 | ~189K LOC TypeScript + ~684K LOC SQL (CI) → "~870K LOC" | Brief | ✅ |
| M22 | ~92K SQL + ~50K TS + ~4K Python LOC (Agent Hub) | Brief | ✅ |
| M23 | ~2,277 of 4,749 commits (~48%), Contract Intelligence | Brief | ✅ |
| M24 | 341 of 1,059 commits (~32%), Agent Hub | Brief | ✅ |
| M25 | 11 implementation phases | Brief | ✅ |
| M26 | v1/v2 runtime with feature-flagged rollout and rollback | Brief | ✅ |
| M27 | [X]% token / latency / cost / MTTR reduction | **Not measured** | ❌ do not use until measured |

**Combined footprint** (if a JD stresses scale): both repos together come to ~1.02M LOC and ~2,600 of ~5,800 commits. Use this only as "across two platforms".

---

## 3. Bullet bank by theme

Format: **bullet** · `tags` · metric IDs

### A. Platform / 0→1 ownership (always pick one)

1. Architected 0→1 multi-tenant agentic AI platform for healthcare contract intelligence, serving 100+ clients on 5TB+ of data † · `PLAT AGENT HC` · M1 M2
2. Built enterprise agentic AI platform from scratch, powering contract and price-transparency intelligence for 100+ clients † · `PLAT HC` · M1
3. Led 0→1 architecture of multi-tenant LLM agent platform on Snowflake Cortex AI and AWS, serving 100+ healthcare clients † · `PLAT DATA HC` · M1
4. Architected multi-agent platform turning 5TB+ of payer contract and TiC data into real-time AI insights for 100+ clients † · `HC DATA AGENT` · M1 M2
5. Architected governed, tool-using LLM agent platform end to end, serving 100+ healthcare clients in real time over 5TB+ data † · `PLAT SEC` · M1 M2
6. Architected AI-native healthcare intelligence platform unifying agentic search, governed tool execution and AI reporting · `PLAT AGENT HC` · –
7. Built regulated multi-tenant AI platform on Next.js, TypeScript, Snowpark, Cortex AI and AWS across 11 implementation phases · `PLAT FS DATA` · M25

### B. Agent runtime / orchestration

1. Own cross-cutting agent architecture: ReAct orchestration, subagents, plan mode, memory, observability and per-query cost caps · `AGENT PLAT LEAD` · –
2. Own cross-cutting agent architecture: ReAct runtime, budgeted subagents, scoped memory, policy enforcement and cost governance · `AGENT SEC COST` · –
3. Own multi-tenant agent runtime: orchestration, tool calling, scoped memory, policy enforcement, observability and cost caps · `PLAT AGENT` · –
4. Architected multi-tenant ReAct agent runtime with subagents, plan mode, persistent memory and context compaction at scale · `AGENT` · –
5. Built resilient multi-agent ReAct runtime with plan mode, 30s sandboxed code execution, structured outputs and scoped memory · `AGENT SEC` · M14
6. Built long-running multi-agent runtime: ReAct loop, subagents on halved token budgets, 30s sandboxed code execution, cost caps · `AGENT COST` · M14 M17
7. Engineered ReAct agent runtime with subagents, plan mode and context compaction, enforcing per-tenant policy and token budgets · `AGENT COST` · –
8. Designed tenant-aware ReAct runtime with budgeted subagents, retries, cancellation and graceful degradation for long workflows · `AGENT OPS` · –
9. Built ReAct agent runtime orchestrating 20+ tools, 40+ skill playbooks and subagents with memory for long-running workflows · `AGENT` · M4 M5
10. Bounded subagent recursion with restricted tool registries, inherited deadlines and halved token/iteration budgets per child · `AGENT COST` · M17
11. Engineered fault-tolerant agent loop with bounded iterations, retries, cancellation checks and forced-answer degradation · `AGENT OPS` · –

### C. Capability control plane / tool registry

1. Designed auditable agent control plane: tool registry, JIT discovery and allowlists for 20+ tools, 40+ skill playbooks · `PLAT AGENT SEC` · M4 M5
2. Designed agent capability control plane: tool registry, JIT discovery and org-scoped access, loading only needed tool schemas · `PLAT AGENT` · –
3. Built agent control plane with tool registry, JIT capability discovery and per-tenant allowlists, reducing context overhead · `PLAT COST` · –
4. Designed governed tool and skill registry with just-in-time schema hydration, enforcing least-privilege access across 6 scopes · `PLAT SEC` · M6
5. Architected capability registry and 3-stage scope classifier routing each request to least-privilege tools per tenant · `PLAT SEC AGENT` · M7
6. Created auditable agent control plane: registry, JIT discovery, double-gated skills and scope allowlists across 20+ tools · `PLAT SEC` · M4
7. Applied double-gated, dependency-aware skill discovery so tenants see only workflows their scope and allowlist can run · `PLAT SEC` · –
8. Built 3-stage scope classifier (keyword, thread, low-cost LLM) with off, log-only and enforce modes for safe policy rollout · `SEC OPS COST` · M7 M8

### D. AI security, guardrails & governance

1. Hardened tool-using LLMs with 11 sequential tool gates, prompt-injection defense, tenant isolation and org-level kill switches · `SEC AGENT` · M9
2. Enforced defense-in-depth AI guardrails: 11 tool gates, prompt-injection defense, tenant isolation and per-query cost caps · `SEC COST` · M9
3. Built defense-in-depth controls for LLM tool use: registry validation, rate limits, untrusted-content envelopes, kill switches · `SEC` · –
4. Sandboxed code execution: read-only SQL on approved datasets, org-gated Python with 30s timeouts and 50KB output caps · `SEC AGENT` · M14 M15
5. Blocked destructive SQL at procedure, role-grant and execution-context layers, enforcing 3-layer authorization for AI agents · `SEC DATA` · –
6. Passed 14/14 end-to-end security and reliability suite covering prompt injection, cross-tenant isolation and runaway workflows · `SEC EVAL` · M12
7. Prevented cross-tenant leakage via organization-bound reads at the data layer and key discovery before agent memory recall · `SEC HC` · –
8. Shipped AI governance controls: scope allowlists, org kill switches, cost budgets and audit trails for regulated health data · `SEC HC COST` · –

### E. Evals / quality

1. Defined release quality bar for agentic AI: 150-case replay harness, L1–L3 tiers, golden-path tests; 25/25 routing, 14/14 E2E · `EVAL LEAD` · M10 M11 M12 M13
2. Defined eval-gated releases for agentic AI: 150-case replay, L1–L3 tiers, golden-path tests; 100% routing (25/25), 14/14 E2E · `EVAL` · M10 M11 M12 M13
3. Defined agent release gates: 150-case replay harness, L1–L3 tiers, golden-path and scope tests, validating 25/25 tool routing · `EVAL` · M10 M11 M13
4. Set agent quality bar via 150-case replay harness, L1–L3 tiers and golden-path tests, gating rollouts on 25/25 routing · `EVAL OPS` · M10 M11 M13
5. Built release quality bar for LLM agents: 150-case replay harness, L1–L3 tiers, golden paths and error-code coverage gates · `EVAL` · M10 M13
6. Defined release quality bar: 150-case replay harness, L1–L3 tiers, golden paths, production baselines; 14/14 E2E suite · `EVAL SEC` · M10 M12 M13
7. Built LLM eval and regression pipeline: 150 replay cases, trace inspection and baselines to catch agent quality drift · `EVAL OPS` · M10
8. Instituted evaluation-driven development: replay testing, golden paths, baselines; passed 14/14 E2E security/reliability suite · `EVAL SEC` · M12
9. Validated 100% tool routing (25/25) on hospital and Medicare-rate workflows via replay datasets and routing/scope gates · `EVAL HC` · M11

### F. Observability / safe operations / SRE

1. Built agent observability: per-iteration tool traces, lifecycle events, failure records and health/degraded trace patterns · `OPS EVAL` · –
2. Rolled out v2 agent runtime via feature flags, log-only→enforce scope modes and v1 rollback for safe production cutover · `OPS LEAD` · M8 M26
3. Designed safe-ops model for AI workflows: feature-flagged rollout, v1 rollback, dry-run/apply/verify config runbooks · `OPS LEAD` · M26
4. Made agent behavior observable and operable with status telemetry, dedicated failure surfaces, rollout controls and runbooks · `OPS` · –
5. Owned incident readiness for agent platform: failure records, degraded-mode traces, kill switches and rollback runbooks · `OPS SEC LEAD` · –

### G. Async / long-running / durable workflows

1. Standardized async agent workflows (queues, Snowflake tasks, workers, state machine) with feature-flagged rollout and rollback · `PLAT OPS DATA` · M26
2. Defined async agent-report standard (queues, streams, Snowflake tasks, workers, state machine) as paved road for new agents · `PLAT LEAD DATA` · –
3. Built event-driven agent execution with single-claim dispatch, async worker fan-out and append-only lifecycle state machine · `PLAT DATA OPS` · –
4. Engineered fire-and-forget dispatch for minutes-long agent runs with streamed progress telemetry and recoverable state · `PLAT FS` · –

### H. Context engineering / memory

1. Built modular context architecture: static policy prompts, per-turn context, bounded history and compacted tool results · `AGENT COST` · –
2. Engineered context engineering via JIT tool hydration and context compaction, loading only schemas each request requires · `AGENT COST` · –
3. Designed scoped persistent agent memory across thread, user and org boundaries with org-bound reads to prevent tenant leakage · `AGENT SEC` · –
4. Separated agent identity and policy from volatile execution state via layered prompts, plan-mode state and bounded history · `AGENT` · –

### I. Cost & latency governance

1. Enforced per-query cost caps, token/credit accounting and bounded iterations, keeping long-running agent spend predictable · `COST AGENT` · –
2. Cut LLM spend via a 3-stage scope classifier that resolves requests by keyword and thread before invoking a low-cost model · `COST PLAT` · M7
3. Applied cost governance: per-query caps, halved subagent budgets, org kill switches and forced-answer degradation on limits · `COST SEC` · M17

### J. Healthcare data & domain

1. Built healthcare data pipelines: 80-way parallel ingestion, EDI 835 remittance extraction, AI-generated PDF/Excel reports · `HC DATA` · M16
2. Scaled healthcare ingestion with 80-way parallel chunking, EDI 835 remittance extraction and AI-generated PDF/Excel reports · `HC DATA` · M16
3. Delivered payer contract, policy and price-transparency (TiC) intelligence with AI reports, version history and doc viewers · `HC FS` · –
4. Automated hospital and Medicare-rate analysis with tool-using agents, validating 100% routing accuracy across 25 test queries · `HC AGENT EVAL` · M11
5. Built ZIP and presigned-S3 ingestion for large healthcare files with 80-way parallel chunking into Snowflake for AI analysis · `HC DATA PLAT` · M16
6. Extracted EDI 835 remittance data into governed Snowflake models powering AI-generated contract and reimbursement reports · `HC DATA` · –

### K. Data platform / Snowflake

1. Built AI data layer on Snowflake (Snowpark, Cortex AI): 163 stored procedures, 89 seed scripts and 44 skill playbooks · `DATA PLAT` · M20 M5
2. Delivered ~684K LOC of Snowflake SQL and Python procedures backing 158 API routes for healthcare analytics and AI reports · `DATA FS HC` · M18 M21
3. Orchestrated Snowflake tasks, streams and procedures as an async execution layer for long-running AI agents and reports · `DATA PLAT` · –

### L. Full-stack / backend delivery

1. Led delivery of 158 API routes, 442 Snowflake procedures and ~870K LOC (TypeScript, SQL), authoring ~48% of 4,700+ commits · `FS LEAD` · M18 M19 M21 M23
2. Owned end-to-end delivery across 158 API routes and ~870K LOC (TypeScript, SQL), authoring ~48% of 4,700+ commits · `FS LEAD` · M18 M21 M23
3. Shipped 158 API routes, 442 Snowflake procedures and 44 skill playbooks to production; authored ~48% of 4,700+ commits · `FS DATA` · M18 M19 M5 M23
4. Drove platform delivery as lead contributor: ~48% of 4,700+ commits across 158 API routes and 442 Snowflake procedures · `FS LEAD` · M18 M19 M23
5. Built Next.js/TypeScript product surface: 158 API routes, document viewers, version history and PDF/Excel report exports · `FS HC` · M18
6. Contributed across two AI platforms: ~48% of 4,700+ Contract Intelligence commits and ~32% of 1,000+ Agent Hub commits · `FS LEAD` · M23 M24

### M. Paved roads / platform standards

1. Created reusable agent standards spanning API, UI, Snowflake task/stream layers, telemetry, tests and deployment runbooks · `PLAT LEAD` · –
2. Built paved road for new agent families: shared schemas, lifecycle patterns, reference implementations and runbooks · `PLAT LEAD` · –
3. Translated regulated multi-tenant requirements into durable technical standards across product, data, security and platform · `LEAD HC SEC` · –

### N. Leadership (always pick one)

1. Mentor 10+ engineers and set the technical roadmap; built paved-road patterns, runbooks and reference agent implementations † · `LEAD` · M3
2. Mentor 10+ engineers on technical strategy, API/data contracts and eval practices; lead architecture and design reviews † · `LEAD EVAL` · M3
3. Lead architecture and design reviews for 10+ engineers, setting standards for API/data contracts, evals and AI adoption † · `LEAD` · M3
4. Set technical direction for 10+ engineers via design reviews, API/data contracts and eval-driven development practices † · `LEAD EVAL` · M3
5. Grew 10+ engineers through mentorship and cross-team alignment, shipping reusable agent standards adopted by product teams † · `LEAD` · M3
6. Aligned product, data, security and ops stakeholders on explicit architectural trade-offs for regulated AI workflows · `LEAD HC` · –
7. Set operating model for autonomous AI workflows: approval boundaries, cost/latency budgets, rollout and incident response · `LEAD OPS COST` · –

---

## 4. Terms to use only as fluency (skills/summary, never as built work)

These appear in the brief only under *market alignment*. Use them in the Skills section or summary ("architecture fluency"). Do not use them in bullets unless the candidate confirms they implemented them:

- **Protocols:** Model Context Protocol (MCP), Agent2Agent (A2A), agent cards
- **Identity:** agent gateway, non-human identity, OAuth/OIDC hardening
- **Tracing:** OpenTelemetry semantic conventions
- **Execution:** durable execution (Temporal), canary rollout
- **Process:** policy-as-code, zero-trust tool access
- **Not in the brief at all:** LLM-as-a-Judge (also not in the brief)

---

## 5. Presets by role type (pick in this order)

| Target role | Bullets (in order) | Notes |
|---|---|---|
| **Staff/Principal AI Platform** | A1 · C1 · D1 · E1 · G1 · L1 · N1 | Infrastructure ownership, governance and paved roads |
| **Staff Agents Engineer (applied)** | A6 · B9 · C5 · H1 · E3 · D4 · N2 | Runtime depth and context engineering; drops C1 to avoid a second use of M4/M5 |
| **AI Security / Safety / Governance** | A5 · D1 · D4 · C8 · D7 · E6 · N7 | Wording pairs with OWASP LLM Top 10 JDs; E6 carries 14/14 |
| **Evals / Quality Engineer** | A6 · E1 · E7 · F1 · B11 · D3 · N2 | Measurement first |
| **Healthcare AI / Health-tech** | A4 · J1 · J3 · E9 · D8 · B1 · N6 | Payer, TiC, EDI 835 and Medicare terms |
| **Healthcare data / RCM / payer** | A2 · J5 · J6 · K1 · L5 · D7 · N3 | Data-heavy; add HIPAA only if confirmed |
| **SRE / Reliability for AI** | A6 · F2 · F5 · G3 · B8 · I1 · N7 | Rollout, rollback and incident readiness |
| **Senior/Staff Backend or Full-Stack** | A7 · L1 · L5 · G4 · K3 · D5 · N4 | TypeScript/Next.js, APIs, Snowflake |
| **Data Platform / Snowflake** | A3 · K1 · K2 · G2 · J5 · D5 · N3 | Snowpark, Cortex AI, tasks/streams |
| **Founding / early-stage startup** | A1 · B1 · C1 · E1 · L4 · J1 · N1 | Breadth plus ownership signal |

**Before finalizing any preset, check:**
- **No metric ID repeats.** For example, D6 and E1 both carry M12, so pick only one of them.
- **No lead verb repeats.**
- **Every † bullet is confirmed.**

---

## 6. JD keyword → bullet lookup

| JD says… | Prefer |
|---|---|
| agent runtime, harness, orchestration, ReAct, multi-agent | B1–B11 |
| tool calling, function calling, tool registry, capabilities | C1–C8, B9 |
| context engineering, context window, memory | H1–H4, C2 |
| guardrails, AI safety, prompt injection, red teaming | D1–D8 |
| sandboxing, code execution, least privilege | D4, D5, C4, C5 |
| evals, evaluation, regression, benchmarks, golden datasets | E1–E9 |
| observability, tracing, monitoring, SLOs | F1, F4, E7 |
| reliability, incident, on-call, rollout, rollback | F2, F3, F5 |
| async, event-driven, queues, long-running, durable execution | G1–G4, K3 |
| cost, FinOps, token budget, latency | I1–I3, B6, B10 |
| multi-tenant, tenant isolation, RBAC, authorization | D7, C4, C5, B3 |
| Snowflake, Snowpark, Cortex, data platform, ETL | K1–K3, J5 |
| healthcare, payer, provider, claims, EDI, price transparency, TiC | J1–J6, E9, A4 |
| TypeScript, Next.js, APIs, full-stack | L1–L6 |
| technical strategy, mentorship, cross-functional, roadmap | N1–N7, M1–M3 |
| platform standards, paved road, developer experience | M1–M3, G2 |

---

## 7. Gaps to fill later (would strengthen every preset)

- **Measured outcomes.** Collect even one number each for: token reduction from JIT discovery, p95 latency, cost per query, time-to-ship a new agent family, and incident/MTTR. Then add [X]% bullets. Principal screeners weight business outcomes over component lists.
- **Adoption metric.** For example, "N agent families shipped on the paved road" or "N teams using the async standard".
- **Compliance.** HIPAA, PHI, SOC 2 or BAA terms only if confirmed. The brief says "regulated", not which regulation.
- **Business impact.** Customer- or revenue-facing results, such as reports generated per month, client hours saved, or contracts analyzed.
