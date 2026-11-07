from filinglens.retrieval.chunking import TABLE_WORDS, TEXT_WORDS, chunk_page, split_blocks

PAGE = """## Liquidity

Cash was strong this year.

Another paragraph about debt.

|(Millions)|2018|2017|
|---|---|---|
|Net income|**5,363**|4,869|
|Capex|(1,577)|(1,373)|

Closing remarks."""

CTX = "[3M 10K FY2018 | ITEM 8 | page 59]"


def test_split_blocks_keeps_tables_whole():
    kinds = [k for k, _ in split_blocks(PAGE)]
    assert kinds == ["text", "text", "text", "table", "text"]


def test_chunks_have_context_and_clean_table():
    chunks = chunk_page(PAGE, 59, CTX, {0: "Consolidated Statement of Cash Flows"})
    assert all(c.text.startswith(CTX) and c.page_num == 59 for c in chunks)
    table = [c for c in chunks if c.kind == "table"]
    assert len(table) == 1 and table[0].table_idx == 0
    assert "Consolidated Statement of Cash Flows" in table[0].text
    assert "**" not in table[0].text and "(1,577)" in table[0].text


def test_big_table_split_repeats_header():
    rows = "\n".join(f"|Line item number {i} with a long label|{i},000|{i},500|" for i in range(120))
    page = f"|(Millions)|2023|2022|\n|---|---|---|\n{rows}"
    chunks = chunk_page(page, 3, CTX, {0: "Balance sheet"})
    assert len(chunks) > 1
    for c in chunks:
        assert "|(Millions)|2023|2022|" in c.text and "Balance sheet" in c.text
        assert len(c.text.split()) <= TABLE_WORDS + 40
    assert sum(c.text.count("Line item number") for c in chunks) == 120  # no row lost or duplicated


def test_long_text_is_cut():
    page = " ".join(["word"] * (TEXT_WORDS * 3 + 10))
    chunks = chunk_page(page, 1, CTX, {})
    assert len(chunks) == 4
    assert all(len(c.text.split()) <= TEXT_WORDS + len(CTX.split()) for c in chunks)
