"""Fail (exit 1) if the latest recorded eval of the gated system regressed.

Thresholds live in evals/gate.json. Each check looks at the most recent full run
(n >= min_n) of that system on that split in evals/history.jsonl and compares it with
the threshold minus the allowed noise. Runs locally and in CI (no API calls).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    gate = json.loads((ROOT / "evals" / "gate.json").read_text())
    history = [json.loads(l) for l in (ROOT / "evals" / "history.jsonl").read_text().splitlines() if l.strip()]
    failures = []
    for check in gate["checks"]:
        runs = [h for h in history if h["system"] == gate["system"] and h["split"] == check["split"]
                and h["n"] >= check["min_n"] and h.get(check["metric"]) is not None]
        if not runs:
            failures.append(f"{check['split']}/{check['metric']}: no recorded run with n >= {check['min_n']}")
            continue
        latest = max(runs, key=lambda h: h["run"])
        value, floor = latest[check["metric"]], check["min"] - check.get("noise", 0)
        status = "ok " if value >= floor else "FAIL"
        print(f"{status} {gate['system']} {check['split']:4} {check['metric']:18} {value:.3f} "
              f"(needs >= {floor:.3f}) from {latest['run']}")
        if value < floor:
            failures.append(f"{check['split']}/{check['metric']} = {value} < {floor}")
    for f in failures:
        print("REGRESSION:", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
