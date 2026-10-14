"""Lazy, validated stage settings and evidence-based company ordering.

Importing this module reads no configuration, starts no browser, and performs
no network requests. Unknown company facts remain unknown.
"""

from collections.abc import Mapping
from copy import deepcopy
import math
import os
import re


PUBLIC_SOURCES = (
    "greylock", "sequoia", "a16z", "yc", "hn", "hiringcafe",
    "wellfound", "crunchbase",
)
DEFAULTS = {
    "db_path": "data/job_pipeline/pipeline.sqlite3",
    "default_set": "startup-companies",
    "default_limit": 25,
    "sources": list(PUBLIC_SOURCES[:6]),
    "source_config": {},
    "discovery_limit_per_source": 50,
    "discovery_target_companies": 250,
    "discovery_source_limits": {},
    "discovery_refresh": False,
    "discovery_render_enabled": False,
    "verification_limit_companies": 25,
    "verification_refresh": False,
    "verification_render_enabled": False,
    "verification_prioritize_established": True,
    "verification_freshness_days": 7,
    "established_min_employees": 50,
    "established_funding_stages": [
        *("Series " + chr(letter) for letter in range(ord("B"), ord("Z") + 1)),
        "IPO", "Public",
    ],
    "public_render_max_pages": 5,
    "public_render_timeout_seconds": 15,
}


def _mapping(config):
    if config is None:
        from config import job_pipeline
        config = job_pipeline
    if isinstance(config, Mapping):
        return dict(config)
    try:
        return {key: value for key, value in vars(config).items() if not key.startswith("_")}
    except TypeError as error:
        raise ValueError("Pipeline configuration must be a mapping or configuration module") from error


def _positive_int(config, key):
    value = config[key]
    if type(value) is not int or value < 1:
        raise ValueError(f"{key} must be a positive integer")


def _boolean(config, key):
    if type(config[key]) is not bool:
        raise ValueError(f"{key} must be a boolean")


def _sources(value, key):
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{key} must be a list of public source names")
    if any(not isinstance(source, str) or source not in PUBLIC_SOURCES for source in value):
        raise ValueError(f"{key} contains an unsupported public source name")
    return list(dict.fromkeys(value))


def resolve_config(config=None, stage="discovery"):
    """Return stage defaults plus supplied values, validating only that stage.

    Legacy configurations with ``default_limit`` and no new stage budget keep
    that limit. A partial dictionary without either uses the new stage default.
    Other adapter options are preserved for callers.
    """
    if not isinstance(stage, str) or stage not in {"discovery", "verification"}:
        raise ValueError("Pipeline settings stage must be discovery or verification")
    supplied = _mapping(config)
    resolved = {**deepcopy(DEFAULTS), **supplied}
    budget = "discovery_limit_per_source" if stage == "discovery" else "verification_limit_companies"
    if budget not in supplied and "default_limit" in supplied:
        resolved[budget] = supplied["default_limit"]
    _positive_int(resolved, budget)
    for key in (stage + "_refresh", stage + "_render_enabled"):
        _boolean(resolved, key)

    if not isinstance(resolved["db_path"], (str, os.PathLike)) or not str(resolved["db_path"]).strip():
        raise ValueError("db_path must be a nonempty filesystem path")
    if not isinstance(resolved["default_set"], str) or not resolved["default_set"].strip():
        raise ValueError("default_set must be a nonempty string")

    if stage == "discovery":
        target = resolved["discovery_target_companies"]
        if target is not None:
            _positive_int(resolved, "discovery_target_companies")
        resolved["sources"] = _sources(resolved["sources"], "sources")
        for key in ("discovery_source_limits", "source_config"):
            if not isinstance(resolved[key], Mapping):
                raise ValueError(f"{key} must be a mapping keyed by public source name")
            _sources(list(resolved[key]), key)
            resolved[key] = dict(resolved[key])
        for source, value in resolved["discovery_source_limits"].items():
            if type(value) is not int or value < 1:
                raise ValueError(f"discovery_source_limits[{source!r}] must be a positive integer")
        for source, options in resolved["source_config"].items():
            if not isinstance(options, Mapping):
                raise ValueError(f"source_config[{source!r}] must be a mapping")
        resolved["source_config"] = deepcopy(resolved["source_config"])
    else:
        _boolean(resolved, "verification_prioritize_established")
        for key in ("verification_freshness_days", "established_min_employees"):
            _positive_int(resolved, key)
        stages = resolved["established_funding_stages"]
        if not isinstance(stages, (list, tuple)) or any(not isinstance(value, str) or not value.strip() for value in stages):
            raise ValueError("established_funding_stages must be a list of nonempty funding-stage names")
        if any(_funding_stage(value) is None for value in stages):
            raise ValueError("established_funding_stages contains an unrecognized funding-stage name")
        resolved["established_funding_stages"] = list(stages)

    # Renderer settings are relevant only when this stage requests rendering.
    if resolved[stage + "_render_enabled"]:
        _positive_int(resolved, "public_render_max_pages")
        timeout = resolved["public_render_timeout_seconds"]
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("public_render_timeout_seconds must be a finite positive number")
    return resolved


def employee_count_lower_bound(value):
    """Read an explicit count/range conservatively; never parse descriptions."""
    if type(value) is int:
        return value if value >= 0 else None
    if not isinstance(value, str):
        return None
    count = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
    match = re.fullmatch(
        rf"\s*({count})\s*(?:([-–—]|to)\s*({count})|\+)?\s*(?:employees?)?\s*",
        value, re.I,
    )
    if not match:
        return None
    lower = int(match[1].replace(",", ""))
    if match[3] is not None and int(match[3].replace(",", "")) < lower:
        return None
    return lower


def _funding_stage(value):
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.casefold().strip().split())
    series = re.fullmatch(r"series\s+([a-z])\s*\+?(?:\s+round)?", normalized)
    if series:
        return "series " + series[1]
    if normalized in {"pre-seed", "pre seed", "preseed"}:
        return "pre-seed"
    if normalized == "seed":
        return "seed"
    if normalized in {"ipo", "post-ipo", "post ipo"}:
        return "ipo"
    if normalized in {"public", "publicly traded"}:
        return "public"
    return None


def _company_maturity(company, config):
    count = employee_count_lower_bound(company.get("employee_count"))
    stage = _funding_stage(company.get("funding_stage"))
    established_stages = {_funding_stage(value) for value in config["established_funding_stages"]}
    established_stages.discard(None)
    if (count is not None and count >= config["established_min_employees"]
            or stage in established_stages):
        return "established"
    if (count is not None and count < config["established_min_employees"]
            or stage in {"pre-seed", "seed", "series a"}):
        return "early"
    return "unknown"


def company_maturity(company, config=None):
    """Classify only the explicit employee/funding facts in a company record."""
    return _company_maturity(company, resolve_config(config, "verification"))


def prioritize_companies(companies, config=None):
    """Stable established, early, unknown ordering before verification's budget."""
    config = resolve_config(config, "verification")
    companies = list(companies)
    if not config["verification_prioritize_established"]:
        return companies
    buckets = {"established": 0, "early": 1, "unknown": 2}
    return sorted(companies, key=lambda company: buckets[_company_maturity(company, config)])
