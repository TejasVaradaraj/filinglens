import json

import pytest

from filinglens import config, llm


def test_cost_standard_tier():
    # Under 100K input tokens: $0.10 / $0.50 per 1M
    assert llm.cost_usd(100_000, 0) == pytest.approx(0.01)
    assert llm.cost_usd(50_000, 1_000) == pytest.approx(0.005 + 0.0005)


def test_cost_long_tier_applies_above_100k():
    assert llm.cost_usd(150_000, 1_000) == pytest.approx(150_000 / 1e6 * 0.50 + 1_000 / 1e6 * 2.50)


def test_batch_is_half_price():
    assert llm.cost_usd(50_000, 1_000, batch=True) == pytest.approx(llm.cost_usd(50_000, 1_000) / 2)


def test_split_is_disjoint_and_grouped_by_filing():
    split = json.loads((config.EVALS_DIR / "splits.json").read_text())
    assert len(split["dev"]) == 100 and len(split["test"]) == 50
    assert not set(split["dev"]) & set(split["test"])


def test_no_filing_on_both_sides():
    from filinglens.dataset import load_split
    if not (config.FINANCEBENCH_DIR / "data").exists():
        pytest.skip("FinanceBench not downloaded")
    dev_docs = {q.doc_name for q in load_split("dev")}
    test_docs = {q.doc_name for q in load_split("test")}
    assert not dev_docs & test_docs


def test_cache_aware_cost():
    # 1,000 uncached + 9,000 cache-read input tokens, 500 output, standard tier
    c = llm.cost_usd(1_000, 500, cache_read=9_000)
    assert c == pytest.approx((1_000 + 900) / 1e6 * 0.10 + 500 / 1e6 * 0.50)
    assert llm.cost_usd(0, 0, cache_write=50_000) == pytest.approx(50_000 * 1.25 / 1e6 * 0.10)
