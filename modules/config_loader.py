import os
import json
import shutil
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


def load_runtime_config():
    ensure_runtime_config_exists()
    try:
        with open(RUNTIME_CONFIG_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("⚠️ Could not load runtime config. Using fallback.")
        return {
            "replace_job_title": False,
            "rewrite_bullets": False,
            "resume_path": "",
            "job_id": "",
            "first_name": "first",
            "last_name": "last",
            "job_title": "job",
            "job_description": "",
        }


def save_runtime_config(updated_config: dict):
    ensure_runtime_config_exists()
    with open(RUNTIME_CONFIG_FILE, "w") as f:
        json.dump(updated_config, f, indent=4)


# For debugging / dev testing
if __name__ == "__main__":
    print(load_runtime_config())