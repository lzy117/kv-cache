# GPU 实验汇报演讲稿

大家好，我这次汇报的是 SGLang KV Cache 淘汰策略实验。实验目标是把 2Q 缓存淘汰策略接入真实的 SGLang 服务，并和 LRU、SLRU 等策略比较，看它是否能在扫描污染场景下更好地保护热点前缀。

首先介绍一下背景。大模型推理中，prompt 的前缀会被计算成 KV cache。如果后续请求复用了相同前缀，就可以直接命中缓存，减少 prefill 计算，降低 TTFT。SGLang 使用 RadixCache 来组织这些前缀节点。当显存有限、KV cache 被挤满时，就必须决定哪些节点被淘汰，这就是本实验关注的问题。

2Q 的核心思想是把缓存分成试用和保护两个阶段。新插入节点先进入 A1in，说明它还只是“可能有用”的内容；如果后续再次命中，它会进入 Am，表示它已经被证明有复用价值；而被淘汰的一次性节点会在 A1out 中留下 ghost 记录。理论上，这种机制能减少一次性长文档 scan 对热点前缀的污染。

工程上，我做了几部分工作。第一，阅读 SGLang 的 RadixCache 和 eviction policy 代码，新增 TwoQStrategy，并在插入、命中、拆分和淘汰路径上维护 2Q 状态。第二，修改 CLI 注册逻辑，让真实服务可以通过 `--radix-eviction-policy 2q` 启动。第三，构造 W1 到 W4 四类 workload，并写 replay 和 collect 脚本，采集 `cached_tokens`、hit rate、TTFT 等指标。最后，我在 RTX 3090 上部署 Qwen2.5-7B-Instruct，完成真实 GPU 实验。

实验结果分两部分。W1 到 W3 主要用于验证链路和常规场景，分别覆盖 few-shot 前缀复用、多轮对话和 Zipf 热点租户。结果显示 LRU、SLRU、2Q 的 hit rate 基本完全一致，说明这些场景没有制造足够强的 eviction 压力，因此不适合作为证明 2Q 优势的主证据。

真正关键的是 W4 pressure。我重新设计了 hot -> scan -> hot 的压力 trace：先预热一批热点租户，再插入一次性长文档 scan，然后立刻回访热点请求。这个设计可以观察 scan 之后热点 KV 是否还留在缓存里。全局结果显示，2Q 和 SLRU 完全持平，hit rate 约 22.30%，略高于 LRU 的 22.21%；但 LFU 达到 27.97%，表现最好。

进一步只看 scan 后 32 条热点回访请求，结论更清楚：2Q 和 SLRU 的回访 hit rate 都是 45.40%，略高于 LRU 的 45.19%；LFU 则达到 58.70%。这说明当前 workload 中稳定高频热点非常明显，LFU 因为累计频率，所以更容易保留热点。2Q 起到了类似 SLRU 的热点保护效果，但没有显著超过 SLRU。

因此，本实验的最终结论不是“2Q 全面最优”，而是：当前 2Q 实现已经能真实接入 SGLang，并在扫描污染压力下略优于 LRU、与 SLRU 持平；但由于当前实现没有严格的 A1in、A1out、Am 容量配额，它更接近 SLRU-like 策略。后续如果继续优化，需要实现严格队列容量、记录 ghost hit，并设计热点阶段变化的 workload 来进一步区分 2Q 和 LFU。
