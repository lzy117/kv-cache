#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
source "$HOME/sgl-dev/bin/activate"

LAB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$LAB_DIR"

PYTHONPATH=vendor python - <<'PY'
from sglang.srt.mem_cache.evict_policy import (
    FIFOStrategy,
    LFUStrategy,
    LRUStrategy,
    SLRUStrategy,
)
from sglang.srt.mem_cache.radix_cache import RadixCache

print("ok")
print(
    RadixCache.__name__,
    LRUStrategy.__name__,
    LFUStrategy.__name__,
    FIFOStrategy.__name__,
    SLRUStrategy.__name__,
)
PY

