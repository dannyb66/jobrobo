# SponsorSkip: Bullet Bank for JD-Based Resume Optimization

**Project:** SPONSORSKIP, Agentic AI Hackathon (Fetch.ai), September 2024
**Sources:**
- Portfolio site ([dannyb66.github.io](https://dannyb66.github.io)): "Built with the team at Fetch.ai's agentic hackathon… detecting and skipping sponsored segments in YouTube videos."
- Candidate-supplied details on the current resume: 24 hours, 4-person team, 1st of 50.
- **No public repo, Devpost or demo link was found** (checked Oct 12, 2026).

**Purpose:** pre-approved, single-line bullets for a hackathon entry. The optimizer picks **1–2 bullets**, and only for roles where agents, 0→1 speed or hackathon wins add signal.

---

## 0. Rules for the optimizer (read first)

1. **Line fit.** Every bullet is 108–126 characters, so it fits on one line.
2. **How many.** Pick **1–2 bullets**: one from **A (Overview)**, optionally one from **B (Result)**. Drop this project entirely when space is tight; it's the weakest entry in the section.
3. **† candidate-supplied.** "24 hours", "4-person team" and "1st of 50" aren't publicly verifiable. Keep proof ready: a placement email, an event page or a Devpost link.
4. **‡ stack unconfirmed.** Fetch.ai uAgents, Agentverse and multi-agent decomposition are plausible for this event but not confirmed. Use these bullets only if you built it that way.
5. **No repeated numbers or lead verbs** across the resume.
6. **Location line.** The resume shows "San Francisco, CA". Make sure it matches the hackathon's actual location, or write "Remote" or "Virtual".

**Tag legend:**
- `AGENT` agentic AI
- `AI` applied LLM
- `ARCH` architecture
- `LEAD` team / ownership
- `PRODUCT` product thinking
- `DATA` data handling

---

## 1. Default set (1–2 lines)

- Built SponsorSkip at Fetch.ai agentic hackathon, detecting and auto-skipping sponsored YouTube segments with LLM agents
- Prototyped agentic YouTube ad-segment detection at Fetch.ai hackathon in 24 hours with a 4-person team, placed first of 50 †

---

## 2. Metric registry

| ID | Metric | Source | Status |
|---|---|---|---|
| P1 | 24-hour build | Candidate | † |
| P2 | 4-person team | Candidate | † |
| P3 | 1st place of 50 teams | Candidate | † keep proof ready |

---

## 3. Bullet bank by theme

Format: **bullet** · `tags` · metric IDs  (‡ = confirm stack before use)

### A. Overview (always pick one)

A1. Built SponsorSkip at hackathon: transcript ingestion, detecting, auto-skipping sponsored YouTube segments with LLM agents · `AGENT AI` · –
A2. Built SponsorSkip at Fetch.ai agentic hackathon, detecting and auto-skipping sponsored YouTube segments with LLM agents · `AGENT AI` · –
A3. Built agentic AI tool that ingests YouTube transcripts, classifies sponsor segments with an LLM and auto-skips in playback · `AGENT AI` · –
A4. Shipped SponsorSkip, an LLM-agent system that finds sponsored segments in YouTube transcripts and skips them automatically · `AGENT AI` · –

### B. Result / speed (candidate-supplied, confirm)

B1. Prototyped agentic YouTube ad-segment detection at Fetch.ai hackathon in 24 hours with a 4-person team, placed first of 50 † · `AGENT LEAD` · P1 P2 P3
B2. Won first place of 50 teams at Fetch.ai agentic AI hackathon with SponsorSkip, an LLM agent that auto-skips YouTube sponsors † · `AGENT` · P3
B3. Led 4-person team to ship a working multi-agent sponsor-detection demo in 24 hours, taking 1st of 50 teams at Fetch.ai † · `LEAD AGENT` · P1 P2 P3
B4. Delivered a 24-hour 0→1 agentic AI prototype with a 4-person team, from transcript ingestion to live auto-skip demo † · `AGENT LEAD` · P1 P2

### C. Architecture (confirm stack before use)

C1. Designed multi-agent pipeline on Fetch.ai uAgents: transcript ingestion, LLM sponsor classification and auto-skip actions ‡ · `AGENT ARCH` · –
C2. Decomposed sponsor detection into cooperating agents for transcript fetch, LLM segment labeling and player skip control ‡ · `AGENT ARCH` · –
C3. Built LLM classification over timestamped transcript chunks, mapping detected sponsor spans to precise player skip ranges · `AI DATA` · –
C4. Registered SponsorSkip agents on Fetch.ai Agentverse for discovery and messaging between ingestion and classifier agents ‡ · `AGENT ARCH` · –

### D. Product / UX angle

D1. Turned a consumer pain point into an agentic demo: auto-skipping in-video sponsor reads via transcript-level LLM tagging · `PRODUCT AI` · –
D2. Scoped, built and demoed an agentic browser workflow under hackathon constraints, prioritizing a reliable end-to-end skip loop · `PRODUCT LEAD` · –

---

## 4. Do not claim

- **Accuracy, precision or recall numbers, user counts or installs**, unless they were measured.
- **"Production" or "deployed to users".** It was a hackathon prototype.
- **Specific Fetch.ai components** (uAgents, Agentverse, DeltaV) unless confirmed.

---

## 5. Presets by role type

| Target role | Bullets | Notes |
|---|---|---|
| **Agents / Applied AI** | A2 + B2 | Agent keyword plus the win |
| **Founding / early-stage** | A3 + B4 | 0→1 speed |
| **Staff/Principal (leadership)** | B3 | One line with the team lead and the win |
| **AI Platform / Infra** | omit | Low signal next to Codex Self-Hosted |
| **Space-constrained** | B2 only, or omit | |

**Note on ordering:** if both B2 and the Codex project bullets are used, place SponsorSkip last in the projects section.

---

## 6. JD keyword → bullet lookup

| JD says… | Prefer |
|---|---|
| agents, multi-agent, agentic workflows | A2, C1‡, C2‡, B3 |
| LLM classification, NLP, transcripts | A3, C3 |
| hackathon, 0→1, rapid prototyping | B1, B4, D2 |
| leadership, team | B3, D2 |
| consumer product, UX | D1, A4 |

---

## 7. Gaps to fill later

- **Publish the code** as a repo or Devpost page with a 60-second demo. It turns the † claims into verifiable ones.
- **Record the stack** (framework, model, transcript source) so the ‡ bullets can be used safely.
- **Add one quality metric** if available, e.g., "flagged X of Y sponsor reads in a 20-video test set".
