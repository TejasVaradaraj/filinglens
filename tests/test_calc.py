import pytest

from filinglens.calc import CalcError, Value, calculate, fmt


def v(id, value, unit="USD", scale="millions", period="FY2023", label="x"):
    return Value(id, label, value, unit, scale, period)


def test_scales_normalize_before_math():
    # 1,577 (millions) + 423,000 (thousands) = 2.0 billion
    r = calculate("sum", [v("a", 1577), v("b", 423_000, scale="thousands")])
    assert r.value == pytest.approx(2_000_000_000)
    assert r.text == "$2.00 billion"


def test_difference_keeps_sign():
    r = calculate("difference", [v("a", 7453), v("b", 5175)])
    assert r.value == pytest.approx(2_278e6) and r.text == "$2.28 billion"
    assert calculate("difference", [v("a", 7453), v("b", 5175)], out_scale="millions").text == "$2,278 million"


def test_percent_change_uses_abs_old_value():
    # A loss shrinking from -100 to -50 is a +50% improvement, not -50%.
    r = calculate("percent_change", [v("new", -50, period="FY2023"), v("old", -100, period="FY2022")])
    assert r.value == pytest.approx(50.0)


def test_percent_change_rejects_same_period():
    with pytest.raises(CalcError, match="two different periods"):
        calculate("percent_change", [v("a", 1), v("b", 2)])


def test_units_must_match():
    with pytest.raises(CalcError, match="units differ"):
        calculate("sum", [v("a", 1), v("b", 2, unit="shares")])


def test_ratio_across_scales():
    # quick ratio: (2,605 + 24,506) / 50,171, everything in millions
    num = calculate("sum", [v("cash", 2605), v("ar", 24506)])
    cl = v("cl", 50171)
    r = calculate("ratio", [Value("n", "quick assets", num.value, "USD", "units", "FY2022"), cl])
    assert r.value == pytest.approx(0.5404, abs=1e-4) and r.text == "0.54"


def test_percent_of_and_margin():
    r = calculate("percent_of", [v("oi", 6539), v("rev", 34229)])
    assert r.text == "19.10%"


def test_cagr():
    r = calculate("cagr", [v("end", 121), v("start", 100)], years=2)
    assert r.value == pytest.approx(10.0)


def test_per_share_and_percent_are_never_scaled():
    assert Value("e", "EPS", 6.2, "USD_per_share", "millions", "FY2023").base == 6.2
    assert Value("m", "margin", 19.1, "percent", "millions", "FY2023").base == 19.1


def test_zero_denominator():
    with pytest.raises(CalcError):
        calculate("ratio", [v("a", 1), v("b", 0)])


@pytest.mark.parametrize("x, unit, scale, text", [
    (389e6, "USD", "billions", "$0.39 billion"),
    (-1.577e9, "USD", None, "-$1.58 billion"),
    (5_466_312_000, "USD", "millions", "$5,466 million"),
    (982, "count", None, "982"),
    (6.2, "USD_per_share", None, "$6.20"),
])
def test_fmt(x, unit, scale, text):
    assert fmt(x, unit, scale) == text


def test_difference_of_percents_is_percentage_points():
    r = calculate("difference", [v("a", 19.1, unit="percent", scale="units"), v("b", 20.8, unit="percent", scale="units")])
    assert r.text == "-1.70 percentage points"
