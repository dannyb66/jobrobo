"""Read-only admission report for discovery/careers artifacts before LinkedIn work."""
from argparse import ArgumentParser
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.job_pipeline.models import read_artifact
from modules.job_pipeline.careers import evaluate_role


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def valid_url(value):
    parsed = urlparse(value or "")
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username and not parsed.password


def validate(companies_path, roles_path, db_path, *, search_config=None, freshness_days=None):
    from config import search, job_pipeline
    search_config = search if search_config is None else search_config
    freshness_days = job_pipeline.verification_freshness_days if freshness_days is None else freshness_days
    companies = read_artifact(companies_path, "companies")
    roles = read_artifact(roles_path, "verified_roles")
    now = datetime.now(timezone.utc)
    problems, checks = [], []

    def check(name, condition, detail=None):
        checks.append({"name": name, "passed": bool(condition), "detail": detail})
        if not condition:
            problems.append({"check": name, "detail": detail})

    company_ids = [row.get("id") for row in companies.records]
    role_ids = [row.get("id") for row in roles.records]
    check("company_ids_unique", all(isinstance(value, str) and value for value in company_ids) and len(set(company_ids)) == len(company_ids))
    check("role_ids_unique", all(isinstance(value, str) and value for value in role_ids) and len(set(role_ids)) == len(role_ids))
    check("verification_input_provenance", "companies:" + companies.set_name in roles.input_set_ids)
    by_company = {row["id"]: row for row in companies.records}
    eligible = []
    for company in companies.records:
        sources = company.get("sources", [])
        check("company_provenance:" + company["id"], bool(sources) and all(
            valid_url(source.get("url")) and source.get("name") and source.get("observed_at") for source in sources
        ))
        for source in sources:
            try:
                observed = timestamp(source["observed_at"])
                check("company_observation_time:" + company["id"], observed <= now + timedelta(minutes=5))
            except (KeyError, ValueError, TypeError) as exc:
                check("company_observation_time:" + company["id"], False, str(exc))
    for role in roles.records:
        rid = role["id"]
        check("role_parent:" + rid, role.get("company_id") in by_company and role.get("company", {}).get("id") == role.get("company_id"))
        check("role_fields:" + rid, isinstance(role.get("title"), str) and bool(role["title"].strip())
              and isinstance(role.get("description"), str) and bool(role["description"].strip())
              and valid_url(role.get("career_url")) and type(role.get("eligible")) is bool)
        check("official_careers_provenance:" + rid, any(
            source.get("kind") == "career_verification" and valid_url(source.get("url")) and source.get("observed_at")
            for source in role.get("sources", [])
        ))
        try:
            observed = timestamp(role["verified_at"])
            fresh = now - timedelta(days=freshness_days) <= observed <= now + timedelta(minutes=5)
            check("role_freshness:" + rid, fresh)
        except (KeyError, ValueError, TypeError) as exc:
            fresh = False
            check("role_freshness:" + rid, False, str(exc))
        current = evaluate_role(deepcopy(role), search_config)
        check("canonical_eligibility:" + rid, current["eligible"] == role["eligible"]
              and sorted(current["exclusion_reasons"]) == sorted(role.get("exclusion_reasons", [])))
        if current["eligible"] and fresh and role.get("status") == "open":
            eligible.append(rid)
    database = Path(db_path).resolve()
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        for artifact in (companies, roles):
            saved = connection.execute("SELECT * FROM runs WHERE run_id=?", (artifact.run_id,)).fetchone()
            check("persisted_run:" + artifact.stage, bool(saved) and saved["stage"] == artifact.stage
                  and saved["set_name"] == artifact.set_name and saved["status"] in {"complete", "partial"})
            ids = {row["entity_id"] for row in connection.execute(
                "SELECT entity_id FROM set_memberships WHERE stage=? AND set_name=?", (artifact.stage, artifact.set_name))}
            check("persisted_set:" + artifact.stage, ids == {row["id"] for row in artifact.records})
            if saved:
                check("persisted_errors:" + artifact.stage, json.loads(saved["errors"]) == artifact.errors)
        check("no_search_or_application_runs", connection.execute(
            "SELECT COUNT(*) FROM runs WHERE stage IN ('linkedin_jobs','applications')").fetchone()[0] == 0)
        check("no_application_entities", connection.execute("SELECT COUNT(*) FROM entities WHERE stage='applications'").fetchone()[0] == 0)
    return {
        "schema_version": 1, "validated_at": now.isoformat(), "read_only": True,
        "artifacts": [{"path": str(Path(path).resolve()), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
                      for path in (companies_path, roles_path)],
        "database": str(database), "company_count": len(companies.records), "role_count": len(roles.records),
        "eligible_open_fresh_role_count": len(eligible), "eligible_role_ids": eligible,
        "discovery_errors": companies.errors, "verification_errors": roles.errors,
        "exclusion_counts": dict(Counter(reason for role in roles.records for reason in role.get("exclusion_reasons", []))),
        "all_checks_passed": not problems, "problems": problems, "checks": checks,
        "search_admission": "review_required" if not problems and eligible else "held_no_eligible_roles" if not problems else "held_validation_failed",
        "application_admission": "held_pending_explicit_selected_target_review",
    }


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--companies", required=True)
    parser.add_argument("--roles", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = validate(args.companies, args.roles, args.db)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        print("Artifact validation failed: " + str(exc), file=sys.stderr)
        return 2
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({key: result[key] for key in ("all_checks_passed", "company_count", "role_count", "eligible_open_fresh_role_count", "search_admission", "application_admission", "problems")}, indent=2))
    return 0 if result["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
