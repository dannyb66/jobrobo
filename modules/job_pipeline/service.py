"""Independent discovery and verification stages over cumulative named sets."""

from copy import deepcopy
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import StageResult, read_artifact, utc_now
from .store import PipelineStore


def _config(config):
    if config is None:
        from config import job_pipeline
        config = job_pipeline
    return dict(config) if isinstance(config, Mapping) else {name: value for name, value in vars(config).items() if not name.startswith("_")}


def _stage_config(config, stage, **overrides):
    from .settings import resolve_config
    supplied = _config(config)
    supplied.update({name: value for name, value in overrides.items() if value is not None})
    return resolve_config(supplied, stage)


@contextmanager
def _stage_renderer(render, config, stage):
    if render is not None or not config[stage + "_render_enabled"]:
        yield render
    else:
        from .rendering import public_renderer
        with public_renderer(config) as renderer:
            yield renderer


def load_inputs(store, inputs, expected_stage):
    """Inputs may be versioned JSON artifacts or persisted stage set names."""
    artifacts = []
    for value in inputs:
        if isinstance(value, (dict, StageResult)):
            artifact = read_artifact(value, expected_stage)
        elif Path(value).is_file() or str(value).lower().endswith(".json"):
            artifact = read_artifact(value, expected_stage)
        else:
            name = str(value)
            if name.startswith(expected_stage + ":"):
                name = name[len(expected_stage) + 1:]
            records = store.load_set(expected_stage, name)
            if not records:
                raise ValueError(f"Unknown or empty {expected_stage} input set: {name}")
            artifact = StageResult.create(expected_stage, name, "stored-set:" + name, records)
        artifacts.append(artifact)
    # Validate all inputs before making any import persistent.
    return [store.import_artifact(artifact, expected_stage) for artifact in artifacts]


def _inputs_id(artifacts):
    return list(dict.fromkeys(f"{artifact.stage}:{artifact.set_name}" for artifact in artifacts))


def _error(source, error):
    return {"source": source, "code": type(error).__name__, "message": str(error), "retryable": True}


def discover_companies(input_sets=(), set_name=None, limit=None, db_path=None,
                       sources=None, refresh=None, config=None, discover=None, client=None, render=None,
                       target_companies=None, render_enabled=None):
    if target_companies is not None and (type(target_companies) is not int or target_companies < 0):
        raise ValueError("Discovery target must be a nonnegative integer; 0 disables it")
    configured_sources = sources
    if sources is not None:
        if not isinstance(sources, (list, tuple)) or any(not isinstance(source, str) or not source for source in sources):
            raise ValueError("Discovery sources must be a list of source names")
        if discover is not None:
            # Injected adapters may use diagnostic/custom names; built-in adapters use the public allowlist.
            from .settings import PUBLIC_SOURCES
            configured_sources = [source for source in sources if source in PUBLIC_SOURCES]
    if target_companies == 0:
        config = dict(_config(config), discovery_target_companies=None)
    config = _stage_config(config, "discovery", discovery_limit_per_source=limit,
                           discovery_refresh=refresh, discovery_render_enabled=render_enabled,
                           discovery_target_companies=None if target_companies == 0 else target_companies,
                           sources=configured_sources, db_path=db_path, default_set=set_name)
    limit_overridden = limit is not None
    limit, refresh = config["discovery_limit_per_source"], config["discovery_refresh"]
    target = config["discovery_target_companies"]
    set_name = config["default_set"] if set_name is None else set_name
    db_path = config["db_path"] if db_path is None else db_path
    if discover is None:
        from .sources import discover_source
        discover = discover_source
    selected = list(sources if sources is not None else config.get("sources", []))
    with PipelineStore(db_path) as store:
        artifacts = load_inputs(store, input_sets, "companies")
        run_id = store.begin_run("companies", set_name, _inputs_id(artifacts), {
            "sources": selected, "limit": limit, "source_limits": {} if limit_overridden else config["discovery_source_limits"],
            "target_companies": target, "refresh": refresh, "render_enabled": config["discovery_render_enabled"],
        })
        delta, errors = [], []
        successful_sources = len(artifacts) + bool(store.load_set("companies", set_name))
        try:
            with _stage_renderer(render, config, "discovery") as render:
                for artifact in artifacts:
                    delta.extend(store.upsert_many("companies", set_name, artifact.records, run_id, artifact.created_at))
                for source in selected:
                    remaining = None if target is None else target - len(store.load_set("companies", set_name))
                    if remaining is not None and remaining <= 0:
                        break
                    source_limit = limit if limit_overridden else config["discovery_source_limits"].get(source, limit)
                    if remaining is not None:
                        source_limit = min(source_limit, remaining)
                    checkpoint_key = "discover:" + source
                    checkpoint = None if refresh else store.get_checkpoint(checkpoint_key, set_name)
                    if isinstance(checkpoint, dict) and checkpoint.get("complete"):
                        successful_sources += 1
                        continue
                    cursor = checkpoint.get("cursor") if isinstance(checkpoint, dict) else checkpoint
                    try:
                        source_config = {**config, **config.get("source_config", {}).get(source, {})}
                        result = discover(source, source_config, cursor=cursor, limit=source_limit, client=client, render=render)
                        records = list(result.get("records", []))[:source_limit]
                        delta.extend(store.upsert_many("companies", set_name, records, run_id))
                        source_errors = list(result.get("errors", []))
                        errors.extend(source_errors)
                        if not source_errors or records:
                            successful_sources += 1
                        # Failed pages retain their prior cursor; success advances independently.
                        if not source_errors or records:
                            store.save_checkpoint(checkpoint_key, set_name, {"cursor": result.get("cursor"), "complete": bool(result.get("complete"))})
                    except Exception as error:
                        errors.append(_error(source, error))
            status = "complete" if not errors else "partial" if successful_sources else "failed"
            store.finish_run(run_id, status, errors)
        except BaseException:
            store.finish_run(run_id, "interrupted", errors)
            raise
        cumulative = store.load_set("companies", set_name)
        # Return canonical cumulative forms after possible alias merges.
        ids = {record["id"] for record in delta}
        delta = [record for record in cumulative if record["id"] in ids]
        return StageResult.create("companies", set_name, run_id, cumulative, delta, errors, _inputs_id(artifacts))


def verify_careers(input_sets=(), set_name=None, limit=None, db_path=None,
                   refresh=None, search_config=None, verify=None, client=None, render=None,
                   config=None, render_enabled=None, prioritize_established=None, resume_path=None):
    from .ranking import load_resume_profile, rank_roles
    resume_profile = load_resume_profile(resume_path) if resume_path is not None else None
    config = _stage_config(config, "verification", verification_limit_companies=limit,
                           verification_refresh=refresh, verification_render_enabled=render_enabled,
                           verification_prioritize_established=prioritize_established,
                           db_path=db_path, default_set=set_name)
    limit, refresh = config["verification_limit_companies"], config["verification_refresh"]
    freshness_days = config["verification_freshness_days"]
    set_name = config["default_set"] if set_name is None else set_name
    db_path = config["db_path"] if db_path is None else db_path
    if search_config is None:
        from config import search
        search_config = search
    if verify is None:
        from .careers import verify_company
        verify = verify_company
    from .careers import priority_tier, evaluate_verification_role
    with PipelineStore(db_path) as store:
        artifacts = load_inputs(store, input_sets, "companies")
        if artifacts:
            companies = [record for artifact in artifacts for record in artifact.records]
            companies = list({record["id"]: record for record in companies}.values())
        else:
            companies = store.load_set("companies", set_name)
            if not companies:
                raise ValueError("No companies available; discover or import a companies set first")
        from .settings import prioritize_companies
        companies = prioritize_companies(companies, config)
        input_ids = _inputs_id(artifacts) or ["companies:" + set_name]
        run_id = store.begin_run("verified_roles", set_name, input_ids, {
            "limit": limit, "refresh": refresh, "freshness_days": freshness_days,
            "prioritize_established": config["verification_prioritize_established"],
            "established_min_employees": config["established_min_employees"],
            "established_funding_stages": config["established_funding_stages"],
            "render_enabled": config["verification_render_enabled"],
        })
        delta, errors = [], []
        successful_companies = int(bool(store.load_set("verified_roles", set_name)))
        checked = 0
        try:
            with _stage_renderer(render, config, "verification") as render:
                for company in companies:
                    if checked >= limit:
                        break
                    checkpoint_key = "verify:" + company["id"]
                    checkpoint = None if refresh else store.get_checkpoint(checkpoint_key, set_name)
                    if isinstance(checkpoint, dict) and checkpoint.get("complete"):
                        try:
                            verified_at = datetime.fromisoformat(checkpoint["verified_at"].replace("Z", "+00:00"))
                            if verified_at.tzinfo is None:
                                verified_at = verified_at.replace(tzinfo=timezone.utc)
                            now = datetime.now(timezone.utc)
                            if now - timedelta(days=freshness_days) <= verified_at <= now + timedelta(minutes=5):
                                # Recompute derived decisions without claiming a new careers observation.
                                cached = []
                                for previous in store.load_set("verified_roles", set_name):
                                    if previous.get("company_id") == company["id"]:
                                        updated = dict(previous, company=company)
                                        updated["priority_tier"] = priority_tier(company, previous.get("title", ""), config)
                                        evaluate_verification_role(updated, search_config)
                                        cached.append(updated)
                                delta.extend(store.upsert_many("verified_roles", set_name, cached, run_id))
                                successful_companies += 1
                                continue
                        except (KeyError, TypeError, ValueError):
                            pass
                    checked += 1
                    try:
                        result = verify(company, search_config, client=client, render=render)
                        now = utc_now()
                        records = []
                        for raw in result.get("records", []):
                            record = deepcopy(raw)
                            record.setdefault("company", company)
                            record.setdefault("company_id", company["id"])
                            record.setdefault("verified_at", now)
                            record["verification_run_id"] = run_id
                            record["priority_tier"] = priority_tier(record["company"], record.get("title", ""), config)
                            records.append(record)
                        company_update = {**company, "hiring_status": result.get("status", "unknown"), "careers_verified_at": now}
                        store.upsert_many("companies", set_name, [company_update], run_id)
                        updated = store.upsert_many("verified_roles", set_name, records, run_id)
                        delta.extend(updated)
                        source_errors = list(result.get("errors", []))
                        errors.extend(source_errors)
                        complete = bool(result.get("complete")) and not source_errors
                        if complete or records:
                            successful_companies += 1
                        if complete:
                            observed_ids = {record["id"] for record in updated}
                            for record in records:
                                if record.get("id"):
                                    current = store.resolve_record("verified_roles", record["id"])
                                    if current:
                                        observed_ids.add(current["id"])
                            # Include unchanged role IDs too, resolved by their saved identity.
                            observed_urls = {record.get("career_url") for record in records if record.get("career_url")}
                            raw_ids = {record.get("id") for record in records}
                            vanished = []
                            for previous in store.roles_for_company(company["id"]):
                                if previous.get("company_id") != company["id"] or previous.get("status") != "open":
                                    continue
                                if previous["id"] in observed_ids or previous["id"] in raw_ids or previous.get("career_url") in observed_urls:
                                    continue
                                closed = evaluate_verification_role({**previous, "status": "closed", "verified_at": now, "verification_run_id": run_id}, search_config)
                                closed["exclusion_reasons"].append("No longer listed on complete careers board")
                                closed["verification_exclusion_reasons"] = list(closed["exclusion_reasons"])
                                vanished.append(closed)
                            delta.extend(store.upsert_many("verified_roles", set_name, vanished, run_id))
                            store.save_checkpoint(checkpoint_key, set_name, {"complete": True, "verified_at": now})
                        elif not source_errors:
                            errors.append({"source": company["id"], "code": "incomplete", "message": "Careers verification incomplete; previous roles retained", "retryable": True})
                    except Exception as error:
                        errors.append(_error(company["id"], error))
            status = "complete" if not errors else "partial" if successful_companies else "failed"
            store.finish_run(run_id, status, errors)
        except BaseException:
            store.finish_run(run_id, "interrupted", errors)
            raise
        # Presentation metadata is recomputed, not persisted as fresh careers evidence.
        cumulative = rank_roles(store.load_set("verified_roles", set_name), resume_profile)
        changed_ids = {record["id"] for record in delta}
        return StageResult.create("verified_roles", set_name, run_id, cumulative,
                                  [record for record in cumulative if record["id"] in changed_ids], errors, input_ids)


def rank_careers(input_sets=(), set_name=None, db_path=None, resume_path=None, as_of=None):
    """Rerank saved verification offline, without importing/reobserving source records."""
    from uuid import uuid4
    from .models import DEFAULT_DB_PATH
    from .ranking import as_of_datetime, load_resume_profile, rank_roles

    now = as_of_datetime(as_of)
    profile = load_resume_profile(resume_path) if resume_path is not None else None
    db_path = DEFAULT_DB_PATH if db_path is None else db_path
    inputs = list(input_sets) or [set_name]
    artifacts = []
    for value in inputs:
        is_artifact = isinstance(value, (dict, StageResult))
        if isinstance(value, (str, Path)):
            is_artifact = Path(value).is_file() or str(value).lower().endswith(".json")
        if is_artifact:
            artifacts.append(read_artifact(value, "verified_roles"))
        else:
            if value is None or not Path(db_path).is_file():
                raise ValueError("Rank careers requires a verified-role artifact or existing saved set")
            name = str(value).removeprefix("verified_roles:")
            with PipelineStore(db_path) as store:
                records = store.load_set("verified_roles", name)
            if not records:
                raise ValueError(f"Unknown or empty verified_roles input set: {name}")
            artifacts.append(StageResult.create("verified_roles", name, "stored-set:" + name, records))
    records = {}
    for artifact in artifacts:
        for record in artifact.records:
            if not isinstance(record.get("id"), str) or not record["id"].strip():
                raise ValueError("Rank careers requires a stable ID for every verified role")
            if record["id"] in records and record != records[record["id"]]:
                raise ValueError(f"Conflicting saved records for role ID: {record['id']}")
            records[record["id"]] = record
    ranked = rank_roles(records.values(), profile, as_of=now)
    return StageResult.create("verified_roles", set_name or artifacts[0].set_name, "rank:" + str(uuid4()), ranked,
                              errors=[error for artifact in artifacts for error in artifact.errors],
                              input_set_ids=_inputs_id(artifacts))
