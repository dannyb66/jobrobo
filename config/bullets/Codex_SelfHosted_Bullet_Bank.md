# Codex Self-Hosted: Bullet Bank for JD-Based Resume Optimization

**Project:** CODEX SELF-HOSTED, Open-Source LLM Inference Platform (September 2026 – Present)
**Sources:**
- [github.com/dannyb66/codex-selfhosted](https://github.com/dannyb66/codex-selfhosted): README, `server/models.json`, `server/qwen38-fp8-streaming.txt` (read Oct 12, 2026)
- The current resume

**Purpose:** pre-approved, fact-checked, single-line bullets. A resume optimizer, human or AI, picks 3–5 per JD using the tags and rules below.

---

## 0. Rules for the optimizer (read first)

1. **Line fit.** Every bullet is 108–126 characters, so it fits on one line in the current template. Never merge bullets.
2. **How many.** Pick **3–5 bullets** for this project. Always take one from **A (Platform)**. Fill the rest by JD match.
3. **No repeated numbers.** Each metric ID (§2) appears once in the final set. This applies across the whole resume, Trek bullets included.
4. **No repeated lead verbs** within this project, and preferably across the resume.
5. **Facts only.** Never change a number. Bullets marked **†** use candidate-supplied figures that are **not in the public README** (e.g., 100 tok/s, 7x, 5 models, INT4). Use them only after the README or benchmark notes are updated to back them.
6. **Ownership caveat.** The repo's S3 bucket and environment reference the employer's AWS dev account. Confirm with the employer that this can be presented as a personal open-source project.
7. **Mirror JD wording.** For example: "model serving" vs "inference", "speculative decoding", "quantization", "FinOps", "zero trust".

**Tag legend:**
- `PLAT` AI platform
- `INFRA` cloud/IaC
- `SERVE` model serving
- `PERF` performance
- `QUANT` quantization
- `MODEL` model selection
- `EVAL` evaluation
- `COST` FinOps
- `SEC` security
- `API` API compatibility
- `AGENT` agentic coding
- `OPS` reliability
- `CI` build/release
- `TEST` testing
- `DX` developer experience

---

## 1. Default set (general Staff/Principal AI platform roles)

- Architected self-hosted LLM inference platform serving Codex from vLLM on AWS GPUs via ECS, EC2 ASG and Terraform
- Boosted 27B model throughput 4.3x (14→60 tok/s) with MTP speculative decoding in vLLM, achieving 85–96% draft-token acceptance
- Benchmarked 4 open-weight LLMs on A10G/L40S GPUs; chose Qwen3-Coder-30B-A3B MoE after root-causing Devstral tool-call failures
- Reduced cold start 32% (17→11.5 min) and image size 74% (34→9GB) by streaming FP8 weights from S3 instead of baking them in
- Secured inference behind IAM+MFA-gated SSM tunnel with no public ingress; built Responses API proxy fixing vLLM 400s

---

## 2. Metric registry

| ID | Metric | Source | Status |
|---|---|---|---|
| C1 | 4 open-weight models (Qwen2.5-14B AWQ, Qwen3-Coder-30B-A3B AWQ MoE, 27B FP8+MTP, Devstral Small 2 24B) | README / models.json | ✅ (resume says 5 †) |
| C2 | ~60 tok/s decode, 27B FP8 + MTP, single L40S | README | ✅ |
| C3 | ~100 tok/s, 7x speedup | Candidate | † not in README |
| C4 | 4.3x speedup (≈14 → 60 tok/s with vs without MTP) | Benchmark notes file | ✅ |
| C5 | ~85% MTP draft acceptance (README); 85–96% (notes) | README / notes | ✅ (96% alone needs context) |
| C6 | Image 34GB → 9GB (~74% smaller) | README | ✅ |
| C7 | Cold start ~17 → ~11.5 min (~32% faster) | README | ✅ |
| C8 | 29GB FP8 checkpoint loaded in ~57s | README | ✅ |
| C9 | ~$0.52/hr (g5.xlarge) – ~$1.07/hr (g6e.xlarge), us-east-2 spot | README | ✅ |
| C10 | Spot ~65% off on-demand | README | ✅ (AWS discount, not a measured cut) |
| C11 | 30-min idle TTL auto-down; server max-warm cap | README | ✅ |
| C12 | FP8 KV cache ≈ 2x concurrent sessions | README | ✅ approx. |
| C13 | MoE: 128 experts, 8 active | README | ✅ |
| C14 | 32K (14B) / 65K (30B, 27B) context | README | ✅ |
| C15 | vLLM 0.30.0 Responses-API gaps (developer role, typed content) | README | ✅ |
| C16 | 2 GPU families: A10G 24GB, L40S 48GB | README | ✅ |
| C17 | 24–48GB GPU memory range | README | ✅ |
| C18 | INT4 quantization | Candidate | † README shows AWQ 4-bit; use "AWQ 4-bit" |

---

## 3. Bullet bank by theme

Format: **bullet** · `tags` · metric IDs

### A. Platform / overview (always pick one)

A1. Architected self-hosted LLM inference platform serving Codex from vLLM on AWS GPUs via ECS, EC2 ASG and Terraform · `PLAT INFRA` · –
A2. Built open-source platform running Codex CLI on self-hosted vLLM over AWS ECS GPUs, with Terraform IaC and scale-to-zero · `PLAT INFRA COST` · –
A3. Created self-hosted alternative to the OpenAI API: Codex CLI on vLLM over AWS GPUs, with 1-command up/down and $0 idle cost · `PLAT COST DX` · –
A4. Designed multi-account LLM serving stack (vLLM, AWS ECS, EC2 spot ASG, ECR, Terraform) replacing paid OpenAI API calls · `PLAT INFRA` · –
A5. Delivered Terraform-provisioned GPU inference stack (ECS, ASG capacity provider, ECR, IAM) serving Codex on vLLM on demand · `INFRA PLAT` · –
A6. Launched open-source vLLM inference platform on AWS ECS GPUs, letting Codex CLI run agentic coding on open-weight models · `PLAT AGENT` · –
A7. Architected end-to-end LLM inference platform: CLI client, vLLM GPU image and Terraform IaC on AWS ECS with scale-to-zero · `PLAT INFRA DX` · –

### B. Inference performance (MTP speculative decoding)

B1. Accelerated decode 4.3x to 60 tok/s on one L40S GPU via MTP speculative decoding on a 27B FP8 model at ~85% draft acceptance · `PERF SERVE` · C2 C4 C5
B2. Optimized vLLM serving with FP8 weights and MTP speculative decoding, reaching 60 tok/s on one L40S at ~85% draft acceptance · `PERF SERVE` · C2 C5
B3. Boosted 27B model throughput 4.3x (14→60 tok/s) with MTP speculative decoding in vLLM, achieving 85–96% draft-token acceptance · `PERF SERVE` · C2 C4 C5
B4. Increased single-GPU decode throughput 4.3x via MTP speculative decoding and CUDA graphs, serving a 27B FP8 model at 60 tok/s · `PERF SERVE` · C2 C4
B5. Boosted 27B model throughput 7x (14→100 tok/s) with MTP speculative decoding in vLLM, achieving ~96% token acceptance † · `PERF SERVE` · C3 C5
B6. Tuned vLLM serving (FP8, AWQ 4-bit, MTP speculative decoding, FP8 KV cache) for 60 tok/s decode on a single 48GB L40S GPU · `PERF SERVE QUANT` · C2 C17

### C. Quantization, model evaluation & selection

C1. Evaluated 4 open-weight models (14B–30B, AWQ/FP8, incl. MoE) on A10G and L40S GPUs for Codex tool-calling compatibility · `EVAL MODEL` · C1 C16
C2. Benchmarked 4 open-weight LLMs on A10G/L40S GPUs; chose Qwen3-Coder-30B-A3B MoE after root-causing Devstral tool-call failures · `EVAL MODEL AGENT` · C1 C16
C3. Evaluated 5 open models (AWQ/FP8/INT4, 14B–30B incl. MoE) on A10G, L40S GPUs for agentic coding task compatibility † · `EVAL MODEL` · C1
C4. Qualified 14B–30B open-weight models for agentic coding, diagnosing Mistral tool-call ID/schema mismatches breaking Codex · `EVAL AGENT` · –
C5. Profiled 4 open-weight coding LLMs on A10G and L40S GPUs, sizing VRAM, KV cache and 32K–65K context windows for agents · `EVAL MODEL PERF` · C1 C14
C6. Applied AWQ 4-bit and FP8 quantization plus FP8 KV cache to fit 14B–30B models on 24–48GB GPUs, ~doubling concurrent sessions · `QUANT PERF` · C12 C17
C7. Built config-driven model registry to swap 4 open-weight LLMs via one Terraform variable, with no code change across GPU types · `PLAT MODEL DX` · C1
C8. Assessed dense and MoE open-weight models (128 experts, 8 active) on 24–48GB GPUs, fitting VRAM, context and tool parsers · `MODEL EVAL` · C13 C17

### D. GPU FinOps / cost

D1. Engineered GPU FinOps: image 34GB→9GB, cold start 17→11.5 min, $0 idle, serving 14B–27B models at ~$0.52–1.07/hr · `COST PERF` · C6 C7 C9
D2. Drove GPU FinOps with scale-to-zero, spot capacity (~65% off) and 30-min idle auto-down, serving models at $0.52–1.07/hr · `COST` · C9 C10 C11
D3. Lowered GPU spend ~65% with spot capacity and scale-to-zero, running 14B–27B models at $0.52–1.07/hr and $0 when idle · `COST` · C9 C10
D4. Designed two-layer cost guardrails (client idle reaper + server max-warm cap) so GPUs scale to $0 even if a laptop closes · `COST OPS` · –
D5. Engineered GPU FinOps: scale-to-zero, ~65% spot savings and layered idle auto-shutdown so warm GPUs never bill unattended · `COST OPS` · C10

### E. Cold start & weight streaming

E1. Reduced cold start 32% (17→11.5 min) and image size 74% (34→9GB) by streaming FP8 weights from S3 instead of baking them in · `PERF INFRA COST` · C6 C7
E2. Streamed a 29GB FP8 checkpoint from S3 into GPU memory in ~57s via Run:ai Model Streamer, avoiding HF download and NAT fees · `PERF INFRA` · C8
E3. Replaced baked-in weights with S3 streaming via Run:ai Model Streamer, shrinking the vLLM image 74% and zeroing NAT egress · `INFRA COST` · C6
E4. Cut cold start from ~17 to ~11.5 min by streaming weights from S3 over a VPC gateway endpoint instead of HF downloads · `PERF INFRA` · C7

### F. Security / zero-trust access

F1. Secured inference behind IAM+MFA-gated SSM tunnel with no public ingress; built Responses API proxy fixing vLLM 400s · `SEC API` · –
F2. Enforced zero-trust access: IAM+MFA-gated SSM tunnels, isolated security groups, no public ingress and no API keys on wire · `SEC` · –
F3. Hardened access via MFA-backed IAM and SSM port-forwarding to a private GPU endpoint, exposing zero public ports or API keys · `SEC` · –
F4. Kept model traffic private with IAM-gated SSM port-forwarding and per-account MFA sessions, eliminating exposed endpoints · `SEC` · –

### G. API compatibility / agent integration

G1. Built OpenAI Responses API compatibility proxy fixing vLLM 400s (developer role, typed content), unblocking Codex on vLLM · `API AGENT` · C15
G2. Engineered OpenAI Responses API shim for vLLM, mapping developer→system roles and flattening typed content, with unit tests · `API TEST` · –
G3. Wrote streaming Responses API proxy rewriting roles and flattening content, turning vLLM 400 errors into 200s for every model · `API AGENT` · –
G4. Integrated Codex agent tool-calling with open-weight models on vLLM, curating MCP tools to fit 32K-context 14B deployments · `AGENT API` · C14

### H. Reliability, ops & CI

H1. Resolved single-GPU ECS rolling-deploy deadlock by pinning max 100%/min 0% and disabling AZ rebalancing, codified in Terraform · `OPS INFRA` · –
H2. Debugged ECS deploys stuck in PROVISIONING on a 1-GPU service; fixed rollout limits in Terraform for deadlock-free updates · `OPS INFRA` · –
H3. Automated x86 GPU image builds with AWS CodeBuild and ECR, bypassing slow ARM emulation to ship a 9GB vLLM serving image · `CI INFRA` · C6
H4. Unit-tested Responses API proxy rewrites (role mapping, chunk flattening) to guard Codex compatibility across vLLM upgrades · `TEST API` · –

### I. Concurrency & developer experience

I1. Scaled one GPU to many concurrent Codex sessions via vLLM continuous batching; FP8 KV cache ~doubled session capacity · `PERF SERVE` · C12
I2. Shipped multi-account CLI (up/chat/exec/resume/down) with per-env MFA sessions and tunnels, deployable to any AWS account · `DX PLAT SEC` · –
I3. Enabled concurrent agentic coding sessions over one shared tunnel via vLLM continuous batching with isolated session state · `AGENT PERF DX` · –

---

## 4. Do not claim (unless the README is updated)

- **"5 models", "INT4", "~100 tok/s" or "7x".** Not backed by the public repo yet. If you have newer benchmarks, add them to the README first.
- **Production users or traffic.** This is a personal or developer platform; there are no user, request-volume or uptime figures.
- **Training or fine-tuning.** Not done here; it's inference only.
- **Kubernetes.** It runs on ECS + EC2 ASG, not EKS/K8s.
- **"Cut GPU cost 65%" as a measured result.** That's AWS's spot discount. Phrase it as "spot capacity (~65% off)".

---

## 5. Presets by role type

| Target role | Bullets (in order) | Notes |
|---|---|---|
| **Staff/Principal AI Platform** | A1 · B1 · C2 · E1 · F1 | Default set; breadth plus depth |
| **ML Inference / Model Serving** | A6 · B3 · C6 · E2 · C5 | Speculative decoding, quantization, KV cache, weight streaming |
| **GPU / Cloud FinOps / Infra** | A5 · D2 · E1 · H1 · F2 | Cost guardrails, Terraform, deploy reliability |
| **Applied AI / Agents / Dev Tools** | A6 · C2 · G1 · I3 · B2 | Codex tool-calling, model choice, concurrency |
| **Security-minded platform** | A4 · F2 · G2 · D4 · H3 | Zero trust, MFA, tested proxy |
| **Founding / generalist** | A3 · B1 · D1 · F1 | Four-line compact version |
| **One-line only** | A2 or A3 | When space is tight |

**Before you finalize, check:**
- **Metrics:** no metric ID repeats. For example, D1 and E1 both use C6 and C7, so pick one of them.
- **Lead verbs:** no lead verb repeats.

---

## 6. JD keyword → bullet lookup

| JD says… | Prefer |
|---|---|
| LLM inference, model serving, vLLM, throughput, latency | B1–B6, I1 |
| speculative decoding, quantization, FP8, AWQ, KV cache | B1–B6, C6 |
| model evaluation, model selection, open-weight, MoE | C1–C8 |
| GPU, CUDA, A10G, L40S, VRAM | B4, C5, C6, C8 |
| cost optimization, FinOps, spot, autoscaling, scale-to-zero | D1–D5, A2, A3 |
| cold start, startup latency, model loading, S3 | E1–E4 |
| Terraform, IaC, AWS ECS, EC2, ECR, CodeBuild | A1, A4, A5, H1–H3 |
| security, zero trust, IAM, MFA, private networking | F1–F4 |
| OpenAI API, Responses API, compatibility, proxy | G1–G3 |
| agents, agentic coding, tool calling, MCP, Codex | A6, C2, C4, G4, I3 |
| reliability, deployment, incident, debugging | H1, H2 |
| testing, CI/CD | H3, H4, G2 |
| developer experience, CLI, multi-tenant/multi-account | I2, A3 |

---

## 7. Gaps to fill later

- **Measured latency:** p50/p95 time-to-first-token, plus tokens/s at 1, 4 and 8 concurrent sessions.
- **Cost comparison:** a cost-per-1M-tokens comparison against the OpenAI API, so you have a real "saved X%" claim.
- **A dated benchmark table** in the README for the 100 tok/s, 7x and INT4 claims, which would make the † bullets safe to use.
- **Adoption:** GitHub stars, forks or external users, if any.
