#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BASE_URL="${BASE_URL:-http://127.0.0.1:30000}"
MODEL="${MODEL:-Qwen/Qwen2.5-7B-Instruct}"
PROFILE="${PROFILE:-smoke}"
SEED="${SEED:-20260708}"
POLICIES="${POLICIES:-lru lfu fifo slru 2q}"
WORKLOADS="${WORKLOADS:-w1 w2 w3 w4}"
PRESSURES="${PRESSURES:-medium high}"
CONCURRENCY="${CONCURRENCY:-1}"
LIMIT="${LIMIT:-}"
OUTPUT_DIR="${OUTPUT_DIR:-$ROOT/results/raw}"
SUMMARY_OUT="${SUMMARY_OUT:-$ROOT/results/summary.csv}"
FLUSH_ENDPOINT="${FLUSH_ENDPOINT:-/flush_cache}"
REPLAY_EXTRA="${REPLAY_EXTRA:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

mkdir -p "$OUTPUT_DIR"

echo "base_url=$BASE_URL model=$MODEL profile=$PROFILE concurrency=$CONCURRENCY"
echo "policies=$POLICIES"
echo "workloads=$WORKLOADS"
echo "pressures=$PRESSURES"

for policy in $POLICIES; do
  echo "== policy: $policy =="
  echo "Ensure the SGLang server is running with --radix-eviction-policy $policy before this block."
  for pressure in $PRESSURES; do
    for workload in $WORKLOADS; do
      trace="$ROOT/traces/${workload}_${PROFILE}_seed${SEED}.jsonl"
      output="$OUTPUT_DIR/${workload}_${PROFILE}_${policy}_${pressure}.jsonl"
      if [[ ! -f "$trace" ]]; then
        echo "missing trace: $trace" >&2
        exit 1
      fi

      echo "-- flush cache"
      curl -fsS -X POST "${BASE_URL%/}${FLUSH_ENDPOINT}" >/dev/null || true

      limit_args=()
      if [[ -n "$LIMIT" ]]; then
        limit_args=(--limit "$LIMIT")
      fi

      echo "-- replay workload=$workload policy=$policy pressure=$pressure trace=$trace"
      "$PYTHON_BIN" "$ROOT/bench/replay.py" \
        --base-url "$BASE_URL" \
        --trace "$trace" \
        --output "$output" \
        --model "$MODEL" \
        --policy "$policy" \
        --pressure "$pressure" \
        --workload "$workload" \
        --concurrency "$CONCURRENCY" \
        "${limit_args[@]}" \
        $REPLAY_EXTRA
    done
  done
done

"$PYTHON_BIN" "$ROOT/bench/collect.py" "$OUTPUT_DIR/*.jsonl" --output "$SUMMARY_OUT"
echo "summary=$SUMMARY_OUT"
