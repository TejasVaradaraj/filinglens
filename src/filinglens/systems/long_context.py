"""Baseline B: put the whole filing in the prompt.

Simple, slow and expensive: a 10-K is often over 100K tokens, which moves the
call to Haiku's higher long-context price. Haiku 5.5's 1M-token window fits
any single filing, so nothing is truncated.
"""
from filinglens import llm
from filinglens.dataset import Question
from filinglens.pdf_text import page_texts
from filinglens.systems.base import ANSWER_SYSTEM_PROMPT, SystemAnswer


def answer(question: Question) -> SystemAnswer:
    pages = page_texts(question.doc_name)
    filing = "\n\n".join(f"[page {i}]\n{text}" for i, text in enumerate(pages))
    prompt = (f"Here is the full filing {question.doc_name}:\n\n{filing}\n\n"
              f"Question: {question.question}")
    result = llm.complete(prompt, system=ANSWER_SYSTEM_PROMPT)
    return SystemAnswer(result.text, result.cost_usd, result.input_tokens, result.output_tokens,
                        notes={"pages_in_prompt": len(pages)})
