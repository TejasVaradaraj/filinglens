"""Load test the /ask streaming API and report latency percentiles.

    python scripts/load_test.py --url http://localhost:8765 --requests 500 --concurrency 50
    python scripts/load_test.py --url http://localhost:8765 --requests 20 --concurrency 5 --real

Default questions are dev-set questions. For server-overhead tests, start the API with
FL_STUB_SYSTEM=1: the LLM pipeline is replaced by a stub that sleeps like a real answer, so
the numbers measure the server (threads, SSE, auth path), not the model.
Reports time to first event (TTFE), total latency p50/p95/p99, throughput and errors.
"""
import argparse
import asyncio
import statistics
import time

import httpx

from filinglens.dataset import load_split


async def one(client: httpx.AsyncClient, url: str, question: str, key: str | None) -> dict:
    start = time.perf_counter()
    first = None
    events = 0
    headers = {"X-API-Key": key} if key else {}
    try:
        async with client.stream("POST", f"{url}/ask", json={"question": question}, headers=headers,
                                 timeout=180) as r:
            if r.status_code != 200:
                return {"ok": False, "status": r.status_code, "total": time.perf_counter() - start}
            async for line in r.aiter_lines():
                if line.startswith("event:"):
                    events += 1
                    first = first or time.perf_counter() - start
                    if line.strip() in ("event: done", "event: error"):
                        ok = line.strip() == "event: done"
                        return {"ok": ok, "status": 200, "ttfe": first, "total": time.perf_counter() - start,
                                "events": events}
    except httpx.HTTPError as e:
        return {"ok": False, "status": type(e).__name__, "total": time.perf_counter() - start}
    return {"ok": False, "status": "stream ended early", "total": time.perf_counter() - start}


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


async def main(url: str, n: int, concurrency: int, key: str | None) -> None:
    qs = [q.question for q in load_split("dev")]
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=concurrency + 5)) as client:
        async def run(i):
            async with sem:
                return await one(client, url, qs[i % len(qs)], key)
        start = time.perf_counter()
        results = await asyncio.gather(*(run(i) for i in range(n)))
        wall = time.perf_counter() - start
    ok = [r for r in results if r["ok"]]
    errors = {}
    for r in results:
        if not r["ok"]:
            errors[str(r["status"])] = errors.get(str(r["status"]), 0) + 1
    totals = [r["total"] for r in ok]
    ttfe = [r["ttfe"] for r in ok]
    print(f"{n} requests, concurrency {concurrency}, wall {wall:.1f} s, throughput {len(ok) / wall:.1f} req/s")
    print(f"ok {len(ok)}/{n}; errors {errors or 'none'}")
    if ok:
        print(f"total latency  p50 {pct(totals, 50):.2f} s  p95 {pct(totals, 95):.2f} s  p99 {pct(totals, 99):.2f} s"
              f"  mean {statistics.mean(totals):.2f} s")
        print(f"first event    p50 {pct(ttfe, 50):.3f} s  p95 {pct(ttfe, 95):.3f} s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8765")
    ap.add_argument("--requests", type=int, default=200)
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--key", default=None)
    ap.add_argument("--real", action="store_true", help="(informational) the server is running the real pipeline")
    a = ap.parse_args()
    asyncio.run(main(a.url, a.requests, a.concurrency, a.key))
