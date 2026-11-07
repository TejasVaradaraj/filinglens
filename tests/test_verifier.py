from filinglens.calc import Value
from filinglens.verifier import check, numbers_in

KNOWN = {
    "v1": Value("v1", "Cash", 2605, "USD", "millions", "FY2022"),
    "v2": Value("v2", "Receivables", 24506, "USD", "millions", "FY2022"),
    "v3": Value("v3", "Current liabilities", 50171, "USD", "millions", "FY2022"),
    "r1": Value("r1", "quick ratio", 0.5404, "ratio", "units", "FY2022"),
    "v4": Value("v4", "Capex", -1577, "USD", "millions", "FY2018"),
    "v5": Value("v5", "Margin", 19.1, "percent", "units", "FY2022"),
}


def test_supported_answer_passes():
    a = ("**No.** Verizon's FY2022 quick ratio is 0.54 [r1]: cash of $2,605 million [v1] plus "
         "receivables of $24,506 million [v2] over current liabilities of $50,171 million [v3], below 1.0.")
    r = check(a, KNOWN)
    assert r.unsupported == [] and r.precision == 1.0 and len(r.checks) == 4


def test_rescaled_and_negative_numbers_match():
    r = check("Capex was $1.58 billion [v4] in 2018, an outflow of (1,577) [v4].", KNOWN)
    assert r.unsupported == []


def test_invented_number_is_flagged():
    r = check("The quick ratio is 0.54 [r1] and revenue was $136.8 billion.", KNOWN)
    assert [c.text for c in r.unsupported] == ["$136.8 billion"]
    assert r.precision == 0.5


def test_wrong_citation_is_flagged():
    r = check("Cash was $3,100 million [v1].", KNOWN)
    assert r.unsupported and "does not match v1" in r.unsupported[0].reason


def test_unknown_id_is_flagged():
    assert "unknown id" in check("Debt was $9 billion [v9].", KNOWN).unsupported[0].reason


def test_years_quarters_items_and_citation_ids_are_ignored():
    nums = [t for t, _, _ in numbers_in("In FY2023 Q2, per Item 7 on p59 [v1, v2], margins in 2021 and 2022 rose.")]
    assert nums == []


def test_percent_values_match():
    assert check("Operating margin was 19.1% [v5].", KNOWN).unsupported == []


def test_refusal_has_nothing_to_check():
    assert check("Not disclosed in the provided filing. Revenue of $5 billion is not shown.", KNOWN).checks == []


def test_names_dates_and_codes_are_not_numbers():
    nums = [t for t, *_ in numbers_in("3M's notes due June 30 (MMM26) and the 10K filing; Boeing 737MAX.")]
    assert nums == []


def test_rounded_prose_matches_at_written_precision():
    known = {"r4": Value("r4", "margin change", -1.7, "percent", "units", "")}
    assert check("Margin fell about 2 percentage points [r4].", known).unsupported == []
    assert check("Margin fell 2.5 percentage points [r4].", known).unsupported != []


def test_page_backed_numbers_pass_but_invented_ones_fail():
    pages = ["|3.625% Notes due 2026|500|", "Approximately 76% of revenue came from the U.S."]
    r = check("The 3.625% notes [v1]... about 76% of revenue, and 88% elsewhere.", KNOWN, pages)
    assert [c.reason for c in r.checks] == ["page", "page", "no source value, calculation or page"]
