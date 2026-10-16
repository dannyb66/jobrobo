"""Retain dated LinkedIn job URLs from local evidence, without browser actions."""

from argparse import ArgumentParser
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.search_history import load_applied_job_ids


def _read(path, expected):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read valid JSON evidence: {path.name}") from exc
    if not isinstance(data, expected):
        raise ValueError(f"Invalid evidence structure: {path.name}")
    return data


def _timestamp(value, source):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Timezone required")
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid evidence timestamp: {source.name}") from exc


def _job_id(value, source):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r"[0-9]+", str(value)):
        raise ValueError(f"Invalid evidence job ID: {source.name}")
    return str(value)


def _url(job_id):
    return "https://www.linkedin.com/jobs/view/" + job_id + "/"


def _metadata(logs):
    path = logs / "log.txt"
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("Cannot read job title evidence: log.txt") from exc
    found = {}
    for match in re.finditer(r'Trying to Apply to "([^"\r\n]+)" job\. Job ID: ([0-9]+)', text):
        title, separator, company = match[1].rpartition(" | ")
        found[match[2]] = {"title": title if separator else match[1], "company": company if separator else ""}
    return found


def collect_retry_records(logs="logs", *, day=None, timezone_name="America/Los_Angeles",
                          applied_history="all excels/all_applied_applications_history.csv", readiness=None):
    """Validate all inputs before any archive writes and return chronological events.

    A run is included by its start date in the requested timezone. A run start
    fallback is labeled as such; it never becomes an invented job observation.
    """
    try:
        zone = ZoneInfo(timezone_name)
        target = datetime.now(zone).date() if day is None else date.fromisoformat(day) if isinstance(day, str) else day
        if type(target) is not date:
            raise ValueError("Invalid date")
    except (ValueError, TypeError, ZoneInfoNotFoundError) as exc:
        raise ValueError("Invalid backfill date or timezone") from exc
    logs = Path(logs)
    applied = load_applied_job_ids(applied_history)
    titles = _metadata(logs)
    events = []

    def add(info, instant):
        job_id = _job_id(info.get("job_id"), Path(info["source_report"]))
        if any(info.get(key) is not None and type(info.get(key)) is not bool
               for key in ("submission_disabled", "submit_enabled")):
            raise ValueError(f"Invalid submission evidence flags: {Path(info['source_report']).name}")
        if job_id in applied:
            return
        info["job_id"] = job_id
        info["job_url"] = _url(job_id)
        for key, value in titles.get(job_id, {}).items():
            if not info.get(key):
                info[key] = value
        events.append((instant, len(events), info))

    manifests = []
    for path in sorted((logs / "search_runs").glob("*.json")):
        manifest = _read(path, dict)
        started = _timestamp(manifest.get("started_at"), path)
        if started.astimezone(zone).date() != target:
            continue
        queries = manifest.get("queries")
        if (not isinstance(queries, list) or not isinstance(manifest.get("run_id"), str)
                or not manifest["run_id"] or Path(manifest["run_id"]).name != manifest["run_id"]):
            raise ValueError(f"Invalid search manifest: {path.name}")
        checkpoints = {}
        specs = {}
        disabled = True if ":prepare-only:" in str(manifest.get("configuration_id", "")) else None
        for query in queries:
            if not isinstance(query, dict) or not isinstance(query.get("spec"), dict) or not isinstance(query.get("jobs", {}), dict):
                raise ValueError(f"Invalid query evidence: {path.name}")
            spec = query["spec"]
            if not isinstance(spec.get("query_id"), str) or not spec["query_id"]:
                raise ValueError(f"Invalid query identity: {path.name}")
            specs[spec.get("query_id")] = spec
            for raw_id, job in query.get("jobs", {}).items():
                job_id = _job_id(raw_id, path)
                if not isinstance(job, dict):
                    raise ValueError(f"Invalid job evidence: {path.name}")
                if job.get("status") == "applied":
                    applied.add(job_id)
                    continue
                if job.get("updated_at"):
                    seen = _timestamp(job["updated_at"], path)
                    if job_id not in checkpoints or seen > checkpoints[job_id][0]:
                        checkpoints[job_id] = (seen, job["updated_at"])
                if job.get("status") not in {"failed", "in_progress", "prepared", "submitting"}:
                    continue
                info = {"job_id": job_id, "title": job.get("title", ""), "company": job.get("company", ""),
                        "status": job["status"], "reason": job.get("reason", ""),
                        "query_id": spec.get("query_id", ""), "query": query.get("executed_query") or spec.get("query_text", ""),
                        "search_mode": query.get("search_mode") or spec.get("mode", ""),
                        "run_id": manifest["run_id"], "source_report": str(path),
                        "submission_disabled": disabled, "requires_submission_check": disabled is not True}
                instant = started
                if job.get("updated_at"):
                    info["last_seen"] = job["updated_at"]
                    instant = _timestamp(job["updated_at"], path)
                else:
                    info["source_run_started_at"] = manifest["started_at"]
                add(info, instant)
        manifests.append((manifest, started, checkpoints, specs))

    # An applied checkpoint in any included query suppresses all older failures.
    events = [event for event in events if event[2]["job_id"] not in applied]
    for manifest, started, checkpoints, specs in manifests:
        path = logs / "form_validations" / (manifest["run_id"] + ".json")
        if not path.exists():
            continue
        report = _read(path, dict)
        if not isinstance(report.get("records"), list) or type(report.get("submission_disabled")) is not bool:
            raise ValueError(f"Invalid preparation report: {path.name}")
        for record in report["records"]:
            if not isinstance(record, dict) or record.get("status") not in {"started", "failed", "ready"}:
                raise ValueError(f"Invalid preparation record: {path.name}")
            job_id = _job_id(record.get("job_id"), path)
            if record.get("query_id") is not None and not isinstance(record["query_id"], str):
                raise ValueError(f"Invalid preparation query identity: {path.name}")
            spec = specs.get(record.get("query_id"), {})
            info = {**{key: record[key] for key in ("title", "company", "query_id", "status", "reason", "stage", "screenshot", "submit_enabled") if key in record},
                    "job_id": job_id, "run_id": manifest["run_id"], "source_report": str(path),
                    "query": record.get("query") or spec.get("query_text", ""),
                    "submission_disabled": report["submission_disabled"],
                    "requires_submission_check": report["submission_disabled"] is not True}
            instant = started
            if job_id in checkpoints:
                instant, info["last_seen"] = checkpoints[job_id]
            else:
                info["source_run_started_at"] = manifest["started_at"]
                info.pop("last_seen", None)
            add(info, instant)

    if readiness is not None:
        path = Path(readiness)
        for record in _read(path, list):
            if not isinstance(record, dict):
                raise ValueError(f"Invalid readiness evidence: {path.name}")
            observed = _timestamp(record.get("observed_at"), path)
            if observed.astimezone(zone).date() != target:
                continue
            if record.get("stage") != "submit_ready" or type(record.get("employer_submissions")) is not int or record["employer_submissions"] != 0:
                continue
            if not isinstance(record.get("path"), str):
                raise ValueError(f"Invalid LinkedIn readiness URL: {path.name}")
            try:
                parsed = urlparse(record["path"])
            except ValueError as exc:
                raise ValueError(f"Invalid LinkedIn readiness URL: {path.name}") from exc
            match = re.fullmatch(r"/jobs/view/([0-9]+)/?", parsed.path)
            if parsed.scheme != "https" or parsed.hostname not in {"linkedin.com", "www.linkedin.com"} or parsed.username or parsed.password or not match:
                raise ValueError(f"Invalid LinkedIn readiness URL: {path.name}")
            add({"job_id": match[1], "status": "ready", "submission_disabled": True,
                 "requires_submission_check": False, "source_report": str(path),
                 "observed_at": record["observed_at"], "last_seen": record["observed_at"],
                 "submit_enabled": record.get("submit_enabled"),
                 "title": record.get("title", ""), "company": record.get("company", "")}, observed)
    return [info for _, _, info in sorted(events, key=lambda event: (event[0], event[1]))]


def backfill(logs="logs", *, output="logs/deferred_applications/retry_jobs.json", **options):
    from modules.linkedin_deferred import DeferredJobs
    records = collect_retry_records(logs, **options)
    archive = DeferredJobs(output)
    for record in records:
        archive.record(record)
    markdown = Path(output).with_suffix(".md")
    archive.export_markdown(markdown)
    return {**archive.summary(), "source_events": len(records), "markdown": str(markdown)}


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--logs", default="logs")
    parser.add_argument("--output", default="logs/deferred_applications/retry_jobs.json")
    parser.add_argument("--date", dest="day")
    parser.add_argument("--timezone", default="America/Los_Angeles", dest="timezone_name")
    parser.add_argument("--applied-history", default="all excels/all_applied_applications_history.csv")
    parser.add_argument("--readiness")
    args = vars(parser.parse_args(argv))
    try:
        print(json.dumps(backfill(**args), indent=2))
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
