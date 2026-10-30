#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv-captchakraken"
PYTHON="$VENV/bin/python"
CLI="$VENV/bin/captchakraken"
BASE_PYTHON="$HOME/.pyenv/versions/3.11.6/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  if [[ ! -x "$BASE_PYTHON" ]]; then
    echo "error: Python 3.11.6 not found at $BASE_PYTHON" >&2
    exit 1
  fi
  "$BASE_PYTHON" -m venv "$VENV"
fi

if ! "$PYTHON" -c "import captchakraken" >/dev/null 2>&1; then
  "$PYTHON" -m pip install captchakraken==3.2.1 playwright==1.64.0
fi

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

for name in CAPTCHA_KRAKEN_API_KEY CAPTCHA_KRAKEN_BASE_URL VLLM_BASE_URL; do
  if [[ -n "${!name:-}" ]]; then
    printf '%s=set\n' "$name"
  else
    printf '%s=unset\n' "$name"
  fi
done

if [[ -x "$CLI" ]]; then
  # The client reads VLLM_BASE_URL from the environment; the other name is only
  # honoured from ~/.captchakraken/credentials. Export the one the client uses.
  if [[ -n "${CAPTCHA_KRAKEN_BASE_URL:-}" && -z "${VLLM_BASE_URL:-}" ]]; then
    export VLLM_BASE_URL="$CAPTCHA_KRAKEN_BASE_URL"
  fi
  if ! "$CLI" server status; then
    echo "warning: CaptchaKraken auth probe failed; check the key and endpoint" >&2
  fi
else
  echo "warning: CaptchaKraken CLI not found at $CLI" >&2
fi

chmod +x "$ROOT/scripts/setup_captcha_solver.sh"
