#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MITMWEB="$PROJECT_DIR/.venv/bin/mitmweb"
ADDON="$PROJECT_DIR/rocket/main.py"

if [[ ! -x "$MITMWEB" ]]; then
  echo "❌ Не найден исполняемый mitmweb: $MITMWEB"
  echo "Запусти из корня проекта:"
  echo "  uv venv .venv --python 3.11"
  echo "  uv pip install --python .venv/bin/python mitmproxy PyMuPDF"
  exit 1
fi

if [[ ! -f "$ADDON" ]]; then
  echo "❌ Не найден addon: $ADDON"
  exit 1
fi

echo "🔎 Ищу старые mitmweb процессы для rocket/main.py..."

PIDS="$(pgrep -f "mitmweb.*-s .*rocket/main.py" || true)"

if [[ -n "$PIDS" ]]; then
  found=0
  for pid in $PIDS; do
    if [[ "$pid" == "$$" ]]; then
      continue
    fi
    found=1
    echo "🛑 Останавливаю PID $pid"
    kill "$pid" 2>/dev/null || true
  done

  if [[ "$found" == "0" ]]; then
    echo "✅ Старых процессов не найдено"
  fi
  sleep 1

  for pid in $PIDS; do
    if [[ "$pid" == "$$" ]]; then
      continue
    fi
    if kill -0 "$pid" 2>/dev/null; then
      echo "💥 PID $pid ещё жив, kill -9"
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
else
  echo "✅ Старых процессов не найдено"
fi

cd "$PROJECT_DIR"
echo "🚀 Запускаю чистый mitmweb:"
echo "   $MITMWEB -s ./rocket/main.py"
exec "$MITMWEB" -s ./rocket/main.py
