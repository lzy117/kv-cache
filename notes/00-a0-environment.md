# A0 Environment Log

## Host

- Windows workspace: `D:\lzy\Documents\New project`
- WSL distro: Ubuntu 22.04.5 LTS
- WSL Python before setup: 3.10.12
- Windows Git: 2.51.0
- Windows uv: 0.11.2

## WSL Python Environment

Created an isolated WSL environment:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv venv "$HOME/sgl-dev" --python 3.11
source "$HOME/sgl-dev/bin/activate"
uv pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Observed versions:

- uv: 0.11.28
- Python: 3.11.15
- torch: 2.12.1+cpu

## Locked SGLang Version

```bash
git clone --depth 1 --branch v0.5.14 https://github.com/sgl-project/sglang.git "$HOME/sglang-v0.5.14"
cd "$HOME/sglang-v0.5.14"
git rev-parse HEAD
```

Locked source commit:

```text
49e384ce9d304648e9959666ecb8ce8cd98d0deb
```

The tag reference itself is annotated; the peeled source commit is the value
above.

## Import Decision

Attempting editable install:

```bash
uv pip install -e python
```

failed because the source build requested a Rust compiler. Direct import via
`PYTHONPATH=python` also pulled general SGLang package dependencies through
`sglang/__init__.py`.

Decision: use vendor mode for stage A. The repo vendors
`python/sglang/srt/mem_cache` from the locked SGLang commit under
`vendor/sglang/srt/mem_cache`, with small CPU-only import shims in:

- `vendor/sglang/srt/mem_cache/base_prefix_cache.py`
- `vendor/sglang/srt/mem_cache/events.py`
- `vendor/sglang/srt/mem_cache/utils.py`

These shims avoid Triton, disaggregation, allocator, and service metrics imports
that are not needed by the offline RadixCache simulator.

## Verification

```bash
bash scripts/check_vendor_import.sh
```

Expected output:

```text
ok
RadixCache LRUStrategy LFUStrategy FIFOStrategy SLRUStrategy
```

