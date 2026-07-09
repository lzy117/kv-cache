from __future__ import annotations

import argparse
import json
import re
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text)


def common_prefix_len(a: list[str], b: list[str]) -> int:
    total = 0
    for left, right in zip(a, b):
        if left != right:
            break
        total += 1
    return total


@dataclass
class MockCache:
    prompts: list[list[str]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def match(self, tokens: list[str]) -> int:
        with self.lock:
            if not self.prompts:
                return 0
            return max(common_prefix_len(tokens, cached) for cached in self.prompts)

    def insert(self, tokens: list[str]) -> None:
        with self.lock:
            self.prompts.append(tokens)

    def flush(self) -> None:
        with self.lock:
            self.prompts.clear()

    def size(self) -> int:
        with self.lock:
            return len(self.prompts)


class MockHandler(BaseHTTPRequestHandler):
    cache = MockCache()
    ttft_ms = 8.0
    per_token_ms = 1.0

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        parsed = json.loads(raw) if raw else {}
        return parsed if isinstance(parsed, dict) else {}

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server API.
        if self.path == "/health":
            self._send_json(200, {"ok": True, "cached_prompts": self.cache.size()})
            return
        self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - http.server API.
        if self.path == "/flush_cache":
            self._read_json()
            self.cache.flush()
            self._send_json(200, {"ok": True})
            return
        if self.path != "/generate":
            self._send_json(404, {"ok": False, "error": "not found"})
            return

        request = self._read_json()
        prompt = str(request.get("text") or request.get("prompt") or "")
        sampling_params = request.get("sampling_params") or {}
        if not isinstance(sampling_params, dict):
            sampling_params = {}
        tokens = tokenize(prompt)
        prompt_tokens = len(tokens)
        cached_tokens = self.cache.match(tokens)
        max_new_tokens = int(sampling_params.get("max_new_tokens", 1))
        simulated_latency_ms = self.ttft_ms + self.per_token_ms * max_new_tokens
        time.sleep(simulated_latency_ms / 1000.0)
        self.cache.insert(tokens)
        self._send_json(
            200,
            {
                "text": " mock",
                "meta_info": {
                    "prompt_tokens": prompt_tokens,
                    "cached_tokens": cached_tokens,
                    "completion_tokens": max_new_tokens,
                    "ttft_ms": self.ttft_ms,
                    "latency_ms": simulated_latency_ms,
                    "mock_cached_prompts": self.cache.size(),
                    "mock_time": time.time(),
                },
            },
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mock SGLang /generate server for A6 replay debugging.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=30080)
    parser.add_argument("--ttft-ms", type=float, default=8.0)
    parser.add_argument("--per-token-ms", type=float, default=1.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    MockHandler.ttft_ms = args.ttft_ms
    MockHandler.per_token_ms = args.per_token_ms
    server = ThreadingHTTPServer((args.host, args.port), MockHandler)
    print(f"mock server listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
