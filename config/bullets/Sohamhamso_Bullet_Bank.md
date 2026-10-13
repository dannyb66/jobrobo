# Sohamhamso: Bullet Bank for JD-Based Resume Optimization

**Project:** SOHAMHAMSO, AI-Assisted Multilingual Sanskrit Platform ([sohamhamso.org](https://sohamhamso.org))
**Sources:**
- [github.com/dannyb66/sohamhamso](https://github.com/dannyb66/sohamhamso): README and STATUS-CONTRACT.md
- PR #159 docs (AI-SYSTEMS-AND-EVALUATION, AI-VIDEO-AND-YOUTUBE-PLATFORM, ARCHITECTURE, ATS-KEYWORDS), baseline commit `4c94bf2`, read Oct 12, 2026
- PR #23 (lemma-index outage fix)
- Prototype repo `soham-hamso`

**Purpose:** pre-approved, fact-checked, single-line bullets. A resume optimizer, human or AI, picks 2–4 per JD using the tags and rules below.

---

## 0. Rules for the optimizer (read first)

1. **Line fit.** Every bullet is 108–126 characters, so it fits on one line. Never merge bullets.
2. **How many.** Pick **2–4 bullets**. Always take one from **A (Overview)**. Fill the rest by JD match.
3. **No repeated numbers.** Each metric ID (§2) appears once in the final set, across the whole resume.
4. **No repeated lead verbs** within the project, and preferably across the resume.
5. **Honesty guardrails.** The repo's own docs require these:
   - **Never call search "RAG"** and never call the project "agentic". There is no retrieval-to-generation loop or agent runtime.
   - **Never say translations are "human-verified" or "all judged".** All 36,276 rows are published, but only 2,689 carry a judge score and 0 are human-reviewed.
   - **Never claim measured cost, latency, hallucination rate, user counts or video counts.** None are recorded.
   - **Never say "AI-generated video".** Narration is TTS; there's no text-to-video or image model.
   - **"3,023 verses" is shorthand.** The repo counts 3,023 *units* (2,275 verses/sūtras + 748 prose blocks). Prefer "units" or "passages" if challenged.
6. **† bullets** include a claim the repo doesn't prove on its own (e.g., solo ownership). Use them only if true.
7. **Dates.** The resume shows "December 2022 – Present". The current repo's locked V1 plan is dated 2026, with an earlier prototype (`soham-hamso`). Make sure the start date matches a public trace or your own records.

**Tag legend:**
- `PLAT` platform
- `AI` applied AI
- `LLM` LLM integration
- `EVAL` evaluation
- `GOV` responsible AI / provenance / licensing
- `SEARCH` retrieval
- `MEDIA` video/TTS
- `OPS` reliability / workflow ops
- `EDGE` Cloudflare / edge
- `DATA` data engineering
- `PERF` performance
- `SEC` privacy / security
- `FS` full-stack
- `API` external APIs
- `TEST` testing
- `CI` CI/CD
- `LEAD` ownership / docs

---

## 1. Default set (general Staff/Principal AI roles, 3 lines)

- Built multilingual corpus platform: 11 scriptures, 3,023 verses, 36K+ translations and 256K+ word glosses across 12 languages
- Built LLM translation pipeline with LLM-as-a-judge fidelity scoring (1–10, ≥7 to publish) and per-row model/prompt provenance
- Engineered text-to-video pipeline: TTS narration in 10 voices, React/Remotion rendering, FFmpeg encoding, R2 artifact store

---

## 2. Metric registry

| ID | Metric | Source | Status |
|---|---|---|---|
| S1 | 11 texts | README (baseline) | ✅ |
| S2 | 76 chapters | README | ✅ |
| S3 | 3,023 addressed units (2,275 verse/sūtra + 748 prose) | README | ✅ ("verses" is loose) |
| S4 | 36,276 translation rows (3,023 × 12 locales) | README | ✅ |
| S5 | 256,453 word-gloss rows | README | ✅ |
| S6 | 12 locales (English + 11 Indic) | README | ✅ |
| S7 | Judge 1–10 scale; ≥7 → published | STATUS-CONTRACT / AI doc | ✅ |
| S8 | 2,689 rows carry a judge score | AI doc | ✅ (use with care) |
| S9 | 3,072-dim embeddings (text-embedding-3-large) | AI doc | ✅ |
| S10 | Reciprocal rank fusion, k = 60 | AI doc | ✅ |
| S11 | 1,000-entry query-vector LRU, 7-day TTL | AI doc | ✅ |
| S12 | Dispatch concurrency 3; max 3 attempts; exponential backoff from 5s | AI doc | ✅ |
| S13 | 9-state media lifecycle | Video doc | ✅ |
| S14 | 6 scheduled/dispatch GitHub Actions workflows (upload currently manual) | Video doc | ✅ |
| S15 | ~180K `word_glosses` rows scanned per cold isolate before fix | PR #23 | ✅ |
| S16 | 10 configured TTS voices (1 English + 9 Indic) | Video doc | ✅ configured, not all verified live |
| S17 | Loudness gate > −40 LUFS; codec/duration/size gates | Video doc | ✅ |
| S18 | Shorts 1080×1920; chapters 1920×1080 | Video doc | ✅ |
| S19 | 4 decision records | README | ✅ (reconstructed, not contemporaneous) |
| S20 | 250+ commits | GitHub | ✅ |
| S21 | 140+ issues | GitHub | ✅ |
| S22 | 6 texts auto-excluded from dataset export | README | ✅ |
| S23 | 5 CSV tables + JSON shards + TEI-XML | README | ✅ |
| S24 | 12 uploads/day cap; 8,000-unit local quota ceiling | Video doc | ✅ configured |
| S25 | 2 isolated Turso DBs (corpus vs PII) | Architecture doc | ✅ |

---

## 3. Bullet bank by theme

Format: **bullet** · `tags` · metric IDs

### A. Platform / overview (always pick one)

A1. Built multilingual corpus platform: 11 scriptures, 3,023 verses, 36K+ translations and 256K+ word glosses across 12 languages · `PLAT DATA AI` · S1 S3 S4 S5 S6
A2. Launched sohamhamso.org, an AI-assisted Sanskrit reader serving 3,023 units across 11 texts in 12 languages on the edge · `PLAT AI EDGE` · S1 S3 S6
A3. Shipped AI-native scripture platform on Astro, Cloudflare Workers and Turso, unifying reader, open dataset and video pipeline · `PLAT EDGE FS` · –
A4. Built AI-assisted multilingual reader end to end: corpus ingestion, LLM translation, hybrid search, edge SSR, video automation · `PLAT AI FS` · –
A5. Founded non-profit AI scripture platform, owning product, architecture and delivery over 250+ commits and 140+ issues · `PLAT LEAD` · S20 S21

### B. LLM translation & grounding

B1. Generated 36K+ grounded Claude translations from Sanskrit, morphology and glosses with versioned prompts across 12 locales · `LLM AI DATA` · S4 S6
B2. Grounded LLM translations in Devanagari, IAST, word glosses, meter and prior-verse context to preserve technical terms · `LLM AI` · –
B3. Built Claude translation pipeline emitting structured JSON (translation, glosses, confidence, term resolutions) per verse · `LLM AI DATA` · –
B4. Designed versioned prompt templates (v1-sanskrit-grounded, v1-judge) with temperature 0.2/0.0 for reproducible LLM output · `LLM EVAL` · –

### C. Evaluation, provenance & responsible AI

C1. Built LLM translation pipeline with LLM-as-a-judge fidelity scoring (1–10, ≥7 to publish) and per-row model/prompt provenance · `EVAL LLM GOV` · S7
C2. Gated AI translations with an LLM-as-a-judge Sanskrit-fidelity rubric, publishing only scores ≥7 and holding the rest · `EVAL GOV` · S7
C3. Designed AI provenance contract: ai_assisted/status matrix, judge scores and model/prompt versions surfaced in reader badges · `GOV EVAL FS` · –
C4. Applied responsible-AI labeling: AI translations flagged 'not verified' with model/prompt metadata until expert-reviewed · `GOV AI` · –
C5. Documented evaluation limits (shared judge/generator model, no calibration set) and a 50-row-per-language audit plan · `EVAL GOV LEAD` · –

### D. LLM batch orchestration

D1. Orchestrated LLM batch jobs with bounded concurrency, 3-attempt exponential backoff and per-language JSONL run ledgers · `LLM OPS` · S12
D2. Built fault-tolerant LLM dispatch: concurrency cap of 3, retries on 429/5xx/timeouts, dry-run mode and nonzero exit on failure · `LLM OPS` · S12
D3. Scaled translation generation across 11 Indic languages with idempotent unit selection, so reruns never regenerate drafts · `LLM DATA OPS` · –

### E. Search & retrieval

E1. Built hybrid search: FTS5 lexical plus text-embedding-3-large vectors fused via reciprocal rank fusion with lexical fallback · `SEARCH AI` · –
E2. Implemented semantic search with 3,072-dim embeddings, cosine scoring, RRF blending and a 1,000-entry query-vector LRU cache · `SEARCH AI PERF` · S9 S11
E3. Shipped blended lexical + semantic search API (RRF, k=60) with graceful lexical fallback when vectors or keys are unavailable · `SEARCH API` · S10
E4. Embedded multilingual translations in 100-item batches into Float32 BLOBs keyed by verse, language and model for retrieval · `SEARCH DATA` · –

### F. AI video / media pipeline

F1. Engineered text-to-video pipeline: TTS narration in 10 voices, React/Remotion rendering, FFmpeg encoding, R2 artifact store · `MEDIA AI` · S16
F2. Built AI video pipeline turning verse translations into narrated Shorts and chapters via Google TTS, Remotion, FFmpeg and R2 · `MEDIA AI` · –
F3. Built end-to-end media pipeline from SQLite corpus to YouTube: TTS, Remotion, FFmpeg QA gates, R2 storage and analytics sync · `MEDIA PLAT` · –
F4. Designed 10-stage AI video pipeline: manifest, TTS, Remotion, FFmpeg encode, QA, R2 store, upload, review and analytics · `MEDIA PLAT` · –
F5. Automated multilingual video generation: Google TTS, Remotion layouts with Indic fonts, FFmpeg QA and R2-to-YouTube publishing · `MEDIA AI` · –
F6. Built human-in-the-loop video pipeline: TTS narration, Remotion render, FFmpeg QA, unlisted YouTube upload, manual publish · `MEDIA GOV` · –
F7. Productionized AI video generation with Google TTS, Remotion and FFmpeg, enforcing LUFS, codec and duration QA before upload · `MEDIA OPS` · S17
F8. Built Whisper + GPT-4 prototype transcribing Sanskrit chants into time-synced bilingual lyric videos for a YouTube channel · `MEDIA AI` · –

### G. Media reliability & workflow ops

G1. Engineered fault-tolerant media workflows with SQL leases, 9-state lifecycle, bounded retries and SHA-256 artifact checks · `OPS MEDIA` · S13
G2. Automated media ops via 6 GitHub Actions workflows: render, upload, analytics sync, digest and lease sweep with alerting · `OPS CI` · S14
G3. Gated renders on media QA (LUFS loudness, codecs, duration) and checksum-verified uploads before human review and publish · `OPS MEDIA GOV` · S17
G4. Enforced YouTube quota safety (12 uploads/day, 8,000-unit ceiling) with batch halts, reauth errors and failure-stage tracking · `OPS API` · S24
G5. Recovered stalled jobs via lease sweeps and supersede logic, re-rendering only when manifest hashes or templates change · `OPS MEDIA` · –

### H. Edge platform & architecture

H1. Split edge data into isolated corpus and PII Turso databases, with SSR verse routes and HMAC-hashed subscriber identifiers · `SEC EDGE DATA` · S25
H2. Chose edge SSR over static builds to avoid per-verse, per-locale page explosion, serving 12 locales from Cloudflare Workers · `EDGE PLAT` · S6
H3. Separated native Bun/SQLite build tooling from edge-compatible libSQL SSR on Cloudflare Workers, with parity tests across both · `EDGE FS` · –
H4. Designed static-first architecture pre-rendering indexes from SQLite with on-demand SSR verse routes on Cloudflare Workers · `EDGE PLAT` · –

### I. Performance & incident response

I1. Resolved Turso read-quota outage by materializing a lemma index at build, ending ~180K-row scans per cold edge isolate · `OPS PERF EDGE` · S15
I2. Root-caused production outage from cold-isolate gloss scans (~180K rows) and shipped build-time lemma index with migration · `OPS PERF` · S15

### J. Data engineering & open dataset

J1. Published open dataset (CSV, JSON, TEI-XML) with SHA-256 checksums and license-aware export excluding 6 restricted texts · `DATA GOV` · S22
J2. Enforced data contracts with Zod-validated ingestion, reconciliation tests and Vitest/Playwright/axe CI regression suites · `DATA TEST` · –
J3. Built transactional corpus ingestion from YAML shards into SQLite: 11 texts, 76 chapters and 256K+ gloss rows with validation · `DATA` · S1 S2 S5
J4. Integrated Vidyut Sanskrit morphological analysis for word-by-word glosses and transliteration; tested with Playwright, Vitest · `DATA AI TEST` · –
J5. Managed per-source licensing (MIT code, CC-BY-SA content) across MIRI, GRETIL and Wikisource with automated export exclusions · `GOV DATA` · –

### K. Engineering leadership & documentation

K1. Documented architecture via 4 decision records, AI evaluation limits and runbooks, making calibration gaps explicit · `LEAD GOV` · S19
K2. Ran project as solo technical owner: roadmap of 140+ issues, 250+ commits, decision records and operator runbooks † · `LEAD` · S20 S21

---

## 4. Do not claim

- **RAG, agents, MCP or tool-calling.** The repo explicitly marks these as not established.
- **Human-reviewed or expert-verified translations, or accuracy percentages.**
- **Video counts, views, subscribers, cost per video, latency or user numbers.** None are measured.
- **Kubernetes, Kafka, Go, GPU inference or training.** None are present here; GPU inference work belongs in Codex Self-Hosted.
- **Production YouTube auto-publishing.** Upload is paused or manual, and human review happens before anything goes public.
- **Azure Speech, Node/Docker/D1 or the Rudri ASR/OCR pipeline.** Branch-only or uncommitted; label them "experimental" if mentioned at all.

---

## 5. Presets by role type

| Target role | Bullets (in order) | Notes |
|---|---|---|
| **Staff/Principal AI (general)** | A1 · C1 · F1 | Default; scale, evals, multimodal |
| **AI Evaluation / Responsible AI** | A2 · C2 · C3 · D1 | Judge gating, provenance contract, batch orchestration |
| **LLM Applications / Applied AI** | A4 · B1 · E1 · C1 | Grounded generation plus hybrid search |
| **Search / Retrieval** | A2 · E2 · E3 · B3 | Embeddings, RRF, caching |
| **Platform / Edge / Full-stack** | A3 · H1 · I1 · J2 | Cloudflare, Turso split, outage fix, data contracts |
| **SRE / Reliability** | A3 · I2 · G1 · G4 | Incident root cause, leases, quota safety |
| **Media / Multimodal AI** | A1 · F7 · G1 · F6 | TTS, Remotion/FFmpeg, QA gates, human-in-the-loop |
| **Data Engineering** | A3 · J3 · J1 · J4 | Ingestion, open dataset, morphology |
| **Founding / generalist (2 lines)** | A5 · C1 | Ownership plus AI depth |

**Before you finalize, check:**
- **Metrics:** no metric ID repeats. For example, A1 and J3 both carry S1 and S5; if both are needed, swap A1 for A3.
- **Lead verbs:** no lead verb repeats.

---

## 6. JD keyword → bullet lookup

| JD says… | Prefer |
|---|---|
| LLM, generative AI, prompt engineering, structured output | B1–B4 |
| evaluation, LLM-as-a-judge, quality gates, groundedness | C1, C2, C5, B2 |
| responsible AI, provenance, governance, transparency | C3, C4, J5, F6 |
| batch processing, retries, orchestration, rate limits | D1–D3, G1 |
| search, embeddings, semantic, vector, ranking | E1–E4 |
| TTS, speech, video, multimodal, media pipeline | F1–F8, G3 |
| workflow orchestration, GitHub Actions, CI/CD | G2, G1, J2 |
| reliability, incident, on-call, root cause, performance | I1, I2, G5 |
| edge, Cloudflare Workers, serverless, SSR | H1–H4, A3 |
| privacy, PII, security | H1 |
| data engineering, ETL, schema, data quality | J1–J4 |
| open data, licensing, compliance | J1, J5 |
| multilingual, localization, i18n, Indic | A1, A2, B1, H2, F5 |
| ownership, architecture decisions, documentation | K1, K2, A5 |

---

## 7. Gaps to fill later

- **Measured outcomes:** monthly visitors, search latency p95, translation cost per 1K units, and videos published with views. Any one of these makes the overview bullet much stronger.
- **Human-review coverage:** run the planned quarterly 50-row audit, then claim "X% judge-human agreement".
- **Embedding coverage:** report the share of units with vectors, plus a small retrieval benchmark (e.g., recall@10 on 50 queries).
- **Zenodo DOI:** publish the DOI so "open dataset" links to a citable artifact.
