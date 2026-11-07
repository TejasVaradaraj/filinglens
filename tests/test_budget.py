import pytest

from filinglens import llm


def test_budget_guard_blocks_calls_over_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "LEDGER", tmp_path / "ledger.json")
    monkeypatch.setenv("FL_BUDGET_USD", "0.01")
    llm._check_budget()                 # empty ledger: allowed
    llm._ledger_update(0.004)
    llm._check_budget()                 # under the cap
    llm._ledger_update(0.007)           # now $0.011
    with pytest.raises(llm.BudgetExceeded):
        llm._check_budget()


def test_no_cap_means_no_block(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "LEDGER", tmp_path / "ledger.json")
    monkeypatch.delenv("FL_BUDGET_USD", raising=False)
    llm._ledger_update(100.0)
    llm._check_budget()


def test_ledger_survives_concurrent_writers(tmp_path, monkeypatch):
    import json
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(llm, "LEDGER", tmp_path / "ledger.json")
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda _: llm._ledger_update(0.001), range(400)))
    data = json.loads((tmp_path / "ledger.json").read_text())
    assert data["calls"] == 400 and abs(data["total_usd"] - 0.4) < 1e-9
