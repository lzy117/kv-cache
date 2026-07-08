# RadixCache Internals Notes

Upstream basis:

- SGLang tag: `v0.5.14`
- Source commit: `49e384ce9d304648e9959666ecb8ce8cd98d0deb`
- Local source path: `vendor/sglang/srt/mem_cache/`

## TreeNode State

`TreeNode` is defined in `radix_cache.py`.

Important fields:

- `children`: radix children keyed by the first token/page key of a child edge.
- `parent`: parent node pointer.
- `key`: the token span represented by this edge.
- `value`: KV pool indices for this edge; `None` means the node has been evicted.
- `lock_ref`: request/storage protection count. Nodes with positive `lock_ref` are not evictable.
- `last_access_time`: updated during prefix match and insert traversal.
- `creation_time`: set once at node creation; used by FIFO/FILO.
- `hit_count`: incremented during insert traversal or new-node creation, except chunked self-reference cases.
- `hash_value`: lazily computed page hashes for KV cache events.
- `priority`: request priority propagated along insert paths; used by priority eviction.

The root node is special:

- key and value are empty;
- `lock_ref = 1`;
- priority is initialized to a very small value;
- it is not considered evictable.

## Prefix Match

Public entry: `RadixCache.match_prefix`.

Flow:

1. Convert the key to bigram view if EAGLE mode is enabled.
2. Return the empty result if cache is disabled or the key is empty.
3. Page-align the key by `page_size`.
4. Call `_match_prefix_helper(root, key)`.
5. Concatenate matched node values into `device_indices`.

`_match_prefix_helper` updates `last_access_time` on the root and every child it traverses. If a lookup ends inside an existing child edge, it calls `_split_node` so the matched prefix becomes an explicit node boundary. This is important for later eviction and future prefix matches: a shared prefix can become an internal node.

## Insert

Public entry: `RadixCache.insert`.

Key details:

- `priority` defaults to 0 if missing.
- Traversed nodes update `last_access_time`.
- `priority` is propagated with `max(existing, new_priority)`.
- Existing matched nodes get `hit_count += 1`, unless the request is chunked.
- If insertion splits an existing edge, the new parent node inherits the child priority, hit count, lock ref, and the prefix slice of value/hash state.
- If remaining key tokens exist after traversal, a new leaf is created and `evictable_size_ += len(key)`.

The accounting unit is token count, not node count. This matters for policy comparison: evicting one long leaf can free far more capacity than evicting several small leaves, so hit-rate and eviction behavior should be interpreted in token space.

## Eviction

Public entry: `RadixCache.evict(EvictParams(num_tokens=N))`.

Flow:

1. Copy the current `evictable_leaves` set.
2. Build a heap of `(eviction_strategy.get_priority(node), node)`.
3. Pop the lowest-priority leaf.
4. Free its KV indices with `token_to_kv_pool_allocator.free(x.value)`.
5. Add `len(x.value)` to `num_evicted`.
6. Delete the leaf from its parent.
7. If the parent now has no children and `lock_ref == 0`, push that parent into the heap.
8. Emit a remove event if events are enabled.
9. Stop once at least the requested token count has been evicted or the heap is empty.

Core constraint: RadixCache evicts only leaves. Internal nodes are protected while they still have non-evicted descendants. A hot shared prefix can therefore survive because it is structurally internal, even if the eviction strategy would otherwise rate it as old or low-frequency.

## Leaf Status

`_update_leaf_status(node)` maintains `evictable_leaves`:

- If `node.evicted` or `node.lock_ref > 0`, remove it from `evictable_leaves`.
- If any child is not evicted, remove the node from `evictable_leaves`.
- Otherwise, the node is a live unlocked leaf and can be evicted.

This is why all policies are effectively "policy X over evictable leaves", not policy X over the whole radix tree.

## lock_ref Accounting

`inc_lock_ref(node)` walks from the node to the root:

- When a node changes from `lock_ref == 0` to protected, `evictable_size_ -= len(node.key)` and `protected_size_ += len(node.key)`.
- Then it increments `lock_ref`.
- Leaf status is refreshed at every step.

`dec_lock_ref(node)` does the inverse:

- When a node changes from `lock_ref == 1` to unlocked, `evictable_size_ += len(node.key)` and `protected_size_ -= len(node.key)`.
- Then it decrements `lock_ref`.
- Leaf status is refreshed at every step.

This can make real-server behavior differ from a naive offline replay: in-flight requests temporarily shrink the effective evictable pool.

## Eviction Strategies

All built-in strategies implement `EvictionStrategy.get_priority(node)`.
The heap pops the smallest priority first.

| Strategy | Priority | Meaning |
|---|---|---|
| LRU | `last_access_time` | Oldest accessed leaf first |
| LFU | `(hit_count, last_access_time)` | Lowest hit count first, LRU tie-break |
| FIFO | `creation_time` | Oldest created leaf first |
| MRU | `-last_access_time` | Most recently used leaf first |
| FILO | `-creation_time` | Newest created leaf first |
| Priority | `(priority, last_access_time)` | Lowest request priority first, LRU tie-break |
| SLRU | `(is_protected, last_access_time)` | `hit_count >= 2` leaves are protected from probationary leaves |

Important nuance: the heap is built at eviction time from current evictable leaves. It does not maintain a continuously updated heap across all accesses. That is fine for these stateless priority functions, but it is also the reason the interface is narrow.

## CLI / Injection Path

The cache policy flows as:

`server_args.radix_eviction_policy` -> `kv_cache_builder.py` -> `CacheInitParams.eviction_policy` -> `RadixCache.__init__` -> `get_eviction_strategy(policy)`.

Observed in `v0.5.14`:

- `evict_policy.py` defines seven strategy classes.
- `utils.py` registers seven strategy factories: `lru`, `lfu`, `fifo`, `mru`, `filo`, `priority`, `slru`.
- `server_args.py` default CLI choices list only `lru`, `lfu`, `slru`, `priority`.

So the code layer contains seven policies, but not all are necessarily exposed by the default CLI choices in this tag. For GPU experiments, FIFO/MRU/FILO may need a small CLI registration patch or a config path that calls `add_radix_eviction_policy_choices`.

## Why get_priority Cannot Express Full 2Q

`get_priority(node)` is a stateless scoring hook. It sees one node and returns a comparable value. Full 2Q needs state and events:

- A1in: a FIFO probationary queue with a token budget.
- A1out: a ghost queue that remembers recently evicted keys without holding KV.
- Am: a main LRU queue for entries promoted after a second arrival.

The key missing operations are:

- on hit: decide whether a key is promoted from A1out/ A1in into Am;
- on insert: place a new key into A1in or Am depending on ghost history;
- on eviction: record A1in victims into A1out;
- on split: preserve or derive queue state for newly exposed prefix nodes.

These decisions cannot be represented by a pure per-node priority function. This is the engineering basis for adding eviction event hooks.

## Workload Design Implication

Because only leaves are evictable, policy differences should depend strongly on tree shape.

Prediction:

- Shallow and wide trees with shared heads, such as few-shot prompts that reuse common subject prefixes, should show small policy differences. Shared prefixes become internal nodes and are structurally protected.
- Deep and narrow trees, such as independent multi-turn conversations, should expose more leaf-level choice. Recency-aware policies should matter more.
- Frequency-skewed tenant/system-prompt workloads should favor LFU-like or 2Q-like policies when hot tenants repeatedly reappear.
- Scan-polluted workloads should be the strongest case for 2Q because one-time long leaves can be filtered through A1in/A1out instead of displacing Am.

This implication should guide W1-W4 trace design and later be checked with tree-shape statistics.

