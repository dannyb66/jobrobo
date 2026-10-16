"""Atomic audit snapshots for preparation-only runs, with no submission state.

Each distinct job is one attempt. Updating its outcome preserves its position
and previously recorded audit metadata. The caller decides when to stop using
``limit_reached``; outcome updates remain possible after reaching the limit.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile


class PreparationReport:
    """Collect a single invocation's preparation outcomes in insertion order."""

    def __init__(self, path, limit):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("Preparation limit must be a positive integer")
        self.path = Path(path)
        self.limit = limit
        self._records = {}

    @property
    def records(self):
        return deepcopy(list(self._records.values()))

    @property
    def attempted(self):
        return len(self._records)

    @property
    def limit_reached(self):
        return self.attempted >= self.limit

    def summary(self):
        return self._summary(self._records)

    def _summary(self, records):
        entries = list(records.values())
        return {
            "submission_disabled": True,
            "limit": self.limit,
            "attempted": len(entries),
            "ready": sum(row["status"] == "ready" for row in entries),
            "failed": sum(row["status"] == "failed" for row in entries),
            "in_progress": sum(row["status"] == "started" for row in entries),
            "records": deepcopy(entries),
        }

    def record(self, info):
        """Upsert one job and atomically persist the full preparation snapshot.

        Validation, JSON encoding or filesystem failure leaves the previous
        in-memory report and any existing report file intact.
        """
        if not isinstance(info, dict):
            raise ValueError("Preparation record must be a dictionary")
        raw_job_id = info.get("job_id")
        if isinstance(raw_job_id, bool) or not isinstance(raw_job_id, (str, int)):
            raise ValueError("Preparation record requires a job_id")
        job_id = str(raw_job_id).strip()
        if not job_id:
            raise ValueError("Preparation record requires a nonempty job_id")
        if not isinstance(info.get("status"), str) or info["status"] not in {"started", "ready", "failed"}:
            raise ValueError("Preparation status must be started, ready or failed")

        candidate = deepcopy(self._records)
        candidate[job_id] = {**candidate.get(job_id, {}), **deepcopy(info), "job_id": job_id}
        # Encode before opening a temporary file, so unsupported audit values
        # cannot replace an existing snapshot or partially update memory.
        payload = json.dumps(self._summary(candidate), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix="." + self.path.name + ".", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self._records = candidate
        return deepcopy(candidate[job_id])
