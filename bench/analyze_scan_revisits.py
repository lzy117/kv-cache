from __future__ import annotations

import argparse
import csv
import glob
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    rows.sort(key=lambda row: int(row.get("sequence", row.get("arrival_order", 0))))
    return rows


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def discover_files(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        full_pattern = pattern if Path(pattern).is_absolute() else str(ROOT / pattern)
        paths.extend(Path(p) for p in glob.glob(full_pattern))
    return sorted(set(paths))


def analyze_file(path: Path, window: int) -> list[dict[str, Any]]:
    rows = read_jsonl(path)
    details: list[dict[str, Any]] = []
    policy = rows[0].get("policy", "") if rows else ""
    workload = rows[0].get("workload", "") if rows else ""
    pressure = rows[0].get("pressure", "") if rows else ""

    for index, row in enumerate(rows):
        request_id = str(row.get("request_id", ""))
        if not request_id.startswith("w4-scan-"):
            continue

        scan_id = request_id.removeprefix("w4-scan-")
        revisits = rows[index + 1 : index + 1 + window]
        for offset, revisit in enumerate(revisits, start=1):
            revisit_id = str(revisit.get("request_id", ""))
            if not revisit_id.startswith("w4-hot-"):
                continue
            details.append(
                {
                    "source_file": str(path),
                    "policy": revisit.get("policy", policy),
                    "pressure": revisit.get("pressure", pressure),
                    "workload": revisit.get("workload", workload),
                    "scan_id": scan_id,
                    "offset_after_scan": offset,
                    "request_id": revisit_id,
                    "ok": revisit.get("ok", False),
                    "prompt_tokens": int(revisit.get("prompt_tokens", 0)),
                    "cached_tokens": int(revisit.get("cached_tokens", 0)),
                    "hit_rate": float(revisit.get("hit_rate", 0.0)),
                    "ttft_ms": float(revisit.get("ttft_ms", 0.0)),
                    "latency_ms": float(revisit.get("latency_ms", 0.0)),
                }
            )
    return details


def summarize(details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in details:
        key = (str(row["policy"]), str(row["pressure"]), str(row["workload"]))
        grouped[key].append(row)

    summaries: list[dict[str, Any]] = []
    for (policy, pressure, workload), rows in sorted(grouped.items()):
        ok_rows = [row for row in rows if row["ok"]]
        cached = [float(row["cached_tokens"]) for row in ok_rows]
        hit_rates = [float(row["hit_rate"]) for row in ok_rows]
        ttfts = [float(row["ttft_ms"]) for row in ok_rows]
        prompt_tokens = sum(int(row["prompt_tokens"]) for row in ok_rows)
        cached_tokens = sum(int(row["cached_tokens"]) for row in ok_rows)
        scan_count = len({row["scan_id"] for row in rows})
        summaries.append(
            {
                "policy": policy,
                "pressure": pressure,
                "workload": workload,
                "scan_count": scan_count,
                "hot_revisit_rows": len(rows),
                "ok": len(ok_rows),
                "failed": len(rows) - len(ok_rows),
                "prompt_tokens": prompt_tokens,
                "cached_tokens": cached_tokens,
                "hit_rate": cached_tokens / prompt_tokens if prompt_tokens else 0.0,
                "cached_tokens_mean": statistics.fmean(cached) if cached else 0.0,
                "cached_tokens_p50": percentile(cached, 0.50),
                "cached_tokens_p90": percentile(cached, 0.90),
                "hit_rate_mean": statistics.fmean(hit_rates) if hit_rates else 0.0,
                "hit_rate_p50": percentile(hit_rates, 0.50),
                "hit_rate_p90": percentile(hit_rates, 0.90),
                "ttft_p50_ms": percentile(ttfts, 0.50),
                "ttft_p90_ms": percentile(ttfts, 0.90),
                "ttft_p99_ms": percentile(ttfts, 0.99),
            }
        )
    return summaries


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze hot-request metrics immediately after W4 scan requests."
    )
    parser.add_argument(
        "patterns",
        nargs="+",
        help="Raw JSONL files or glob patterns, e.g. results/raw_pressure_w4_limit500/*.jsonl",
    )
    parser.add_argument("--window", type=int, default=32)
    parser.add_argument(
        "--detail-out",
        type=Path,
        default=Path("results/scan_revisit_detail.csv"),
    )
    parser.add_argument(
        "--summary-out",
        type=Path,
        default=Path("results/scan_revisit_summary.csv"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    files = discover_files(args.patterns)
    if not files:
        raise SystemExit(f"No raw JSONL files matched: {args.patterns}")

    details: list[dict[str, Any]] = []
    for path in files:
        details.extend(analyze_file(path, args.window))
    if not details:
        raise SystemExit("No scan -> hot revisit rows found.")

    detail_out = args.detail_out if args.detail_out.is_absolute() else ROOT / args.detail_out
    summary_out = args.summary_out if args.summary_out.is_absolute() else ROOT / args.summary_out
    write_csv(detail_out, details)
    write_csv(summary_out, summarize(details))
    print(f"detail={detail_out}")
    print(f"summary={summary_out}")


if __name__ == "__main__":
    main()
