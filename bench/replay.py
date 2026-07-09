from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if limit is not None and len(rows) >= limit:
                break
    rows.sort(key=lambda row: row.get("arrival_order", len(rows)))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build_payload(row: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    sampling_params = {
        "max_new_tokens": int(row.get("max_tokens", args.max_new_tokens)),
        "temperature": args.temperature,
    }
    if args.top_p is not None:
        sampling_params["top_p"] = args.top_p
    if args.stop:
        sampling_params["stop"] = args.stop

    payload: dict[str, Any] = {
        "text": row["prompt"],
        "sampling_params": sampling_params,
    }
    if args.model:
        payload["model"] = args.model
    return payload


def first_number(mapping: dict[str, Any], names: tuple[str, ...], default: float = 0.0) -> float:
    for name in names:
        value = mapping.get(name)
        if isinstance(value, (int, float)):
            return float(value)
    return default


def extract_metrics(
    response_json: dict[str, Any], fallback_prompt_tokens: int, fallback_latency_ms: float
) -> dict[str, Any]:
    meta = response_json.get("meta_info") or response_json.get("meta") or {}
    usage = response_json.get("usage") or {}
    if not isinstance(meta, dict):
        meta = {}
    if not isinstance(usage, dict):
        usage = {}

    prompt_tokens = first_number(
        meta,
        ("prompt_tokens", "input_tokens", "num_prompt_tokens"),
        first_number(usage, ("prompt_tokens",), float(fallback_prompt_tokens)),
    )
    cached_tokens = first_number(
        meta,
        ("cached_tokens", "cache_hit_tokens", "num_cached_tokens"),
        first_number(usage, ("cached_tokens",), 0.0),
    )
    completion_tokens = first_number(
        meta,
        ("completion_tokens", "output_tokens", "num_output_tokens"),
        first_number(usage, ("completion_tokens",), 0.0),
    )
    ttft_ms = first_number(
        meta,
        (
            "ttft_ms",
            "time_to_first_token_ms",
            "first_token_latency_ms",
        ),
        first_number(
            meta,
            ("ttft", "time_to_first_token", "first_token_latency"),
            fallback_latency_ms / 1000.0,
        )
        * 1000.0,
    )

    return {
        "prompt_tokens": int(prompt_tokens),
        "cached_tokens": int(cached_tokens),
        "completion_tokens": int(completion_tokens),
        "ttft_ms": float(ttft_ms),
        "server_meta": meta,
    }


def post_json(url: str, payload: dict[str, Any], timeout_sec: float) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        body = response.read().decode("utf-8")
        parsed = json.loads(body) if body else {}
        if not isinstance(parsed, dict):
            parsed = {"response": parsed}
        return response.status, parsed


def flush_cache(args: argparse.Namespace) -> None:
    if not args.flush_before:
        return
    url = args.base_url.rstrip("/") + args.flush_endpoint
    post_json(url, {}, args.timeout_sec)


def post_one(
    row: dict[str, Any],
    sequence: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    url = args.base_url.rstrip("/") + args.endpoint
    payload = build_payload(row, args)
    started = time.perf_counter()
    started_wall = time.time()
    error = ""
    status_code = 0
    response_json: dict[str, Any] = {}
    for attempt in range(args.max_retries + 1):
        try:
            status_code, response_json = post_json(url, payload, args.timeout_sec)
            break
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            error = repr(exc)
        except Exception as exc:  # noqa: BLE001 - raw replay should keep running.
            error = repr(exc)
        if attempt < args.max_retries:
            time.sleep(args.retry_backoff_sec * (attempt + 1))

    ended = time.perf_counter()
    latency_ms = (ended - started) * 1000.0
    approx_prompt_tokens = int(row.get("approx_prompt_tokens", 0))
    metrics = extract_metrics(response_json, approx_prompt_tokens, latency_ms)
    prompt_tokens = metrics["prompt_tokens"]
    cached_tokens = metrics["cached_tokens"]

    return {
        "ok": not error,
        "error": error,
        "status_code": status_code,
        "sequence": sequence,
        "request_id": row.get("request_id", f"request-{sequence:06d}"),
        "arrival_order": row.get("arrival_order", sequence),
        "trace": str(args.trace),
        "workload": args.workload or row.get("workload", ""),
        "policy": args.policy,
        "pressure": args.pressure,
        "model": args.model,
        "prompt_tokens": prompt_tokens,
        "cached_tokens": cached_tokens,
        "hit_rate": cached_tokens / prompt_tokens if prompt_tokens else 0.0,
        "completion_tokens": metrics["completion_tokens"],
        "ttft_ms": metrics["ttft_ms"],
        "latency_ms": latency_ms,
        "started_at": started_wall,
        "ended_at": started_wall + latency_ms / 1000.0,
        "response_meta": metrics["server_meta"],
    }


def replay(args: argparse.Namespace) -> list[dict[str, Any]]:
    trace_rows = read_jsonl(args.trace, args.limit)
    flush_cache(args)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = []
        for sequence, row in enumerate(trace_rows):
            if args.request_interval_ms > 0 and sequence > 0:
                time.sleep(args.request_interval_ms / 1000.0)
            futures.append(executor.submit(post_one, row, sequence, args))
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda row: row["sequence"])
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay trace JSONL against SGLang native /generate.")
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:30000")
    parser.add_argument("--endpoint", default="/generate")
    parser.add_argument("--flush-endpoint", default="/flush_cache")
    parser.add_argument("--flush-before", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--policy", default="")
    parser.add_argument("--pressure", default="")
    parser.add_argument("--workload", default="")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeout-sec", type=float, default=120.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--retry-backoff-sec", type=float, default=0.5)
    parser.add_argument("--request-interval-ms", type=float, default=0.0)
    parser.add_argument("--max-new-tokens", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=None)
    parser.add_argument("--stop", action="append", default=[])
    args = parser.parse_args()
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")
    args.trace = args.trace if args.trace.is_absolute() else ROOT / args.trace
    args.output = args.output if args.output.is_absolute() else ROOT / args.output
    return args


def main() -> None:
    args = parse_args()
    started = time.perf_counter()
    rows = replay(args)
    elapsed = time.perf_counter() - started
    write_jsonl(args.output, rows)
    ok = sum(1 for row in rows if row["ok"])
    prompt_tokens = sum(int(row["prompt_tokens"]) for row in rows if row["ok"])
    cached_tokens = sum(int(row["cached_tokens"]) for row in rows if row["ok"])
    hit_rate = cached_tokens / prompt_tokens if prompt_tokens else 0.0
    print(
        f"wrote {args.output} requests={len(rows)} ok={ok} "
        f"hit_rate={hit_rate:.4f} elapsed_sec={elapsed:.2f}"
    )


if __name__ == "__main__":
    main()
