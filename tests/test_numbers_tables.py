"""The tricky parsing cases from real filings."""
import pytest

from filinglens.parsing.numbers import detect_scale, is_per_share_label, parse_number
from filinglens.parsing.tables import page_tables


@pytest.mark.parametrize("cell, expected", [
    ("(1,234)", -1234), ("**(370)**", -370), ("$ 5,363", 5363), ("**$**<br>**5,363**", 5363),
    ("1,488", 1488), ("12.5%", 12.5), ("(2.3)%", -2.3), ("—", 0.0), ("-", 0.0), ("$ (57)", -57),
    ("-1.2", -1.2), ("0.66", 0.66),
    ("_3.6 %_", 3.6), ("<sup>$</sup> 29,499", 29499), ("(a) (26)", -26), ("(1) 2,992", 2992),
])
def test_parse_number(cell, expected):
    assert parse_number(cell) == pytest.approx(expected)


@pytest.mark.parametrize("cell", ["Net income", "2018 vs 2017", "Note 3", "", "1.2.3"])
def test_parse_number_rejects_text(cell):
    # Labels and years-with-words are not numbers; empty cells are not numbers either.
    assert parse_number(cell) is None


@pytest.mark.parametrize("text, scale", [
    ("(Millions)", 1_000_000),
    ("(In millions, except per share amounts)", 1_000_000),
    ("Dollars in thousands", 1_000),
    ("(in thousands, except per share data)", 1_000),
    ("$ in billions", 1_000_000_000),
    ("Years ended December 31", None),
])
def test_detect_scale(text, scale):
    assert detect_scale(text) == scale


def test_per_share_rows_flagged():
    assert is_per_share_label("Diluted earnings per share")
    assert is_per_share_label("EPS - basic")
    assert not is_per_share_label("Net sales")


CASH_FLOW_PAGE = """# **3M Company Consolidated Statement of Cash Flows Years ended December 31**

|**(Millions)**|**2018**|**2017**|**2016**|
|---|---|---|---|
|**Cash Flows from Operating Activities**||||
|Net income including noncontrolling interest|**$**<br>**5,363**|$ 4,869|$ 5,058|
|Company pension and postretirement contributions|**(370)**|(967)|(383)|
|Purchases of property, plant and equipment (PP&E)|**(1,577)**|(1,373)|(1,420)|
"""


def test_cash_flow_table_values_and_scale():
    [t] = page_tables(CASH_FLOW_PAGE)
    assert t.header == ["(Millions)", "2018", "2017", "2016"]
    assert t.scale == 1_000_000
    capex = next(r for r, v in zip(t.rows, t.values) if r[0].startswith("Purchases of property"))
    assert t.values[t.rows.index(capex)] == [-1577, -1373, -1420]
    assert t.values[1] == [5363, 4869, 5058]
    assert "Cash Flows" in t.title


DOLLAR_COLUMNS_PAGE = """In millions, except per share data

|Fiscal year|2023||2022|
|---|---|---|---|
|Revenue|$|46,298|$|51,761|
|Diluted EPS|$|6.20|$|10.01|
"""


def test_separate_dollar_columns_are_dropped_and_page_scale_inherited():
    [t] = page_tables(DOLLAR_COLUMNS_PAGE)
    assert t.values == [[46298, 51761], [6.20, 10.01]]
    assert t.scale == 1_000_000
    assert t.cells_json()["per_share_rows"] == [1]


TWO_LINE_HEADER = """|Year Ended|Year Ended|
|---|---|---|
|Item|Dec 31, 2022|Dec 31, 2021|
|Net sales|100|90|
"""


def test_two_line_header_merged():
    [t] = page_tables(TWO_LINE_HEADER)
    assert t.header[1:] == ["Year Ended Dec 31, 2022", "Year Ended Dec 31, 2021"]
    assert t.values == [[100, 90]]


SPLIT_SCALE = """|Years Ended|2021|2020|
|---|---|---|
|(dol|lars in million|s, except per share)|
|Revenue|133,613|128,292|
"""


def test_scale_split_across_cells_is_detected():
    [t] = page_tables(SPLIT_SCALE)
    assert t.scale == 1_000_000
