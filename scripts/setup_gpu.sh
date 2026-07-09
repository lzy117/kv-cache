#!/usr/bin/env bash
set -euo pipefail

# Initialize a rented GPU machine for the SGLang KV-cache lab.
#
# Typical usage after cloning this lab repo:
#   bash scripts/setup_gpu.sh
#
# Or bootstrap from a remote repository:
#   LAB_REPO_URL=https://github.com/<user>/sglang-cache-lab.git bash setup_gpu.sh

WORKDIR="${WORKDIR:-$HOME/sglang-cache-lab-run}"
LAB_REPO_URL="${LAB_REPO_URL:-}"
LAB_BRANCH="${LAB_BRANCH:-main}"
SGLANG_REPO_URL="${SGLANG_REPO_URL:-https://github.com/sgl-project/sglang.git}"
SGLANG_TAG="${SGLANG_TAG:-v0.5.14}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$WORKDIR/venv}"
MODEL_PATH="${MODEL_PATH:-Qwen/Qwen2.5-7B-Instruct}"
MEM_FRACTION_STATIC="${MEM_FRACTION_STATIC:-0.85}"
PORT="${PORT:-30000}"
ATTENTION_BACKEND="${ATTENTION_BACKEND:-}"
INSTALL_SGLANG="${INSTALL_SGLANG:-1}"

mkdir -p "$WORKDIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -d "$SCRIPT_DIR/../.git" ]]; then
  LAB_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  if [[ -z "$LAB_REPO_URL" ]]; then
    echo "LAB_REPO_URL is required when setup_gpu.sh is not run from an existing lab checkout." >&2
    exit 1
  fi
  LAB_DIR="$WORKDIR/sglang-cache-lab"
  if [[ ! -d "$LAB_DIR/.git" ]]; then
    git clone "$LAB_REPO_URL" "$LAB_DIR"
  fi
  git -C "$LAB_DIR" fetch --all --tags
  git -C "$LAB_DIR" checkout "$LAB_BRANCH"
  git -C "$LAB_DIR" pull --ff-only || true
fi

echo "lab_dir=$LAB_DIR"
echo "workdir=$WORKDIR"

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r "$LAB_DIR/requirements.txt"

SGLANG_DIR="$WORKDIR/sglang"
if [[ ! -d "$SGLANG_DIR/.git" ]]; then
  git clone "$SGLANG_REPO_URL" "$SGLANG_DIR"
fi
git -C "$SGLANG_DIR" fetch --all --tags
git -C "$SGLANG_DIR" checkout "$SGLANG_TAG"

PATCH_SRC="$LAB_DIR/patches/sglang-2q-mem-cache.patch"
PATCH_TMP="/tmp/sglang-2q-mem-cache.patch"
cp "$PATCH_SRC" "$PATCH_TMP"

if grep -q "TwoQStrategy" "$SGLANG_DIR/python/sglang/srt/mem_cache/evict_policy.py"; then
  echo "2Q patch already appears to be applied."
else
  (cd "$SGLANG_DIR/python" && git apply --check "$PATCH_TMP")
  (cd "$SGLANG_DIR/python" && git apply "$PATCH_TMP")
fi

if [[ "$INSTALL_SGLANG" == "1" ]]; then
  python -m pip install -e "$SGLANG_DIR/python[all]"
else
  echo "INSTALL_SGLANG=0, skipping editable SGLang install."
fi

python -m py_compile \
  "$LAB_DIR/bench/replay.py" \
  "$LAB_DIR/bench/mock_server.py" \
  "$LAB_DIR/bench/collect.py"

python - <<'PY'
from pathlib import Path
import sys

try:
    from sglang.srt.mem_cache.utils import get_eviction_strategy
    strategy = get_eviction_strategy("2q")
    print(f"2q import smoke ok: {strategy.__class__.__name__}")
except Exception as exc:
    print(f"2q import smoke failed: {exc!r}", file=sys.stderr)
    raise
PY

LAUNCH_SCRIPT="$WORKDIR/launch_2q_server.sh"
cat > "$LAUNCH_SCRIPT" <<EOF
#!/usr/bin/env bash
set -euo pipefail
source "$VENV_DIR/bin/activate"
python -m sglang.launch_server \\
  --model-path "$MODEL_PATH" \\
  --radix-eviction-policy 2q \\
  --mem-fraction-static "$MEM_FRACTION_STATIC" \\
  --host 0.0.0.0 \\
  --port "$PORT" ${ATTENTION_BACKEND:+\\
  --attention-backend "$ATTENTION_BACKEND"}
EOF
chmod +x "$LAUNCH_SCRIPT"

cat <<EOF

Setup complete.

Next steps:
1. Start the 2Q server:
   $LAUNCH_SCRIPT
2. In another shell, run a smoke replay:
   source "$VENV_DIR/bin/activate"
   BASE_URL=http://127.0.0.1:$PORT POLICIES=2q WORKLOADS=w1 PRESSURES=smoke LIMIT=10 bash "$LAB_DIR/scripts/run_matrix.sh"

EOF
