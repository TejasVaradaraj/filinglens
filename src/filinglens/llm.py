"""The single doorway to the LLM.

Every model call in FilingLens goes through `complete()`, so cost, token counts
and latency are recorded the same way everywhere, and swapping models later is
a one-file change.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from functools import lru_cache

import anthropic

from filinglens import config, tracing


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_s: float
    stop_reason: str | None = None
    raw: object = field(default=None, repr=False)


CACHE_WRITE_MULT = 1.25   # writing a prompt-cache entry (5-minute TTL)
CACHE_READ_MULT = 0.10    # reading from the cache


def cost_usd(input_tokens: int, output_tokens: int, batch: bool = False,
             cache_write: int = 0, cache_read: int = 0) -> float:
    """Dollar cost of one call. Over 100K input tokens, the long-context rate applies.
    input_tokens are the uncached ones; cached tokens are reported separately by the API."""
    total_in = input_tokens + cache_write + cache_read
    tier = "long" if total_in > config.LONG_CONTEXT_THRESHOLD else "standard"
    price = config.PRICES[tier]
    cost = (input_tokens + cache_write * CACHE_WRITE_MULT + cache_read * CACHE_READ_MULT) / 1e6 * price["input"] \
        + output_tokens / 1e6 * price["output"]
    return cost * (0.5 if batch else 1.0)


def _usage_cost(usage) -> float:
    return cost_usd(usage.input_tokens, usage.output_tokens,
                    cache_write=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                    cache_read=getattr(usage, "cache_read_input_tokens", 0) or 0)


# --- Spending guard ---------------------------------------------------------------
# Every call's cost is added to a ledger file. If FL_BUDGET_USD is set, calls stop once
# the ledger reaches it (at most one call can overshoot, since cost is known afterwards).
# Shared across processes and threads via a file lock.
LEDGER = config.DATA_DIR / "spend_ledger.json"


class BudgetExceeded(RuntimeError):
    pass


def _ledger_update(add: float = 0.0) -> float:
    import fcntl
    import json
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        raw = f.read()
        data = json.loads(raw) if raw.strip() else {"total_usd": 0.0, "calls": 0}
        if add:
            data["total_usd"] += add
            data["calls"] += 1
            f.seek(0)
            f.truncate()
            f.write(json.dumps(data))
        fcntl.flock(f, fcntl.LOCK_UN)
    return data["total_usd"]


def _check_budget() -> None:
    budget = os.getenv("FL_BUDGET_USD")
    if budget and _ledger_update() >= float(budget):
        raise BudgetExceeded(f"Spend ledger reached the FL_BUDGET_USD cap of ${float(budget):.2f} ({LEDGER})")


@lru_cache(maxsize=1)
def client() -> anthropic.Anthropic:
    config.require_anthropic_key()
    # max_retries handles rate limits (429) and transient server errors with backoff.
    return anthropic.Anthropic(max_retries=5)


def complete(
    user: str,
    system: str | None = None,
    effort: str = config.DEFAULT_EFFORT,
    max_tokens: int = 4000,
    json_schema: dict | None = None,
) -> LLMResult:
    """Send one user message and return the text answer plus usage and cost.

    With json_schema, the API constrains the reply to valid JSON matching the
    schema (structured outputs), so `json.loads(result.text)` always works.
    """
    output_config: dict = {"effort": effort}
    if json_schema:
        output_config["format"] = {"type": "json_schema", "schema": json_schema}
    kwargs = dict(
        model=config.MODEL,
        max_tokens=max_tokens,
        output_config=output_config,
        messages=[{"role": "user", "content": user}],
    )
    if system:
        kwargs["system"] = system
    _check_budget()
    start = time.perf_counter()
    response = client().messages.create(**kwargs)
    latency = time.perf_counter() - start
    # Haiku 5.5 may return thinking blocks before the answer; keep only the text.
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    usage = response.usage
    _ledger_update(_usage_cost(usage))
    tracing.record_llm(usage.input_tokens, usage.output_tokens, _usage_cost(usage), latency)
    return LLMResult(
        text=text,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=_usage_cost(usage),
        latency_s=latency,
        stop_reason=response.stop_reason,
        raw=response,
    )


def chat(messages: list, system: str, tools: list, effort: str = config.DEFAULT_EFFORT,
         max_tokens: int = 4000, cache: bool = True) -> tuple[object, float]:
    """One turn of a tool-use conversation. Returns (raw response, cost in USD).

    cache=True turns on automatic prompt caching: each turn re-sends the whole
    conversation (pages included), so later turns read that prefix from cache at 10% price."""
    extra = {"cache_control": {"type": "ephemeral"}} if cache else {}
    _check_budget()
    start = time.perf_counter()
    response = client().messages.create(
        model=config.MODEL, max_tokens=max_tokens, output_config={"effort": effort},
        system=system, tools=tools, messages=messages, **extra,
    )
    usage = response.usage
    cost = _usage_cost(usage)
    _ledger_update(cost)
    tracing.record_llm(usage.input_tokens, usage.output_tokens, cost, time.perf_counter() - start)
    return response, cost


if __name__ == "__main__":
    print(f"ledger: ${_ledger_update():.4f} spent since it was created ({LEDGER}); "
          f"cap FL_BUDGET_USD={os.getenv('FL_BUDGET_USD', 'unset')}")
