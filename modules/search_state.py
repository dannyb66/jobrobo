"""Durable per-query checkpoints; unfinished runs restart each query on page one."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

from modules.search_planner import SearchSpec


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def plan_fingerprint(specs, profile=None):
    # Call with the deterministic plan so stochastic AI wording cannot prevent resume.
    data = {"queries": [spec.to_dict() for spec in specs]}
    if profile is not None:
        data["generation_settings"] = {key: profile.get(key) for key in (
            "dynamic_search_enabled", "ai_query_refinement_enabled", "role_lanes", "skills",
        )}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class SearchManifest:
    def __init__(self, path, data):
        self.path, self.data = Path(path), data

    @classmethod
    def applied_ids(cls, directory):
        # Also protects later runs when submission succeeded but CSV logging failed.
        ids = set()
        for path in Path(directory).glob("*.json"):
            data = json.loads(path.read_text())
            ids.update(job_id for row in data["queries"] for job_id, job in row["jobs"].items()
                       if job["status"] in {"applied", "submitting"})
        return ids

    @classmethod
    def find_resume(cls, directory, configuration_id):
        for path in sorted(Path(directory).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            # Never discard or overwrite a corrupt run silently.
            data = json.loads(path.read_text())
            if data["configuration_id"] == configuration_id and data["status"] != "complete":
                manifest = cls(path, data)
                for query in data["queries"]:
                    if query["status"] == "running":
                        query["status"] = "pending"
                data["status"] = "running"
                data["stop_reason"] = None
                manifest.save()
                return manifest
        return None

    @classmethod
    def create(cls, directory, specs, configuration_id=None):
        now = timestamp()
        run_id = str(uuid.uuid4())
        data = {
            "run_id": run_id, "profile_name": specs[0].profile_name,
            "profile_version": specs[0].profile_version,
            "configuration_id": configuration_id or plan_fingerprint(specs),
            "started_at": now, "last_updated_at": now, "status": "running",
            "current_query_id": None, "stop_reason": None,
            "queries": [{
                "spec": spec.to_dict(), "status": "pending", "search_mode": None,
                "fallback_reason": None, "warnings": [], "applied_count": 0,
                "collected_count": 0, "processed_job_ids": [], "jobs": {},
                "last_page": 1, "last_job_id": None, "stop_reason": None,
            } for spec in specs],
        }
        manifest = cls(Path(directory) / f"{run_id}.json", data)
        manifest.save()
        return manifest

    def save(self):
        self.data["last_updated_at"] = timestamp()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".checkpoint-")
        try:
            with os.fdopen(descriptor, "w") as handle:
                json.dump(self.data, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def queries(self):
        return [SearchSpec(**row["spec"]) for row in self.data["queries"] if row["status"] != "complete"]

    def query(self, query_id):
        return next(row for row in self.data["queries"] if row["spec"]["query_id"] == query_id)

    def begin_query(self, spec):
        row = self.query(spec.query_id)
        row["status"], row["last_page"], row["stop_reason"] = "running", 1, None
        self.data["current_query_id"] = spec.query_id
        self.save()

    def record_mode(self, spec, mode, fallback_reason=None, warnings=(), diagnostics=None):
        row = self.query(spec.query_id)
        spec.mode = mode
        row["spec"]["mode"] = row["search_mode"] = mode
        row["fallback_reason"] = fallback_reason
        row["executed_query"] = spec.classic_query if mode == "classic" else spec.query_text
        row["warnings"].extend(warnings)
        if diagnostics is not None:
            # Diagnostics augment existing manifests without changing resume identity.
            row["search_diagnostics"] = diagnostics
        self.save()

    def processed_ids(self):
        return {job_id for row in self.data["queries"] for job_id in row["processed_job_ids"]}

    def record_job(self, spec, job_id, status, reason=None, page=1):
        row = self.query(spec.query_id)
        if status not in {"in_progress", "submitting", "applied", "collected", "failed", "skipped"}:
            raise ValueError(f"Unsupported job status: {status}")
        if status in {"applied", "collected"} and any(
            job_id in other["jobs"] and other["jobs"][job_id]["status"] in {"applied", "collected"}
            for other in self.data["queries"] if other is not row
        ):
            status, reason = "skipped", "Previously completed under another query"
        previous = row["jobs"].get(job_id, {}).get("status")
        # Once submission is recorded, a later UI/CSV failure must not erase it.
        if (previous == "applied" and status != "applied"
                or previous == "submitting" and status in {"failed", "skipped", "in_progress"}):
            row["warnings"].append(f"Post-submit issue for {job_id}: {reason or status}")
        else:
            row["jobs"][job_id] = {"status": status, "reason": reason, "updated_at": timestamp()}
            for outcome, counter in (("applied", "applied_count"), ("collected", "collected_count")):
                row[counter] = sum(job["status"] == outcome for job in row["jobs"].values())
        if status != "in_progress" and job_id not in row["processed_job_ids"]:
            row["processed_job_ids"].append(job_id)
        row["last_job_id"], row["last_page"] = job_id, page or 1
        self.save()

    def quota_met(self, spec):
        row = self.query(spec.query_id)
        return row["applied_count"] + row["collected_count"] >= spec.quota

    def has_uncertain_submission(self, spec):
        return any(job["status"] == "submitting" for job in self.query(spec.query_id)["jobs"].values())

    def resolve_submission(self, query_id, job_id, outcome):
        """Resolve only after the operator verifies LinkedIn's application status."""
        if outcome not in {"applied", "failed"}:
            raise ValueError("Verified outcome must be applied or failed")
        row = self.query(query_id)
        if row["jobs"].get(job_id, {}).get("status") != "submitting":
            raise ValueError("Only an uncertain submission can be resolved")
        row["jobs"][job_id] = {"status": outcome, "reason": "Application status manually verified on LinkedIn", "updated_at": timestamp()}
        row["applied_count"] = sum(job["status"] == "applied" for job in row["jobs"].values())
        row["warnings"].append(f"Uncertain submission {job_id} resolved as {outcome}")
        self.save()

    def finish_query(self, spec, reason):
        row = self.query(spec.query_id)
        row["status"], row["stop_reason"] = "complete", reason
        self.save()

    def interrupt(self, reason):
        self.data["status"], self.data["stop_reason"] = "interrupted", reason
        self.save()

    def finish(self):
        if all(row["status"] == "complete" for row in self.data["queries"]):
            self.data["status"], self.data["current_query_id"] = "complete", None
            self.data["stop_reason"] = "all_queries_complete"
        else:
            self.data["status"] = "interrupted"
        self.save()
