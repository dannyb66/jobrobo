"""Contract tests for the CAPTCHA solver bridge. No browser, no network."""
import json

import pytest

from modules import captcha_solver


class FakeDriver:
    capabilities = {"goog:chromeOptions": {"debuggerAddress": "127.0.0.1:9999"}}

    current_url = "https://jobs.ashbyhq.com/x/y"

    def __init__(self, address="127.0.0.1:9999"):
        self.capabilities = {"goog:chromeOptions": {"debuggerAddress": address}}


@pytest.fixture(autouse=True)
def enabled_solver(monkeypatch):
    monkeypatch.setenv("CAPTCHA_SOLVER", "1")
    monkeypatch.setenv("CAPTCHA_KRAKEN_API_KEY", "ck_live_test")
    monkeypatch.setenv("VLLM_BASE_URL", "https://api.captchakraken.com/v1")


def test_disabled_returns_disabled(monkeypatch):
    monkeypatch.delenv("CAPTCHA_SOLVER", raising=False)
    monkeypatch.setattr(captcha_solver, "_env", lambda name: "")
    record = captcha_solver.solve(FakeDriver())
    assert record["status"] == captcha_solver.DISABLED
    assert not captcha_solver.cleared(record)


def test_available_reports_missing_credentials(monkeypatch):
    monkeypatch.setenv("CAPTCHA_KRAKEN_API_KEY", "")
    monkeypatch.setenv("VLLM_API_KEY", "")
    monkeypatch.setenv("VLLM_BASE_URL", "")
    monkeypatch.setattr(captcha_solver, "_dotenv", lambda: {})
    monkeypatch.setattr(captcha_solver.shutil, "which", lambda name: "/usr/bin/node")
    monkeypatch.setattr(captcha_solver, "VENV_PYTHON", __import__("pathlib").Path("/bin/echo"))
    monkeypatch.setattr(captcha_solver, "_credentials_present", lambda: False)
    ok, why = captcha_solver.available()
    assert not ok
    assert "CAPTCHA_KRAKEN_API_KEY" in why


def test_available_reports_missing_venv(monkeypatch):
    monkeypatch.setattr(captcha_solver.shutil, "which", lambda name: None)
    monkeypatch.setattr(captcha_solver, "VENV_PYTHON", __import__("pathlib").Path("/nope/python"))
    ok, why = captcha_solver.available()
    assert not ok
    assert ".venv-captchakraken" in why or "setup_captcha_solver" in why


def test_dotenv_is_read_without_export(monkeypatch):
    for name in ("CAPTCHA_SOLVER", "CAPTCHA_KRAKEN_API_KEY", "VLLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(captcha_solver, "_dotenv",
                        lambda: {"CAPTCHA_SOLVER": "1",
                                 "CAPTCHA_KRAKEN_API_KEY": "k",
                                 "VLLM_BASE_URL": "https://api.captchakraken.com/v1"})
    assert captcha_solver.enabled()
    ok, why = captcha_solver.available()
    assert ok, why


def test_solve_passes_credentials_and_url_to_child(monkeypatch):
    seen = {}

    class Completed:
        stdout = json.dumps({"status": "cleared", "levels": ["detected"], "token_length": 42})
        stderr = ""

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["env"] = kwargs.get("env") or {}
        return Completed()

    monkeypatch.setattr(captcha_solver.subprocess, "run", fake_run)
    monkeypatch.setattr(captcha_solver, "cdp_url", lambda driver: "ws://127.0.0.1:9999/devtools/browser/x")
    record = captcha_solver.solve(FakeDriver())
    assert record["status"] == "cleared"
    assert captcha_solver.cleared(record)
    assert "--url" in seen["command"]
    assert seen["env"]["CAPTCHA_KRAKEN_API_KEY"] == "ck_live_test"
    assert seen["env"]["VLLM_BASE_URL"].startswith("https://")
    # The vendor reads VLLM_BASE_URL from the environment and the other name
    # only from its credentials file; sending one alone dials localhost.
    assert seen["env"]["CAPTCHA_KRAKEN_BASE_URL"].startswith("https://")


def test_solve_without_cdp_endpoint(monkeypatch):
    monkeypatch.setattr(captcha_solver, "cdp_url", lambda driver: None)
    record = captcha_solver.solve(FakeDriver())
    assert record["status"] == "error"
    assert "CDP" in record["detail"]


def test_timeout_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(captcha_solver, "cdp_url", lambda driver: "ws://x")

    def boom(command, **kwargs):
        raise captcha_solver.subprocess.TimeoutExpired(command, kwargs.get("timeout"))

    monkeypatch.setattr(captcha_solver.subprocess, "run", boom)
    record = captcha_solver.solve(FakeDriver(), timeout=5)
    assert record["status"] == "timeout"


def test_no_sidecar_output_is_error(monkeypatch):
    class Completed:
        stdout = ""
        stderr = "traceback-ish"

    monkeypatch.setattr(captcha_solver, "cdp_url", lambda driver: "ws://x")
    monkeypatch.setattr(captcha_solver.subprocess, "run", lambda *a, **k: Completed())
    record = captcha_solver.solve(FakeDriver())
    assert record["status"] == "error"
    assert "traceback" in record["detail"]


def test_last_json_line_wins(monkeypatch):
    class Completed:
        stdout = "noise\n" + json.dumps({"status": "no_challenge", "detail": "none"}) + "\n"
        stderr = ""

    monkeypatch.setattr(captcha_solver, "cdp_url", lambda driver: "ws://x")
    monkeypatch.setattr(captcha_solver.subprocess, "run", lambda *a, **k: Completed())
    record = captcha_solver.solve(FakeDriver())
    assert record["status"] == "no_challenge"


def test_cleared_requires_evidence():
    assert not captcha_solver.cleared({"status": "cleared", "token_length": -1, "levels": []})
    assert captcha_solver.cleared({"status": "cleared", "token_length": 10, "levels": []})
    assert captcha_solver.cleared({"status": "cleared", "token_length": -1,
                                   "levels": ["challenge_cleared"]})
    assert not captcha_solver.cleared({"status": "rejected", "token_length": 10, "levels": []})
    assert not captcha_solver.cleared(None)


def test_describe_names_outcome_and_evidence():
    text = captcha_solver.describe({"status": "unsupported", "provider": "hcaptcha", "responses": 2})
    assert "unsupported" in text
    assert "hcaptcha" in text
    assert "responses=2" in text


def test_debugger_address_and_missing_capabilities():
    assert captcha_solver.debugger_address(FakeDriver()) == "127.0.0.1:9999"

    class Bare:
        capabilities = {}

    assert captcha_solver.debugger_address(Bare()) is None
