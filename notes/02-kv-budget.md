# A2 KV 显存账本与模型选型

## 本阶段结论

主实验建议使用 **Qwen2.5-7B-Instruct**，调试和快速扫参使用 **Qwen2.5-1.5B**，不建议使用 Llama-2 7B 作为主实验模型。

原因很简单：Llama-2 7B 是 MHA 结构，每 token KV cache 约 512 KiB，在 24GB GPU 上可用 KV 池太小；Qwen2.5 系列使用 GQA，KV cache 明显更省，能让淘汰实验处在更合理的容量尺度上。

## KV cache 字节数公式

每 token KV cache 字节数：

```text
每 token KV 字节数 = 2 × kv_head 数 × head_dim × 层数 × 精度字节数
```

其中：

- `2`：分别对应 Key 和 Value。
- `kv_head 数`：GQA/MQA 会显著减少这个数，MHA 中通常等于 attention heads。
- `head_dim`：通常等于 `hidden_size / num_attention_heads`。
- `层数`：每层都要保存 K/V。
- `精度字节数`：fp16/bf16 通常都是 2 字节。

本阶段按 fp16/bf16 都为 2 字节估算。

## 候选模型结构参数

结构参数来自各模型的 Hugging Face `config.json`。

| 模型 | 层数 | attention heads | kv heads | hidden size | head_dim | 结构 |
|---|---:|---:|---:|---:|---:|---|
| Llama-2 7B | 32 | 32 | 32 | 4096 | 128 | MHA |
| Qwen2.5-7B-Instruct | 28 | 28 | 4 | 3584 | 128 | GQA |
| Qwen2.5-1.5B | 28 | 12 | 2 | 1536 | 128 | GQA |

参考配置：

- Qwen2.5-7B-Instruct：`https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/raw/main/config.json`
- Qwen2.5-1.5B：`https://huggingface.co/Qwen/Qwen2.5-1.5B/raw/main/config.json`
- Llama-2 7B HF 结构参考：`https://huggingface.co/NousResearch/Llama-2-7b-hf/raw/main/config.json`

## 每 token KV 占用

### Llama-2 7B

```text
2 × 32 × 128 × 32 × 2 = 524288 bytes = 512 KiB / token
```

### Qwen2.5-7B-Instruct

```text
2 × 4 × 128 × 28 × 2 = 57344 bytes = 56 KiB / token
```

### Qwen2.5-1.5B

```text
2 × 2 × 128 × 28 × 2 = 28672 bytes = 28 KiB / token
```

## 24GB GPU 上的 KV 池粗估

假设：

- GPU 显存：24GB
- `mem_fraction_static = 0.85`
- 静态预算：`24 × 0.85 = 20.4GB`
- 静态预算大致由“模型权重 + KV 池”共享

估算公式：

```text
KV 池 ≈ 24GB × 0.85 - 模型权重占用
```

权重占用这里使用粗估值：

- Llama-2 7B：约 13.5GB
- Qwen2.5-7B-Instruct：约 15.2GB
- Qwen2.5-1.5B：约 3.1GB

注意：这里的 GB 是租卡前粗估口径，不是最终实验口径。最终必须用 SGLang 启动日志中的 `max_total_num_tokens` 校准。

## 粗估容量表

| 模型 | 每 token KV | 粗估 KV 池 | 可缓存 token，十进制 GB 口径 | 可缓存 token，GiB 口径 | 结论 |
|---|---:|---:|---:|---:|---|
| Llama-2 7B | 512 KiB | 约 6.9GB | 约 1.3 万 | 约 1.4 万 | 太小，不适合作主实验 |
| Qwen2.5-7B-Instruct | 56 KiB | 约 5.2GB | 约 9.1 万 | 约 9.7 万 | 主实验模型 |
| Qwen2.5-1.5B | 28 KiB | 约 17.3GB | 约 60.3 万 | 约 64.8 万 | 调试和快速扫参 |

## 为什么否决 Llama-2 7B

Llama-2 7B 的问题不是模型不能跑，而是 KV cache 太贵。

它的每 token KV 是 512 KiB，是 Qwen2.5-7B-Instruct 的 9 倍多。这样在 24GB 卡上 KV 池只有约 1.4 万 token。对于本实验来说，这会带来两个问题：

1. trace 工作集稍微大一点就会进入极端淘汰状态；
2. 缓存池过小，策略差异可能更多反映“池太小”而不是策略本身。

所以 Llama-2 7B 可以作为账本反例，不适合作为主实验模型。

## 为什么选择 Qwen2.5-7B-Instruct 做主实验

Qwen2.5-7B-Instruct 使用 GQA，只有 4 个 KV heads，每 token KV 约 56 KiB。

在 24GB 卡上，它大约能提供 9 万 token 级别的 KV 池。这对本实验更合适：

- 池足够大，可以构造 2-5 倍池大小的 trace 工作集；
- 仍然会发生真实淘汰；
- 7B 级模型更接近实际应用，不像 1.5B 那么偏调试；
- Qwen 系列在国内下载和部署相对方便。

因此主实验使用 Qwen2.5-7B-Instruct。

## 为什么保留 Qwen2.5-1.5B

Qwen2.5-1.5B 的每 token KV 约 28 KiB，权重也小，24GB 卡上粗估可缓存 60 万 token 以上。

它适合：

- 快速验证 SGLang 服务能启动；
- 调试 replay/collect 脚本；
- 扫并发和压力参数；
- 在低成本下跑小矩阵，检查趋势是否合理。

但它不适合作为唯一主实验模型，因为它的权重小、KV 池大，缓存压力尺度和 7B 主实验差异较大。

## 对后续 trace 设计的影响

后续 A3/A4 设计 trace 时，应该优先围绕 Qwen2.5-7B 的真实池大小设计。

租卡前粗估：

```text
Qwen2.5-7B-Instruct KV 池 ≈ 9 万 token
```

那么可以先设计两档压力：

- 中压：工作集约 2 倍池大小，即约 18 万 token；
- 高压：工作集约 4-5 倍池大小，即约 36-45 万 token。

等 GPU 阶段拿到真实 `max_total_num_tokens` 后，再按真实池大小重算 trace 或重采样。

## 后续必须校准的数字

A2 的数字是理论账本，不是最终实验数据。

GPU 冒烟阶段必须记录：

- SGLang 启动日志里的 `max_total_num_tokens`；
- 实际使用的 `mem_fraction_static`；
- 模型加载后的可用 KV token 数；
- 是否因为 backend、dtype、chunked prefill、其他运行参数影响池大小。

最终 README 和简历里不要写 A2 粗估值，应该写真机日志校准后的数字。

