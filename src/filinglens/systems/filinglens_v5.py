"""FilingLens v5 (Phase 7): multi-company questions by decomposition.

v4's planner filters retrieval to ONE company, so "Coca-Cola vs PepsiCo" questions only ever
see one company's filings (cross-company baseline: 1/12). v5:
1. decompose: if the question names 2+ companies, split it into one sub-question per company
   (cheap structured call). Otherwise run v4 unchanged.
2. run each sub-question through the full v4 pipeline in parallel (threads): scope gate,
   reranked retrieval, verified extraction, calculator, citation check.
3. merge: renumber every verified value (v1..vN across all sub-answers) and composed results.
4. compose: the answer writer sees the merged values and the sub-answers and can only do math
   with the `calculate` tool; the final answer goes through the citation checker.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

from filinglens import llm, tracing
from filinglens.calc import Value
from filinglens.dataset import Question
from filinglens.systems import filinglens_v4
from filinglens.systems.base import SystemAnswer
from filinglens.systems.filinglens_v2 import _tool_loop, _values_table
from filinglens.verifier import check, repair_prompt

DECOMPOSE_SYSTEM = """You split questions about SEC filings that involve more than one company.
If the question compares or combines two or more companies, return one sub-question per company
that asks only for that company's numbers needed, keeping the fiscal years and metric names.
If it is about a single company (even across several years), return an empty list.
JSON only: {"subquestions": [{"company": "<name>", "question": "<self-contained question>"}]}"""

DECOMPOSE_SCHEMA = {
    "type": "object",
    "properties": {"subquestions": {"type": "array", "items": {
        "type": "object", "properties": {"company": {"type": "string"}, "question": {"type": "string"}},
        "required": ["company", "question"], "additionalProperties": False}}},
    "required": ["subquestions"], "additionalProperties": False,
}

COMPOSE_NOTE = """This question was split by company. The sub-answers below were produced from each
company's own filings; their numbers are listed as VERIFIED VALUES with the ids to cite.
Combine them to answer the original question. Use `calculate` for any comparison math."""


def decompose(question: str) -> tuple[list[dict], float]:
    r = llm.complete(f"Question: {question}", system=DECOMPOSE_SYSTEM, json_schema=DECOMPOSE_SCHEMA,
                     max_tokens=1500)
    subs = json.loads(r.text)["subquestions"]
    return (subs if len(subs) >= 2 else []), r.cost_usd


def _renumber(text: str, mapping: dict[str, str]) -> str:
    return re.sub(r"\[((?:[vr]\d+)(?:\s*,\s*[vr]\d+)*)\]",
                  lambda m: "[" + ", ".join(mapping.get(i.strip(), i.strip()) for i in m.group(1).split(",")) + "]",
                  text)


def answer(question: Question, emit=None) -> SystemAnswer:
    with tracing.span("decompose"):
        subs, cost = decompose(question.question)
    if not subs:
        result = filinglens_v4.answer(question, emit=emit)
        result.cost_usd += cost
        return result
    if emit:
        emit("plan", {"company": " + ".join(s["company"] for s in subs), "fiscal_years": [],
                      "query": " | ".join(s["question"] for s in subs)})

    parent = tracing._current.get()

    def run_sub(i_sub):
        i, sub = i_sub
        q = Question(id=f"{question.id}_s{i}", company=sub["company"], doc_name="", question_type="sub",
                     question=sub["question"], answer="")
        # Each thread starts with an empty context; attach its span to the parent trace by hand.
        with tracing.trace(f"sub{i}") as t:
            res = filinglens_v4.answer(q)
        if parent is not None:
            parent.children.append(t)
        return res

    with ThreadPoolExecutor(len(subs)) as pool:
        results = list(pool.map(run_sub, enumerate(subs, 1)))

    # Merge every sub-answer's verified values into one id space: v1..vN.
    known: dict[str, Value] = {}
    quotes: dict[str, str] = {}
    sub_texts, pages, page_texts = [], [], []
    for sub, res in zip(subs, results):
        cost += res.cost_usd
        mapping = {}
        for v in (res.notes or {}).get("values", []):
            new = f"v{len(known) + 1}"
            mapping[v["id"]] = new
            known[new] = Value(new, f"{sub['company']}: {v['label']}", v["value"], v["unit"], v["scale"],
                               v["period"], v["doc"], v["page"])
            quotes[new] = v["quote"]
        for c in (res.notes or {}).get("calculations", []):
            new = f"v{len(known) + 1}"  # a sub-answer's calculator result becomes a citable value here
            mapping[c["id"]] = new
            known[new] = Value(new, f"{sub['company']}: {c['formula']}", c["value"], c.get("unit", "USD"),
                               "units", "")
            quotes[new] = f"calculated: {c['formula']} = {c['text']}"
        sub_texts.append(f"[{sub['company']}] {sub['question']}\n{_renumber(res.text, mapping)}")
        pages += res.retrieved_pages
    if emit:
        emit("values", [{"id": i, "label": v.label, "value": v.value, "unit": v.unit, "scale": v.scale,
                         "period": v.period, "doc": v.doc, "page": v.page, "quote": quotes[i]}
                        for i, v in known.items()])

    with tracing.span("compose"):
        user = (f"{COMPOSE_NOTE}\n\nVERIFIED VALUES:\n{_values_table(list(known.values()), quotes)}\n\n"
                "SUB-ANSWERS:\n" + "\n\n".join(sub_texts) + f"\n\nOriginal question: {question.question}")
        messages = [{"role": "user", "content": user}]
        calcs: list[dict] = []
        text, c, in_tok, out_tok = _tool_loop(messages, known, calcs, emit)
        cost += c
        page_texts = [s for s in sub_texts]  # sub-answers are the composer's only sources besides values
        report = check(text, known, page_texts)
        if report.unsupported:
            messages.append({"role": "user", "content": repair_prompt(report)})
            new_text, c2, i2, o2 = _tool_loop(messages, known, calcs, emit)
            cost += c2
            new_report = check(new_text, known, page_texts)
            if len(new_report.unsupported) <= len(report.unsupported):
                text, report = new_text, new_report
    if emit:
        emit("answer", {"text": text})
        emit("citations", {"precision": report.precision,
                           "numbers": [{"text": x.text, "ok": x.ok, "source": x.reason} for x in report.checks]})
    return SystemAnswer(text, cost, in_tok, out_tok, retrieved_pages=pages, notes={
        "decomposed": [s["question"] for s in subs], "sub_answers": [r.text for r in results],
        "values": [{**v.__dict__, "quote": quotes.get(i, "calculated in Python")} for i, v in known.items()],
        "calculations": calcs,
        "citation_check": {"precision": report.precision, "repair_round": False,
                           "numbers": [{"text": x.text, "ok": x.ok, "reason": x.reason} for x in report.checks]},
    })
