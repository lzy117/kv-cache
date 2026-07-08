from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from array import array
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

import torch

from sglang.srt.mem_cache.base_prefix_cache import EvictParams, InsertParams, MatchPrefixParams
from sglang.srt.mem_cache.radix_cache import RadixCache, RadixKey


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]|[^\s]", re.UNICODE)


class NoOpAllocator:
    """Minimal allocator object for RadixCache.evict in CPU simulation."""

    device = "cpu"

    def free(self, value: Any) -> None:
        return None


def stable_token_id(token: str) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    # Keep ids positive and within signed int64.
    return int.from_bytes(digest, "little") & ((1 << 63) - 1)


def tokenize_regex_hash(text: str) -> list[int]:
    return [stable_token_id(tok) for tok in TOKEN_PATTERN.findall(text)]


def make_key(token_ids: list[int]) -> RadixKey:
    return RadixKey(token_ids=array("q", token_ids), extra_key=None)


def make_value(length: int) -> torch.Tensor:
    # Values only need length and slice/clone behavior for simulation.
    return torch.arange(length, dtype=torch.int64)


def read_trace(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    rows.sort(key=lambda row: row["arrival_order"])
    return rows


def create_cache(policy: str) -> RadixCache:
    cache = RadixCache.create_simulated(mock_allocator=NoOpAllocator(), page_size=1)
    cache.eviction_policy = policy
    # Recreate after changing policy, because create_simulated initializes from params.
    from sglang.srt.mem_cache.utils import get_eviction_strategy

    cache.eviction_strategy = get_eviction_strategy(policy)
    return cache


def simulate_trace(trace_path: Path, policy: str, pool_size: int, limit: int | None = None) -> dict[str, Any]:
    cache = create_cache(policy)
    rows = read_trace(trace_path)
    if limit is not None:
        rows = rows[:limit]

    total_prompt_tokens = 0
    total_cached_tokens = 0
    total_inserted_prefix_hits = 0
    evict_calls = 0
    evicted_tokens = 0
    max_cache_tokens = 0
    start = time.perf_counter()

    for row in rows:
        token_ids = tokenize_regex_hash(row["prompt"])
        if not token_ids:
            continue
        key = make_key(token_ids)
        match = cache.match_prefix(MatchPrefixParams(key=key))
        cached_tokens = len(match.device_indices)
        insert_result = cache.insert(InsertParams(key=key, value=make_value(len(token_ids))))
        total_prompt_tokens += len(token_ids)
        total_cached_tokens += cached_tokens
        total_inserted_prefix_hits += insert_result.prefix_len

        overflow = cache.total_size() - pool_size
        if overflow > 0:
            result = cache.evict(EvictParams(num_tokens=overflow))
            evict_calls += 1
            evicted_tokens += result.num_tokens_evicted
        max_cache_tokens = max(max_cache_tokens, cache.total_size())

    elapsed = time.perf_counter() - start
    hit_rate = total_cached_tokens / total_prompt_tokens if total_prompt_tokens else 0.0
    return {
        "trace": trace_path.stem,
        "policy": policy,
        "pool_size": pool_size,
        "requests": len(rows),
        "prompt_tokens": total_prompt_tokens,
        "cached_tokens": total_cached_tokens,
        "hit_rate": hit_rate,
        "insert_prefix_hits": total_inserted_prefix_hits,
        "evict_calls": evict_calls,
        "evicted_tokens": evicted_tokens,
        "final_cache_tokens": cache.total_size(),
        "max_cache_tokens": max_cache_tokens,
        "elapsed_sec": elapsed,
    }


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "workload",
        "trace",
        "policy",
        "pool_size",
        "requests",
        "prompt_tokens",
        "cached_tokens",
        "hit_rate",
        "insert_prefix_hits",
        "evict_calls",
        "evicted_tokens",
        "final_cache_tokens",
        "max_cache_tokens",
        "elapsed_sec",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run offline RadixCache trace simulations.")
    parser.add_argument("--config", type=Path, default=ROOT / "configs" / "sim_config.json")
    parser.add_argument("--profile", choices=["smoke", "main"], default=None)
    parser.add_argument("--workload", choices=["all", "w1", "w2", "w3", "w4"], default="all")
    parser.add_argument("--policy", choices=["all", "lru", "lfu", "fifo", "mru", "filo", "priority", "slru"], default="all")
    parser.add_argument("--pool-size", type=int, action="append", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    policies = config["policies"] if args.policy == "all" else [args.policy]
    pool_sizes = args.pool_size if args.pool_size else config["pool_sizes"]

    traces = config["traces"]
    if args.profile:
        seed = config.get("seed", 20260708)
        traces = {
            key: f"traces/{key}_{args.profile}_seed{seed}.jsonl"
            for key in ["w1", "w2", "w3", "w4"]
        }
    workloads = list(traces.keys()) if args.workload == "all" else [args.workload]

    rows: list[dict[str, Any]] = []
    for workload in workloads:
        trace_path = ROOT / traces[workload]
        for policy in policies:
            for pool_size in pool_sizes:
                result = simulate_trace(trace_path, policy, pool_size, limit=args.limit)
                result["workload"] = workload
                rows.append(result)
                print(
                    f"{workload} {policy} pool={pool_size} "
                    f"hit={result['hit_rate']:.4f} "
                    f"cached={result['cached_tokens']}/{result['prompt_tokens']} "
                    f"evict_calls={result['evict_calls']}",
                    flush=True,
                )

    output = args.output or (ROOT / config["output"])
    write_csv(output, rows)
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
