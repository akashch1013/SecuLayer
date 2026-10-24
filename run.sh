#!/usr/bin/env bash
# Start the SecuLayer demo: ./run.sh [--live] [--no-open]
# Replay mode (the default) needs no network and no API key. Ctrl+C stops it.
set -euo pipefail

usage() { echo "Usage: ./run.sh [--live] [--no-open]"; }

mode=replay
open_browser=1
for arg in "$@"; do
  case "$arg" in
    --live) mode=live ;;
    --no-open) open_browser=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg"; usage; exit 2 ;;
  esac
done

# The project lives on the external drive. If the drive isn't mounted, this path won't resolve.
script_dir="$(dirname "${BASH_SOURCE[0]}")"
if ! repo="$(cd "$script_dir" 2>/dev/null && pwd -P)" || [ ! -f "$repo/pyproject.toml" ]; then
  echo "Can't find the SecuLayer project folder. Is the external drive plugged in?"
  echo "Plug it in and open it in the file manager, then run ./run.sh again."
  exit 1
fi
cd "$repo"
device_id() { stat -c %d "$1" 2>/dev/null || stat -f %d "$1"; }
if [ "$(device_id "$repo")" = "$(device_id /)" ]; then
  echo "Note: the project is on the internal disk; docs/PLAN.md §8.5 expects the external drive."
fi

# Keep every cache on the drive, never in ~/.cache or ~/.npm.
export UV_CACHE_DIR="${UV_CACHE_DIR:-$repo/.cache/uv}"
export npm_config_cache="${npm_config_cache:-$repo/.cache/npm}"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$repo/.cache/ms-playwright}"

command -v uv >/dev/null || { echo "uv isn't installed or isn't on PATH."; exit 1; }
command -v node >/dev/null || { echo "Node.js 22.23 or newer is required. Install it, then run ./run.sh again."; exit 1; }
if ! node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 23) ? 0 : 1)'; then
  echo "Node.js 22.23 or newer is required; found $(node --version)."
  exit 1
fi

# Install dependencies only if they're missing.
if [ ! -d .venv ]; then
  echo "Installing the Python environment (needs the network, once)…"
  uv sync --frozen
fi
if [ ! -d web/node_modules ]; then
  command -v npm >/dev/null || { echo "npm isn't installed or isn't on PATH."; exit 1; }
  echo "Installing web dependencies (needs the network, once; this can take several minutes)…"
  (cd web && npm ci)
fi

# Rebuild the frontend only if it's missing or older than its sources.
if [ ! -f web/dist/index.html ] || [ -n "$(find web/src web/index.html web/vite.config.ts web/package-lock.json -newer web/dist/index.html -print -quit 2>/dev/null)" ]; then
  echo "Building the frontend…"
  (cd web && npm run build)
fi

# The classifier is optional. Startup stays offline; download explicitly with fetch-model.
classifier_dir="${SECULAYER_CLASSIFIER_DIR:-models/prompt-guard-2-22m}"
if [ ! -f "$classifier_dir/model.quant.onnx" ]; then
  echo "Classifier not downloaded; recorded scores will be used."
  echo "For local checks on new content: uv run --frozen seculayer fetch-model"
fi

host="${SECULAYER_HOST:-127.0.0.1}"
port="${SECULAYER_PORT:-8765}"
url="http://$host:$port"

browser_command=""
if command -v xdg-open >/dev/null; then browser_command=xdg-open
elif command -v open >/dev/null; then browser_command=open
fi
if [ "$open_browser" = 1 ] && [ -n "$browser_command" ]; then
  (
    for _ in $(seq 1 60); do
      if curl -fsS "$url/api/health" >/dev/null 2>&1; then
        "$browser_command" "$url/" >/dev/null 2>&1 || true
        exit 0
      fi
      sleep 0.5
    done
  ) &
fi

exec uv run --frozen seculayer serve --host "$host" --port "$port" --mode "$mode"
