"""Structured JSON logs and an in-process metrics sink.

The join key across transaction_log, retrieval_log and graph_checkpoint is
request_id -> turn_id -> stage, so every log line carries whatever of those is known.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
from collections import defaultdict
from typing import Any

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
turn_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("turn_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if rid := request_id_var.get():
            payload["request_id"] = rid
        if tid := turn_id_var.get():
            payload["turn_id"] = tid
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # uvicorn's own access log duplicates our middleware's line.
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False


def log(logger: logging.Logger, level: int, msg: str, **fields: Any) -> None:
    logger.log(level, msg, extra={"extra_fields": fields})


class Metrics:
    """Counters, latency samples, and the running token/cost totals."""

    def __init__(self) -> None:
        self.counters: dict[str, int] = defaultdict(int)
        self.latencies: dict[str, list[float]] = defaultdict(list)
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_usd = 0.0

    def incr(self, name: str, by: int = 1) -> None:
        self.counters[name] += by

    def observe(self, name: str, ms: float) -> None:
        samples = self.latencies[name]
        samples.append(ms)
        if len(samples) > 1000:
            del samples[:-1000]

    def record_usage(self, tokens_in: int, tokens_out: int, cost: float) -> None:
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.cost_usd = round(self.cost_usd + cost, 8)

    def snapshot(self) -> dict[str, Any]:
        def pct(xs: list[float], p: float) -> float:
            if not xs:
                return 0.0
            ordered = sorted(xs)
            idx = min(len(ordered) - 1, int(p * len(ordered)))
            return round(ordered[idx], 2)

        return {
            "counters": dict(self.counters),
            "latency_ms": {
                name: {"p50": pct(xs, 0.5), "p95": pct(xs, 0.95), "max": round(max(xs), 2)}
                for name, xs in self.latencies.items()
                if xs
            },
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": round(self.cost_usd, 6),
        }


METRICS = Metrics()
