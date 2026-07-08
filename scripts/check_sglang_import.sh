#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
source "$HOME/sgl-dev/bin/activate"

SGLANG_DIR="${SGLANG_DIR:-$HOME/sglang-v0.5.14}"
cd "$SGLANG_DIR"

PYTHONPATH=python python - <<'PY'
from sglang.srt.mem_cache.radix_cache import RadixCache

print("ok")
print(RadixCache)
PY

