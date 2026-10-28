"""Fingerprint-bound cache for verified, job-specific optimized resumes."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_hash(path: Path) -> str | None:
    try:
        return _sha256(path.read_bytes()) if path.is_file() else None
    except OSError:
        return None


def _config_dependencies(config: dict, repo_root: Path) -> dict[str, str]:
    """Hash configured files plus optimizer and active prompt sources."""
    paths: set[Path] = set()

    def visit(value, key=""):
        if isinstance(value, dict):
            for child_key, item in value.items():
                visit(item, str(child_key))
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item, key)
        elif isinstance(value, str) and any(token in key.casefold() for token in ("path", "file", "prompt")):
            # Configuration also carries long prompt/context text. Only path-
            # named settings can be file dependencies; never interpret prose
            # as a filename (which can raise ENAMETOOLONG on some platforms).
            if len(value) > 4096:
                return
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = repo_root / candidate
            try:
                if candidate.is_file():
                    paths.add(candidate.resolve())
            except OSError:
                pass

    visit(config)
    paths.update((repo_root / relative).resolve() for relative in (
        "modules/ai/resume_optimizer.py",
        "modules/resume_all_bullets.py",
        "config/prompts/resume_bullets.txt",
    ) if (repo_root / relative).is_file())
    result = {}
    for path in sorted(paths):
        digest = _file_hash(path)
        if digest:
            try:
                name = str(path.relative_to(repo_root.resolve()))
            except ValueError:
                name = str(path)
            result[name] = digest
    return result


def resume_cache_fingerprint(*, job_id: str, job_description: str, source_resume: str | Path,
                             job_title: str, first_name: str, last_name: str,
                             config: dict, repo_root: str | Path) -> str:
    """Return a content key; changes to JD/source/config/code invalidate it."""
    root = Path(repo_root).resolve()
    source = Path(source_resume).expanduser().resolve()
    payload = {
        "cache_version": 1,
        "job_id": str(job_id),
        "job_title": str(job_title or "job"),
        "first_name": str(first_name or "first"),
        "last_name": str(last_name or "last"),
        "job_description_sha256": _sha256(str(job_description or "").encode("utf-8")),
        "source_resume_sha256": _file_hash(source),
        "config": config,
        "dependencies": _config_dependencies(config, root),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256(encoded)


def cache_record_path(source_resume: str | Path, job_id: str, fingerprint: str) -> Path:
    source = Path(source_resume).expanduser().resolve()
    root = source.parent.parent / "temp" / "job_resume_cache" / str(job_id)
    return root / f"{fingerprint}.json"


@contextmanager
def resume_cache_lock(record_path: Path):
    """Serialize a cache miss and generation so parallel jobs don't duplicate API calls."""
    lock_path = record_path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def load_cached_resume(record_path: Path, fingerprint: str, verifier) -> Path | None:
    """Return only an intact PDF whose original job-bound verifier still passes."""
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        pdf = Path(record["pdf_path"]).expanduser().resolve()
        if record.get("fingerprint") != fingerprint or not pdf.is_file() or pdf.suffix.lower() != ".pdf":
            return None
        if _file_hash(pdf) != record.get("pdf_sha256") or not verifier(pdf):
            return None
        return pdf
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def store_cached_resume(record_path: Path, fingerprint: str, pdf_path: str | Path) -> bool:
    """Atomically index a generated PDF after its caller has verified it."""
    pdf = Path(pdf_path).expanduser().resolve()
    if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
        return False
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record = {"version": 1, "fingerprint": fingerprint, "pdf_path": str(pdf),
              "pdf_sha256": _file_hash(pdf)}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=record_path.parent,
                                         prefix=record_path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(record, stream, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, record_path)
        return True
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
