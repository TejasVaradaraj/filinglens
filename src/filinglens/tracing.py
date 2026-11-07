"""Lightweight tracing: where does each question spend its time and money?

    with tracing.trace("question") as t:      # root, one per question
        with tracing.span("retrieve"):        # nested stages
            ...                               # llm.complete()/chat() inside report usage here
    t.to_dict()                               # JSON-serializable tree

Report for an eval run (per-stage latency, LLM calls, tokens, cost):
    python -m filinglens.tracing <run_dir>

The current span lives in a ContextVar, so instrumented code needs no extra arguments.
Each question runs in one thread, which is where its trace is started.
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Span:
    name: str
    start: float = field(default_factory=time.perf_counter)
    end: float | None = None
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    llm_seconds: float = 0.0
    children: list["Span"] = field(default_factory=list)
    attrs: dict = field(default_factory=dict)

    @property
    def seconds(self) -> float:
        return (self.end or time.perf_counter()) - self.start

    def total(self, attr: str):
        return getattr(self, attr) + sum(c.total(attr) for c in self.children)

    def to_dict(self) -> dict:
        return {"name": self.name, "seconds": round(self.seconds, 3), "llm_calls": self.llm_calls,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "cost_usd": round(self.cost_usd, 6), "llm_seconds": round(self.llm_seconds, 3),
                "attrs": self.attrs, "children": [c.to_dict() for c in self.children]}


_current: ContextVar[Span | None] = ContextVar("filinglens_span", default=None)


@contextmanager
def trace(name: str):
    """Start a new root span (ignores any span already active in this context)."""
    root = Span(name)
    token = _current.set(root)
    try:
        yield root
    finally:
        root.end = time.perf_counter()
        _current.reset(token)


@contextmanager
def span(name: str, **attrs):
    parent = _current.get()
    s = Span(name, attrs=attrs)
    if parent is not None:
        parent.children.append(s)
    token = _current.set(s)
    try:
        yield s
    finally:
        s.end = time.perf_counter()
        _current.reset(token)


def record_llm(input_tokens: int, output_tokens: int, cost: float, seconds: float) -> None:
    """Called by llm.py after every model call; attributes usage to the active span."""
    s = _current.get()
    if s is None:
        return
    s.llm_calls += 1
    s.input_tokens += input_tokens
    s.output_tokens += output_tokens
    s.cost_usd += cost
    s.llm_seconds += seconds


def annotate(**attrs) -> None:
    s = _current.get()
    if s is not None:
        s.attrs.update(attrs)


def _walk(d: dict, path: str = ""):
    here = f"{path}/{d['name']}" if path else d["name"]
    yield here, d
    for c in d["children"]:
        yield from _walk(c, here)


def report(run_dir: Path) -> str:
    rows = [json.loads(l) for l in (run_dir / "results.jsonl").read_text().splitlines()]
    traces = [r["trace"] for r in rows if r.get("trace")]
    if not traces:
        return "no traces in this run (it predates tracing)"
    agg = defaultdict(lambda: defaultdict(float))
    for t in traces:
        for path, d in _walk(t):
            depth_name = path.split("/", 1)[1] if "/" in path else "(total)"
            a = agg[depth_name]
            a["n"] += 1
            a["seconds"] += d["seconds"]
            for k in ("llm_calls", "input_tokens", "output_tokens", "cost_usd", "llm_seconds"):
                a[k] += d[k]
    total_cost = sum(a["cost_usd"] for a in agg.values())
    total_secs = agg["(total)"]["seconds"] / len(traces)
    lines = [f"{len(traces)} traced questions; mean {total_secs:.2f} s and "
             f"${total_cost / len(traces):.5f} per question (LLM cost, excluding the judge)\n",
             "| stage | ran on | mean s | LLM calls/q | in tokens/q | out tokens/q | cost/q | share of cost |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    n = len(traces)
    for name, a in sorted(agg.items(), key=lambda kv: kv[0]):
        lines.append(f"| {name} | {int(a['n'])} | {a['seconds'] / a['n']:.2f} | {a['llm_calls'] / n:.2f} | "
                     f"{a['input_tokens'] / n:,.0f} | {a['output_tokens'] / n:,.0f} | ${a['cost_usd'] / n:.5f} | "
                     f"{(a['cost_usd'] / total_cost * 100) if total_cost else 0:.0f}% |")
    return "\n".join(lines)


if __name__ == "__main__":
    print(report(Path(sys.argv[1])))
