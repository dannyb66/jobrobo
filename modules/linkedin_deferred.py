"""Durable LinkedIn jobs retained for review and a later application.

Ingestion timestamps describe this library write. Source occurrence timestamps
are retained only when supplied by a caller; backfills do not invent history.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile

from modules.search_history import file_lock


def _job_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Deferred job requires a numeric job_id")
    value = str(value).strip()
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError("Deferred job requires a numeric job_id")
    return value


def _atomic_write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="." + path.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class DeferredJobs:
    """Load and atomically upsert a retry library, without modifying applications."""

    def __init__(self, path):
        self.path = Path(path)
        self._records = {}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != 1 or data.get("purpose") != "retry_prepared_applications":
                raise ValueError("Unsupported deferred jobs document")
            if not isinstance(data.get("records"), list):
                raise ValueError("Deferred jobs document requires records")
            for item in data["records"]:
                if not isinstance(item, dict):
                    raise ValueError("Invalid deferred job record")
                job_id = _job_id(item.get("job_id"))
                disabled = item.get("submission_disabled")
                if job_id in self._records or "submission_disabled" not in item or not self._valid_flag(disabled):
                    raise ValueError("Invalid or duplicate deferred job record")
                if item.get("job_url") != self._url(job_id) or not isinstance(item.get("history"), list):
                    raise ValueError("Invalid deferred job URL or history")
                self._records[job_id] = deepcopy(item)

    @staticmethod
    def _url(job_id):
        return "https://www.linkedin.com/jobs/view/" + job_id + "/"

    @staticmethod
    def _valid_flag(value):
        return value is None or type(value) is bool

    @property
    def records(self):
        return deepcopy(list(self._records.values()))

    def summary(self):
        return {"path": str(self.path), "count": len(self._records)}

    def record(self, info):
        """Keep metadata and a distinct source/run/status event for a tested job.

        ``submission_disabled`` must be supplied as True, False or None (unknown
        in an older report). The library never initiates an application. Source
        timestamps are never inferred from the ingestion clock. Empty historical
        metadata cannot erase an existing job description or title.
        """
        with file_lock(str(self.path) + ".lock"):
            # Other instances may have committed since this object was loaded.
            # Refresh only into a local snapshot; failures keep this object's
            # previous memory and the previously committed file unchanged.
            fresh = DeferredJobs(self.path)._records
            return self._record(info, fresh)

    def _record(self, info, records):
        if not isinstance(info, dict):
            raise ValueError("Deferred job record must be a dictionary")
        job_id = _job_id(info.get("job_id"))
        disabled = info.get("submission_disabled")
        if "submission_disabled" not in info or not self._valid_flag(disabled):
            raise ValueError("submission_disabled must be True, False or None")
        # This describes the final button's observed enabled state, not whether
        # submission was permitted or occurred. Never derive one from the other.
        submit_enabled = info.get("submit_enabled")
        if not self._valid_flag(submit_enabled):
            raise ValueError("submit_enabled must be True, False or None")
        status = info.get("status")
        if not isinstance(status, str) or not status.strip():
            raise ValueError("Deferred job requires a source status")
        if info.get('verified_submission_outcome') not in {None, 'applied', 'not_submitted'}:
            raise ValueError('Invalid verified submission outcome')
        candidate = deepcopy(records)
        previous = candidate.get(job_id, {})
        entry = deepcopy(previous)
        reserved = {"job_id", "job_url", "history", "created_at", "updated_at", "submit_enabled"}
        for key, value in deepcopy(info).items():
            if key == "description" and isinstance(value, str) and value.strip().lower() in {"unknown", "n/a", "na"}:
                continue
            if key not in reserved and value is not None and value != "":
                entry[key] = value
        entry.update(job_id=job_id, job_url=self._url(job_id), submission_disabled=disabled)
        if "submit_enabled" in info:
            entry["submit_enabled"] = submit_enabled
        history = entry.setdefault("history", [])
        event = {"status": status, "submit_enabled": submit_enabled, "submission_disabled": disabled}
        for key in ("run_id", "source_report", "last_seen", "observed_at", "reason", "requires_submission_check", "verified_submission_outcome"):
            if info.get(key) is not None and info.get(key) != "":
                event[key] = deepcopy(info[key])
        identity = lambda row: (row.get("run_id"), row.get("source_report"), row.get("status"))
        existing = next((row for row in history if identity(row) == identity(event)), None)
        if existing is None:
            history.append(event)
        else:
            reasons = list(existing.get("reasons", []))
            for reason in (existing.get("reason"), event.get("reason")):
                if reason and reason not in reasons:
                    reasons.append(reason)
            existing.update(event)
            if len(reasons) > 1:
                existing["reasons"] = reasons
        if status == "failed" and info.get("reason"):
            reasons = entry.setdefault("failed_reasons", [])
            if info["reason"] not in reasons:
                reasons.append(deepcopy(info["reason"]))
        # Late failure/backfill records remain in history, but cannot reopen a
        # confirmed application or clear an unresolved submission hold.
        preserve_state = previous.get('status') == 'applied' and status != 'applied'
        verified_not_submitted = info.get('verified_submission_outcome') == 'not_submitted' and status == 'failed'
        if previous.get('status') == 'submission_uncertain' and status != 'applied' and not verified_not_submitted:
            preserve_state = True
        if previous.get('observed_at') and info.get('observed_at') and status != 'applied':
            try:
                old = datetime.fromisoformat(previous['observed_at'].replace('Z', '+00:00'))
                new = datetime.fromisoformat(info['observed_at'].replace('Z', '+00:00'))
                preserve_state |= new < old
            except (TypeError, ValueError):
                pass
        if preserve_state:
            for key in ('status', 'reason', 'run_id', 'source_report', 'observed_at',
                        'submission_disabled', 'submit_enabled', 'requires_submission_check'):
                if key in previous:
                    entry[key] = deepcopy(previous[key])
                else:
                    entry.pop(key, None)
        if entry.get('status') == 'applied':
            entry['requires_submission_check'] = False
        elif previous.get('requires_submission_check') is True and not verified_not_submitted:
            entry['requires_submission_check'] = True
        if entry == previous:
            self._records = candidate
            return deepcopy(entry)
        now = datetime.now(timezone.utc).isoformat()
        entry.setdefault("created_at", now)
        entry["updated_at"] = now
        candidate[job_id] = entry
        document = {"version": 1, "purpose": "retry_prepared_applications", "records": list(candidate.values())}
        payload = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        _atomic_write(self.path, payload)
        self._records = candidate
        return deepcopy(entry)

    def export_markdown(self, path):
        """Write a compact URL index, omitting job descriptions and form answers."""
        target = Path(path)
        if target.resolve() in {self.path.resolve(), Path(str(self.path) + ".lock").resolve()}:
            raise ValueError("Markdown export must not replace the JSON library or its lock")
        with file_lock(str(self.path) + ".lock"):
            # Export the latest committed library while holding the writer lock;
            # an older instance must not publish an index that loses newer jobs.
            fresh = DeferredJobs(self.path)._records
            self._export_markdown(target, fresh)
            self._records = fresh
        return target

    def _export_markdown(self, target, records):
        def cell(value):
            return str(value or "").replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")
        lines = ["# Deferred LinkedIn jobs", "", "Saved jobs for later review. Historical submission state may be unknown; verify before retrying.", "",
                 "| Job title | Company | Job URL | Last test status |", "| --- | --- | --- | --- |"]
        for item in records.values():
            lines.append("| " + " | ".join(cell(item.get(key, "")) for key in ("title", "company", "job_url", "status")) + " |")
        _atomic_write(target, "\n".join(lines) + "\n")


def is_deferred_document(path):
    """Return whether *path* is the review/retry ledger rather than a stage artifact."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (isinstance(data, dict) and data.get("version") == 1
            and data.get("purpose") == "retry_prepared_applications")


def build_retry_batch(path, profile, config, limit, applied_ids=(), job_id=None):
    """Turn a bounded, safe subset of the retry ledger into direct LinkedIn targets.

    Retry records deliberately do not become verified-careers pipeline artifacts.
    The live employer, job ID, location, Easy Apply state, application history and
    current form are still checked by the standard browser runner.
    """
    from modules.search_planner import SearchSpec, filters_snapshot, stable_id

    if type(limit) is not int or limit < 1:
        raise ValueError("Retry limit must be a positive integer")
    document = DeferredJobs(path)
    applied = {str(value) for value in applied_ids}
    requested_id = str(job_id) if job_id is not None else None
    runnable_statuses = {
        "ready", "failed", "entry_failed", "card_pending", "retry_queued",
        "details_pending", "platform_limit",
    }
    candidates = sorted(document.records, key=lambda row: row.get("updated_at", ""), reverse=True)
    if requested_id is not None:
        candidates = [row for row in candidates if str(row["job_id"]) == requested_id]
        if not candidates:
            raise ValueError(f"Job ID {requested_id} is not in the deferred retry ledger")
    specs, selected = [], {}
    blocked = []
    current_filters = filters_snapshot(config)
    for record in candidates:
        job_id = str(record["job_id"])
        status = record.get("status")
        if status == "applied" or job_id in applied:
            continue
        if status == 'submission_uncertain' or record.get("requires_submission_check") is True:
            blocked.append(job_id)
            continue
        if status not in runnable_statuses:
            continue
        title, company = record.get("title"), record.get("company")
        if not isinstance(title, str) or not title.strip() or not isinstance(company, str) or not company.strip():
            continue
        query = record.get("query")
        if not isinstance(query, str) or not query.strip():
            query = f"Find {title.strip()} roles at {company.strip()}"
        query_id = stable_id("retry", job_id)
        company_context = {
            "id": "retry:" + job_id,
            "name": company.strip(),
            "aliases": [],
        }
        spec = SearchSpec(
            query_id=query_id,
            query_text=query.strip(),
            source="retry",
            mode=record.get("search_mode") if record.get("search_mode") in {"ai", "classic"} else "ai",
            profile_name=profile.get("profile_name", "retry"),
            profile_version=profile.get("profile_version", "1"),
            filters_snapshot=current_filters,
            quota=1,
            classic_query=f"{company.strip()} {title.strip()}",
            pipeline_context={"company": company_context, "company_id": company_context["id"]},
        )
        specs.append(spec)
        selected.setdefault(query_id, []).append({
            "linkedin_id": job_id,
            "title": title.strip(),
            "company": company.strip(),
            "description": record.get("description") or "Unknown",
        })
        if len(specs) >= limit:
            break
    if not specs:
        if blocked:
            raise ValueError("No safe retry candidates; submission outcome must be checked first for: " + ", ".join(blocked[:5]))
        raise ValueError("No unapplied, eligible records found in the retry ledger")
    return specs, selected
