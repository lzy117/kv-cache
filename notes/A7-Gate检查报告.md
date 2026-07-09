# A7 Gate 检查报告

检查日期：2026-07-09

## 总体结论

本地可验证项目：通过。

外部依赖项目：仍需人工完成 GitHub remote/push，以及在真实 GPU Linux 环境中执行 `scripts/setup_gpu.sh`。

因此当前状态是：**A7 条件通过，可以准备 B1；正式租卡前必须先完成远端同步。**

## Checklist

| Gate 项 | 状态 | 证据 |
| --- | --- | --- |
| A1 机制笔记 + evict 流程图完成 | 通过 | `notes/01-radix-internals.md` 已包含 evict 文字流程和 Mermaid 流程图 |
| 模型选型定稿，显存账本算完 | 通过 | `notes/02-kv-budget.md` |
| 4 类 trace 生成完毕、固定 seed、已 commit | 通过 | `traces/generate_traces.py`、`configs/trace_plan.json`；生成物按 `.gitignore` 不入库 |
| 模拟器跑通，5 策略 × 4 负载预测矩阵已出 | 通过 | `results/sim_matrix.csv` 共 80 行，包含 `lru/lfu/fifo/slru/2q` |
| 2Q 单测全绿 | 通过 | `pytest tests/test_twoq_policy.py -q`：5 passed |
| 2Q 在 W4 按预期赢下 LRU | 通过但需说明 | W4 下 2Q 明显高于 LRU/FIFO，但没有超过 SLRU/LFU |
| replay/collect 在 mock 端点调通 | 通过 | WSL mock server + `run_matrix.sh` 最小矩阵：4 requests，1 summary group |
| `notes/03-predictions.md` 已写死 | 通过 | git 历史显示仅 A3 提交修改该文件 |
| 2Q patch 可应用到上游 | 通过 | `patches/sglang-2q-mem-cache.patch` 在 SGLang `v0.5.14/python` 下 `git apply --check` 通过 |
| `scripts/setup_gpu.sh` 已写好 | 通过 | 脚本语法检查通过；包含 clone、patch、install、2Q import smoke、launch 脚本生成 |
| `scripts/setup_gpu.sh` 在干净 GPU 环境演练 | 待完成 | 本机无 GPU；需 B1 前在租用机或干净 Linux 环境执行 |
| 全部代码 push 到 GitHub | 待完成 | 当前仓库没有 remote；需要用户配置远端后 push |
| 实验矩阵与预计时长排成表 | 通过 | `configs/gpu_experiment_plan.csv`，48 行，预计约 23.9 小时基础计划 |
| 历史中无真实 HF/GitHub token | 通过 | 扫描命中仅 `.env.example` 的空 `HF_TOKEN=` 和公开 `HF_ENDPOINT` |
| generated trace/raw 未入库 | 通过 | `git ls-files traces/*.jsonl traces/manifest_*.json results/raw/*` 无输出 |

## 已运行命令

```bash
wsl -e bash -lc 'bash -n scripts/setup_gpu.sh && bash -n scripts/run_matrix.sh'
wsl -e bash -lc 'cp patches/sglang-2q-mem-cache.patch /tmp/sglang-2q-mem-cache.patch && cd $HOME/sglang-v0.5.14/python && git apply --check /tmp/sglang-2q-mem-cache.patch'
wsl -e bash -lc 'source $HOME/sgl-dev/bin/activate && python -m pytest tests/test_twoq_policy.py -q'
wsl -e bash -lc 'BASE_URL=http://127.0.0.1:30080 POLICIES=lru WORKLOADS=w1 PRESSURES=mock LIMIT=4 CONCURRENCY=1 PROFILE=smoke OUTPUT_DIR=results/raw/a7_gate_mock SUMMARY_OUT=results/a7_gate_mock_summary.csv bash scripts/run_matrix.sh'
```

PowerShell 检查：

```powershell
Import-Csv results/sim_matrix.csv
git ls-files traces/*.jsonl traces/manifest_*.json results/raw/*
git log --oneline -- notes/03-predictions.md
git log -p --all | Select-String -Pattern 'hf_|github_pat|HF_TOKEN|GITHUB_TOKEN'
```

## W4 预期修正

A3 的原始预测写的是 W4 中 2Q 最有机会显著占优。A5/A7 的模拟结果更精确：

- 2Q 明显优于 LRU/FIFO；
- 2Q 接近 SLRU/LFU；
- 2Q 没有超过 SLRU/LFU。

原因：

1. RadixCache 只能淘汰叶子，削弱了扫描污染对共享前缀的破坏。
2. 当前 W4 中稳定热点的 `hit_count` 足够让 SLRU/LFU 保护它们。
3. 当前 2Q 没有 token 级 A1in 配额，扫描隔离不如严格论文版强。

这不阻塞进入 B 阶段，但真机报告里必须如实写成“2Q 对 LRU/FIFO 的扫描抵抗有效，但相对 SLRU/LFU 仅接近或小幅落后”。

## 租卡前剩余动作

1. 配置 GitHub remote，并 push 当前主仓库。
2. 如果有 SGLang fork，创建或更新 `2q-eviction` 分支；如果暂时没有 fork，B1 可用 `patches/sglang-2q-mem-cache.patch` 在租用机上打 patch。
3. 在租用机或干净 Linux 环境运行：

```bash
bash scripts/setup_gpu.sh
```

4. 记录 `max_total_num_tokens`，回填 B2 压力标定。
5. 完成上述外部项后，再打 `gate-passed` tag。
