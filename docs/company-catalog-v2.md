# Company catalog v2: researched industry, technical fit and next action

## Deliverables

Repository: `/Users/deepakbasavaraju/Documents/GitHub/jobrobo`.

| File | Purpose |
|---|---|
| `data/company_names.json` | **Original v1, unchanged byte-for-byte.** |
| `data/company_names.v2.json` | Newer version, now enriched through a public-source review of every company. |
| `data/company_names.v2.csv` | Minimal quick view: one row per company, derived from the updated JSON. |
| `data/company_names.v2.schema.json` | JSON Schema 2020-12: structure, enum and evidence validation. |
| `scripts/build_company_catalog_v2.py` | Initial saved-source builder and common integrity/schema checks. |
| `scripts/update_company_catalog_research.py` | Integrates reviewed research batches and generates/checks CSV. |

All **292 names**, aliases, source-task memberships, provenance, original identity flags and tiers remain in their original order. Original SHA-256: `a29aa2cea3f8005b6ac251b7431ed2567fbb0a3ca195304d9c58eda450562ffe`.

The latest pass reviewed all 292 entries against **302 public official/company or investor source references**, using saved domains, descriptions and source cohorts to avoid namesake collisions. Each row records the source, date, summary and limitations. Some evidence is an indexed official-source extract rather than a fully opened page; this distinction is recorded, not hidden. A public-source classification is not a legal-employer verification or a hiring guarantee.

Nothing is wired into JobRobo execution settings. No applications, employer contact, application-history reconciliation, task-status changes, commit or push were performed.

## Current coverage

| Primary industry | Count |
|---|---:|
| `ai_agents` | 18 |
| `infrastructure_devtools` | 39 |
| `enterprise_software` | 43 |
| `fintech` | 56 |
| `security` | 20 |
| `robotics_industrial` | 44 |
| `healthcare` | 24 |
| `consumer` | 28 |
| `other` | 20 |
| `unknown` | 0 |
| **Total** | **292** |

All 292 have a primary industry and a catalog-identity match; confidence is **207 high / 85 medium**. These are confidence in the broad classification, not candidate-fit scores. Grouped names remain grouped watchlist entities, not separate legal-employer counts.

**158** companies have one or more supported technical-domain tags. **134** have `no_supported_tag`: reviewed evidence did not support one of the six specific technical tags. This does **not** mean poor fit or no engineering jobs. Technical tags were not manufactured to fill every row.

Overlapping tag counts: AI agents/RAG **94**; backend/distributed systems **42**; ML infrastructure **31**; robotics software **25**; Kubernetes/SRE **11**; full-stack **6**. Do not sum overlapping tags as companies.

Company next actions: **208 research**, **84 watchlist**. All nine historical identity holds received a matching public-source identity review; the historical v1 flags remain intact, while current resolution lives under `classification.research_review.identity`.

### Important identity corrections

- **Sentra:** `sentra.app`, the source-cohort organizational-memory startup, not the similarly named security firm.
- **Neon:** the Speedrun game-commerce/payment company, not the database company or the separately retained Open Education Applications / Neon.
- **Cleo:** `hicleo.com` family-care platform, not the finance chatbot.
- **Hercules:** `hercules.app`, the source-cohort app builder, not `hercules.ai`.
- **Dream / Dream Labs:** distinct built-environment design and robotics entities.
- **Syncere:** official funding announcement connects the company to its LUME home-robot product; these are not conflicting employer identities.
- **SuperMe:** official Series A announcement matches the expert-knowledge network and supplied company description.
- **Munari Labs:** investor-cohort mapping supports the Munari product identity; historical legal-name equivalence remains explicitly unestablished.

Inspect each company's source and limitations for the exact basis. A retained catalog name is not silently renamed or merged.

## Overall JSON structure

```text
{
  schema_version: 2,
  ... unchanged original top-level metadata,
  derived_from: {path, sha256, schema_version: 1},
  classification_policy: {
    classified_at_utc,
    method: "public_source_review_v1",
    scope, industry_assignment, identity_resolution_policy,
    identity_holds_preserved: true,
    runtime_integration: false,
    companies_reviewed: 292,
    research_coverage: {
      with_public_sources, identity_confirmed,
      identity_ambiguous, unknown_industry
    },
    source_hashes_verified: [{source_id, sha256}],
    enums: {industry: [...], tech_fit: [...], company_next_action: [...]},
    ... initial-pass metadata
  },
  classification_counts: {
    companies, industry: {enum: count}, status: {enum: count},
    tech_fit_tags_overlapping: {enum: count}, companies_with_tech_tags
  },
  companies: [{
    name, aliases, source_tasks, provenance,
    ... unchanged original optional fields,
    classification: {
      classified_at_utc, method,
      industry: {value, confidence, evidence: [...], reason},
      tech_fit: {
        assessment, tags: [{value, confidence, evidence: [...]}], reason
      },
      status: {
        value, scope: "company_next_action", reason,
        basis_provenance_indices: [0, ...]
      },
      research_review: {
        identity, rationale, limitations,
        sources: [{url, title, excerpt, checked_at_utc}],
        checked_at_utc
      }
    }
  }]
}
```

Legacy `generated_at_utc`, `counts`, `validation`, `source_manifest` and tier labels describe the original compilation, not this fresh research. Use `classification_policy.classified_at_utc`, `research_review` and `classification_counts` for the updated review. Original tiers remain under `companies[*].provenance[*].tier`; they are neither industry categories nor fit scores. The old `industry_precedence` describes the initial rules pass only; current assignments use reviewed product/customer context.

## Industry enum: exactly one per company

| Value | Definition |
|---|---|
| `ai_agents` | General AI models, agents or AI-native platforms where no narrower primary vertical is more useful. |
| `infrastructure_devtools` | Cloud/data infrastructure, databases, networking, observability, inference and developer tools. |
| `enterprise_software` | Business, productivity, workflow, marketing or enterprise applications. |
| `fintech` | Finance, payments, insurance, payroll, financial compliance, crypto and financial/prediction-market infrastructure. |
| `security` | Cybersecurity, application/data security, human-risk security and privacy/security-centric products. |
| `robotics_industrial` | Robotics, autonomy, defense, aviation, space, semiconductors/hardware, energy, manufacturing and built-environment/physical systems. |
| `healthcare` | Health, clinical, therapeutics, biotech and veterinary care. |
| `consumer` | Consumer/community/media/retail/marketplace products and services. |
| `other` | Evidenced sectors outside the above buckets, including education, consulting and sustainability services. |
| `unknown` | Insufficient industry evidence or unresolved intended identity. Supported for future updates, unused in this pass. |

This is a pragmatic broad taxonomy, not a legal industry code. Prefer the primary product/customer vertical over enabling technology: insurance AI remains fintech; clinical AI remains healthcare. Investor cohort, company name, funding stage and a generic job title are not industry evidence. Diversified groups are classified at the retained target scope (e.g. Amazon / AWS), with uncertainty recorded.

## Technical-fit enum: overlapping tags, not scores

| Value | Required domain signal |
|---|---|
| `backend_distributed_systems` | Backend/API/platform services, distributed systems, streaming, storage or serverless. |
| `kubernetes_sre` | Kubernetes/k8s, SRE, DevOps/DevSecOps or operational reliability/observability. |
| `ai_agents_rag` | Agents, agentic workflows, harnesses, retrieval or RAG. |
| `full_stack` | Explicit full-stack or frontend/backend web-application engineering/platform capabilities. |
| `ml_infrastructure` | Model serving/inference, ML platform, MLOps, research or model-evaluation infrastructure. |
| `robotics_software` | Robotics, autonomy, robotic perception or related physical-system software. |

Assessment enum:

- `domain_overlap_only`: one or more evidence-supported tags.
- `no_supported_tag`: researched, but no sufficiently specific supported tag in the reviewed material.
- `not_assessed`: supported for the initial/legacy classification method; not used in this updated pass.

The tags describe product/technical-domain relevance. They are **not** a verified resume match, current job requirement, or assurance of openings. Do not infer level, pay, location, remote eligibility, sponsorship, work authorization or permission to apply. Those checks belong to the exact requisition and the resume actually used for that firm. Empty tags deliberately avoid adding generic backend/full-stack tags merely because a firm employs engineers.

## Company next-action status enum

| Value | Entry condition |
|---|---|
| `research` | Continue to exact current requisitions and candidate-fit checks. A researched company can still have this next action. |
| `qualified_opening_found` | A specific current role has recorded URL/date and satisfied role-level fit checks. Not assigned here; broad company research is insufficient. |
| `watchlist` | Existing explicit priority watchlist membership, initially Task 26. Not a claim about vacancy availability. |
| `identity_needs_verification` | Intended company still ambiguous; do not attribute roles or technical tags until resolved. |
| `deprioritized` | Deliberate documented decision with a reason, never inferred from missing evidence alone. Not assigned here. |

The scope is always `company_next_action`. This is **not** a task-tracker status (`Review`, `Done`, etc.), vacancy state or application history. Do not infer `applied`, `interviewing`, `rejected` or `not_applied`. Reconcile application history separately **per requisition**.

Current rule: ambiguous identity wins; otherwise Task 26 membership remains `watchlist`; others remain `research`. Resolving an identity hold does not authorize applying. `basis_provenance_indices` addresses the same company's unchanged provenance array; current identity evidence is in `research_review.sources`.

## Evidence and confidence contract

The current public-evidence shape is:

```json
{
  "url": "https://example.com/product",
  "title": "Official product page",
  "excerpt": "Brief paraphrase of the observed product or technical-domain evidence.",
  "checked_at_utc": "2026-11-14T02:42:06.256Z"
}
```

The example is illustrative, not a real company citation. `excerpt` is a short evidence summary, not a claim of verbatim quotation. `checked_at_utc` records this research observation, not publication date or a guarantee that the fact will remain current. Per-company `limitations` distinguish fully opened sources from indexed source extracts, partial/blocked pages, grouped brands and unresolved legal-name details. Reused evidence can support both industry and tags; read its substance rather than treating the presence of a URL as proof of every possible tag.

The schema also accepts the initial saved-source evidence shape `{source_id, record_pointer, field, source_observed_at, excerpt}`. Resolve that through the unchanged `source_manifest`; `field` is one of `description`, `category`, `acquisition.note`, `roles.title`, `ownership_evidence`. A null legacy source date remains unknown, not the time of fresh verification.

Confidence enum:

- `high`: explicit product/domain evidence with a clear catalog identity match.
- `medium`: broad inference, composite target or indexed/partial evidence requiring more caution.
- `low`: weak but useful provisional evidence; unused here.
- `unknown`: industry only, no supported classification. Technical tags are omitted instead of adding an unknown tag.

Current identity enum: `confirmed` / `ambiguous`. Confirmed means the **intended catalog company/product** matches the evidence; it does not certify its employing legal entity, ownership, all brands, or the continuing availability of a vacancy. No source instructions are execution authorization.

## CSV quick view

`data/company_names.v2.csv` has exactly one header and **292 rows**, in JSON order:

```text
name,industry,tech_fit_tags,status,confidence,identity,source_tasks,tiers,reference_url,checked_at_utc
```

Multiple tags, tasks and tiers are joined with ` | ` inside one cell. `reference_url` is the first recorded public evidence URL, which may be an investor profile rather than the company's homepage. JSON remains authoritative for multiple sources, uncertainty and explanations. The CSV is generated only after the JSON enrichment has been validated and is checked as an exact projection. It contains no application-state assumptions.

## Validation and maintenance

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/build_company_catalog_v2.py --check
PYTHONDONTWRITEBYTECODE=1 python3 scripts/update_company_catalog_research.py --check
```

Checks include schema/enums; 292 unique normalized names; exact preservation of all v1 company fields and legacy metadata; unchanged v1 SHA-256; count reconciliation; evidence/identity/tag/status invariants; and CSV field/order/value equality across all 292 rows. The installed `jsonschema` package is used. Focused negative tests also rejected duplicate/missing research rows, invalid tags, unsupported classifications, invalid industries, changed names/provenance/counts, application-status leakage, CSV corruption and loss of research identity evidence. These are data-integrity checks, not a full JobRobo application test suite or live vacancy qualification.

Inspect a real entry:

```python
import json
from pathlib import Path
catalog = json.loads(Path('data/company_names.v2.json').read_text())
print(json.dumps(next(c for c in catalog['companies'] if c['name'] == 'OpenAI'), indent=2))
```

The initial builder now **refuses to overwrite a publicly researched v2** with the old keyword pass, even with `--rebuild-v2`. The research updater accepts reviewed batch arrays with one exact-name entry per company, validates the complete 292-company set and atomically replaces each validated output. Preserve source evidence and review manual edits before regenerating. Keep v1 unchanged; use explicit reviewed v2 updates or a new version for later taxonomy changes. No separate classification tracker ID was fabricated.
