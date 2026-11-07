"""EDGAR client behavior with a fake network: no real requests are made."""
import io
import json
import time
import urllib.error

import pytest

from filinglens.edgar import EdgarClient, FilingRef

TICKERS = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
SUBMISSIONS = {"filings": {"recent": {
    "form": ["10-K", "8-K", "10-Q"],
    "accessionNumber": ["0000320193-23-000106", "x", "0000320193-23-000077"],
    "filingDate": ["2023-11-03", "x", "2023-08-04"],
    "reportDate": ["2023-09-30", "x", "2023-07-01"],
    "primaryDocument": ["aapl-20230930.htm", "x", "aapl-20230701.htm"],
}}}


class FakeNet:
    def __init__(self, fail_first: int = 0):
        self.calls, self.fail_first = [], fail_first

    def __call__(self, req, timeout):
        self.calls.append((req.full_url, req.get_header("User-agent")))
        if len(self.calls) <= self.fail_first:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
        url = req.full_url
        body = (json.dumps(TICKERS) if "company_tickers" in url else
                json.dumps(SUBMISSIONS) if "submissions" in url else "<html>10-K</html>")
        return io.BytesIO(body.encode())


@pytest.fixture
def client(tmp_path):
    net = FakeNet()
    return EdgarClient("Test User test@example.com", tmp_path, opener=net, rate=1000), net


def test_requires_contact_user_agent(tmp_path):
    with pytest.raises(RuntimeError):
        EdgarClient("anonymous", tmp_path)


def test_lists_only_requested_forms_and_sends_user_agent(client):
    c, net = client
    refs = c.list_filings("aapl", ("10-K", "10-Q"))
    assert [r.form for r in refs] == ["10-K", "10-Q"]
    assert refs[0].url.endswith("/320193/000032019323000106/aapl-20230930.htm")
    assert all(ua == "Test User test@example.com" for _, ua in net.calls)


def test_download_is_idempotent(client):
    c, net = client
    ref = c.list_filings("AAPL")[0]
    p1 = c.download(ref)
    n = len(net.calls)
    p2 = c.download(ref)
    assert p1 == p2 and p1.read_text() == "<html>10-K</html>"
    assert len(net.calls) == n  # second download came from cache


def test_retries_429(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    net = FakeNet(fail_first=2)
    c = EdgarClient("T t@example.com", tmp_path, opener=net, rate=1000)
    assert c.cik_for("AAPL") == 320193
    assert len(net.calls) == 3


def test_throttle_spaces_requests(tmp_path):
    net = FakeNet()
    c = EdgarClient("T t@example.com", tmp_path, opener=net, rate=20)  # 50 ms apart
    start = time.monotonic()
    for i in range(4):
        c.get(f"https://example.com/{i}", tmp_path / f"{i}.txt")
    assert time.monotonic() - start >= 0.15
