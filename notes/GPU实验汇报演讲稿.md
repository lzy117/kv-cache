# GPU 实验汇报演讲稿

大家好，我这次汇报的是 SGLang KV Cache 淘汰策略实验。这个实验不是只在模拟器里比较算法，而是把 2Q 淘汰策略接入真实的 SGLang 服务，再用 Qwen2.5-7B-Instruct 在 RTX 3090 上验证它和 LRU、SLRU、LFU 的差异。

先说问题背景。大模型推理时，prompt 的前缀会被计算成 KV cache。如果后续请求复用了相同前缀，服务就可以命中已有 KV，减少 prefill 计算，从而降低 TTFT。SGLang 使用 RadixCache，也就是前缀树，来管理这些 KV 节点。真正的问题发生在显存预算不足的时候：哪些 KV 节点应该留下，哪些应该被淘汰。这就是 eviction policy 的作用。

2Q 的核心思想是把缓存内容分成“试用”和“保护”两个阶段。新插入的节点先进入 A1in，代表它只是可能有用；如果它再次命中，就进入 Am，表示它已经证明有复用价值；如果 A1in 里的节点被淘汰，会在 A1out 里留下 ghost 记录。理论预期是：一次性长文档 scan 不应该把已经复用过的热点前缀挤出去，所以 2Q 应该在扫描污染场景下更有机会超过 LRU。

工程实现上，我主要改了三层。第一层是策略本身，在 `vendor/sglang/srt/mem_cache/evict_policy.py` 里新增 `TwoQStrategy`。其中 `get_priority` 决定淘汰优先级：A1in 返回最低优先级，所以最先被淘汰；Am 返回最高优先级，所以被保护；未知节点位于中间。`on_insert` 根据节点 fingerprint 是否出现在 A1out 中，决定新节点进入 A1in 还是直接进入 Am。`on_hit` 会把 A1in 节点提升到 Am，`on_evict` 会把被淘汰的 A1in 节点写入 A1out。

第二层是把这个策略接入 RadixCache 的生命周期。只写一个策略类是不够的，因为 RadixCache 会发生节点插入、前缀命中、节点拆分和 leaf 删除。因此我在 `radix_cache.py` 里增加了 hook：`_insert_helper` 调用 `on_insert`，`_match_prefix_helper` 和 `_inc_hit_count` 调用 `on_hit`，`_split_node` 调用 `on_split`，`_delete_leaf` 调用 `on_evict`。这样 2Q 的队列状态才会跟随真实前缀树变化，而不是只停留在离线模拟。

第三层是实验链路。我修改了策略注册和 CLI choice，让服务可以通过 `--radix-eviction-policy 2q` 启动；然后用 `traces/generate_traces.py` 构造 W1 到 W4 trace；用 `bench/replay.py` 调 SGLang `/generate` 接口，并从返回的 `meta_info` 中提取 `prompt_tokens`、`cached_tokens`、`ttft_ms`；最后用 `bench/analyze_scan_revisits.py` 从 raw JSONL 中拆出 scan 请求之后的热点回访请求。

实验设计上，W1 是 few-shot 公共前缀复用，W2 是多轮对话，W3 是 Zipf 热点租户，这三组主要用来验证链路。结果显示 LRU、SLRU、2Q 的 hit rate 基本一致，说明这些 workload 没有制造足够强的淘汰压力。真正关键的是 W4 pressure，我把它设计成 hot -> scan -> hot：先预热热点租户，再插入一次性长文档 scan，然后立刻访问热点请求。这样可以直接观察 scan 之后热点 KV 是否还留在缓存中。

从全局 W4 pressure 看，2Q 的 hit rate 是 22.30%，LRU 是 22.21%，SLRU 也是 22.30%，LFU 是 27.97%。如果只看全局平均，2Q 只比 LRU 略高，和 SLRU 持平。为了更准确，我进一步只看 scan 后 32 条热点回访请求：2Q 和 SLRU 的 hit rate 都是 45.40%，LRU 是 45.19%，LFU 是 58.70%。这个 raw 级别分析说明，当前 2Q 确实有一点热点保护效果，但没有和 SLRU 拉开差距；LFU 反而更强，是因为这个 workload 中热点租户非常稳定，累计频率信号很有效。

最后结论是：本实验已经完成了 2Q 在真实 SGLang 服务中的接入、运行和分析；但当前实现不能证明 2Q 全面优于已有策略。更准确的说法是，2Q 在扫描污染压力下略优于 LRU，与 SLRU 几乎一致，而 LFU 在稳定热点场景下表现最好。造成 2Q 和 SLRU 接近的原因，是当前实现虽然有 A1in、A1out、Am 三类状态，但没有严格控制 A1in 和 Am 的容量比例，所以实际行为更像 SLRU-like。

如果继续优化，下一步应该实现严格的 A1in、A1out、Am 队列容量预算，记录 ghost hit，并设计热点阶段会变化的 workload。这样才能更清楚地区分 2Q、SLRU 和 LFU 的适用边界。
