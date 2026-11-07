"""Score an answer against the FinanceBench gold answer.

Two paths:
- Numeric gold answers (like "$1577.00" or "24.5%") are scored by code: correct
  if any number in the prediction is within 1% of the gold number. This is cheap,
  deterministic and can't be sweet-talked.
- Everything else goes to an LLM judge with a fixed rubric.

Every score is one of: correct, incorrect, refused. "Refused" is kept separate
because a refusal is a different failure from a wrong answer (a hallucination).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from filinglens import llm

TOLERANCE = 0.01
# The judge runs at medium effort: at low, it was too literal on yes/no and direction
# questions (see evals/judge_audit.json). Grading is cheap, so the extra thinking is worth it.
JUDGE_EFFORT = "medium"
JUDGE_VOTES = 3

_SCALES = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12,
           "k": 1e3, "m": 1e6, "mm": 1e6, "bn": 1e9, "b": 1e9}

# A gold answer is "numeric" if it is just one number, maybe with $, %, sign or scale word.
_NUMERIC_GOLD = re.compile(
    r"^\s*[-−]?\s*\$?\s*\(?[-−]?\d[\d,]*(\.\d+)?\)?\s*%?\s*"
    r"(thousand|million|billion|trillion)?\s*(usd)?\s*\.?\s*$",
    re.IGNORECASE,
)
_NUMBER = re.compile(
    r"(?P<neg>[-−(])?\s*\$?\s*(?P<num>\d[\d,]*(?:\.\d+)?|\.\d+)\s*(?P<pct>%)?"
    r"\s*(?P<scale>thousand|million|billion|trillion|bn|mm|k|m|b)?\b",
    re.IGNORECASE,
)
_REFUSAL = re.compile(
    r"not (?:disclosed|provided|available|stated|reported|found|possible to determine)"
    r"|cannot (?:be )?determine|can't determine|unable to determine|insufficient information"
    r"|(?:does|do|did) not (?:disclose|provide|contain|include|specify|break out|report)|no information"
    r"|not (?:in|covered by) (?:the|our|this) (?:database|filings)|no filings? (?:for|from|covering)",
    re.IGNORECASE,
)


@dataclass
class Score:
    verdict: str  # "correct" | "incorrect" | "refused"
    method: str   # "numeric" | "judge"
    reason: str = ""
    judge_cost_usd: float = 0.0


def is_numeric_answer(gold: str) -> bool:
    return bool(_NUMERIC_GOLD.match(gold))


def extract_numbers(text: str) -> list[float]:
    """All numbers in the text, with scale words applied and (1,234) read as negative."""
    values = []
    for m in _NUMBER.finditer(text):
        try:
            value = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        scale = (m.group("scale") or "").lower()
        value *= _SCALES.get(scale, 1.0)
        if m.group("neg") in ("-", "−", "("):
            value = -value
        values.append(value)
    return values


def numbers_match(gold: float, pred: float, tol: float = TOLERANCE) -> bool:
    """Within `tol` relative error. Also accepts the same number written at a
    different scale (1,577 million vs 1.577 billion) or as a fraction vs a percent
    (24.5% vs 0.245), since the question usually fixes the unit."""
    if gold == 0:
        return abs(pred) < 1e-9
    for factor in (1, 1e3, 1e-3, 1e6, 1e-6, 1e9, 1e-9, 100, 0.01):
        if abs(pred * factor - gold) / abs(gold) <= tol:
            return True
    return False


def looks_like_refusal(text: str) -> bool:
    return bool(_REFUSAL.search(text))


def score_numeric(gold: str, prediction: str) -> Score:
    gold_values = extract_numbers(gold)
    if not gold_values:
        return Score("incorrect", "numeric", "could not parse gold number")
    gold_value = gold_values[0]
    for value in extract_numbers(prediction):
        if numbers_match(gold_value, value):
            return Score("correct", "numeric", f"found {value:g} ~ {gold_value:g}")
    if looks_like_refusal(prediction):
        return Score("refused", "numeric", "prediction refuses")
    return Score("incorrect", "numeric", f"no number within 1% of {gold_value:g}")


JUDGE_SYSTEM = """You grade answers to financial-analysis questions about SEC filings.
You get the question, the gold (correct) answer, and a candidate answer.

Rules:
- "correct": the candidate reaches the same conclusion as the gold answer, and every
  number that matters agrees with gold within about 1% (rounding and units like
  "million" vs "billion" are fine if the value is the same). Extra correct detail is fine.
- "incorrect": the candidate contradicts the gold answer, gets a key number wrong,
  or misses the main point. Length or confident tone never makes an answer correct.
- For yes/no, direction ("improved or declined") or "which one" questions, grade the
  candidate's main conclusion first. If the conclusion matches gold and the numbers it
  gives are consistent with gold (even if computed a slightly different way, or labeled
  with a different but equivalent fiscal-year name), it is "correct".
- "refused": the candidate's headline answer declines or says the information is not
  disclosed/available, even if it adds some related detail afterwards.

Reply with JSON only: {"verdict": "correct" | "incorrect" | "refused", "reason": "<one sentence>"}"""


def majority(verdicts: list[str]) -> str:
    """Most common verdict; ties go to the stricter one (incorrect > refused > correct)."""
    strictness = {"incorrect": 0, "refused": 1, "correct": 2}
    return max(set(verdicts), key=lambda v: (verdicts.count(v), -strictness[v]))


def score_with_judge(question: str, gold: str, prediction: str) -> Score:
    """Ask the judge JUDGE_VOTES times and take the majority. Haiku 5.5 has no
    temperature setting, so a single call flips on borderline answers."""
    prompt = (f"Question:\n{question}\n\nGold answer:\n{gold}\n\n"
              f"Candidate answer:\n{prediction}\n\nGrade the candidate.")
    votes, cost = [], 0.0
    for _ in range(JUDGE_VOTES):
        result = llm.complete(prompt, system=JUDGE_SYSTEM, effort=JUDGE_EFFORT, max_tokens=4000)
        votes.append(parse_judge_reply(result.text))
        cost += result.cost_usd
    verdict = majority([v for v, _ in votes])
    reason = next(r for v, r in votes if v == verdict)
    split = "" if len({v for v, _ in votes}) == 1 else f" [votes: {', '.join(v for v, _ in votes)}]"
    return Score(verdict, "judge", reason + split, judge_cost_usd=cost)


def parse_judge_reply(text: str) -> tuple[str, str]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        data = {}
    verdict = str(data.get("verdict", "")).lower()
    if verdict not in {"correct", "incorrect", "refused"}:
        return "incorrect", f"unparseable judge reply: {text[:200]}"
    return verdict, str(data.get("reason", ""))


def score(question: str, gold: str, prediction: str) -> Score:
    if gold == "NOT_DISCLOSED":
        # Unanswerable question: the only correct behavior is to refuse, in the headline.
        refused = looks_like_refusal(prediction[:300])
        return Score("correct" if refused else "incorrect", "refusal",
                     "refused as expected" if refused else "answered an unanswerable question")
    if not prediction.strip():
        return Score("incorrect", "numeric", "empty answer")
    if is_numeric_answer(gold):
        return score_numeric(gold, prediction)
    return score_with_judge(question, gold, prediction)
