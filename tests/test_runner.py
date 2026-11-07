"""End-to-end runner test with a fake system and a fake judge: no API calls."""
import json

import pytest

from filinglens import config
from filinglens.eval import runner, scoring
from filinglens.systems.base import SystemAnswer


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    if not (config.FINANCEBENCH_DIR / "data").exists():
        pytest.skip("FinanceBench not downloaded")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    # A "system" that just echoes the gold answer, and fails on one question.
    calls = []

    def fake_system(q):
        calls.append(q.id)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return SystemAnswer(text=q.answer, cost_usd=0.001)

    monkeypatch.setattr(runner, "get_system", lambda name: fake_system)
    monkeypatch.setattr(scoring, "score_with_judge",
                        lambda q, g, p: scoring.Score("correct", "judge", "fake"))
    return calls


def test_run_scores_saves_and_resumes(fake_env):
    run_dir = runner.run("fake", "dev", limit=5, workers=1, resume=None)
    rows = [json.loads(l) for l in (run_dir / "results.jsonl").read_text().splitlines()]
    summary = json.loads((run_dir / "summary.json").read_text())
    assert len(rows) == 5
    assert summary["errors"] == 1 and summary["verdicts"]["correct"] == 4

    # Resume retries only the errored question.
    fake_env.clear()
    runner.run("fake", "dev", limit=5, workers=1, resume=run_dir)
    assert len(fake_env) == 1
    summary = json.loads((run_dir / "summary.json").read_text())
    assert summary["n"] == 5 and summary["errors"] == 0
