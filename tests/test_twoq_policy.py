from __future__ import annotations

import sys
from array import array
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from sglang.srt.mem_cache.base_prefix_cache import EvictParams, InsertParams, MatchPrefixParams
from sglang.srt.mem_cache.evict_policy import TwoQStrategy
from sglang.srt.mem_cache.radix_cache import RadixCache, RadixKey
from sglang.srt.mem_cache.utils import get_eviction_strategy


class NoOpAllocator:
    device = "cpu"

    def free(self, value):
        return None


def make_cache() -> RadixCache:
    cache = RadixCache.create_simulated(mock_allocator=NoOpAllocator(), page_size=1)
    cache.eviction_policy = "2q"
    cache.eviction_strategy = get_eviction_strategy("2q")
    return cache


def key(tokens: list[int]) -> RadixKey:
    return RadixKey(token_ids=array("q", tokens), extra_key=None)


def value(tokens: list[int]) -> torch.Tensor:
    return torch.tensor(tokens, dtype=torch.int64)


def only_child(cache: RadixCache):
    return next(iter(cache.root_node.children.values()))


def test_a1in_eviction_records_ghost_history():
    cache = make_cache()
    strategy: TwoQStrategy = cache.eviction_strategy

    cache.insert(InsertParams(key=key([1, 2, 3]), value=value([1, 2, 3])))
    node = only_child(cache)
    assert strategy.node_segment[node.id] == TwoQStrategy.A1IN

    cache.evict(EvictParams(num_tokens=3))

    assert tuple([1, 2, 3]) in strategy.a1out
    assert node.id not in strategy.node_segment


def test_ghost_hit_promotes_reinserted_node_to_am():
    cache = make_cache()
    strategy: TwoQStrategy = cache.eviction_strategy

    cache.insert(InsertParams(key=key([4, 5, 6]), value=value([4, 5, 6])))
    cache.evict(EvictParams(num_tokens=3))
    assert tuple([4, 5, 6]) in strategy.a1out

    cache.insert(InsertParams(key=key([4, 5, 6]), value=value([4, 5, 6])))
    node = only_child(cache)

    assert tuple([4, 5, 6]) not in strategy.a1out
    assert strategy.node_segment[node.id] == TwoQStrategy.AM


def test_resident_hit_promotes_a1in_node_to_am():
    cache = make_cache()
    strategy: TwoQStrategy = cache.eviction_strategy

    cache.insert(InsertParams(key=key([31, 32, 33]), value=value([31, 32, 33])))
    node = only_child(cache)
    assert strategy.node_segment[node.id] == TwoQStrategy.A1IN

    match = cache.match_prefix(MatchPrefixParams(key=key([31, 32, 33])))

    assert len(match.device_indices) == 3
    assert strategy.node_segment[node.id] == TwoQStrategy.AM


def test_split_preserves_twoq_segment_state():
    cache = make_cache()
    strategy: TwoQStrategy = cache.eviction_strategy

    cache.insert(InsertParams(key=key([7, 8, 9, 10]), value=value([7, 8, 9, 10])))
    original = only_child(cache)
    assert strategy.node_segment[original.id] == TwoQStrategy.A1IN

    cache.match_prefix(MatchPrefixParams(key=key([7, 8])))
    parent = only_child(cache)
    child = next(iter(parent.children.values()))

    assert parent.key.raw_token_ids().tolist() == [7, 8]
    assert child.key.raw_token_ids().tolist() == [9, 10]
    assert strategy.node_segment[parent.id] == TwoQStrategy.AM
    assert strategy.node_segment[child.id] == TwoQStrategy.AM


def test_twoq_prefers_evicting_scan_leaf_before_am_leaf():
    cache = make_cache()
    strategy: TwoQStrategy = cache.eviction_strategy

    hot = [11, 12, 13]
    scan = [21, 22, 23, 24]

    cache.insert(InsertParams(key=key(hot), value=value(hot)))
    cache.evict(EvictParams(num_tokens=len(hot)))
    cache.insert(InsertParams(key=key(hot), value=value(hot)))
    hot_node = only_child(cache)
    assert strategy.node_segment[hot_node.id] == TwoQStrategy.AM

    cache.insert(InsertParams(key=key(scan), value=value(scan)))
    cache.evict(EvictParams(num_tokens=len(scan)))

    match = cache.match_prefix(MatchPrefixParams(key=key(hot)))
    assert len(match.device_indices) == len(hot)
    assert tuple(scan) in strategy.a1out
