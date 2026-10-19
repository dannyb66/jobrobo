import os
import json
import shutil
import tempfile
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
import sys


def resource_path(relative_path: str) -> Path:
    """ Get path to resource, works for dev and for py2app bundle """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller-style; not needed here
        return Path(sys._MEIPASS) / relative_path
    elif getattr(sys, 'frozen', False):
        # py2app bundle
        return Path(sys.executable).parent.parent / "Resources" / relative_path
    else:
        # Normal dev mode
        return Path(__file__).resolve().parent.parent / relative_path


APP_BUNDLE_CONFIG_FILE = resource_path("config/resume_optimizer_defaults.json")
RUNTIME_CONFIG_DIR = Path.home() / "Library/Application Support/jobrobo/config"
RUNTIME_CONFIG_FILE = RUNTIME_CONFIG_DIR / "resume_optimizer_defaults.json"


def ensure_runtime_config_exists():
    RUNTIME_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not RUNTIME_CONFIG_FILE.exists():
        shutil.copy2(APP_BUNDLE_CONFIG_FILE, RUNTIME_CONFIG_FILE)


def _read_config(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in configuration file: {path}") from exc
    if not isinstance(config, dict):
        raise ValueError(f"Configuration must be a JSON object: {path}")
    return config


def _merge_runtime_defaults(defaults: dict, runtime: dict) -> dict:
    """Fill missing options while preserving user values and legacy behavior."""
    merged = deepcopy(defaults)
    merged.update(runtime)
    if "optimization_mode" not in runtime and (
        "replace_job_title" in runtime or "rewrite_bullets" in runtime
    ):
        merged["optimization_mode"] = (
            "full" if runtime.get("replace_job_title") and runtime.get("rewrite_bullets")
            else "bullets" if runtime.get("rewrite_bullets")
            else "skills"
        )

    # A legacy custom Trek bank remains authoritative when expanding to the
    # multi-project list. Explicit lists, including [], are never replaced.
    if "project_bullet_banks" not in runtime:
        for bank in merged.get("project_bullet_banks", []):
            if bank.get("company") != "Trek Health":
                continue
            for old_key, new_key in (
                ("bullet_bank_path", "path"), ("bullet_bank_company", "company"),
                ("max_bank_bullets", "max_bullets"),
                ("allow_unverified_bullet_terms", "allow_unverified"),
            ):
                if old_key in runtime:
                    bank[new_key] = runtime[old_key]
            if "max_bank_bullets" in runtime:
                maximum = int(runtime["max_bank_bullets"] or 7)
                bank["min_bullets"] = min(int(bank.get("min_bullets", maximum)), maximum)
            break
    return merged


@contextmanager
def _runtime_config_lock():
    """Serialize config initialization and updates across processes and threads."""
    RUNTIME_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = RUNTIME_CONFIG_DIR / (RUNTIME_CONFIG_FILE.name + ".lock")
    with lock_path.open("a+b") as lock_file:
        if os.name == "nt":
            import msvcrt
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load_runtime_config():
    defaults = _read_config(APP_BUNDLE_CONFIG_FILE)
    ensure_runtime_config_exists()
    return _merge_runtime_defaults(defaults, _read_config(RUNTIME_CONFIG_FILE))


def peek_runtime_config():
    """Read atomic config snapshots without provisioning files or taking a write lock."""
    defaults = _read_config(APP_BUNDLE_CONFIG_FILE)
    return _merge_runtime_defaults(defaults, _read_config(RUNTIME_CONFIG_FILE)) if RUNTIME_CONFIG_FILE.exists() else defaults


def load_runtime_config():
    with _runtime_config_lock():
        return _load_runtime_config()


def save_runtime_config(updated_config: dict):
    with _runtime_config_lock():
        config = _load_runtime_config()
        config.update(updated_config)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=RUNTIME_CONFIG_DIR,
                prefix="resume-optimizer-", suffix=".json", delete=False,
            ) as f:
                temporary_path = Path(f.name)
                json.dump(config, f, indent=4)
                f.write("\n")
            os.replace(temporary_path, RUNTIME_CONFIG_FILE)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


# For debugging / dev testing
if __name__ == "__main__":
    print(load_runtime_config())
