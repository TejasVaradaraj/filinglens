"""The single doorway to the LLM.

Every model call in FilingLens goes through `complete()`, so cost, token counts
and latency are recorded the same way everywhere, and swapping models later is
a one-file change.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import lru_cache

import anthropic

from filinglens import config


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_s: float
    stop_reason: str | None = None
    raw: object = field(default=None, repr=False)


def cost_usd(input_tokens: int, output_tokens: int, batch: bool = False) -> float:
    """Dollar cost of one call. Over 100K input tokens, the long-context rate applies."""
    tier = "long" if input_tokens > config.LONG_CONTEXT_THRESHOLD else "standard"
    price = config.PRICES[tier]
    cost = input_tokens / 1e6 * price["input"] + output_tokens / 1e6 * price["output"]
    return cost * (0.5 if batch else 1.0)


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
) -> LLMResult:
    """Send one user message and return the text answer plus usage and cost."""
    kwargs = dict(
        model=config.MODEL,
        max_tokens=max_tokens,
        output_config={"effort": effort},
        messages=[{"role": "user", "content": user}],
    )
    if system:
        kwargs["system"] = system
    start = time.perf_counter()
    response = client().messages.create(**kwargs)
    latency = time.perf_counter() - start
    # Haiku 5.5 may return thinking blocks before the answer; keep only the text.
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    usage = response.usage
    return LLMResult(
        text=text,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=cost_usd(usage.input_tokens, usage.output_tokens),
        latency_s=latency,
        stop_reason=response.stop_reason,
        raw=response,
    )
