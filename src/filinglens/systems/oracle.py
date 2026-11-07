"""Oracle: give the model exactly the gold evidence pages.

Not a real system (it peeks at the answer key's page numbers). It is the
ceiling for "perfect retrieval": if the oracle gets a question wrong, the
problem is reading or math, not finding the page.
"""
import os

from filinglens import llm
from filinglens.dataset import Question
from filinglens.parsing.extractors import extract_pages
from filinglens.systems.base import ANSWER_SYSTEM_PROMPT, SystemAnswer

# Which extractor turns the gold pages into text. Set ORACLE_PARSER to compare parsers.
PARSER = os.getenv("ORACLE_PARSER", "pymupdf")


def answer(question: Question) -> SystemAnswer:
    pages = sorted({(e.doc_name, e.evidence_page_num) for e in question.evidence})
    excerpts = "\n\n".join(
        f"[{doc} | page {num}]\n{extract_pages(PARSER, doc, [num])[0][num]}" for doc, num in pages
    )
    prompt = f"Filing excerpts:\n\n{excerpts}\n\nQuestion: {question.question}"
    result = llm.complete(prompt, system=ANSWER_SYSTEM_PROMPT)
    return SystemAnswer(result.text, result.cost_usd, result.input_tokens, result.output_tokens,
                        retrieved_pages=pages, notes={"parser": PARSER})
