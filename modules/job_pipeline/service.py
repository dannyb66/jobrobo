"""Independent discovery and verification stages over cumulative named sets."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import DEFAULT_DB_PATH, StageResult, read_artifact, utc_now
from .store import PipelineStore


def _config(config):
    if config is None:
        from config import job_pipeline
        config = job_pipeline
    return config if isinstance(config, dict) else {name: value for name, value in vars(config).items() if not name.startswith("_")}


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


def discover_companies(input_sets=(), set_name="startup-companies", limit=25, db_path=DEFAULT_DB_PATH,
                       sources=None, refresh=False, config=None, discover=None, client=None, render=None):
    if type(limit) is not int or limit < 1:
        raise ValueError("Pipeline limit must be a positive integer")
    config = _config(config)
    if discover is None:
        from .sources import discover_source
        discover = discover_source
    selected = list(sources if sources is not None else config.get("sources", []))
    with PipelineStore(db_path) as store:
        artifacts = load_inputs(store, input_sets, "companies")
        run_id = store.begin_run("companies", set_name, _inputs_id(artifacts), {"sources": selected, "limit": limit, "refresh": refresh})
        delta, errors = [], []
        successful_sources = len(artifacts) + bool(store.load_set("companies", set_name))
        try:
            for artifact in artifacts:
                delta.extend(store.upsert_many("companies", set_name, artifact.records, run_id, artifact.created_at))
            for source in selected:
                checkpoint_key = "discover:" + source
                checkpoint = None if refresh else store.get_checkpoint(checkpoint_key, set_name)
                if isinstance(checkpoint, dict) and checkpoint.get("complete"):
                    successful_sources += 1
                    continue
                cursor = checkpoint.get("cursor") if isinstance(checkpoint, dict) else checkpoint
                try:
                    source_config = {**config, **config.get("source_config", {}).get(source, {})}
                    result = discover(source, source_config, cursor=cursor, limit=limit, client=client, render=render)
                    records = list(result.get("records", []))[:limit]
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


def verify_careers(input_sets=(), set_name="startup-companies", limit=25, db_path=DEFAULT_DB_PATH,
                   refresh=False, search_config=None, verify=None, client=None, render=None):
    if type(limit) is not int or limit < 1:
        raise ValueError("Pipeline limit must be a positive integer")
    if search_config is None:
        from config import search
        search_config = search
    if verify is None:
        from .careers import verify_company
        verify = verify_company
    with PipelineStore(db_path) as store:
        artifacts = load_inputs(store, input_sets, "companies")
        if artifacts:
            companies = [record for artifact in artifacts for record in artifact.records]
            companies = list({record["id"]: record for record in companies}.values())
        else:
            companies = store.load_set("companies", set_name)
            if not companies:
                raise ValueError("No companies available; discover or import a companies set first")
        input_ids = _inputs_id(artifacts) or ["companies:" + set_name]
        run_id = store.begin_run("verified_roles", set_name, input_ids, {"limit": limit, "refresh": refresh})
        delta, errors = [], []
        successful_companies = int(bool(store.load_set("verified_roles", set_name)))
        checked = 0
        try:
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
                        if verified_at + timedelta(days=_config(None).get("verification_freshness_days", 7)) > datetime.now(timezone.utc):
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
                            vanished.append({**previous, "status": "closed", "eligible": False,
                                             "verified_at": now, "verification_run_id": run_id,
                                             "exclusion_reasons": ["No longer listed on complete careers board"]})
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
        cumulative = store.load_set("verified_roles", set_name)
        changed_ids = {record["id"] for record in delta}
        return StageResult.create("verified_roles", set_name, run_id, cumulative,
                                  [record for record in cumulative if record["id"] in changed_ids], errors, input_ids)
