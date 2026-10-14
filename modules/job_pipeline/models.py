"""Portable pipeline contracts without browser or optional dependency imports."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path

DEFAULT_DB_PATH = "data/job_pipeline/pipeline.sqlite3"
STAGES = ("companies", "verified_roles", "linkedin_jobs", "applications")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StageResult(Mapping):
    stage: str
    set_name: str
    run_id: str
    created_at: str
    input_set_ids: list = field(default_factory=list)
    records: list = field(default_factory=list)
    delta: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    schema_version: int = 1

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("Unsupported pipeline artifact schema_version; expected 1")
        if self.stage not in STAGES:
            raise ValueError(f"Unsupported pipeline stage: {self.stage}")
        for name in ("set_name", "run_id", "created_at"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"Artifact {name} must be nonempty text")
        try:
            datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("Artifact created_at must be an ISO timestamp") from error
        if not isinstance(self.input_set_ids, list) or any(not isinstance(value, str) for value in self.input_set_ids):
            raise ValueError("Artifact input_set_ids must be a list of strings")
        for name in ("records", "delta", "errors"):
            if not isinstance(getattr(self, name), list) or any(not isinstance(row, dict) for row in getattr(self, name)):
                raise ValueError(f"Artifact {name} must be a list of objects")
        # Enforce portable JSON now, rather than after persisting part of a stage.
        json.dumps(asdict(self), allow_nan=False)

    @classmethod
    def create(cls, stage, set_name, run_id, records, delta=(), errors=(), input_set_ids=()):
        return cls(stage, set_name, run_id, utc_now(), list(input_set_ids), list(records), list(delta), list(errors))

    @classmethod
    def from_dict(cls, payload, expected_stage=None):
        if isinstance(payload, cls):
            payload = payload.to_dict()
        if not isinstance(payload, dict):
            raise ValueError("A pipeline artifact must be a JSON object")
        required = {"schema_version", "stage", "set_name", "run_id", "created_at", "input_set_ids", "records", "delta", "errors"}
        if set(payload) != required:
            raise ValueError("Pipeline artifact has missing or unsupported fields")
        result = cls(**deepcopy(payload))
        if expected_stage and result.stage != expected_stage:
            raise ValueError(f"Expected {expected_stage} artifact, got {result.stage}")
        return result

    def to_dict(self):
        return asdict(self)

    def __getitem__(self, key):
        if key not in self.__dataclass_fields__:
            raise KeyError(key)
        return getattr(self, key)

    def __iter__(self):
        return iter(self.__dataclass_fields__)

    def __len__(self):
        return len(self.__dataclass_fields__)


@dataclass
class LinkedInRunRequest:
    mode: str
    input_sets: list
    set_name: str
    output_path: str | None = None
    limit: int = 25
    db_path: str = DEFAULT_DB_PATH
    refresh: bool = False

    def __post_init__(self):
        if self.mode not in {"search", "apply", "search-and-apply"}:
            raise ValueError("LinkedIn mode must be search, apply, or search-and-apply")
        if type(self.limit) is not int or self.limit < 1:
            raise ValueError("Pipeline limit must be a positive integer")
        if not isinstance(self.set_name, str) or not self.set_name.strip():
            raise ValueError("Pipeline set_name must be nonempty")
        if not isinstance(self.input_sets, list):
            raise ValueError("LinkedIn input_sets must be a list")
        self.input_sets = [StageResult.from_dict(item).to_dict() for item in self.input_sets]


def read_artifact(payload_or_path, expected_stage=None):
    if isinstance(payload_or_path, (str, Path)):
        payload_or_path = json.loads(Path(payload_or_path).read_text(encoding="utf-8"))
    return StageResult.from_dict(payload_or_path, expected_stage)


def write_artifact(result, path):
    """Write an artifact atomically; a failed write preserves the previous export."""
    import os
    import tempfile

    payload = StageResult.from_dict(result).to_dict()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pipeline-export-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
