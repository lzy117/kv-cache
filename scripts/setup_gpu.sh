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
SGLANG_CLONE_DEPTH="${SGLANG_CLONE_DEPTH:-1}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$WORKDIR/venv}"
MODEL_PATH="${MODEL_PATH:-Qwen/Qwen2.5-7B-Instruct}"
MEM_FRACTION_STATIC="${MEM_FRACTION_STATIC:-0.85}"
PORT="${PORT:-30000}"
ATTENTION_BACKEND="${ATTENTION_BACKEND:-}"
INSTALL_SGLANG="${INSTALL_SGLANG:-1}"
INSTALL_RUST="${INSTALL_RUST:-1}"
RUST_MIN_VERSION="${RUST_MIN_VERSION:-1.85.0}"
RESET_SGLANG_SOURCE="${RESET_SGLANG_SOURCE:-1}"
RUSTUP_DIST_SERVER="${RUSTUP_DIST_SERVER:-https://rsproxy.cn}"
RUSTUP_UPDATE_ROOT="${RUSTUP_UPDATE_ROOT:-https://rsproxy.cn/rustup}"
export RUSTUP_DIST_SERVER
export RUSTUP_UPDATE_ROOT

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

rust_version_ok() {
  if ! command -v rustc >/dev/null 2>&1; then
    return 1
  fi
  local version
  version="$(rustc --version | awk '{print $2}')"
  [[ "$(printf '%s\n%s\n' "$RUST_MIN_VERSION" "$version" | sort -V | head -n1)" == "$RUST_MIN_VERSION" ]]
}

install_rustup_stable() {
  if ! command -v curl >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1 && [[ "$(id -u)" == "0" ]]; then
      apt-get update
      apt-get install -y curl ca-certificates
    else
      echo "curl is required to install a recent Rust toolchain." >&2
      exit 1
    fi
  fi
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
  # shellcheck source=/dev/null
  source "$HOME/.cargo/env"
  rustup default stable
}

if [[ "$INSTALL_RUST" == "1" ]]; then
  if [[ -f "$HOME/.cargo/env" ]]; then
    # shellcheck source=/dev/null
    source "$HOME/.cargo/env"
  fi
  if ! rust_version_ok; then
    echo "Rust >= $RUST_MIN_VERSION is required for SGLang's edition2024 crates."
    echo "Current rustc: $(rustc --version 2>/dev/null || echo missing)"
    echo "Installing/updating Rust stable with rustup..."
    install_rustup_stable
  fi
  if ! rust_version_ok; then
    echo "Rust toolchain is still too old after installation: $(rustc --version 2>/dev/null || echo missing)" >&2
    exit 1
  fi
  echo "Using Rust toolchain: $(rustc --version), $(cargo --version)"
fi

SGLANG_DIR="$WORKDIR/sglang"
if [[ ! -d "$SGLANG_DIR/.git" ]]; then
  if [[ -e "$SGLANG_DIR" ]]; then
    echo "$SGLANG_DIR exists but is not a git checkout. Remove it and rerun setup." >&2
    exit 1
  fi
  git clone --depth "$SGLANG_CLONE_DEPTH" --branch "$SGLANG_TAG" "$SGLANG_REPO_URL" "$SGLANG_DIR"
else
  git -C "$SGLANG_DIR" fetch --depth "$SGLANG_CLONE_DEPTH" origin tag "$SGLANG_TAG" || true
  git -C "$SGLANG_DIR" checkout "$SGLANG_TAG"
fi

if [[ "$RESET_SGLANG_SOURCE" == "1" ]]; then
  git -C "$SGLANG_DIR" reset --hard "$SGLANG_TAG"
  git -C "$SGLANG_DIR" clean -fd
fi

PATCH_SRC="$LAB_DIR/patches/sglang-2q-mem-cache.patch"
PATCH_TMP="/tmp/sglang-2q-mem-cache.patch"
cp "$PATCH_SRC" "$PATCH_TMP"

echo "Applying 2Q patch to $SGLANG_DIR..."
if (cd "$SGLANG_DIR/python" && git apply --check "$PATCH_TMP" && git apply "$PATCH_TMP"); then
  echo "2Q patch applied with git apply."
else
  echo "git apply failed; falling back to copying verified vendor mem_cache files."
  cp "$LAB_DIR/vendor/sglang/srt/mem_cache/evict_policy.py" \
    "$SGLANG_DIR/python/sglang/srt/mem_cache/evict_policy.py"
  cp "$LAB_DIR/vendor/sglang/srt/mem_cache/radix_cache.py" \
    "$SGLANG_DIR/python/sglang/srt/mem_cache/radix_cache.py"
  cp "$LAB_DIR/vendor/sglang/srt/mem_cache/utils.py" \
    "$SGLANG_DIR/python/sglang/srt/mem_cache/utils.py"
  python - "$SGLANG_DIR/python/sglang/srt/server_args.py" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = 'RADIX_EVICTION_POLICY_CHOICES = ["lru", "lfu", "slru", "priority"]'
new = 'RADIX_EVICTION_POLICY_CHOICES = ["lru", "lfu", "slru", "priority", "2q"]'
if new not in text:
    if old not in text:
        raise SystemExit(f"Could not find radix eviction choices in {path}")
    text = text.replace(old, new, 1)
    path.write_text(text)
PY
fi
python - "$SGLANG_DIR/python/sglang/srt/mem_cache/utils.py" "$SGLANG_DIR/python/sglang/srt/server_args.py" <<'PY'
from pathlib import Path
import sys

utils_path = Path(sys.argv[1])
server_args_path = Path(sys.argv[2])
utils_text = utils_path.read_text()
server_args_text = server_args_path.read_text()

checks = [
    ("TwoQStrategy import/registration", "TwoQStrategy" in utils_text and '"2q"' in utils_text, utils_path),
    ("2q CLI choice", '"2q"' in server_args_text, server_args_path),
]
failed = False
for name, ok, path in checks:
    if ok:
        continue
    failed = True
    print(f"2Q patch verification failed: {name} missing in {path}", file=sys.stderr)
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        if "2q" in line.lower() or "TwoQ" in line:
            print(f"{path}:{lineno}: {line}", file=sys.stderr)

if failed:
    raise SystemExit(1)
PY
echo "2Q patch applied and policy factory registered."

if [[ "$INSTALL_SGLANG" == "1" ]]; then
  echo "Installing patched SGLang package..."
  python -m pip install -e "$SGLANG_DIR/python[all]"
else
  echo "INSTALL_SGLANG=0, skipping editable SGLang install."
fi

echo "Running bench script py_compile smoke..."
python -m py_compile \
  "$LAB_DIR/bench/replay.py" \
  "$LAB_DIR/bench/mock_server.py" \
  "$LAB_DIR/bench/collect.py"

echo "Running 2Q import smoke..."
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
