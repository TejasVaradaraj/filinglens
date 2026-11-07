"""Check the final answer: every number in it must come from a verified value or a
calculator result.

- A number followed by citations like "[v3]" or "[r1, v2]" must match one of those
  ids within rounding (the writer may round $1,577.4 million to $1.58 billion).
- An uncited number must still match some known value or result.
- Years (1990-2039), small counts used in prose ("two segments", "Item 7") and
  the 1.0 benchmark in ratio talk are allowed without a source.
Returns the unsupported numbers so the writer can be asked to fix them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from filinglens.calc import SCALES, Value

_CITE = re.compile(r"\[((?:[vr]\d+)(?:\s*,\s*[vr]\d+)*)\]")
_NUM = re.compile(
    r"(?P<neg>[-−(])?\$?\s*(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*\)?\s*"
    r"(?P<pct>%|percent(?:age points?)?|pp\b|bps?\b)?\s*(?P<scale>billion|million|thousand|bn\b|mm\b|[mb]\b)?",
    re.IGNORECASE,
)
_SCALE_WORD = {"billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mm": 1e6, "m": 1e6, "thousand": 1e3}
ALLOWED_PLAIN = {0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 12.0, 100.0}
REL_TOL = 0.006  # rounding: 1,577 -> 1.58 billion is 0.2%; 0.5389 -> 0.54 is 0.2%


@dataclass
class NumberCheck:
    text: str
    value: float
    cited: list[str]
    ok: bool
    reason: str = ""


@dataclass
class Report:
    checks: list[NumberCheck] = field(default_factory=list)

    @property
    def unsupported(self) -> list[NumberCheck]:
        return [c for c in self.checks if not c.ok]

    @property
    def precision(self) -> float:
        """Share of numbers in the answer that trace to a value or result (1.0 if no numbers)."""
        return 1.0 if not self.checks else sum(c.ok for c in self.checks) / len(self.checks)


def _candidates(v: Value) -> list[float]:
    """Ways a known value can legitimately appear in prose."""
    out = [v.value, abs(v.value)]
    if v.unit not in ("percent", "ratio", "USD_per_share"):
        base = v.base
        out += [base, abs(base)]
    if v.unit == "ratio":  # 0.54 can also be written 54%
        out += [v.value * 100, abs(v.value) * 100]
    return out


def _matches(x: float, v: Value, step: float = 0.0) -> bool:
    """x matches v within rounding. `step` is the precision the answer wrote x at
    (e.g. 0.01 for "1.58 billion" -> 1e7 after scaling), so "about 2 points" for 1.7 is fine."""
    for c in _candidates(v):
        if c == 0:
            if abs(x) < 1e-9:
                return True
            continue
        if abs(abs(x) - abs(c)) <= max(REL_TOL * abs(c), step / 2 + 1e-12):
            return True
    return False


_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"


def _on_page(raw: str, pages: list[str]) -> bool:
    digits = raw.replace(",", "")
    return any(raw in p or (len(digits) >= 2 and re.search(rf"(?<![\d.]){re.escape(digits)}(?![\d])", p.replace(",", "")))
               for p in pages)


def numbers_in(answer: str) -> list[tuple[str, float, list[str], float, str]]:
    """(matched text, value, cited ids, rounding step, raw digits) for each number in the answer."""
    found = []
    for m in _NUM.finditer(answer):
        raw = m.group("num")
        start, end = m.start("num"), m.end("num")
        if re.fullmatch(r"(19[9]\d|20[0-3]\d)", raw) and not m.group("pct") and not m.group("scale"):
            continue  # a year
        before = answer[max(0, start - 6):start]
        if re.search(r"[vrpQ]$|FY$|Item\s?$", before, re.IGNORECASE) or before.endswith("["):
            continue  # citation ids [v3], page refs p59, Q2, FY2023, Item 7
        if (start > 0 and answer[start - 1].isalpha()) or (end < len(answer) and answer[end].isalpha()):
            continue  # part of a name or code: 3M, MMM26, 10-K's 10K, 737MAX
        if re.search(_MONTHS + r"\s*$", answer[max(0, start - 12):start], re.IGNORECASE):
            continue  # a date: June 30, Dec. 31
        scale = (m.group("scale") or "").lower()
        if scale in ("m", "b") and "$" not in m.group(0):
            scale = ""  # a bare m/b only means million/billion right after a dollar amount
        x = float(raw.replace(",", ""))
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        step = 10.0 ** -decimals
        if scale in _SCALE_WORD:
            x *= _SCALE_WORD[scale]
            step *= _SCALE_WORD[scale]
        if m.group("neg") in ("-", "−", "("):
            x = -x
        tail = answer[m.end():m.end() + 40]
        cite = _CITE.match(tail.lstrip(" *.,;:)")) or _CITE.search(tail[:25])
        cited = [c.strip() for c in cite.group(1).split(",")] if cite else []
        found.append((m.group(0).strip(), x, cited, step, raw))
    return found


def check(answer: str, known: dict[str, Value], pages: list[str] | None = None) -> Report:
    """Value-backed: matches a verified value / calculator result (the cited one if cited).
    Page-backed: not a value, but the number appears verbatim on a provided page.
    Anything else is unsupported."""
    report = Report()
    pages = pages or []
    if answer.lower().lstrip("*").startswith("not disclosed"):
        return report
    for text, x, cited, step, raw in numbers_in(answer):
        if abs(x) in ALLOWED_PLAIN and not cited:
            continue
        if cited and (missing := [c for c in cited if c not in known]):
            report.checks.append(NumberCheck(text, x, cited, False, f"cites unknown id {missing[0]}"))
        elif cited and any(_matches(x, known[c], step) for c in cited):
            report.checks.append(NumberCheck(text, x, cited, True, "value"))
        elif any(_matches(x, v, step) for v in known.values()):
            report.checks.append(NumberCheck(text, x, cited, True, "value (different id than cited)" if cited else "value"))
        elif _on_page(raw, pages):
            report.checks.append(NumberCheck(text, x, cited, True, "page"))
        else:
            reason = f"does not match {', '.join(cited)}" if cited else "no source value, calculation or page"
            report.checks.append(NumberCheck(text, x, cited, False, reason))
    return report


def repair_prompt(report: Report) -> str:
    lines = [f"- {c.text}: {c.reason}" for c in report.unsupported]
    return ("Some numbers in your answer are not supported by the verified values or calculator results:\n"
            + "\n".join(lines)
            + "\nRewrite the answer so every number is copied from a value or computed with the "
              "`calculate` tool, with its [id]. Remove any number you cannot support.")


__all__ = ["check", "repair_prompt", "Report", "SCALES"]
