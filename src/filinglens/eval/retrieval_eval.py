"""Retrieval-only eval: does the gold evidence page show up in the top k?

Usage:
    python -m filinglens.eval.retrieval_eval --split dev --searchers keyword vector hybrid \
        --filters none company period

Prints an ablation table of recall@k (exact page and page±1) and filing-level recall.
Planner outputs are cached in data/cache/plans.json, so re-runs cost nothing.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor

from filinglens import config
from filinglens.dataset import Question, load_split
from filinglens.retrieval.planner import Plan, candidate_filings, plan
from filinglens.retrieval.search import SEARCHERS

KS = (1, 5, 10)
PLAN_CACHE = config.CACHE_DIR / "plans_v2.json"  # v2: plans include search_query


def cached_plans(questions: list[Question]) -> dict[str, Plan]:
    cache = json.loads(PLAN_CACHE.read_text()) if PLAN_CACHE.exists() else {}
    todo = [q for q in questions if q.id not in cache]
    with ThreadPoolExecutor(6) as pool:
        for q, p in zip(todo, pool.map(lambda q: plan(q.question), todo)):
            cache[q.id] = p.model_dump()
    PLAN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    PLAN_CACHE.write_text(json.dumps(cache, indent=1))
    return {q.id: Plan(**cache[q.id]) for q in questions}


def page_hit(gold: set[tuple[str, int]], hits, k: int, slack: int = 0) -> bool:
    return any((h.doc_name, p) in gold for h in hits[:k] for p in range(h.page_num - slack, h.page_num + slack + 1))


def query_for(q: Question, p: Plan, mode: str) -> str:
    """raw = the question as asked; rewrite = planner's query; both = question + rewrite."""
    return {"raw": q.question, "rewrite": p.search_query or q.question,
            "both": f"{q.question} {p.search_query}"}[mode]


def evaluate(questions, plans, searcher: str, filt: str, query: str = "raw") -> dict:
    fn = SEARCHERS[searcher]

    def one(q):
        hits = fn(query_for(q, plans[q.id], query), max(KS), candidate_filings(plans[q.id], filt))
        gold = {(e.doc_name, e.evidence_page_num) for e in q.evidence}
        return {
            **{f"page@{k}": page_hit(gold, hits, k) for k in KS},
            **{f"page±1@{k}": page_hit(gold, hits, k, 1) for k in KS},
            "filing@5": any(h.doc_name in {d for d, _ in gold} for h in hits[:5]),
        }

    with ThreadPoolExecutor(4) as pool:
        rows = list(pool.map(one, questions))
    return {m: round(100 * sum(r[m] for r in rows) / len(rows)) for m in rows[0]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default="dev")
    ap.add_argument("--searchers", nargs="+", default=list(SEARCHERS))
    ap.add_argument("--filters", nargs="+", default=["none", "company", "period"])
    ap.add_argument("--queries", nargs="+", default=["raw"], choices=["raw", "rewrite", "both"])
    args = ap.parse_args()
    questions = load_split(args.split)
    plans = cached_plans(questions)
    planner_cost = sum(p.cost_usd for p in plans.values())
    print(f"{len(questions)} questions; planner picked a company for "
          f"{sum(1 for p in plans.values() if p.company)}; planner cost ${planner_cost:.4f}\n")
    cols = ["page@1", "page@5", "page@10", "page±1@5", "filing@5"]
    print("| searcher | filter | query | " + " | ".join(cols) + " |")
    print("|---|---|---|" + "---:|" * len(cols))
    for s in args.searchers:
        for f in args.filters:
            for qm in args.queries:
                r = evaluate(questions, plans, s, f, qm)
                print(f"| {s} | {f} | {qm} | " + " | ".join(f"{r[c]}%" for c in cols) + " |", flush=True)


if __name__ == "__main__":
    main()
