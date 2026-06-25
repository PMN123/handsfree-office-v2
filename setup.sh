#!/usr/bin/env bash
# HandsFree Office — server bootstrap (PRD D3, §8.6).
# Installs Ollama + the local NLU model and the Python dependencies.
# Local-only: no cloud, no API keys. Run once before first use.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL="${OLLAMA_MODEL:-qwen2.5:3b-instruct}"
PY="${PYTHON:-python3}"

echo "==> HandsFree Office setup"

# 1) Install Ollama if absent.
if command -v ollama >/dev/null 2>&1; then
  echo "==> Ollama already installed"
else
  echo "==> Installing Ollama..."
  case "$(uname -s)" in
    Darwin)
      if command -v brew >/dev/null 2>&1; then
        brew install ollama
      else
        echo "Homebrew not found. Install Ollama from https://ollama.com/download then re-run." >&2
        exit 1
      fi
      ;;
    Linux)
      curl -fsSL https://ollama.com/install.sh | sh
      ;;
    *)
      echo "Unsupported OS for auto-install — see https://ollama.com/download" >&2
      exit 1
      ;;
  esac
fi

# 2) Make sure the Ollama service is reachable, then pull the model.
if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "==> Starting Ollama service..."
  (ollama serve >/dev/null 2>&1 &) || true
  for _ in $(seq 1 15); do
    curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
  done
fi

echo "==> Pulling model: ${MODEL}  (one-time, multi-GB download)"
ollama pull "${MODEL}"

# 3) Python dependencies.
echo "==> Installing Python dependencies"
"${PY}" -m pip install -r "${HERE}/server/requirements.txt"

echo ""
echo "==> Done. Start the server with:"
echo "      ${PY} ${HERE}/server/server.py"
