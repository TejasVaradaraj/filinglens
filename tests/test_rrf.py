from filinglens.retrieval.search import RRF_K, Hit, _or_query, rrf


def h(i):
    return Hit(i, "D", i, "text", f"t{i}", 0.0)


def test_rrf_rewards_agreement():
    vector = [h(1), h(2), h(3)]
    keyword = [h(3), h(4), h(1)]
    fused = rrf([vector, keyword], k=4)
    assert [x.chunk_id for x in fused][:2] == [1, 3]   # in both lists
    assert fused[0].score == 1 / (RRF_K + 1) + 1 / (RRF_K + 3)


def test_or_query_keeps_words_and_years():
    q = _or_query("What is 3M's FY2018 capex (in USD millions)? P&G 2019")
    terms = set(q.split(" | "))
    assert {"capex", "fy2018", "usd", "millions", "pg", "2019"} <= terms
