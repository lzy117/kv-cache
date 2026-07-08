# Vendor Mode

This directory contains a CPU-stage vendor copy of SGLang's
`python/sglang/srt/mem_cache` package.

- Upstream: https://github.com/sgl-project/sglang
- Tag: `v0.5.14`
- Source commit: `49e384ce9d304648e9959666ecb8ce8cd98d0deb`

The copy is used only for offline trace simulation and mechanism tests. The
actual 2Q implementation should still be developed in a SGLang fork branch and
exported into this repo as patches.

Local CPU-only shims are applied to avoid importing Triton, disaggregation, and
server metrics modules during offline simulation. See `notes/00-a0-environment.md`.

