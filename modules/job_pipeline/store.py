"""Cumulative SQLite entities, provenance, named sets, and resumable stage runs."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlparse
import uuid

from .models import DEFAULT_DB_PATH, STAGES, StageResult, read_artifact, utc_now


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def canonical_domain(value):
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip().lower()
    parsed = urlparse(candidate if "://" in candidate else "https://" + candidate)
    host = (parsed.hostname or "").rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host if "." in host and " " not in host else None


def _moment(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.timestamp()
    except (AttributeError, TypeError, ValueError):
        return 0


def _combine(existing, incoming, incoming_is_newer=True):
    result = deepcopy(existing)
    for key, value in incoming.items():
        if key in {"sources", "aliases"}:
            combined = list(result.get(key) or [])
            markers = {_json(item) for item in combined}
            for item in value or []:
                if _json(item) not in markers:
                    combined.append(deepcopy(item))
                    markers.add(_json(item))
            result[key] = combined
        elif key in {"exclusion_reasons", "unverified_preferences"} and isinstance(value, list):
            if incoming_is_newer or key not in result:
                result[key] = deepcopy(value)
        elif value is not None and value != "" and value != [] and value != {}:
            if incoming_is_newer or key not in result or result[key] in (None, "", [], {}):
                result[key] = deepcopy(value)
    return result


class PipelineStore:
    def __init__(self, db_path=DEFAULT_DB_PATH):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path, timeout=15)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                stage TEXT NOT NULL, entity_id TEXT NOT NULL, natural_key TEXT NOT NULL,
                record TEXT NOT NULL, observed_at TEXT NOT NULL,
                PRIMARY KEY(stage, entity_id), UNIQUE(stage, natural_key)
            );
            CREATE TABLE IF NOT EXISTS company_domains (
                domain TEXT PRIMARY KEY, company_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS entity_redirects (
                stage TEXT NOT NULL, alias_id TEXT NOT NULL, entity_id TEXT NOT NULL,
                PRIMARY KEY(stage, alias_id)
            );
            CREATE TABLE IF NOT EXISTS observations (
                observation_id TEXT PRIMARY KEY, stage TEXT NOT NULL, entity_id TEXT NOT NULL,
                run_id TEXT NOT NULL, observed_at TEXT NOT NULL, record TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS set_memberships (
                stage TEXT NOT NULL, set_name TEXT NOT NULL, entity_id TEXT NOT NULL,
                first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                PRIMARY KEY(stage, set_name, entity_id)
            );
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, stage TEXT NOT NULL, set_name TEXT NOT NULL,
                input_set_ids TEXT NOT NULL, configuration TEXT NOT NULL,
                status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, errors TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS checkpoints (
                source TEXT NOT NULL, set_name TEXT NOT NULL, cursor TEXT NOT NULL,
                updated_at TEXT NOT NULL, PRIMARY KEY(source, set_name)
            );
            PRAGMA user_version=1;
        """)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.connection.close()

    @staticmethod
    def _validate(stage, set_name):
        if stage not in STAGES:
            raise ValueError(f"Unsupported pipeline stage: {stage}")
        if not isinstance(set_name, str) or not set_name.strip():
            raise ValueError("Pipeline set_name must be nonempty")

    def begin_run(self, stage, set_name, input_set_ids=(), config=None):
        self._validate(stage, set_name)
        run_id = str(uuid.uuid4())
        with self.connection:
            self.connection.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, 'running', ?, NULL, '[]')",
                                    (run_id, stage, set_name, _json(list(input_set_ids)), _json(config or {}), utc_now()))
        return run_id

    def finish_run(self, run_id, status, errors=()):
        if status not in {"complete", "partial", "failed", "interrupted"}:
            raise ValueError("Unsupported pipeline run status")
        with self.connection:
            result = self.connection.execute("UPDATE runs SET status=?, finished_at=?, errors=? WHERE run_id=?",
                                             (status, utc_now(), _json(list(errors)), run_id))
            if result.rowcount != 1:
                raise ValueError("Unknown pipeline run ID")

    def get_run(self, run_id):
        row = self.connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        for key in ("input_set_ids", "configuration", "errors"):
            result[key] = json.loads(result[key])
        return result

    def get_checkpoint(self, source, set_name):
        row = self.connection.execute("SELECT cursor FROM checkpoints WHERE source=? AND set_name=?", (source, set_name)).fetchone()
        return json.loads(row["cursor"]) if row else None

    def save_checkpoint(self, source, set_name, cursor):
        with self.connection:
            self.connection.execute("INSERT INTO checkpoints VALUES (?, ?, ?, ?) ON CONFLICT(source,set_name) DO UPDATE SET cursor=excluded.cursor,updated_at=excluded.updated_at",
                                    (source, set_name, _json(cursor), utc_now()))

    def load_set(self, stage, set_name):
        self._validate(stage, set_name)
        rows = self.connection.execute("SELECT e.record FROM entities e JOIN set_memberships s ON s.stage=e.stage AND s.entity_id=e.entity_id WHERE s.stage=? AND s.set_name=? ORDER BY s.first_seen,e.entity_id", (stage, set_name))
        return [json.loads(row["record"]) for row in rows]

    def resolve_record(self, stage, entity_id):
        if stage not in STAGES:
            raise ValueError(f"Unsupported pipeline stage: {stage}")
        entity_id = self._resolve(stage, str(entity_id))
        row = self.connection.execute("SELECT record FROM entities WHERE stage=? AND entity_id=?", (stage, entity_id)).fetchone()
        return json.loads(row["record"]) if row else None

    def application_for_job(self, job_id):
        """Application status is global across output sets and imported aliases."""
        job_id = str(job_id)
        row = self.connection.execute("SELECT record FROM entities WHERE stage='applications' AND natural_key=?", (job_id,)).fetchone()
        return json.loads(row["record"]) if row else None

    def roles_for_company(self, company_id):
        """Current company roles across every named set, including closed records."""
        company_id = self._resolve("companies", str(company_id))
        rows = self.connection.execute("SELECT record FROM entities WHERE stage='verified_roles' ORDER BY entity_id")
        return [record for row in rows if (record := json.loads(row["record"])).get("company_id") == company_id]

    def _canonicalize_role_references(self, record):
        result = deepcopy(record)
        for key in ("role_id", "verified_role_id", "upstream_role_id", "career_job_id"):
            if result.get(key) is not None:
                result[key] = self._resolve("verified_roles", str(result[key]))
        for key in ("role_ids", "verified_role_ids", "upstream_role_ids", "career_job_ids"):
            if isinstance(result.get(key), list):
                result[key] = list(dict.fromkeys(self._resolve("verified_roles", str(value)) for value in result[key]))
        if isinstance(result.get("career_roles"), list):
            parents = {}
            for parent in result["career_roles"]:
                if not isinstance(parent, dict):
                    continue
                current = self.resolve_record("verified_roles", parent["id"]) if parent.get("id") else None
                parent = current or deepcopy(parent)
                if parent.get("company_id"):
                    parent["company_id"] = self._resolve("companies", str(parent["company_id"]))
                if isinstance(parent.get("company"), dict) and parent["company"].get("id"):
                    parent["company"]["id"] = self._resolve("companies", str(parent["company"]["id"]))
                parents[parent.get("id") or _hash(_json(parent))] = parent
            result["career_roles"] = list(parents.values())
        return result

    def _resolve(self, stage, entity_id):
        visited = set()
        while entity_id not in visited:
            visited.add(entity_id)
            row = self.connection.execute("SELECT entity_id FROM entity_redirects WHERE stage=? AND alias_id=?", (stage, entity_id)).fetchone()
            if not row:
                break
            entity_id = row["entity_id"]
        return entity_id

    def _domains(self, record):
        values = [record.get("domain"), record.get("website"), *(record.get("aliases") or [])]
        values = [value.get("domain") or value.get("website") if isinstance(value, dict) else value for value in values]
        return list(dict.fromkeys(domain for value in values if (domain := canonical_domain(value))))

    def _merge_companies(self, winner, loser):
        if winner == loser:
            return
        old = self.connection.execute("SELECT * FROM entities WHERE stage='companies' AND entity_id=?", (loser,)).fetchone()
        new = self.connection.execute("SELECT * FROM entities WHERE stage='companies' AND entity_id=?", (winner,)).fetchone()
        if old and new:
            merged = _combine(json.loads(new["record"]), json.loads(old["record"]), _moment(old["observed_at"]) > _moment(new["observed_at"]))
            merged["id"] = winner
            merged_at = old["observed_at"] if _moment(old["observed_at"]) > _moment(new["observed_at"]) else new["observed_at"]
            self.connection.execute("UPDATE entities SET record=?,observed_at=? WHERE stage='companies' AND entity_id=?", (_json(merged), merged_at, winner))
            memberships = self.connection.execute("SELECT * FROM set_memberships WHERE stage='companies' AND entity_id=?", (loser,)).fetchall()
            for member in memberships:
                self.connection.execute("INSERT OR IGNORE INTO set_memberships VALUES ('companies', ?, ?, ?, ?)", (member["set_name"], winner, member["first_seen"], member["last_seen"]))
            self.connection.execute("DELETE FROM set_memberships WHERE stage='companies' AND entity_id=?", (loser,))
            self.connection.execute("DELETE FROM entities WHERE stage='companies' AND entity_id=?", (loser,))
        self.connection.execute("UPDATE company_domains SET company_id=? WHERE company_id=?", (winner, loser))
        self.connection.execute("UPDATE observations SET entity_id=? WHERE stage='companies' AND entity_id=?", (winner, loser))
        self.connection.execute("UPDATE entity_redirects SET entity_id=? WHERE stage='companies' AND entity_id=?", (winner, loser))
        self.connection.execute("INSERT OR REPLACE INTO entity_redirects VALUES ('companies', ?, ?)", (loser, winner))
        for row in self.connection.execute("SELECT * FROM entities WHERE stage!='companies'").fetchall():
            # A prior role collision may already have rewritten or removed this row.
            row = self.connection.execute("SELECT * FROM entities WHERE stage=? AND entity_id=?", (row["stage"], row["entity_id"])).fetchone()
            if row is None:
                continue
            record = json.loads(row["record"])
            if record.get("company_id") != loser and (record.get("company") or {}).get("id") != loser:
                continue
            record["company_id"] = winner
            if isinstance(record.get("company"), dict):
                record["company"]["id"] = winner
            natural_key = self._natural_key(row["stage"], record)
            collision = self.connection.execute("SELECT * FROM entities WHERE stage=? AND natural_key=? AND entity_id!=?", (row["stage"], natural_key, row["entity_id"])).fetchone()
            if collision:
                target = collision["entity_id"]
                record = _combine(json.loads(collision["record"]), record, _moment(row["observed_at"]) > _moment(collision["observed_at"]))
                record["id"] = target
                merged_at = row["observed_at"] if _moment(row["observed_at"]) > _moment(collision["observed_at"]) else collision["observed_at"]
                self.connection.execute("UPDATE entities SET record=?,observed_at=? WHERE stage=? AND entity_id=?", (_json(record), merged_at, row["stage"], target))
                for member in self.connection.execute("SELECT * FROM set_memberships WHERE stage=? AND entity_id=?", (row["stage"], row["entity_id"])).fetchall():
                    self.connection.execute("INSERT OR IGNORE INTO set_memberships VALUES (?, ?, ?, ?, ?)", (row["stage"], member["set_name"], target, member["first_seen"], member["last_seen"]))
                self.connection.execute("DELETE FROM set_memberships WHERE stage=? AND entity_id=?", (row["stage"], row["entity_id"]))
                self.connection.execute("UPDATE observations SET entity_id=? WHERE stage=? AND entity_id=?", (target, row["stage"], row["entity_id"]))
                self.connection.execute("INSERT OR REPLACE INTO entity_redirects VALUES (?, ?, ?)", (row["stage"], row["entity_id"], target))
                self.connection.execute("DELETE FROM entities WHERE stage=? AND entity_id=?", (row["stage"], row["entity_id"]))
                if row["stage"] == "verified_roles":
                    for dependent in self.connection.execute("SELECT * FROM entities WHERE stage IN ('linkedin_jobs','applications')").fetchall():
                        payload = json.loads(dependent["record"])
                        changed = False
                        for key in ("role_id", "verified_role_id", "upstream_role_id", "career_job_id"):
                            if payload.get(key) == row["entity_id"]:
                                payload[key], changed = target, True
                        for key in ("role_ids", "verified_role_ids", "upstream_role_ids", "career_job_ids"):
                            if isinstance(payload.get(key), list) and row["entity_id"] in payload[key]:
                                payload[key] = list(dict.fromkeys(target if value == row["entity_id"] else value for value in payload[key]))
                                changed = True
                        canonical = self._canonicalize_role_references(payload)
                        if changed or canonical != payload:
                            payload = canonical
                            self.connection.execute("UPDATE entities SET record=? WHERE stage=? AND entity_id=?", (_json(payload), dependent["stage"], dependent["entity_id"]))
            else:
                self.connection.execute("UPDATE entities SET record=?,natural_key=? WHERE stage=? AND entity_id=?", (_json(record), natural_key, row["stage"], row["entity_id"]))

    def _company_id(self, record):
        domains = self._domains(record)
        supplied_id = str(record["id"]) if record.get("id") is not None else None
        candidates = []
        if supplied_id:
            resolved = self._resolve("companies", supplied_id)
            if self.connection.execute("SELECT 1 FROM entities WHERE stage='companies' AND entity_id=?", (resolved,)).fetchone():
                candidates.append(resolved)
        for domain in domains:
            row = self.connection.execute("SELECT company_id FROM company_domains WHERE domain=?", (domain,)).fetchone()
            if row:
                candidates.append(self._resolve("companies", row["company_id"]))
        company_id = candidates[0] if candidates else supplied_id or "company:" + _hash(domains[0] if domains else str(record.get("name", "unknown")).strip().casefold())
        for other in set(candidates) - {company_id}:
            self._merge_companies(company_id, other)
        if supplied_id and supplied_id != company_id:
            self.connection.execute("INSERT OR REPLACE INTO entity_redirects VALUES ('companies', ?, ?)", (supplied_id, company_id))
        for domain in domains:
            self.connection.execute("INSERT OR REPLACE INTO company_domains VALUES (?, ?)", (domain, company_id))
        if domains:
            record["domain"] = domains[0]
            aliases, seen = [], set()
            for value in [*(record.get("aliases") or []), *domains]:
                marker = _json(value)
                if marker not in seen:
                    aliases.append(value)
                    seen.add(marker)
            record["aliases"] = aliases
        return company_id

    def _natural_key(self, stage, record):
        if stage == "companies":
            return record["id"]
        if stage in {"linkedin_jobs", "applications"}:
            job_id = record.get("job_id") or record.get("linkedin_id")
            if job_id:
                return str(job_id)
            supplied = str(record.get("id") or "")
            numeric = supplied.split(":")[-1]
            if numeric.isdigit() and (supplied == numeric or supplied.startswith(("linkedin:", "application:"))):
                return numeric
        if stage == "verified_roles":
            location = _json(record.get("locations") or [])
            identity = record.get("career_url") or f"{str(record.get('title', '')).casefold()}|{location}"
            if not record.get("career_url") and (not record.get("company_id") or not record.get("title")):
                return str(record.get("id") or _hash(_json(record)))
            return str(record.get("company_id", "")) + "|" + identity
        return str(record.get("id") or record.get("url") or _hash(_json(record)))

    def _upsert(self, stage, set_name, incoming, run_id, observed_at):
        if not isinstance(incoming, dict):
            raise ValueError("Pipeline records must be objects")
        record = deepcopy(incoming)
        if stage == "companies":
            entity_id = self._company_id(record)
            if not record.get("name") and not self._domains(record):
                raise ValueError("A company needs a name or domain")
        else:
            if isinstance(record.get("company"), dict):
                company_evidence_at = record.get("company_observed_at") or record.get("verified_at") or record.get("discovered_at") or observed_at
                company, _ = self._upsert("companies", set_name, record["company"], run_id, company_evidence_at)
                record["company"], record["company_id"] = company, company["id"]
            elif record.get("company_id"):
                record["company_id"] = self._resolve("companies", str(record["company_id"]))
            if stage in {"linkedin_jobs", "applications"}:
                record = self._canonicalize_role_references(record)
            entity_id = str(record.get("id") or record.get("job_id") or stage.rstrip("s") + ":" + _hash(self._natural_key(stage, record)))
            entity_id = self._resolve(stage, entity_id)
        record["id"] = entity_id
        natural_key = self._natural_key(stage, record)
        old = self.connection.execute("SELECT * FROM entities WHERE stage=? AND (entity_id=? OR natural_key=?) ORDER BY entity_id=? DESC LIMIT 1", (stage, entity_id, natural_key, entity_id)).fetchone()
        effective_at = record.get("verified_at") or record.get("updated_at") or observed_at
        if old:
            if entity_id != old["entity_id"]:
                self.connection.execute("INSERT OR REPLACE INTO entity_redirects VALUES (?, ?, ?)", (stage, entity_id, old["entity_id"]))
                entity_id = old["entity_id"]
                record["id"] = entity_id
            previous = json.loads(old["record"])
            newer = _moment(effective_at) >= _moment(old["observed_at"])
            merged = _combine(previous, record, newer)
            if stage == "applications" and previous.get("status") == "applied" and record.get("status") != "applied":
                merged = _combine(previous, record, False)
                merged["status"] = "applied"
            resolution = record.get("submission_resolution") or {}
            verified_resolution = isinstance(resolution, dict) and resolution.get("verified") is True and bool(resolution.get("reason")) and newer
            if (stage == "applications" and previous.get("status") == "submitting"
                    and record.get("status") not in {"submitting", "applied"} and not verified_resolution):
                merged = _combine(previous, record, False)
                merged["status"] = "submitting"
            if (previous.get("status") == "closed" and record.get("status") == "open"
                    and _moment(effective_at) <= _moment(old["observed_at"])):
                for key in ("status", "eligible", "verified_at", "exclusion_reasons"):
                    if key in previous:
                        merged[key] = previous[key]
            # Unknown evidence does not prove a previously open/closed role changed.
            if merged.get("status") == "unknown" and previous.get("status") in {"open", "closed"}:
                merged["status"] = previous["status"]
            changed = _json(merged) != _json(previous)
            self.connection.execute("UPDATE entities SET record=?, observed_at=? WHERE stage=? AND entity_id=?", (_json(merged), effective_at if newer else old["observed_at"], stage, entity_id))
        else:
            merged, changed = record, True
            self.connection.execute("INSERT INTO entities VALUES (?, ?, ?, ?, ?)", (stage, entity_id, natural_key, _json(merged), effective_at))
        new_membership = self.connection.execute("SELECT 1 FROM set_memberships WHERE stage=? AND set_name=? AND entity_id=?", (stage, set_name, entity_id)).fetchone() is None
        self.connection.execute("INSERT INTO set_memberships VALUES (?, ?, ?, ?, ?) ON CONFLICT(stage,set_name,entity_id) DO UPDATE SET last_seen=excluded.last_seen", (stage, set_name, entity_id, observed_at, observed_at))
        observation_id = _hash(_json([stage, entity_id, run_id, incoming]))
        self.connection.execute("INSERT OR IGNORE INTO observations VALUES (?, ?, ?, ?, ?, ?)", (observation_id, stage, entity_id, run_id, observed_at, _json(incoming)))
        return merged, changed or new_membership

    def upsert_many(self, stage, set_name, records, run_id, observed_at=None):
        self._validate(stage, set_name)
        # Materialize and validate before starting a transaction.
        records = list(records)
        _json(records)
        observed_at = observed_at or utc_now()
        changed = {}
        with self.connection:
            for record in records:
                merged, updated = self._upsert(stage, set_name, record, run_id, observed_at)
                if updated:
                    changed[merged["id"]] = merged
        return list(changed.values())

    def import_artifact(self, payload_or_path, expected_stage=None):
        artifact = read_artifact(payload_or_path, expected_stage)
        changed_ids = set()
        selected_ids = []
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO runs VALUES (?, ?, ?, ?, '{}', ?, ?, ?, ?)",
                                    (artifact.run_id, artifact.stage, artifact.set_name, _json(artifact.input_set_ids), "partial" if artifact.errors else "complete", artifact.created_at, artifact.created_at, _json(artifact.errors)))
            for record in artifact.records:
                saved, changed = self._upsert(artifact.stage, artifact.set_name, record, artifact.run_id, artifact.created_at)
                selected_ids.append(saved["id"])
                if changed:
                    changed_ids.add(saved["id"])
        # An edited export may intentionally select a subset for application.
        # Resolve those records against current state without broadening selection.
        selected = {}
        for ident in selected_ids:
            record = self.resolve_record(artifact.stage, ident)
            if record:
                selected[record["id"]] = record
        changed_ids = {self._resolve(artifact.stage, ident) for ident in changed_ids}
        cumulative = list(selected.values())
        return StageResult(artifact.stage, artifact.set_name, artifact.run_id, artifact.created_at,
                           artifact.input_set_ids, cumulative,
                           [record for record in cumulative if record["id"] in changed_ids], artifact.errors)
