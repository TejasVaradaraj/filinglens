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


def test_wrong_page_fails():
    assert "not in the excerpts" in verify(val(page=60), PAGES)


def test_invented_quote_fails():
    assert verify(val(quote="Capital expenditures were $1,600 million in 2018"), PAGES) == \
        "quote not found on the cited page"


def test_number_not_in_quote_fails():
    assert "does not appear" in verify(val(value=-1600), PAGES)
