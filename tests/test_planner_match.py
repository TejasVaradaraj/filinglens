import pytest

from filinglens.retrieval import planner


@pytest.fixture(autouse=True)
def fake_companies(monkeypatch):
    monkeypatch.setattr(planner, "companies", lambda: ("3M", "Best Buy", "Johnson & Johnson", "Coca-Cola"))


@pytest.mark.parametrize("name, expected", [
    ("Best Buy", "Best Buy"), ("Best Buy Co., Inc.", "Best Buy"), ("best-buy", "Best Buy"),
    ("JOHNSON & JOHNSON", "Johnson & Johnson"), ("Coca Cola", "Coca-Cola"), ("3M Company", "3M"),
    ("Tesla", None), ("", None),
])
def test_match_company(name, expected):
    assert planner.match_company(name) == expected
