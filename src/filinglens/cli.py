"""Ask FilingLens from the terminal and watch it work.

    python -m filinglens.cli "What was 3M's FY2018 capex in USD millions?"
"""
from __future__ import annotations

import sys
import time

from filinglens.dataset import Question
from filinglens.systems import filinglens_v4 as system

BOLD, DIM, GREEN, RED, RESET = "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[0m"


def show(event: str, data) -> None:
    if event == "plan":
        years = ", ".join(f"FY{y}" for y in data["fiscal_years"]) or "any year"
        print(f"{DIM}plan     {data['company']} | {years} | search: {data['query']}{RESET}")
    elif event == "retrieval":
        print(f"{DIM}pages    " + ", ".join(f"{p['doc']} p{p['page']}" for p in data["pages"]) + RESET)
    elif event == "values":
        for v in data:
            print(f"{DIM}value    [{v['id']}] {v['label']} {v['period']} = {v['value']:g} "
                  f"({v['unit']}, {v['scale']}) <- {v['doc']} p{v['page']}{RESET}")
    elif event == "calculation":
        print(f"{DIM}calc     [{data['id']}] {data['formula']} = {data['text']}{RESET}")
    elif event == "repair":
        print(f"{DIM}repair   unsupported numbers: {', '.join(data['unsupported'])}{RESET}")
    elif event == "answer":
        print(f"\n{BOLD}{data['text']}{RESET}\n")
    elif event == "citations":
        nums = data["numbers"]
        ok = sum(n["ok"] for n in nums)
        color = GREEN if ok == len(nums) else RED
        print(f"{color}citations {ok}/{len(nums)} numbers traced to a value, calculation or page{RESET}")
        for n in nums:
            if not n["ok"]:
                print(f"{RED}  unsupported: {n['text']} ({n['source']}){RESET}")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    question = " ".join(sys.argv[1:])
    start = time.perf_counter()
    result = system.answer(Question(id="cli", company="", doc_name="", question_type="cli",
                                           question=question, answer=""), emit=show)
    print(f"{DIM}${result.cost_usd:.4f} | {time.perf_counter() - start:.1f}s{RESET}")


if __name__ == "__main__":
    main()
