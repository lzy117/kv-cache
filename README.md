# SGLang Cache Lab

Trace-driven experiments for SGLang RadixAttention KV-cache eviction policies.

## Scope

This repository is the main lab repo for:

- offline workload trace generation;
- CPU trace replay simulation;
- benchmark replay and result collection scripts;
- notes, prediction matrices, figures, and experiment summaries;
- exported patches for the SGLang fork branch that implements stateful 2Q eviction.

The companion SGLang fork branch will hold upstream-facing changes such as eviction event hooks and the full 2Q implementation.

## Locked Upstream

- Upstream: https://github.com/sgl-project/sglang
- Candidate locked tag: `v0.5.14`
- Candidate tag commit: `49e384ce9d304648e9959666ecb8ce8cd98d0deb`
- Release page: https://github.com/sgl-project/sglang/releases/tag/v0.5.14

Before GPU experiments, this tag should remain fixed unless an A0 import smoke test proves it unusable.

## Current A0 Status

Direct editable installation of SGLang `v0.5.14` in a CPU-only WSL environment
currently fails because the package build wants a Rust compiler. To keep the
offline phase lightweight, this repo uses vendor mode for the pure-Python
`sglang.srt.mem_cache` package. The vendor copy is patched only to avoid
service/GPU imports that are irrelevant to CPU trace simulation.

Verify the current vendor import path with:

```bash
bash scripts/check_vendor_import.sh
```

## Method

The project follows a theory-first workflow:

1. Read and document SGLang RadixCache internals.
2. Build a KV-cache memory budget and choose models.
3. Generate fixed workload traces with deterministic seeds.
4. Run a CPU trace simulator before renting GPUs.
5. Implement and test stateful 2Q eviction in a fork.
6. Run GPU experiments only after the A7 gate is fully green.

## Repository Layout

```text
.
├── analysis/              # plotting scripts and figures
├── bench/                 # replay.py, collect.py, and mock server tools
├── configs/               # experiment matrix configs
├── notes/                 # mechanism notes and frozen predictions
├── patches/               # exported SGLang fork patches
├── results/               # submitted summaries and sim matrix
├── scripts/               # setup and matrix runner scripts
├── simulator/             # offline trace replay simulator
├── traces/                # trace generator scripts, not generated traces
└── vendor/                # optional fallback copies of upstream cache files
```

Generated traces and raw per-request benchmark outputs are intentionally ignored by Git.
