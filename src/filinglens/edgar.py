"""Download filings from SEC EDGAR, politely and idempotently.

Usage:
    python -m filinglens.edgar AAPL --forms 10-K 10-Q --limit 4

SEC rules (https://www.sec.gov/os/accessing-edgar-data): declare who you are in the
User-Agent, stay under 10 requests/second. We do 5/s, retry 429/5xx with backoff,
and cache every response on disk, so re-running never re-downloads anything.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from filinglens import config

MAX_REQUESTS_PER_SECOND = 5
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"


@dataclass
class FilingRef:
    ticker: str
    cik: int
    form: str
    accession: str        # 0000320193-23-000106
    filing_date: str
    report_date: str
    primary_document: str

    @property
    def url(self) -> str:
        return DOC_URL.format(cik=self.cik, accession=self.accession.replace("-", ""),
                              document=self.primary_document)


class EdgarClient:
    def __init__(self, user_agent: str | None = None, cache_dir: Path | None = None,
                 opener=urllib.request.urlopen, rate: float = MAX_REQUESTS_PER_SECOND):
        self.user_agent = user_agent or config.SEC_USER_AGENT
        if not self.user_agent or "@" not in self.user_agent:
            raise RuntimeError('Set SEC_USER_AGENT in .env, e.g. SEC_USER_AGENT="Your Name you@example.com"')
        self.cache_dir = cache_dir or config.DATA_DIR / "raw" / "edgar"
        self._open = opener
        self._min_interval = 1.0 / rate
        self._last = 0.0
        self._lock = threading.Lock()
        self.requests_made = 0

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last + self._min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def get(self, url: str, cache_path: Path, retries: int = 4) -> bytes:
        """GET with on-disk cache. A cached file is returned without any network call."""
        if cache_path.exists():
            return cache_path.read_bytes()
        for attempt in range(retries + 1):
            self._throttle()
            req = urllib.request.Request(url, headers={"User-Agent": self.user_agent,
                                                       "Accept-Encoding": "identity"})
            try:
                self.requests_made += 1
                with self._open(req, timeout=30) as resp:
                    body = resp.read()
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                    time.sleep(2 ** attempt)  # 1, 2, 4, 8 s
                    continue
                raise
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_suffix(cache_path.suffix + ".part")
        tmp.write_bytes(body)
        tmp.replace(cache_path)  # atomic: a crash never leaves a half-written cache file
        return body

    def cik_for(self, ticker: str) -> int:
        data = json.loads(self.get(TICKERS_URL, self.cache_dir / "company_tickers.json"))
        for row in data.values():
            if row["ticker"].upper() == ticker.upper():
                return int(row["cik_str"])
        raise KeyError(f"Unknown ticker {ticker!r}")

    def list_filings(self, ticker: str, forms: tuple[str, ...] = ("10-K", "10-Q")) -> list[FilingRef]:
        cik = self.cik_for(ticker)
        # Submissions change as new filings arrive, so cache them per day.
        day = time.strftime("%Y-%m-%d")
        data = json.loads(self.get(SUBMISSIONS_URL.format(cik=cik),
                                   self.cache_dir / "submissions" / f"CIK{cik:010d}_{day}.json"))
        recent = data["filings"]["recent"]
        refs = []
        for i, form in enumerate(recent["form"]):
            if form in forms:
                refs.append(FilingRef(ticker.upper(), cik, form, recent["accessionNumber"][i],
                                      recent["filingDate"][i], recent["reportDate"][i],
                                      recent["primaryDocument"][i]))
        return refs

    def download(self, ref: FilingRef) -> Path:
        path = self.cache_dir / "filings" / ref.ticker / f"{ref.accession}_{ref.primary_document}"
        self.get(ref.url, path)
        meta = path.with_name(path.name + ".json")
        if not meta.exists():
            meta.write_text(json.dumps(asdict(ref), indent=1))
        return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ticker")
    parser.add_argument("--forms", nargs="+", default=["10-K", "10-Q"])
    parser.add_argument("--limit", type=int, default=4, help="most recent N matching filings")
    args = parser.parse_args()
    client = EdgarClient()
    for ref in client.list_filings(args.ticker, tuple(args.forms))[: args.limit]:
        path = client.download(ref)
        print(f"{ref.form:5} {ref.report_date}  {path}")
    print(f"{client.requests_made} network requests (everything else came from cache)")


if __name__ == "__main__":
    main()
