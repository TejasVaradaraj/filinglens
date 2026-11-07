"""Append an eval run's headline numbers to evals/history.jsonl (committed score history).

Usage: python scripts/record_run.py <run_dir> [<run_dir> ...]
Re-recording the same run replaces its line, so the history has one entry per run.
"""
import json
import sys
from pathlib import Path

HISTORY = Path(__file__).resolve().parents[1] / "evals" / "history.jsonl"


def citation_precision(run_dir: Path):
    nums = ok = 0
    for line in (run_dir / "results.jsonl").read_text().splitlines():
        cc = (json.loads(line).get("notes") or {}).get("citation_check")
        if cc:
            nums += len(cc["numbers"])
            ok += sum(n["ok"] for n in cc["numbers"])
    return round(ok / nums, 4) if nums else None


def record(run_dir: Path) -> dict:
    meta = json.loads((run_dir / "meta.json").read_text())
    s = json.loads((run_dir / "summary.json").read_text())
    entry = {
        "run": run_dir.name, "date": meta["started"][:8], "system": meta["system"], "tag": meta.get("tag", ""),
        "split": meta["split"], "n": s["n"], "accuracy": s["accuracy"], "refusal_rate": s["refusal_rate"],
        "hallucination_rate": s["hallucination_rate"], "citation_precision": citation_precision(run_dir),
        "cost_per_q": round(s["system_cost_usd"] / max(s["n"], 1), 5), "latency_p95_s": s["latency_p95_s"],
        "model": meta.get("model"),
    }
    lines = [l for l in HISTORY.read_text().splitlines() if l.strip()] if HISTORY.exists() else []
    lines = [l for l in lines if json.loads(l)["run"] != entry["run"]] + [json.dumps(entry)]
    lines.sort(key=lambda l: json.loads(l)["run"])
    HISTORY.write_text("\n".join(lines) + "\n")
    return entry


if __name__ == "__main__":
    for d in sys.argv[1:]:
        e = record(Path(d))
        print(f"recorded {e['system']}/{e['split']} ({e['n']} q): accuracy {e['accuracy']:.0%}")
