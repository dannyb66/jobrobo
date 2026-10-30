"""Solve an in-page CAPTCHA through CaptchaKraken, from the Selenium lane.

The solver needs a Playwright ``Page``; this lane drives Selenium. Rather than
port the lane, we attach to the *same* browser over CDP and let the 3.11
sidecar solve the live tab. The application stays on 3.10 because
``captchakraken`` requires 3.11+.

``solve`` never raises on a CAPTCHA failure and never clicks Submit. It returns
a normalized record so callers branch on data rather than exceptions.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT / ".venv-captchakraken" / "bin" / "python"
SIDECAR = ROOT / "scripts" / "captcha_solve.py"
DEFAULT_TIMEOUT = 100

# Outcomes a caller may act on. ``cleared`` is the only one that means "go on".
CLEARED = "cleared"
NO_CHALLENGE = "no_challenge"
UNSUPPORTED = "unsupported"
DISABLED = "disabled"

LEVELS = ("detected", "model_response", "token_present", "challenge_cleared")


def enabled() -> bool:
    """Opt-in, and off in tests unless asked for."""
    return _env("CAPTCHA_SOLVER").strip().lower() in {"1", "true", "yes", "on"}


def enable() -> None:
    """Turn the solver on for this process, e.g. from an explicit CLI flag."""
    os.environ["CAPTCHA_SOLVER"] = "1"


def _dotenv() -> dict:
    """Read .env directly so callers never have to export it.

    Without VLLM_BASE_URL the vendor silently dials localhost and reports an
    unhealthy local server, which reads like a bad key.
    """
    path = ROOT / ".env"
    values = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


def _env(name: str) -> str:
    return os.getenv(name) or _dotenv().get(name, "")


def _credentials_present() -> bool:
    if _env("CAPTCHA_KRAKEN_API_KEY") or _env("VLLM_API_KEY"):
        return bool(_base_url())
    return (Path.home() / ".captchakraken" / "credentials").is_file()


def _base_url() -> str:
    """Preferred spelling first; both names are accepted here."""
    return _env("CAPTCHA_KRAKEN_BASE_URL") or _env("VLLM_BASE_URL")


def available() -> tuple[bool, str]:
    """Why the solver cannot run, if it cannot. Cheap, side-effect free."""
    if shutil.which("node") is None and not VENV_PYTHON.is_file():
        return False, "no .venv-captchakraken interpreter and no node"
    if not VENV_PYTHON.is_file():
        return False, f"{VENV_PYTHON} is missing; run scripts/setup_captcha_solver.sh"
    if not SIDECAR.is_file():
        return False, f"{SIDECAR} is missing"
    if not _credentials_present():
        return False, "CAPTCHA_KRAKEN_API_KEY and CAPTCHA_KRAKEN_BASE_URL are both required"
    return True, ""


def debugger_address(driver) -> str | None:
    return (
        driver.capabilities.get("goog:chromeOptions", {}).get("debuggerAddress")
        if getattr(driver, "capabilities", None)
        else None
    )


def cdp_url(driver) -> str | None:
    """Resolve the CDP websocket from the Selenium debugger address."""
    import urllib.request

    address = debugger_address(driver)
    if not address:
        return None
    try:
        with urllib.request.urlopen(f"http://{address}/json/version", timeout=5) as handle:
            return json.load(handle).get("webSocketDebuggerUrl")
    except Exception:
        return None


def _normalized(status: str, detail: str = "", **extra) -> dict:
    record = {"status": status, "detail": detail, "provider": None, "levels": [],
              "token_length": -1, "responses": 0, "elapsed_ms": 0, "screenshot": None}
    record.update(extra)
    return record


def solve(driver, *, expect_provider: str | None = None, timeout: int = DEFAULT_TIMEOUT,
          screenshot_dir: str | Path | None = None, wait_painted_ms: int = 0) -> dict:
    """Try to clear a challenge on the current tab. Never raises."""
    if not enabled():
        return _normalized(DISABLED, "CAPTCHA_SOLVER is not enabled")
    ready, why = available()
    if not ready:
        return _normalized(DISABLED, why)

    url = cdp_url(driver)
    if not url:
        return _normalized("error", "browser has no CDP endpoint; launch with a debugging port")

    page_url = ""
    try:
        page_url = driver.current_url
    except Exception:
        pass

    # Three loops, not five: a board that has not cleared in three is rarely
    # going to, and the caller retries a rejection with a fresh solve anyway.
    command = [str(VENV_PYTHON), str(SIDECAR), "--cdp", url, "--url", page_url,
               "--max-responses", "3", "--overall-timeout-ms", "75000"]
    if wait_painted_ms:
        command += ["--wait-painted-ms", str(wait_painted_ms)]
    if expect_provider:
        command += ["--expect-provider", expect_provider]

    screenshot = None
    if screenshot_dir:
        handle = tempfile.NamedTemporaryFile(
            prefix="captcha-", suffix=".png", dir=str(screenshot_dir), delete=False)
        handle.close()
        screenshot = handle.name
        command += ["--screenshot", screenshot]

    # Explicit env: .env is a local file, not the parent process environment.
    # Both base-URL names are forwarded: ``config.base_url()`` reads
    # ``VLLM_BASE_URL`` from the environment, while ``CAPTCHA_KRAKEN_BASE_URL``
    # is only honoured from the credentials file. Sending the first alone
    # silently falls back to localhost:8000 and looks like a dead local server.
    base_url = _base_url()
    child_env = {**os.environ,
                 "CAPTCHA_KRAKEN_API_KEY": _env("CAPTCHA_KRAKEN_API_KEY"),
                 "CAPTCHA_KRAKEN_BASE_URL": base_url,
                 "VLLM_BASE_URL": base_url}
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                                   env={k: v for k, v in child_env.items() if v})
    except subprocess.TimeoutExpired:
        return _normalized("timeout", f"sidecar exceeded {timeout}s", screenshot=screenshot)

    payload = {}
    for line in reversed((completed.stdout or "").strip().splitlines()):
        try:
            payload = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    if not payload:
        detail = (completed.stderr or completed.stdout or "no sidecar output").strip()[-800:]
        return _normalized("error", detail, screenshot=screenshot)

    payload.setdefault("levels", [])
    payload.setdefault("token_length", -1)
    payload.setdefault("responses", 0)
    if payload.get("status") != CLEARED and os.getenv("CAPTCHA_DEBUG") == "1":
        # The sidecar's own log is otherwise unreachable once it exits.
        payload["debug"] = (completed.stderr or "")[-4000:]
    # A status outside the known set is still reported, never coerced.
    return payload


def cleared(record) -> bool:
    """Challenge is gone *and* carries the evidence that matters."""
    if not record or record.get("status") != CLEARED:
        return False
    levels = record.get("levels") or []
    return record.get("token_length", -1) > 0 or "challenge_cleared" in levels


def describe(record) -> str:
    if not record:
        return "no solver result"
    parts = [record.get("status", "unknown")]
    if record.get("provider"):
        parts.append(f"provider={record['provider']}")
    if record.get("responses"):
        parts.append(f"responses={record['responses']}")
    if record.get("detail"):
        parts.append(record["detail"])
    return "; ".join(parts)
