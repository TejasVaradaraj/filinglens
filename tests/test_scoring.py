"""Scoring must be right, or every number we report is wrong."""
import pytest

from filinglens.eval import scoring


@pytest.mark.parametrize("gold", ["$1577.00", "0.66", "24.5%", "$8.70", "-1.2%", "$1,577 million", "(370)"])
def test_numeric_gold_detected(gold):
    assert scoring.is_numeric_answer(gold)


@pytest.mark.parametrize("gold", [
    "Yes, the margins have been consistent.",
    "The entertainment segment grew 9%.",
    "FY2022 and FY2023",
])
def test_text_gold_not_numeric(gold):
    assert not scoring.is_numeric_answer(gold)


def test_extract_numbers_handles_commas_scales_and_parentheses():
    assert scoring.extract_numbers("$1,577 million") == [1_577_000_000]
    assert scoring.extract_numbers("a loss of (370)") == [-370]
    assert scoring.extract_numbers("$1.58 billion") == [1_580_000_000]


@pytest.mark.parametrize("prediction", [
    "Capex was $1,577 million in FY2018.",
    "$1.577 billion",
    "About 1,580.",              # within 1%
    "3M spent $1577.0M on PP&E",
])
def test_numeric_match_correct(prediction):
    assert scoring.score_numeric("$1577.00", prediction).verdict == "correct"


def test_numeric_outside_tolerance_is_incorrect():
    assert scoring.score_numeric("$1577.00", "Capex was $1,700 million.").verdict == "incorrect"


def test_percent_and_fraction_are_equivalent():
    assert scoring.score_numeric("24.5%", "The margin was 0.245.").verdict == "correct"


def test_refusal_detected_for_numeric_question():
    assert scoring.score_numeric("$1577.00", "Not disclosed in the provided filing.").verdict == "refused"


def test_parse_judge_reply():
    assert scoring.parse_judge_reply('{"verdict": "correct", "reason": "ok"}') == ("correct", "ok")
    assert scoring.parse_judge_reply('Sure!\n{"verdict":"REFUSED","reason":"x"}')[0] == "refused"
    assert scoring.parse_judge_reply("garbage")[0] == "incorrect"


def test_empty_answer_is_incorrect_without_calling_judge():
    assert scoring.score("q", "Yes, it grew.", "   ").verdict == "incorrect"


def test_majority_vote_and_strict_ties():
    assert scoring.majority(["correct", "correct", "incorrect"]) == "correct"
    assert scoring.majority(["correct", "refused", "incorrect"]) == "incorrect"
    assert scoring.majority(["refused", "correct"]) == "refused"


def test_not_disclosed_gold_requires_refusal():
    assert scoring.score("q", "NOT_DISCLOSED", "Not disclosed in the provided filing.").verdict == "correct"
    assert scoring.score("q", "NOT_DISCLOSED", "Tesla is not in the database, so I can't answer.").verdict == "correct"
    assert scoring.score("q", "NOT_DISCLOSED", "Revenue was $81,462 million.").verdict == "incorrect"


def test_refusal_phrasings():
    for text in ["The filing excerpts do not disclose the average credit score.",
                 "The excerpts did not break out advertising spend by platform.",
                 "Not disclosed in the provided filing."]:
        assert scoring.looks_like_refusal(text), text
