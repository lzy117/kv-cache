from __future__ import annotations

import argparse
import csv
import glob
import json
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]


def expand_inputs(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        matches = glob.glob(pattern)
        if not matches:
            path = Path(pattern)
            matches = [str(path)]
        for match in matches:
            path = Path(match)
            paths.append(path if path.is_absolute() else ROOT / path)
    return sorted(set(paths))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                row["_source"] = str(path)
                rows.append(row)
    return rows


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def group_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("model", "")),
        str(row.get("policy", "")),
        str(row.get("pressure", "")),
        str(row.get("workload", "")),
        str(row.get("trace", "")),
    )


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(group_key(row), []).append(row)

    summary_rows: list[dict[str, Any]] = []
    for (model, policy, pressure, workload, trace), group in sorted(groups.items()):
        ok_rows = [row for row in group if row.get("ok")]
        prompt_tokens = sum(int(row.get("prompt_tokens", 0)) for row in ok_rows)
        cached_tokens = sum(int(row.get("cached_tokens", 0)) for row in ok_rows)
        completion_tokens = sum(int(row.get("completion_tokens", 0)) for row in ok_rows)
        ttft = [float(row.get("ttft_ms", 0.0)) for row in ok_rows]
        latency = [float(row.get("latency_ms", 0.0)) for row in ok_rows]
        started = [float(row.get("started_at", 0.0)) for row in ok_rows if row.get("started_at")]
        ended = [float(row.get("ended_at", 0.0)) for row in ok_rows if row.get("ended_at")]
        wall_sec = max(ended) - min(started) if started and ended else sum(latency) / 1000.0
        total_tokens = prompt_tokens + completion_tokens
        summary_rows.append(
            {
                "model": model,
                "policy": policy,
                "pressure": pressure,
                "workload": workload,
                "trace": trace,
                "requests": len(group),
                "ok": len(ok_rows),
                "failed": len(group) - len(ok_rows),
                "prompt_tokens": prompt_tokens,
                "cached_tokens": cached_tokens,
                "hit_rate": cached_tokens / prompt_tokens if prompt_tokens else 0.0,
                "completion_tokens": completion_tokens,
                "ttft_p50_ms": percentile(ttft, 0.50),
                "ttft_p90_ms": percentile(ttft, 0.90),
                "ttft_p99_ms": percentile(ttft, 0.99),
                "latency_p50_ms": percentile(latency, 0.50),
                "latency_p90_ms": percentile(latency, 0.90),
                "latency_p99_ms": percentile(latency, 0.99),
                "wall_sec": wall_sec,
                "requests_per_sec": len(ok_rows) / wall_sec if wall_sec > 0 else 0.0,
                "tokens_per_sec": total_tokens / wall_sec if wall_sec > 0 else 0.0,
            }
        )
    return summary_rows


def write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect replay raw JSONL files into summary CSV.")
    parser.add_argument("inputs", nargs="+", help="Raw JSONL path or glob pattern.")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "summary.csv")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output = args.output if args.output.is_absolute() else ROOT / args.output
    rows: list[dict[str, Any]] = []
    for path in expand_inputs(args.inputs):
        rows.extend(read_jsonl(path))
    summary = summarize(rows)
    write_csv(args.output, summary)
    print(f"wrote {args.output} groups={len(summary)} rows={len(rows)}")


if __name__ == "__main__":
    main()
