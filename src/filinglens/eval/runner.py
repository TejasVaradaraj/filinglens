"""Run a system over a split, score every answer, and save the results.

Usage:
    python -m filinglens.eval.runner --system long_context --split dev --limit 20

Each run gets its own folder under data/runs/ with:
    results.jsonl   one line per question (answer, score, cost, latency)
    summary.json    totals and accuracy by question type
Re-running with --resume <run_dir> skips questions that already have a result.
"""
from __future__ import annotations

import argparse
import json
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from filinglens import config, tracing
from filinglens.dataset import Question, load_split
from filinglens.eval import scoring
from filinglens.systems import get_system


def run_one(system, question: Question) -> dict:
    start = time.perf_counter()
    with tracing.trace("question") as t:
        try:
            answer = system(question)
            error = None
        except Exception as exc:  # one bad question must not kill the whole run
            answer, error = None, f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"
    latency = time.perf_counter() - start

    if answer is None:
        score = scoring.Score("incorrect", "error", error or "")
        text, cost, retrieved, notes, tokens = "", 0.0, [], {}, (0, 0)
    else:
        score = scoring.score(question.question, question.answer, answer.text)
        text, cost = answer.text, answer.cost_usd
        retrieved, notes = answer.retrieved_pages, answer.notes
        tokens = (answer.input_tokens, answer.output_tokens)

    gold_pages = sorted({(e.doc_name, e.evidence_page_num) for e in question.evidence})
    return {
        "id": question.id,
        "question_type": question.question_type,
        "question": question.question,
        "gold": question.answer,
        "answer": text,
        "verdict": score.verdict,
        "score_method": score.method,
        "score_reason": score.reason,
        "latency_s": round(latency, 3),
        "system_cost_usd": cost,
        "judge_cost_usd": score.judge_cost_usd,
        "input_tokens": tokens[0],
        "output_tokens": tokens[1],
        "gold_pages": gold_pages,
        "retrieved_pages": retrieved,
        "notes": notes,
        "error": error,
        "trace": t.to_dict(),
    }


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    verdicts = Counter(r["verdict"] for r in rows)
    by_type = defaultdict(Counter)
    for r in rows:
        by_type[r["question_type"]][r["verdict"]] += 1
    latencies = sorted(r["latency_s"] for r in rows)
    return {
        "n": n,
        "accuracy": round(verdicts["correct"] / n, 4) if n else 0,
        "refusal_rate": round(verdicts["refused"] / n, 4) if n else 0,
        # Wrong and not refused: the answer a user would wrongly trust.
        "hallucination_rate": round(verdicts["incorrect"] / n, 4) if n else 0,
        "verdicts": dict(verdicts),
        "accuracy_by_type": {t: round(c["correct"] / sum(c.values()), 4) for t, c in sorted(by_type.items())},
        "errors": sum(1 for r in rows if r["error"]),
        "system_cost_usd": round(sum(r["system_cost_usd"] for r in rows), 4),
        "judge_cost_usd": round(sum(r["judge_cost_usd"] for r in rows), 4),
        "latency_p50_s": latencies[n // 2] if n else 0,
        "latency_p95_s": latencies[min(n - 1, int(n * 0.95))] if n else 0,
    }


def run(system_name: str, split: str, limit: int | None, workers: int, resume: Path | None,
        tag: str = "") -> Path:
    questions = load_split(split)
    if limit:
        questions = questions[:limit]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = resume or config.RUNS_DIR / f"{stamp}_{system_name}{'_' + tag if tag else ''}_{split}"
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"

    done = {}
    if results_path.exists():
        for line in results_path.read_text().splitlines():
            row = json.loads(line)
            if not row["error"]:
                done[row["id"]] = row
    todo = [q for q in questions if q.id not in done]

    (run_dir / "meta.json").write_text(json.dumps({
        "system": system_name, "split": split, "limit": limit, "model": config.MODEL,
        "effort": config.DEFAULT_EFFORT, "tag": tag, "started": stamp, "n_questions": len(questions),
    }, indent=1))

    system = get_system(system_name)
    lock = Lock()
    rows = list(done.values())
    print(f"{system_name} on {split}: {len(todo)} to run, {len(done)} already done -> {run_dir}")
    with open(results_path, "w") as f:
        for row in rows:  # rewrite kept rows; drops old errored rows so they get retried
            f.write(json.dumps(row) + "\n")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_one, system, q): q for q in todo}
            for i, fut in enumerate(as_completed(futures), 1):
                row = fut.result()
                with lock:
                    rows.append(row)
                    f.write(json.dumps(row) + "\n")
                    f.flush()
                mark = {"correct": "✓", "incorrect": "✗", "refused": "–"}[row["verdict"]]
                print(f"  [{i}/{len(todo)}] {mark} {row['id']} ({row['latency_s']:.1f}s, ${row['system_cost_usd']:.4f})"
                      + (f"  ERROR {row['error'].splitlines()[0]}" if row["error"] else ""))

    summary = summarize(rows)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--system", required=True)
    parser.add_argument("--split", default="dev", choices=["dev", "test", "own", "compare"])
    parser.add_argument("--limit", type=int, default=None, help="only the first N questions")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", type=Path, default=None)
    parser.add_argument("--tag", default="", help="label added to the run folder name")
    args = parser.parse_args()
    if args.split == "test":
        print("WARNING: the test split is for final reported numbers only. Don't tune on it.")
    run(args.system, args.split, args.limit, args.workers, args.resume, args.tag)


if __name__ == "__main__":
    main()
