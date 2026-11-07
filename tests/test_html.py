from filinglens.parsing.html import html_to_pages
from filinglens.parsing.tables import page_tables

HTML = """<html><body>
<div><span>Item 7. Management's Discussion and Analysis</span></div>
<p>The following table shows net sales (in millions):</p>
<table>
<tr><td></td><td colspan="2">2026</td><td></td><td colspan="2">2025</td></tr>
<tr><td>Americas</td><td>$</td><td>198,083</td><td></td><td>$</td><td>178,353</td></tr>
<tr><td>Europe</td><td colspan="2">127,604</td><td></td><td colspan="2">111,032</td></tr>
<tr><td>Other income</td><td></td><td>(321</td><td>)</td><td></td><td>(28</td></tr>
</table>
<div style="page-break-after: always"></div>
<div>Item 8. Financial Statements</div>
</body></html>"""


def test_pages_split_at_page_breaks():
    pages = html_to_pages(HTML)
    assert len(pages) == 2 and pages[1].startswith("Item 8.")


def test_dollar_and_paren_columns_align():
    [t] = page_tables(html_to_pages(HTML)[0])
    assert t.values[0] == [198083, 178353] and t.values[1] == [127604, 111032]
    assert t.values[2][0] == -321


def test_headers_land_over_their_numbers():
    html = """<table>
    <tr><td></td><td colspan="3">2026</td><td>Change</td><td colspan="3">2025</td></tr>
    <tr><td>Americas</td><td>$</td><td>198,083</td><td></td><td>11%</td><td>$</td><td>178,353</td><td></td></tr>
    <tr><td>Europe</td><td colspan="2">127,604</td><td></td><td>15%</td><td colspan="2">111,032</td><td></td></tr>
    </table>"""
    [t] = page_tables(html_to_pages(html)[0])
    assert t.header == ["", "2026", "Change", "2025"]
    assert t.values == [[198083, 11, 178353], [127604, 15, 111032]]
