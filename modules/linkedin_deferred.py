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
        for key in ("run_id", "source_report", "last_seen", "observed_at", "reason"):
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
