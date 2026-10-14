"""Pure search planning: no browser, credentials, or resume dependencies."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
import unicodedata


INTENT_FIELDS = (
    "search_location", "sort_by", "date_posted", "salary", "easy_apply_only",
    "experience_level", "job_type", "on_site", "companies", "location",
    "industry", "job_function", "job_titles", "benefits", "commitments",
    "under_10_applicants", "in_your_network", "fair_chance_employer",
)
GATE_FIELDS = (
    "about_company_bad_words", "about_company_good_words", "bad_words",
    "security_clearance", "did_masters", "current_experience",
)


def normalize_query(query):
    return " ".join(unicodedata.normalize("NFKC", query).casefold().split())


def stable_id(source, text):
    digest = hashlib.sha256(normalize_query(text).encode()).hexdigest()[:16]
    return f"{source}:{digest}"


def role_priority(title):
    if re.search(r"\bfounding\b", title, re.I):
        return 2
    leveled = re.sub(r"\bmember(?: of)? technical staff\b", "", title, flags=re.I)
    return 0 if re.search(r"\b(staff|principal)\b", leveled, re.I) else 1


def _get(config, name, default=None):
    return config.get(name, default) if isinstance(config, dict) else getattr(config, name, default)


def filters_snapshot(config):
    return {
        "intent": {key: deepcopy(_get(config, key)) for key in INTENT_FIELDS},
        "gates": {key: deepcopy(_get(config, key)) for key in GATE_FIELDS},
    }


def _text(value, name, max_length=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ValueError(f"{name} must be nonempty text of at most {max_length} characters")
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError(f"{name} contains control characters")
    return " ".join(value.split())


def _quota(value):
    if type(value) is not int or value < 1:
        raise ValueError("Search quota must be a positive integer")
    return value


def validate_profile(profile):
    for key in ("dynamic_search_enabled", "ai_query_refinement_enabled", "resume_search_enabled"):
        if type(_get(profile, key)) is not bool:
            raise ValueError(f"{key} must be True or False")
    for key in ("profile_name", "profile_version", "search_state_dir"):
        _text(_get(profile, key), key)
    for key in ("role_lanes", "skills"):
        values = _get(profile, key)
        if not isinstance(values, list):
            raise ValueError(f"{key} must be a list")
        for value in values:
            _text(value, key, 200)
    if _get(profile, "dynamic_search_enabled") and not _get(profile, "role_lanes"):
        raise ValueError("Dynamic search requires at least one role lane")
    searches = _get(profile, "manual_searches")
    if not isinstance(searches, list):
        raise ValueError("manual_searches must be a list")
    ids = set()
    for item in searches:
        if not isinstance(item, dict) or set(item) - {"id", "query", "enabled", "quota", "notes", "role_label"}:
            raise ValueError("Unsupported manual search definition")
        ident = _text(item.get("id"), "manual search id", 100)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", ident) or ident in ids:
            raise ValueError("Manual search IDs must be unique letters, numbers, dots, dashes, or underscores")
        ids.add(ident)
        _text(item.get("query"), "manual search query")
        if type(item.get("enabled", True)) is not bool:
            raise ValueError("Manual search enabled must be True or False")
        if item.get("quota") is not None:
            _quota(item["quota"])
        for key in ("notes", "role_label"):
            if key in item:
                _text(item[key], key)


@dataclass
class SearchSpec:
    query_id: str
    query_text: str
    source: str
    mode: str
    profile_name: str
    profile_version: str
    filters_snapshot: dict
    quota: int
    classic_query: str
    pipeline_context: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def render_query(role, profile, config):
    """Render requirements each run from the canonical config, never copied defaults."""
    snapshot = filters_snapshot(config)
    intent, gates = snapshot["intent"], snapshot["gates"]
    opening = role if re.match(r"(?i)^(find|search|looking)\b", role) else f"Find {role} roles"
    parts = [opening.rstrip(".") + "."]
    if intent["search_location"]:
        parts.append(f"Location: {intent['search_location']}.")
    labels = {
        "job_type": "Employment type", "on_site": "Work arrangement",
        "experience_level": "Experience level", "companies": "Companies",
        "location": "Additional locations", "industry": "Industries",
        "job_function": "Job functions", "job_titles": "Job titles",
        "benefits": "Benefits", "commitments": "Company commitments",
    }
    for key, label in labels.items():
        if intent[key]:
            parts.append(f"{label}: {', '.join(intent[key])}.")
    if intent["date_posted"] and intent["date_posted"] != "Any time":
        parts.append(f"Posted within the {intent['date_posted'].lower()}.")
    if intent["salary"]:
        parts.append(f"Salary: {intent['salary']}.")
    for key, wording in {
        "easy_apply_only": "Use Easy Apply when available.",
        "under_10_applicants": "Prefer jobs with under 10 applicants.",
        "in_your_network": "Prefer jobs in my network.",
        "fair_chance_employer": "Prefer fair chance employers.",
    }.items():
        if intent[key]:
            parts.append(wording)
    if _get(profile, "skills"):
        parts.append(f"Focus on {', '.join(_get(profile, 'skills'))}.")
    # These hints help discovery. The existing post-discovery gates still enforce them.
    if gates["about_company_bad_words"]:
        parts.append(f"Exclude companies described as: {', '.join(gates['about_company_bad_words'])}.")
        if gates["about_company_good_words"]:
            parts.append(f"Allow company exceptions matching: {', '.join(gates['about_company_good_words'])}.")
    if gates["bad_words"]:
        parts.append(f"Exclude descriptions containing: {', '.join(gates['bad_words'])}.")
    if gates["security_clearance"] is False:
        parts.append("Exclude roles requiring security clearance or polygraph checks.")
    if gates["current_experience"] is not None and gates["current_experience"] >= 0:
        allowance = "; allow two additional years for roles mentioning a master's degree" if gates["did_masters"] else ""
        parts.append(f"Require at most {gates['current_experience']} years of experience{allowance}.")
    return " ".join(parts)


def validate_refinement(response, roles):
    """AI may propose role wording, never quotas, gates, IDs, URLs, or browser actions."""
    if isinstance(response, str):
        response = json.loads(response)
    if not isinstance(response, dict) or set(response) != {"queries"}:
        raise ValueError("Expected only a queries object")
    rows = response["queries"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= min(48, len(roles) * 2):
        raise ValueError("Invalid number of refined query lanes")
    seen, covered, variants = set(), set(), {}
    result = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"role", "role_index", "coverage"}:
            raise ValueError("Unsupported refined query shape")
        role = _text(row["role"], "refined role", 200)
        index, coverage = row["role_index"], row["coverage"]
        if type(index) is not int or not 0 <= index < len(roles):
            raise ValueError("Unsupported role index")
        if type(coverage) not in (int, float) or not 0 <= coverage <= 1:
            raise ValueError("Coverage must be a finite number between zero and one")
        tokens = set(re.findall(r"[a-z]+", normalize_query(role)))
        original = set(re.findall(r"[a-z]+", normalize_query(roles[index])))
        seniority = original.intersection({"staff", "principal", "founding", "senior", "lead", "junior"})
        forbidden = {"ignore", "apply", "exclude", "prefer", "salary", "remote", "hybrid", "clearance", "instructions", "override"}
        specialty = original - {"engineer", "developer", "roles", "staff", "principal", "founding", "senior"}
        engineering = {"engineer", "engineering", "developer", "architect"}
        new_filter_words = (tokens - original).intersection({
            "in", "near", "at", "within", "posted", "located", "salary", "contract", "benefits",
        })
        if (specialty and not tokens.intersection(specialty)
                or not seniority.issubset(tokens) or tokens.intersection(forbidden)
                or original.intersection(engineering) and not tokens.intersection(engineering)
                or new_filter_words
                or not re.fullmatch(r"[\w\s+#/().-]+", role)):
            raise ValueError("Refinement is outside the configured role intent")
        normalized = normalize_query(role)
        if normalized in seen:
            raise ValueError("Duplicate AI role lane")
        seen.add(normalized)
        covered.add(index)
        variants[index] = variants.get(index, 0) + 1
        if variants[index] > 2:
            raise ValueError("At most two variants are supported for each role")
        result.append((coverage, role, index))
    if covered != set(range(len(roles))):
        raise ValueError("Refinement must cover every configured role lane")
    return sorted(result, key=lambda item: -item[0])


def build_search_plan(profile, config, refine=None, warn=lambda message: None):
    validate_profile(profile)
    quota = _quota(_get(config, "switch_number", 1))
    snapshot = filters_snapshot(config)
    specs, seen = [], set()

    def add(query, source, ident=None, limit=None, classic=None):
        original = _text(query, "query", 12000)
        query = render_query(original, profile, config)
        normalized = normalize_query(query)
        if normalized in seen:
            return
        seen.add(normalized)
        specs.append(SearchSpec(
            ident or stable_id(source, original), query, source, "ai",
            _get(profile, "profile_name"), _get(profile, "profile_version"),
            deepcopy(snapshot), quota if limit is None else _quota(limit), classic or original,
        ))

    for item in _get(profile, "manual_searches"):
        if item.get("enabled", True):
            add(item["query"], "manual", f"manual:{item['id'].strip()}", item.get("quota"), item.get("role_label"))
    for term in _get(config, "search_terms", []):
        add(term, "legacy")
    if _get(profile, "dynamic_search_enabled"):
        roles = _get(profile, "role_lanes")
        lanes = [(1, role, index) for index, role in enumerate(roles)]
        source = "generated"
        if _get(profile, "ai_query_refinement_enabled"):
            if refine is None:
                warn("AI search refinement unavailable; using deterministic search queries.")
            else:
                try:
                    lanes = validate_refinement(refine(roles, _get(profile, "skills"), snapshot), roles)
                    source = "ai_refined"
                except Exception as error:
                    warn(f"AI search refinement failed ({type(error).__name__}); using deterministic search queries.")
        try:
            for _, role, index in lanes:
                add(role, source, classic=role)
        except Exception as error:
            if not specs:
                raise
            warn(f"Dynamic generation failed ({type(error).__name__}); continuing manual and legacy searches.")
    if not specs:
        raise ValueError("Configure at least one enabled manual, legacy, or generated search")
    specs.sort(key=lambda spec: role_priority(spec.classic_query))
    return specs
