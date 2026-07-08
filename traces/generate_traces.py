from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_SEED = 20260708


SUBJECTS = [
    "abstract algebra",
    "anatomy",
    "astronomy",
    "business ethics",
    "clinical knowledge",
    "college biology",
    "college chemistry",
    "college computer science",
    "college mathematics",
    "college medicine",
    "college physics",
    "computer security",
    "conceptual physics",
    "econometrics",
    "electrical engineering",
    "elementary mathematics",
    "formal logic",
    "global facts",
    "high school biology",
    "high school chemistry",
    "high school computer science",
    "high school european history",
    "high school geography",
    "high school government",
    "high school macroeconomics",
    "high school mathematics",
    "high school microeconomics",
    "high school physics",
    "high school psychology",
    "high school statistics",
    "high school us history",
    "high school world history",
    "human aging",
    "human sexuality",
    "international law",
    "jurisprudence",
    "logical fallacies",
    "machine learning",
    "management",
    "marketing",
    "medical genetics",
    "miscellaneous",
    "moral disputes",
    "moral scenarios",
    "nutrition",
    "philosophy",
    "prehistory",
    "professional accounting",
    "professional law",
    "professional medicine",
    "professional psychology",
    "public relations",
    "security studies",
    "sociology",
    "us foreign policy",
    "virology",
    "world religions",
]


USER_TOPICS = [
    "缓存命中率为什么下降",
    "如何判断一个实验是否可复现",
    "长上下文推理的瓶颈在哪里",
    "怎样解释 TTFT 的变化",
    "为什么共享前缀能降低 prefill",
    "如何设计公平的消融实验",
    "为什么 Zipf 分布常见于真实流量",
    "如何定位离线模拟和真机偏差",
]


ASSISTANT_REPLIES = [
    "可以先把问题拆成状态、事件和指标三部分，再检查每一步是否有可观测日志。",
    "一个可复现实验至少要固定输入、顺序、随机种子、代码版本和运行参数。",
    "长上下文推理通常先受 prefill 计算影响，再受 KV cache 显存容量影响。",
    "TTFT 变化需要同时看 prompt 长度、cached_tokens、并发和服务端排队情况。",
    "共享前缀复用的本质是复用已经计算过的 Key 和 Value，减少重复 attention 计算。",
    "公平消融要保证除了被测变量以外，其余输入和运行条件完全一致。",
    "Zipf 分布意味着少数热点承担大量请求，缓存策略如果能识别热点就会收益明显。",
    "模拟器偏差通常来自 lock_ref、并发交错、tokenizer 差异和真实池大小口径。",
]


@dataclass(frozen=True)
class TraceRecord:
    request_id: str
    prompt: str
    max_tokens: int
    arrival_order: int
    workload: str
    meta: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        approx_prompt_tokens = approximate_tokens(self.prompt)
        return {
            "request_id": self.request_id,
            "prompt": self.prompt,
            "max_tokens": self.max_tokens,
            "arrival_order": self.arrival_order,
            "workload": self.workload,
            "approx_prompt_tokens": approx_prompt_tokens,
            **self.meta,
        }


def approximate_tokens(text: str) -> int:
    # A stable rough proxy for trace planning. The simulator will use a real tokenizer.
    return max(1, math.ceil(len(text) / 4))


def make_few_shot_prefix(subject: str) -> str:
    examples = []
    for i in range(5):
        examples.append(
            "\n".join(
                [
                    f"Example {i + 1} for {subject}.",
                    f"Question: In {subject}, choose the best answer for case {i + 1}.",
                    "A. option alpha",
                    "B. option beta",
                    "C. option gamma",
                    "D. option delta",
                    f"Answer: {'ABCD'[i % 4]}",
                ]
            )
        )
    return (
        "You are an expert exam solver. Answer with only the option letter.\n"
        f"Subject: {subject}\n"
        + "\n\n".join(examples)
        + "\n\n"
    )


def generate_w1(rng: random.Random, subjects: int, requests_per_subject: int) -> list[TraceRecord]:
    selected = SUBJECTS[:subjects]
    prefixes = {subject: make_few_shot_prefix(subject) for subject in selected}
    records: list[TraceRecord] = []
    order = 0
    for round_idx in range(requests_per_subject):
        shuffled = selected[:]
        rng.shuffle(shuffled)
        for subject in shuffled:
            prompt = (
                prefixes[subject]
                + f"Question: Held-out {subject} question {round_idx + 1}. Which option is correct?\n"
                + "A. cached prefix reuse\nB. random eviction\nC. unrelated answer\nD. no answer\nAnswer:"
            )
            records.append(
                TraceRecord(
                    request_id=f"w1-{order:06d}",
                    prompt=prompt,
                    max_tokens=1,
                    arrival_order=order,
                    workload="w1_few_shot",
                    meta={"subject": subject, "round": round_idx},
                )
            )
            order += 1
    return records


def padding_words(prefix: str, count: int) -> str:
    return " ".join(f"{prefix}_{i:03d}" for i in range(count))


def conversation_turn(conv_id: int, turn: int, turn_padding_words: int = 0) -> tuple[str, str]:
    topic = USER_TOPICS[(conv_id + turn) % len(USER_TOPICS)]
    reply = ASSISTANT_REPLIES[(conv_id * 3 + turn) % len(ASSISTANT_REPLIES)]
    user_pad = padding_words(f"user_c{conv_id:04d}_t{turn:02d}", turn_padding_words)
    assistant_pad = padding_words(f"asst_c{conv_id:04d}_t{turn:02d}", turn_padding_words)
    user = f"用户第 {turn + 1} 轮：请结合前面的上下文解释：{topic}。{user_pad}"
    assistant = f"助手第 {turn + 1} 轮：{reply} {assistant_pad}"
    return user, assistant


def generate_w2(
    rng: random.Random,
    conversations: int,
    turns: int,
    turn_padding_words: int = 0,
) -> list[TraceRecord]:
    histories = {cid: [f"System: 你是实验解释助手，当前会话编号为 {cid}。"] for cid in range(conversations)}
    schedule = [(turn, cid) for turn in range(turns) for cid in range(conversations)]
    for turn in range(turns):
        start = turn * conversations
        end = start + conversations
        block = schedule[start:end]
        rng.shuffle(block)
        schedule[start:end] = block

    records: list[TraceRecord] = []
    for order, (turn, cid) in enumerate(schedule):
        user, assistant = conversation_turn(cid, turn, turn_padding_words)
        prompt = "\n".join(histories[cid] + [user, "Assistant:"])
        records.append(
            TraceRecord(
                request_id=f"w2-{order:06d}",
                prompt=prompt,
                max_tokens=48,
                arrival_order=order,
                workload="w2_multiturn",
                meta={"conversation_id": cid, "turn": turn},
            )
        )
        histories[cid].extend([user, assistant])
    return records


def tenant_prompt(tenant_id: int) -> str:
    repeat = 4 + (tenant_id % 9)
    policy_lines = [
        f"Tenant {tenant_id} system policy.",
        "你是企业内部知识库助手，需要遵守租户专属格式和术语。",
        "回答时先给结论，再给依据，最后给可执行步骤。",
    ]
    for i in range(repeat):
        policy_lines.append(
            f"租户 {tenant_id} 专属规则 {i + 1}: 保留项目代号 T{tenant_id:03d}-{i:02d}，优先解释缓存、延迟和成本。"
        )
    return "\n".join(policy_lines) + "\n"


def zipf_indices(rng: random.Random, n: int, alpha: float, count: int) -> list[int]:
    weights = [1.0 / ((rank + 1) ** alpha) for rank in range(n)]
    total = sum(weights)
    cdf = []
    acc = 0.0
    for w in weights:
        acc += w / total
        cdf.append(acc)

    out = []
    for _ in range(count):
        x = rng.random()
        lo, hi = 0, n - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if cdf[mid] < x:
                lo = mid + 1
            else:
                hi = mid
        out.append(lo)
    return out


def generate_w3(
    rng: random.Random,
    tenants: int,
    requests: int,
    zipf_alpha: float,
    workload: str = "w3_zipf_tenants",
    start_order: int = 0,
) -> list[TraceRecord]:
    tenant_prefixes = {tenant_id: tenant_prompt(tenant_id) for tenant_id in range(tenants)}
    tenant_ids = zipf_indices(rng, tenants, zipf_alpha, requests)
    records: list[TraceRecord] = []
    for offset, tenant_id in enumerate(tenant_ids):
        order = start_order + offset
        prompt = (
            tenant_prefixes[tenant_id]
            + f"User request {offset}: 请分析租户 {tenant_id} 最近一次缓存命中率变化，并给出排查顺序。\n"
            + "Assistant:"
        )
        records.append(
            TraceRecord(
                request_id=f"{workload.split('_')[0]}-{order:06d}",
                prompt=prompt,
                max_tokens=32,
                arrival_order=order,
                workload=workload,
                meta={"tenant_id": tenant_id, "zipf_alpha": zipf_alpha},
            )
        )
    return records


def scan_document(scan_id: int, words: int) -> str:
    parts = [
        "一次性长文档扫描请求。",
        f"scan_id={scan_id}",
        "这段内容模拟不会再次出现的 RAG 或长文档输入。",
    ]
    for i in range(words):
        parts.append(f"scan{scan_id:03d}_unique_token_{i:05d}")
    return " ".join(parts)


def generate_w4(
    rng: random.Random,
    tenants: int,
    requests: int,
    zipf_alpha: float,
    scan_every: int,
    scan_doc_words: int,
) -> list[TraceRecord]:
    base = generate_w3(
        rng,
        tenants=tenants,
        requests=requests,
        zipf_alpha=zipf_alpha,
        workload="w4_zipf_with_scans",
    )
    out: list[TraceRecord] = []
    scan_id = 0
    order = 0
    for record in base:
        if order > 0 and order % scan_every == 0:
            prompt = scan_document(scan_id, scan_doc_words) + "\n请总结这份一次性文档。\nAssistant:"
            out.append(
                TraceRecord(
                    request_id=f"w4-scan-{scan_id:06d}",
                    prompt=prompt,
                    max_tokens=16,
                    arrival_order=order,
                    workload="w4_zipf_with_scans",
                    meta={"scan_id": scan_id, "is_scan": True, "scan_doc_words": scan_doc_words},
                )
            )
            scan_id += 1
            order += 1
        item = TraceRecord(
            request_id=f"w4-{order:06d}",
            prompt=record.prompt,
            max_tokens=record.max_tokens,
            arrival_order=order,
            workload="w4_zipf_with_scans",
            meta={**record.meta, "is_scan": False},
        )
        out.append(item)
        order += 1
    return out


def write_jsonl(path: Path, records: Iterable[TraceRecord]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    approx_tokens = 0
    max_prompt = 0
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            row = record.to_json()
            approx = row["approx_prompt_tokens"]
            approx_tokens += approx
            max_prompt = max(max_prompt, approx)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return {"path": str(path), "requests": count, "approx_prompt_tokens_sum": approx_tokens, "max_prompt_tokens": max_prompt}


def load_plan(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_records(workload: str, cfg: dict[str, Any], seed: int) -> list[TraceRecord]:
    rng = random.Random(seed)
    if workload == "w1":
        return generate_w1(rng, **cfg)
    if workload == "w2":
        return generate_w2(rng, **cfg)
    if workload == "w3":
        return generate_w3(rng, **cfg)
    if workload == "w4":
        return generate_w4(rng, **cfg)
    raise ValueError(f"unknown workload: {workload}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic W1-W4 trace JSONL files.")
    parser.add_argument("--plan", type=Path, default=Path("configs/trace_plan.json"))
    parser.add_argument("--profile", choices=["smoke", "main"], default="smoke")
    parser.add_argument("--workload", choices=["all", "w1", "w2", "w3", "w4"], default="all")
    parser.add_argument("--output-dir", type=Path, default=Path("traces"))
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    plan = load_plan(args.plan)
    seed = args.seed if args.seed is not None else int(plan["seed"])
    profile_cfg = plan["profiles"][args.profile]
    workloads = ["w1", "w2", "w3", "w4"] if args.workload == "all" else [args.workload]

    manifest = {
        "seed": seed,
        "profile": args.profile,
        "workloads": [],
    }
    for workload in workloads:
        records = build_records(workload, profile_cfg[workload], seed + len(workload))
        out_path = args.output_dir / f"{workload}_{args.profile}_seed{seed}.jsonl"
        summary = write_jsonl(out_path, records)
        summary["workload"] = workload
        manifest["workloads"].append(summary)

    manifest_path = args.output_dir / f"manifest_{args.profile}_seed{seed}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
