"""Pure preparation and identity checks shared by the two LinkedIn frontends."""

from copy import deepcopy
from datetime import datetime, timezone, timedelta
import re
from urllib.parse import urlparse

from modules.search_planner import SearchSpec, filters_snapshot, normalize_query, render_query, stable_id


def mapping(config):
    return dict(config) if isinstance(config, dict) else {key: value for key, value in vars(config).items() if not key.startswith("_")}


def company_names(company):
    names = [company.get("name", "")]
    for alias in company.get("aliases", []):
        value = alias.get("name", "") if isinstance(alias, dict) else alias
        if isinstance(value, str) and "://" not in value and "." not in value:
            names.append(value)
    return {normalize_company(value) for value in names if value}


def normalize_company(value):
    value = re.sub(r"\b(incorporated|inc|llc|ltd|corporation|corp)\b", "", str(value).casefold())
    return " ".join(re.findall(r"[a-z0-9]+", value))


def company_matches(company, name, linkedin_url=None):
    expected_url = company.get("linkedin_url") or company.get("company_linkedin_url")
    if expected_url and linkedin_url:
        return urlparse(expected_url).path.rstrip("/").casefold() == urlparse(linkedin_url).path.rstrip("/").casefold()
    return normalize_company(name) in company_names(company)


def priority_tier(company, title):
    from .careers import priority_tier as career_priority
    return career_priority(company, title)


def fresh_role(role, days=7):
    try:
        checked = datetime.fromisoformat(role["verified_at"].replace("Z", "+00:00"))
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return now - timedelta(days=days) <= checked <= now + timedelta(minutes=5)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def role_matches(title, description, spec):
    """Engineering-family/level guards, without a local fit score."""
    if not re.search(r"engineer|engineering|developer|architect|member(?: of)? technical staff|\bmts\b", title, re.I):
        return False
    if re.search(r"\b(intern|internship|junior|entry.level|new.grad)\b", title, re.I):
        return False
    if re.search(r"\b(sales|solutions|support|recruiting)\b", title, re.I):
        return False
    expected = spec.pipeline_context.get("career_roles", []) if spec.pipeline_context else []
    def levels(value):
        value = re.sub(r"\bmember(?: of)? technical staff\b", "", value, flags=re.I)
        return 3 if re.search(r"\bprincipal\b", value, re.I) else 2 if re.search(r"\bstaff\b", value, re.I) else 1 if re.search(r"\bsenior\b", value, re.I) else 0
    required = min((levels(row.get("title", "")) for row in expected), default=0)
    actual = levels(title)
    if required > 1 and actual and actual < required:
        return False
    # A related role must still concern the configured AI/platform engineering families.
    text = f"{title} {description}".casefold()
    families = ("software", "backend", "platform", "infrastructure", "systems", "inference", "sdk", "storage", "machine learning", "ml performance", "machines")
    return any(family in text for family in families) or bool(re.search(r"\b(?:ai|ml|sre)\b", text))


def prepare_specs(roles, profile, config):
    config, profile = mapping(config), mapping(profile)
    specs, errors = [], []
    grouped = {}
    for role in roles:
        role = deepcopy(role)
        company = role.get("company") or {}
        if role.get("status") != "open":
            continue
        if not fresh_role(role):
            errors.append({"record_id": role.get("id"), "code": "stale_verification", "message": "Run verify careers before LinkedIn execution"})
            continue
        if not company.get("id") or not company.get("name"):
            errors.append({"record_id": role.get("id"), "code": "missing_company", "message": "Verified company identity is required"})
            continue
        if role.get("company_id") and role["company_id"] != company["id"]:
            errors.append({"record_id": role.get("id"), "code": "identity_mismatch", "message": "Parent role company identity is inconsistent"})
            continue
        from .careers import evaluate_role
        for key, default in {"title": "", "description": "", "workplace_type": "Unknown", "employment_type": "Unknown", "locations": []}.items():
            role.setdefault(key, default)
        evaluate_role(role, config)
        if not role["eligible"]:
            errors.append({"record_id": role.get("id"), "code": "current_config_exclusion", "message": ", ".join(role["exclusion_reasons"])})
            continue
        allowed = {normalize_company(name) for name in config.get("companies", [])}
        if allowed and not allowed.intersection(company_names(company)):
            continue
        key = (company["id"], normalize_query(role.get("title", "")))
        grouped.setdefault(key, []).append(role)
    for (company_id, _), parents in grouped.items():
        primary = parents[0]
        company = deepcopy(primary["company"])
        title = primary["title"]
        scoped = dict(config, companies=[company["name"]])
        context = {
            "company": company, "company_id": company_id,
            "career_roles": deepcopy(parents), "career_job_ids": [row["id"] for row in parents],
            "verification_run_ids": list(dict.fromkeys(row.get("verification_run_id", "") for row in parents if row.get("verification_run_id"))),
            "priority_tier": priority_tier(company, title),
        }
        description_hint = " ".join(primary.get("description", "").split())[:400]
        query = render_query(title, profile, scoped)
        if description_hint:
            query += f" Role context: {description_hint}"
        specs.append(SearchSpec(
            query_id=stable_id("career_verified", f"{company_id}:{title}"), query_text=query,
            source="career_verified", mode="ai", profile_name=profile["profile_name"],
            profile_version=profile["profile_version"], filters_snapshot=filters_snapshot(scoped),
            quota=int(config.get("switch_number", 1)), classic_query=f"{company['name']} {title}",
            pipeline_context=context,
        ))
    specs.sort(key=lambda spec: spec.pipeline_context["priority_tier"])
    return specs, errors


def selected_specs(jobs, profile, config):
    roles = {}
    errors = []
    for job in jobs:
        for role in job.get("career_roles", []):
            roles[role.get("id")] = role
    specs, errors = prepare_specs(list(roles.values()), profile, config)
    by_parent = {role_id: spec for spec in specs for role_id in spec.pipeline_context["career_job_ids"]}
    selected, saved_specs = {}, {}
    for job in jobs:
        if not str(job.get("linkedin_id", "")).isdigit() or job.get("eligible") is not True:
            continue
        spec = next((by_parent[value] for value in job.get("career_job_ids", []) if value in by_parent), None)
        if spec is None:
            continue
        if job.get("company_id") != spec.pipeline_context["company_id"] or not company_matches(spec.pipeline_context["company"], (job.get("company") or {}).get("name", "")):
            errors.append({"record_id": job.get("id"), "code": "identity_mismatch", "message": "Selected job does not match its verified company"})
            continue
        saved = job.get("search_spec") or {}
        query_id = job.get("query_id") or saved.get("query_id") or spec.query_id
        query_text = job.get("query_text") or saved.get("query_text") or spec.query_text
        mode = job.get("search_mode", saved.get("mode", "ai"))
        if mode not in {"ai", "classic"} or not isinstance(query_id, str) or not query_id.strip() or not isinstance(query_text, str) or not query_text.strip():
            errors.append({"record_id": job.get("id"), "code": "invalid_search_metadata", "message": "Selected job needs valid query provenance"})
            continue
        original = deepcopy(spec)
        original.query_id, original.query_text, original.mode = query_id, query_text, mode
        original.classic_query = job.get("classic_query") or saved.get("classic_query") or spec.classic_query
        original.source = job.get("search_source") or saved.get("source") or spec.source
        original.profile_name = job.get("profile_name") or saved.get("profile_name") or spec.profile_name
        original.profile_version = job.get("profile_version") or saved.get("profile_version") or spec.profile_version
        # Current filters and verified parents remain authoritative; only query provenance is restored.
        key = query_id
        if key in saved_specs and (
                saved_specs[key].pipeline_context["company_id"] != job["company_id"]
                or any(getattr(saved_specs[key], name) != getattr(original, name) for name in (
                    "query_text", "classic_query", "mode", "source", "profile_name", "profile_version"))):
            errors.append({"record_id": job.get("id"), "code": "conflicting_query", "message": "A query ID cannot refer to different companies or queries"})
            continue
        saved_specs.setdefault(key, original)
        selected.setdefault(key, []).append(deepcopy(job))
    specs = sorted(saved_specs.values(), key=lambda spec: spec.pipeline_context["priority_tier"])
    return specs, selected, errors
