"""FilingLens v4 (Phase 6): v3 with LLM-reranked retrieval.

Failure analysis on v3: 17 of 38 dev failures were retrieval (14 right filing / wrong page).
The keyword-20 + vector-20 pool holds the gold page for 98/100 questions; Haiku reranking
it raises gold-page-in-final-5 from 76 to 85.
"""
from __future__ import annotations

from filinglens import tracing
from filinglens.dataset import Question
from filinglens.systems.base import SystemAnswer
from filinglens.systems.filinglens_v2 import run_pipeline
from filinglens.systems.filinglens_v3 import scope_refusal


def answer(question: Question, emit=None) -> SystemAnswer:
    with tracing.span("scope_gate"):
        refusal, cost = scope_refusal(question.question)
    if refusal:
        if emit:
            emit("answer", {"text": refusal, "scope_gate": True})
        return SystemAnswer(refusal, cost, notes={"scope_gate": True})
    return run_pipeline(question, verify_answer=True, emit=emit, rerank=True)
