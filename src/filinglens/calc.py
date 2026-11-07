"""The calculator: every number FilingLens reports that isn't copied from a filing comes from here.

The LLM never does arithmetic. It extracts values (with unit, scale and period)
and asks for an operation on value ids; this module normalizes scales, checks
that the units make sense for the operation, computes, and formats the result.
Errors come back as messages the model can act on ("units differ: USD vs shares").
"""
from __future__ import annotations

import math
from dataclasses import dataclass

SCALES = {"units": 1, "thousands": 1_000, "millions": 1_000_000, "billions": 1_000_000_000}
UNITS = ("USD", "shares", "percent", "ratio", "count", "USD_per_share", "other")


@dataclass
class Value:
    id: str
    label: str
    value: float          # as printed in the filing, sign applied: (1,577) -> -1577
    unit: str             # one of UNITS
    scale: str            # one of SCALES (what the filing's "in millions" etc. says)
    period: str           # e.g. "FY2022", "Q2 FY2024", "as of 2022-12-31"
    doc: str = ""
    page: int = -1

    @property
    def base(self) -> float:
        """Value in base units (dollars, shares). Percent/ratio/per-share are never scaled."""
        if self.unit in ("percent", "ratio", "USD_per_share"):
            return self.value
        return self.value * SCALES[self.scale]


class CalcError(ValueError):
    pass


@dataclass
class Result:
    operation: str
    value: float
    unit: str             # unit of the result
    text: str             # human-readable, e.g. "$1.58 billion" or "4.6%"
    formula: str          # e.g. "(Revenue FY2023 - Revenue FY2022) / |Revenue FY2022| x 100"
    inputs: list[str]


def _same_unit(values: list[Value], op: str) -> str:
    units = {v.unit for v in values}
    if len(units) > 1:
        raise CalcError(f"{op}: units differ ({', '.join(sorted(units))}); convert or pick matching values")
    return units.pop()


def _two(values: list[Value], op: str) -> tuple[Value, Value]:
    if len(values) != 2:
        raise CalcError(f"{op} needs exactly 2 values, got {len(values)}")
    return values[0], values[1]


def fmt(x: float, unit: str, out_scale: str | None = None) -> str:
    """Format a base-unit number for an answer: $1.58 billion, 1,577 million shares, 4.6%."""
    if unit == "percent":
        return f"{x:.2f}%".replace(".00%", "%")
    if unit == "ratio":
        return f"{x:.2f}"
    if unit == "USD_per_share":
        return f"${x:,.2f}" if x >= 0 else f"-${-x:,.2f}"
    names = {"billions": "billion", "millions": "million", "thousands": "thousand", "units": ""}
    if out_scale is None:
        a = abs(x)
        out_scale = "billions" if a >= 1e9 else "millions" if a >= 1e6 else "thousands" if a >= 1e4 else "units"
    scaled = x / SCALES[out_scale]
    digits = 2 if abs(scaled) < 100 else 0 if abs(scaled) >= 1000 else 1
    if float(scaled).is_integer() and out_scale == "units":
        digits = 0  # 982 stores, not 982.0
    num = f"{abs(scaled):,.{digits}f}"
    sign = "-" if x < 0 else ""
    word = f" {names[out_scale]}" if names[out_scale] else ""
    if unit == "USD":
        return f"{sign}${num}{word}"
    suffix = {"shares": " shares", "count": ""}.get(unit, "")
    return f"{sign}{num}{word}{suffix}"


def calculate(operation: str, values: list[Value], years: float | None = None,
              out_scale: str | None = None) -> Result:
    if not values:
        raise CalcError("no values given")
    labels = [f"{v.label} {v.period}".strip() for v in values]
    ids = [v.id for v in values]

    if operation in ("sum", "average"):
        unit = _same_unit(values, operation)
        total = math.fsum(v.base for v in values)
        x = total if operation == "sum" else total / len(values)
        formula = " + ".join(labels) if operation == "sum" else f"({' + '.join(labels)}) / {len(values)}"
        return Result(operation, x, unit, fmt(x, unit, out_scale), formula, ids)

    if operation == "difference":
        a, b = _two(values, operation)
        unit = _same_unit([a, b], operation)
        x = a.base - b.base
        text = f"{x:+.2f} percentage points" if unit == "percent" else fmt(x, unit, out_scale)
        return Result(operation, x, unit, text, f"{labels[0]} - {labels[1]}", ids)

    if operation == "ratio":
        a, b = _two(values, operation)
        if b.base == 0:
            raise CalcError("ratio: denominator is zero")
        x = a.base / b.base
        return Result(operation, x, "ratio", f"{x:.2f}", f"{labels[0]} / {labels[1]}", ids)

    if operation == "percent_of":
        a, b = _two(values, operation)
        if a.unit != b.unit:
            raise CalcError(f"percent_of: units differ ({a.unit} vs {b.unit})")
        if b.base == 0:
            raise CalcError("percent_of: whole is zero")
        x = a.base / b.base * 100
        return Result(operation, x, "percent", fmt(x, "percent"), f"{labels[0]} / {labels[1]} x 100", ids)

    if operation == "percent_change":
        new, old = _two(values, operation)
        _same_unit([new, old], operation)
        if new.period == old.period:
            raise CalcError(f"percent_change: both values are for {new.period}; need two different periods")
        if old.base == 0:
            raise CalcError("percent_change: old value is zero")
        x = (new.base - old.base) / abs(old.base) * 100
        return Result(operation, x, "percent", fmt(x, "percent"),
                      f"({labels[0]} - {labels[1]}) / |{labels[1]}| x 100", ids)

    if operation == "cagr":
        end, start = _two(values, operation)
        _same_unit([end, start], operation)
        if not years or years <= 0:
            raise CalcError("cagr: give the number of years between the two values")
        if start.base <= 0 or end.base <= 0:
            raise CalcError("cagr: both values must be positive")
        x = ((end.base / start.base) ** (1 / years) - 1) * 100
        return Result(operation, x, "percent", fmt(x, "percent"),
                      f"({labels[0]} / {labels[1]})^(1/{years:g}) - 1", ids)

    raise CalcError(f"unknown operation {operation!r}")


OPERATIONS = ("sum", "average", "difference", "ratio", "percent_of", "percent_change", "cagr")
