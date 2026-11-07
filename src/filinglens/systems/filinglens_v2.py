"""FilingLens v2 (Phase 4): extracted values + Python calculator + answer writer.

1. Retrieve pages exactly like v1.
2. Extract the needed numbers as typed values (structured outputs); drop any value
   whose quote or digits aren't on its cited page.
3. The answer writer sees the verified values and the pages, and can only do math by
   calling the `calculate` tool on value ids. Python computes; results get ids r1, r2...
   that can be used in later calculations.
4. The final answer cites value/result ids; notes keep the full "show work" record.
"""
from __future__ import annotations

import json

from filinglens import llm
from filinglens.calc import OPERATIONS, SCALES, CalcError, Value, calculate
from filinglens.dataset import Question
from filinglens.extract import extract
from filinglens.systems.base import SystemAnswer
from filinglens.systems.filinglens_v1 import retrieve

MAX_TURNS = 6

CALC_TOOL = {
    "name": "calculate",
    "description": ("Do arithmetic on extracted values (v1, v2, ...) or earlier results (r1, r2, ...). "
                    "Scales (thousands/millions/billions) are normalized automatically. "
                    "percent_change and cagr take [new, old]; ratio and percent_of take [numerator, denominator]; "
                    "difference takes [a, b] and returns a - b."),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": list(OPERATIONS)},
            "value_ids": {"type": "array", "items": {"type": "string"}},
            "years": {"anyOf": [{"type": "number"}, {"type": "null"}], "description": "only for cagr"},
            "out_scale": {"anyOf": [{"type": "string", "enum": list(SCALES)}, {"type": "null"}],
                          "description": "scale to express a USD/shares result in, if the question asks for one"},
        },
        "required": ["operation", "value_ids", "years", "out_scale"],
        "additionalProperties": False,
    },
}

ANSWER_SYSTEM = """You are a financial analyst answering a question about SEC filings.
You get VERIFIED VALUES (copied from the filing and checked against the page) and the excerpts.

Rules:
- Never do arithmetic yourself. For any sum, difference, ratio, percentage, growth rate or
  average, call the `calculate` tool with value ids. Use only numbers from the verified
  values or from tool results.
- Cite every number with its id in brackets, e.g. "capex was $1,577 million [v1]" or
  "a quick ratio of 0.54 [r2]".
- Use standard analyst definitions unless the question gives one: quick ratio = (cash and
  equivalents + short-term investments + receivables) / current liabilities; working capital =
  current assets - current liabilities; operating margin = operating income / revenue; gross
  margin = gross profit / revenue; capex intensity = capex / revenue; effective tax rate =
  income tax expense / pre-tax income (a tax benefit on a pre-tax loss gives a positive rate).
- Answer the question directly first. If it asks yes/no or improved/declined, start with
  that word and commit to it based on the numbers; mention caveats after, briefly.
- If the question asks for a unit ("in USD billions"), give the result in that unit.
- Questions that aren't about numbers (customers, geographies, risks, listed securities,
  events) are answered from the excerpts directly; they need no values.
- Only if the excerpts truly don't contain what's needed, answer
  "Not disclosed in the provided filing." and say what is missing.
- Keep it to 2-4 sentences."""


def _values_table(values: list[Value], quotes: dict[str, str]) -> str:
    return "\n".join(
        f"{v.id}: {v.label} | {v.period} | {v.value:g} ({v.unit}, {v.scale}) | {v.doc} p{v.page} | \"{quotes[v.id][:160]}\""
        for v in values) or "(none)"


def answer(question: Question) -> SystemAnswer:
    r = retrieve(question.question)
    ex = extract(question.question, r.excerpts, r.texts)
    cost = r.plan.cost_usd + ex.cost_usd
    known: dict[str, Value] = {v.id: v for v in ex.values}
    calcs: list[dict] = []

    # The extractor's "missing" note is kept in notes but not shown to the answer writer:
    # in the first v2 run it primed refusals on questions the excerpts could answer.
    user = (f"VERIFIED VALUES:\n{_values_table(ex.values, ex.quotes)}\n\n"
            f"Filing excerpts:\n\n{r.excerpts}\n\nQuestion: {question.question}")
    messages: list = [{"role": "user", "content": user}]
    text, in_tok, out_tok = "", 0, 0
    for _ in range(MAX_TURNS):
        response, c = llm.chat(messages, ANSWER_SYSTEM, [CALC_TOOL])
        cost += c
        in_tok += response.usage.input_tokens
        out_tok += response.usage.output_tokens
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            break
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for tu in tool_uses:
            args = tu.input
            try:
                vals = [known[i] for i in args["value_ids"]]
                res = calculate(args["operation"], vals, years=args.get("years"), out_scale=args.get("out_scale"))
                rid = f"r{len(calcs) + 1}"
                # Results are stored in base units so they can feed later calculations.
                known[rid] = Value(rid, res.formula, res.value, res.unit, "units",
                                   "/".join(sorted({v.period for v in vals})))
                calcs.append({"id": rid, "operation": res.operation, "inputs": res.inputs,
                              "formula": res.formula, "value": res.value, "text": res.text})
                content, is_error = json.dumps({"id": rid, "result": res.text, "formula": res.formula}), False
            except KeyError as e:
                content, is_error = f"Unknown id {e}. Use ids from VERIFIED VALUES or earlier results.", True
            except CalcError as e:
                content, is_error = str(e), True
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": content, "is_error": is_error})
        messages.append({"role": "user", "content": results})
    else:
        text = "Not disclosed in the provided filing. (Stopped: too many calculation steps.)"

    return SystemAnswer(text, cost, in_tok, out_tok, retrieved_pages=r.pages, notes={
        "values": [{**v.__dict__, "quote": ex.quotes[v.id], "repaired_from": ex.repaired.get(v.id)}
                   for v in ex.values],
        "dropped_values": ex.dropped, "calculations": calcs, "missing": ex.missing,
        "company": r.plan.company, "query": r.query,
    })
