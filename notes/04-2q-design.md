# 完整 2Q 策略设计

## 设计目标

2Q 的目标是区分两类内容：

1. 只出现一次的扫描流量：应该被快速淘汰，不能污染主缓存。
2. 短时间内再次出现的真实热点：应该晋升到主缓存，获得更长保护。

在本项目中，2Q 用于 RadixCache 的可淘汰叶子集合。它不改变 RadixCache “只能淘汰叶子” 的基本约束，而是在叶子层维护额外状态。

## 队列结构

### A1in：试用队列

新插入的节点默认进入 A1in。

特点：

- 按 FIFO 顺序淘汰；
- 只给新内容一次试用机会；
- 适合承接扫描流量；
- 节点仍然占 KV cache。

### A1out：幽灵队列

当 A1in 中的节点被淘汰时，它的 key 指纹进入 A1out。

特点：

- 只保存 key 指纹和少量元数据；
- 不保存 KV cache，不占 KV 池；
- 用来判断一个被淘汰过的 key 是否又回来了；
- 有容量上限，超过后丢弃最老 ghost。

### Am：主缓存区

如果一个请求命中 A1out，说明它不是一次性扫描流量，而是短期内再次出现的内容。

这种节点插入后进入 Am。除此之外，在本实验的 KV cache 场景里，A1in 中的 resident node 被再次 `match_prefix` 命中，也说明它已经产生真实复用，因此同样晋升到 Am。

特点：

- 按 LRU 管理；
- 代表通过二次访问验证的热点；
- 淘汰优先级低于 A1in。

## 节点状态

每个活跃节点可以处于：

- `a1in`
- `am`
- 未注册状态

A1out 是 ghost history，不对应活跃节点。

节点状态以 `node.id -> segment` 维护。队列中保存 `node.id`，需要取节点时再通过 `node.id -> node` 解析。

## key 指纹

A1out 需要记录被淘汰节点的历史。RadixCache 中节点可能因为 split 发生变化，所以不能只使用 Python 对象身份。

本实现使用节点从 root 到当前节点的完整 token 路径作为 key 指纹：

```text
fingerprint = tuple(path_token_ids)
```

这样同一个完整前缀再次出现时，可以命中 ghost history。

注意：这是 CPU 模拟阶段的实现。后续移植到上游时，可以考虑使用 RadixCache 已有的 hash/page hash 机制减少内存开销。

## 事件钩子

为了实现完整 2Q，需要给 `EvictionStrategy` 增加可选钩子：

```python
on_insert(node)
on_hit(node)
on_evict(node)
on_split(parent_node, child_node)
```

这些钩子必须向后兼容：已有 LRU/LFU/FIFO/SLRU 不实现也不影响行为。

## 事件语义

### on_insert(node)

当新节点插入 RadixCache 后调用。

规则：

- 如果节点 fingerprint 在 A1out 中，移除 ghost，并把节点放入 Am；
- 否则放入 A1in。

### on_hit(node)

当 match 或 insert 过程中访问已有节点时调用。

规则：

- 如果节点在 A1in 中，晋升到 Am；
- 如果节点在 Am 中，刷新 Am 的 LRU 顺序；
- 如果节点 fingerprint 在 A1out 中，后续完整插入时应进入 Am。

### on_evict(node)

当节点被 RadixCache 淘汰前调用。

规则：

- 如果节点来自 A1in，将 fingerprint 写入 A1out；
- 如果节点来自 Am，直接移除状态；
- 清理 node id 到状态、node id 到 node 的映射。

### on_split(parent_node, child_node)

当一个节点被 split 成“新父节点 + 原 child 剩余段”时调用。

规则：

- 新父节点代表共享前缀，它继承原 child 的段状态；
- 原 child 保留同一段状态；
- 两个节点都注册到策略中；
- 这种做法偏保守，避免 split 导致热点状态丢失。

## 淘汰优先级

`get_priority(node)` 返回可比较元组。

优先级从小到大：

1. A1in 中最早进入的节点；
2. 未注册节点；
3. Am 中最久未访问的节点。

建议元组：

```python
(segment_rank, queue_time, node.last_access_time)
```

其中：

- A1in：`segment_rank = 0`，按 FIFO 时间；
- unknown：`segment_rank = 1`；
- Am：`segment_rank = 2`，按 LRU 时间。

这样扫描流量优先从 A1in 被清掉，Am 热点最后淘汰。

实现上，`queue_time` 不是每次从 `OrderedDict` 中线性查找位置，而是在节点进入 A1in/Am 或 Am 命中刷新时写入一个单调递增的队列时间戳。这样 `get_priority(node)` 是 O(1)，不会在大池模拟时拖慢排序。

## 配额

完整 2Q 通常需要控制 A1in 和 A1out 的大小。

本阶段采用以下简化：

- A1in 不单独强制节点数上限，由全局 KV 池压力和淘汰优先级间接控制；
- A1out ghost 上限可配置，默认 2048，超过后丢弃最老 ghost。

原因：

- RadixCache 当前淘汰以 token 为单位，但策略接口本身不知道总池大小；
- 在 A5 CPU 模拟阶段，先实现完整状态机和 ghost history；
- 后续如果要更贴近论文版 2Q，可以在策略构造时传入 token 配额。

## 与 SLRU 的区别

SLRU 使用 `hit_count` 阈值把节点分成试用段和保护段。它没有幽灵队列。

2Q 的关键区别是 A1out：

- 被淘汰过的内容会留下 ghost；
- 只有短时间内再次出现的内容才会晋升 Am；
- 一次性扫描流量不会因为刚插入就污染主缓存。

因此 W4 扫描污染应该是 2Q 最有机会超过 LRU/SLRU 的场景。

## 当前阶段限制

1. A1in/A1out 配额先按节点数控制，不按 token 精确控制。
2. 当前实现服务于 CPU 模拟器，后续导出到 fork 时需要整理成上游 patch。
3. 并发、`lock_ref`、真实 tokenizer 影响要留到 GPU 阶段校准。
