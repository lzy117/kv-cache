from __future__ import annotations

from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import TYPE_CHECKING, Optional, Tuple, Union

if TYPE_CHECKING:
    from sglang.srt.mem_cache.radix_cache import TreeNode


class EvictionStrategy(ABC):
    @abstractmethod
    def get_priority(self, node: TreeNode) -> Union[float, Tuple]:
        pass

    def on_insert(self, node: TreeNode):
        pass

    def on_hit(self, node: TreeNode):
        pass

    def on_evict(self, node: TreeNode):
        pass

    def on_split(self, parent_node: TreeNode, child_node: TreeNode):
        pass


class LRUStrategy(EvictionStrategy):
    def get_priority(self, node: TreeNode) -> float:
        return node.last_access_time


class LFUStrategy(EvictionStrategy):
    def get_priority(self, node: TreeNode) -> Tuple[int, float]:
        return (node.hit_count, node.last_access_time)


class FIFOStrategy(EvictionStrategy):
    def get_priority(self, node: TreeNode) -> float:
        return node.creation_time


class MRUStrategy(EvictionStrategy):
    def get_priority(self, node: TreeNode) -> float:
        return -node.last_access_time


class FILOStrategy(EvictionStrategy):
    def get_priority(self, node: TreeNode) -> float:
        return -node.creation_time


class PriorityStrategy(EvictionStrategy):
    """Priority-aware eviction: lower priority values evicted first, then LRU within same priority."""

    def get_priority(self, node: TreeNode) -> Tuple[int, float]:
        # Return (priority, last_access_time) so lower priority nodes are evicted first
        return (node.priority, node.last_access_time)


class SLRUStrategy(EvictionStrategy):
    def __init__(self, protected_threshold: int = 2):
        self.protected_threshold = protected_threshold

    def get_priority(self, node: TreeNode) -> Tuple[int, float]:
        # Priority Logic:
        # Smaller value = Evicted earlier.
        #
        # Segment 0 (Probationary): hit_count < threshold
        # Segment 1 (Protected): hit_count >= threshold
        #
        # Tuple comparison: (segment, last_access_time)
        # Nodes in segment 0 will always be evicted before segment 1.
        # Inside the same segment, older nodes (smaller time) are evicted first.

        is_protected = 1 if node.hit_count >= self.protected_threshold else 0
        return (is_protected, node.last_access_time)


class TwoQStrategy(EvictionStrategy):
    """Stateful 2Q eviction with A1in, A1out, and Am.

    This implementation is designed for RadixCache leaf eviction. It uses node
    ids for active queues and full-path token fingerprints for the ghost queue.
    """

    A1IN = "a1in"
    AM = "am"

    def __init__(self, a1out_max_entries: int = 2048):
        self.a1out_max_entries = a1out_max_entries
        self.queue_clock = 0
        self.node_segment: dict[int, str] = {}
        self.node_order: dict[int, int] = {}
        self.node_ref: dict[int, TreeNode] = {}
        self.a1in: OrderedDict[int, None] = OrderedDict()
        self.am: OrderedDict[int, None] = OrderedDict()
        self.a1out: OrderedDict[Tuple[int, ...], None] = OrderedDict()

    def get_priority(self, node: TreeNode) -> Tuple[int, float, float]:
        node_id = node.id
        segment = self.node_segment.get(node_id)
        if segment == self.A1IN:
            queue_time = self.node_order.get(node_id, 0)
            return (0, queue_time, node.last_access_time)
        if segment == self.AM:
            queue_time = self.node_order.get(node_id, 0)
            return (2, queue_time, node.last_access_time)
        return (1, node.creation_time, node.last_access_time)

    def on_insert(self, node: TreeNode):
        fingerprint = self._fingerprint(node)
        if fingerprint in self.a1out:
            self.a1out.pop(fingerprint, None)
            self._set_segment(node, self.AM)
        else:
            self._set_segment(node, self.A1IN)

    def on_hit(self, node: TreeNode):
        node_id = node.id
        segment = self.node_segment.get(node_id)
        if segment == self.AM:
            self.am.pop(node_id, None)
            self.am[node_id] = None
        elif segment == self.A1IN:
            # A resident hit is a direct reuse signal for KV prefixes, so it
            # graduates from the one-hit FIFO queue into the protected LRU queue.
            self._set_segment(node, self.AM)

    def on_evict(self, node: TreeNode):
        node_id = node.id
        segment = self.node_segment.pop(node_id, None)
        self.node_order.pop(node_id, None)
        self.node_ref.pop(node_id, None)
        self.a1in.pop(node_id, None)
        self.am.pop(node_id, None)
        if segment == self.A1IN:
            self.a1out[self._fingerprint(node)] = None
            self._trim_a1out()

    def on_split(self, parent_node: TreeNode, child_node: TreeNode):
        child_segment = self.node_segment.get(child_node.id)
        if child_segment is None:
            return
        self._set_segment(parent_node, child_segment)
        self._set_segment(child_node, child_segment)

    def _set_segment(self, node: TreeNode, segment: str):
        node_id = node.id
        old_segment = self.node_segment.get(node_id)
        if old_segment == self.A1IN:
            self.a1in.pop(node_id, None)
        elif old_segment == self.AM:
            self.am.pop(node_id, None)

        self.node_segment[node_id] = segment
        self.node_order[node_id] = self._next_order()
        self.node_ref[node_id] = node
        if segment == self.A1IN:
            self.a1in[node_id] = None
        elif segment == self.AM:
            self.am[node_id] = None

    def _trim_a1out(self):
        while len(self.a1out) > self.a1out_max_entries:
            self.a1out.popitem(last=False)

    def _next_order(self) -> int:
        self.queue_clock += 1
        return self.queue_clock

    @classmethod
    def _fingerprint(cls, node: TreeNode) -> Tuple[int, ...]:
        parts = []
        cur: Optional[TreeNode] = node
        while cur is not None and cur.parent is not None:
            if cur.key is not None:
                parts.append(tuple(cur.key.raw_token_ids()))
            cur = cur.parent
        tokens = []
        for part in reversed(parts):
            tokens.extend(part)
        return tuple(tokens)
