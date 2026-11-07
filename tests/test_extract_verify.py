from filinglens.extract import verify

PAGES = {("3M_2018_10K", 59): "|Purchases of property, plant and equipment (PP&E)|**(1,577)**|(1,373)|(1,420)|\n"
                              "|Net income including noncontrolling interest|**$**<br>**5,363**|$ 4,869|"}


def val(**kw):
    base = {"doc": "3M_2018_10K", "page": 59, "value": -1577,
            "quote": "Purchases of property, plant and equipment (PP&E) (1,577) (1,373) (1,420)"}
    return {**base, **kw}


def test_value_on_page_passes():
    assert verify(val(), PAGES) is None
    assert verify(val(value=5363, quote="Net income including noncontrolling interest $ 5,363"), PAGES) is None


def test_wrong_page_is_repaired_when_quote_is_on_a_provided_page():
    v = val(page=60)
    assert verify(v, PAGES) is None and v["page"] == 59


def test_unknown_page_and_unknown_quote_fails():
    assert "on no provided page" in verify(val(page=60, quote="Some sentence that is nowhere"), PAGES)


def test_invented_quote_fails():
    assert verify(val(quote="Capital expenditures were $1,600 million in 2018"), PAGES) == \
        "quote not found on the cited page"


def test_number_not_in_quote_fails():
    assert "does not appear" in verify(val(value=-1600), PAGES)


def test_dash_means_zero():
    pages = {("A", 1): "|Business acquisitions|(121)|—|—|"}
    assert verify({"doc": "A", "page": 1, "value": 0, "quote": "Business acquisitions|(121)|—|—|"}, pages) is None


def test_wrong_page_citation_is_repaired():
    pages = {("A", 1): "intro text", ("A", 2): "|Dividends paid to shareholders|**(1,655)**|(1,700)|"}
    v = {"doc": "A", "page": 7, "value": -1655, "quote": "Dividends paid to shareholders|**(1,655)**|(1,700)|"}
    assert verify(v, pages) is None
    assert (v["doc"], v["page"], v["repaired_from"]) == ("A", 2, "A p7")


def test_spacing_differences_tolerated():
    pages = {("A", 4): "|Accounts receivable — net of allowances of $160 and $174|4,947|4,532|"}
    v = {"doc": "A", "page": 4, "value": 4947, "quote": "Accounts receivable — net of allowances of$160and $174|4,947|4,532"}
    assert verify(v, pages) is None


def test_empty_quote_still_fails():
    assert verify({"doc": "A", "page": 1, "value": 0, "quote": ""}, {("A", 1): "x"}) is not None
