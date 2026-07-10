# GPU 实验结果汇总

## 结果文件

本次远程实验产物已归档到 `my_result/`：

- `my_result/results/summary_main_limit200.csv`：W1-W3 main limit=200 的 LRU/SLRU/2Q 对比。
- `my_result/results/summary_main_limit200_3090.csv`：缩短 scan 后的 W4 main limit=200 对比。
- `my_result/results/summary_pressure_w4_limit500.csv`：W4 pressure limit=500 的策略对比。
- `my_result/results/scan_revisit_summary_pressure_w4_limit500.csv`：scan 后热点回访窗口的汇总分析。
- `my_result/results/scan_revisit_detail_pressure_w4_limit500.csv`：scan 后每条热点回访请求的明细。

## W1-W3 main 结果

W1/W2/W3 在 `LIMIT=200` 下，LRU、SLRU、2Q 的 `cached_tokens` 与 `hit_rate` 基本完全一致：

| workload | 2Q hit_rate | LRU hit_rate | SLRU hit_rate | 结论 |
| --- | ---: | ---: | ---: | --- |
| W1 | 65.70% | 65.70% | 65.70% | few-shot 前缀复用场景下，缓存压力不足以区分策略。 |
| W2 | 5.09% | 5.09% | 5.09% | 多轮对话前 200 条复用较弱，策略差异不明显。 |
| W3 | 59.30% | 59.30% | 59.30% | Zipf 热点场景下，三种策略保留了相同前缀集合。 |

这说明 W1-W3 更适合作为正确性与基线 sanity check，不适合作为证明 2Q 优势的主实验。

## W4 pressure 全局结果

`W4 pressure` 使用 hot -> scan -> hot 回访的压力模式，并在高缓存压力下运行 `LIMIT=500`。

| policy | cached_tokens | hit_rate | ttft_p50_ms | ttft_p99_ms | 结论 |
| --- | ---: | ---: | ---: | ---: | --- |
| LFU | 89,636 | 27.97% | 646.35 | 3196.96 | 最好，说明该 trace 对稳定高频热点非常友好。 |
| 2Q | 71,449 | 22.30% | 679.62 | 3196.88 | 与 SLRU 持平，略优于 LRU。 |
| SLRU | 71,449 | 22.30% | 678.77 | 3194.39 | 与 2Q 完全一致。 |
| LRU | 71,160 | 22.21% | 681.72 | 3195.80 | 略低于 2Q/SLRU。 |

2Q 相比 LRU 多命中 289 tokens，hit rate 提升约 0.09 个百分点；优势存在但很小。

## scan 后热点回访分析

只统计每个 scan 后 32 条 hot 回访请求，共 14 个 scan、438 条 hot 回访：

| policy | cached_tokens | hit_rate | hit_rate_p50 | hit_rate_p90 | ttft_p50_ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| LFU | 80,304 | 58.70% | 89.89% | 93.50% | 646.35 |
| 2Q | 62,117 | 45.40% | 1.32% | 93.50% | 681.97 |
| SLRU | 62,117 | 45.40% | 1.32% | 93.50% | 681.34 |
| LRU | 61,828 | 45.19% | 1.32% | 93.50% | 683.46 |

该分析说明：

1. LFU 明显更能保留稳定高频热点。
2. 2Q 与 SLRU 的 scan 后热点保护能力几乎完全一致。
3. 2Q 相比 LRU 有轻微提升，但不足以支撑“显著优于 LRU”的结论。

## 结论

本实验不能证明当前 2Q 实现显著优于 SGLang 现有策略。更稳妥的结论是：

1. 当前 2Q 实现可以接入真实 SGLang，并在 Qwen2.5-7B-Instruct 上稳定运行。
2. 在 W1-W3 常规场景中，2Q、LRU、SLRU 基本无差异。
3. 在 W4 pressure 扫描污染场景中，2Q 与 SLRU 持平，并略优于 LRU。
4. LFU 在稳定高频热点场景下表现最好，说明该 workload 更偏向频率型热点保护。
5. 当前 2Q 实现更接近 SLRU-like 策略，而非完整论文版 2Q，因为 A1in/Am 缺少严格容量配额。

## 后续改进方向

如果要继续增强 2Q，需要从实现而不是 trace 上改进：

1. 为 A1in、A1out、Am 设置明确容量比例。
2. 让 A1in 的大小随 KV pool 容量变化，而不是只靠 eviction priority。
3. 记录 A1out ghost hit 的统计指标，确认 ghost queue 是否真的发挥作用。
4. 设计 phase-shift workload，让热点集合随阶段变化，以暴露 LFU 的频率滞后问题。
