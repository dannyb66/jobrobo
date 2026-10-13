"""Header-safe application history with atomic, lossless schema migration."""

from contextlib import contextmanager
import csv
import os
from pathlib import Path
import shutil
import tempfile

if os.name == "nt":
    import msvcrt
else:
    import fcntl


SEARCH_FIELDS = [
    "Search Run ID", "Search Query ID", "Search Query", "Search Mode",
    "Search Profile", "Search Source",
]


@contextmanager
def file_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        if os.name == "nt":
            if handle.tell() == 0:
                handle.write("0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def search_metadata(manifest=None, spec=None):
    if manifest is None or spec is None:
        return dict.fromkeys(SEARCH_FIELDS, "")
    return dict(zip(SEARCH_FIELDS, [
        manifest.data["run_id"], spec.query_id, spec.classic_query if spec.mode == "classic" else spec.query_text, spec.mode,
        f"{spec.profile_name}@{spec.profile_version}", spec.source,
    ]))


def append_history(path, fieldnames, row):
    path = Path(path)
    fields = list(dict.fromkeys([*fieldnames, *SEARCH_FIELDS]))
    with file_lock(str(path) + ".lock"):
        existing = []
        if path.exists() and path.stat().st_size:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                existing = reader.fieldnames or []
                if "Job ID" not in existing or len(existing) != len(set(existing)):
                    raise ValueError("Unrecognized application history header; original file preserved")
            fields = list(dict.fromkeys([*existing, *fields]))
        if existing and existing != fields:
            # Read and validate all rows before touching the original file.
            with path.open(newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            if any(None in item or any(value is None for value in item.values()) for item in rows):
                raise ValueError("Malformed history row; original file preserved")
            if "Date Applied" in fields and "Date Applied" not in existing:
                # An undated applied-history schema was previously treated as applied.
                # Keep that meaning when adding the date column, without inventing a date.
                for item in rows:
                    item["Date Applied"] = "Unknown (legacy applied history)"
            backup = path.with_name(path.name + ".bak")
            if not backup.exists():
                shutil.copy2(path, backup)
            descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
            try:
                with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(rows)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            if handle.tell() == 0:
                writer.writeheader()
            writer.writerow(row)
            handle.flush()
            os.fsync(handle.fileno())


def load_applied_job_ids(path):
    """Pending external links are not submitted applications."""
    path = Path(path)
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if "Job ID" not in (reader.fieldnames or []):
            raise ValueError("Application history has no Job ID column")
        return {
            row["Job ID"].strip() for row in reader
            if row.get("Job ID", "").strip().isdigit()
            and ("Date Applied" not in row or row["Date Applied"].strip() not in ("", "Pending"))
        }
