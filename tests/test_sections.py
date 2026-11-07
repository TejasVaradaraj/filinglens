from filinglens.parsing.sections import find_sections, section_for_page

TOC = "|Item 1.|Business|3|\n|Item 1A.|Risk Factors|9|\n|Item 7.|MD&A|14|\n|Item 8.|Financial Statements|51|"


def test_10k_items_skip_toc_and_cross_references():
    pages = [
        TOC,
        "### **<u>Item 1. Busines</u>** **<u>s.</u>**\nWe make things.",
        "Item 1A. Risk Factors\nRisks. As discussed in Item 7, margins fell.",
        "## ITEM 7. Management’ s Discussion and Analysis\nSales grew.",
        "Item 1. Business (a running header repeated later)",
        "ITEM 8. Financial Statements and Supplementary Data",
        "notes",
    ]
    secs = find_sections(pages)
    assert [s.item for s in secs] == ["ITEM 1", "ITEM 1A", "ITEM 7", "ITEM 8"]
    assert secs[0].title == "Business"
    assert secs[2].title.startswith("Management’s Discussion")
    assert (secs[2].start_page, secs[2].end_page) == (3, 4)
    assert secs[3].end_page == 6
    assert section_for_page(secs, 4).item == "ITEM 7"
    assert section_for_page(secs, 0) is None


def test_10q_part_ii_restarts_numbering():
    pages = [
        "### **PART I. FINANCIAL INFORMATION**\n### **<u>Item 1. Financial Statements (unaudited)</u>**",
        "### **<u>Item 2. Management's Discussion and Analysis</u>**",
        "## PART II. OTHER INFORMATION\n### **<u>Item 1. Legal Proceedings</u>**\n### **<u>Item 1A. Risk Factors</u>**",
        "### **<u>Item 6. Exhibits</u>**",
    ]
    secs = find_sections(pages, use_parts=True)
    assert [s.item for s in secs] == ["PART I ITEM 1", "PART I ITEM 2", "PART II ITEM 1",
                                      "PART II ITEM 1A", "PART II ITEM 6"]


def test_bare_item_mentions_are_not_headings():
    assert find_sections(["Item 7", "See Item 8 for details"]) == []


def test_item_4a_does_not_block_later_items():
    pages = ["Item 4. Mine Safety Disclosures", "Item 4A. Executive Officers of the Registrant",
             "Item 5. Market for Registrant's Common Equity", "Item 8. Financial Statements"]
    assert [s.item for s in find_sections(pages)] == ["ITEM 4", "ITEM 4A", "ITEM 5", "ITEM 8"]


def test_10q_without_part_heading_infers_part_ii():
    pages = ["## **Item 1. Financial Statements.**", "## **Item 2. Management's Discussion and Analysis.**",
             "Item 1, Business Segments, provides an overview (cross-reference, not a heading)",
             "## **Item 4. Controls and Procedures.**", "## **Item 1.** **<u>Legal Proceedings.</u>**",
             "## **Item 1A. Risk Factors.**", "## **Item 6. Exhibits.**"]
    secs = find_sections(pages, use_parts=True)
    assert [s.item for s in secs] == ["ITEM 1", "ITEM 2", "ITEM 4", "PART II ITEM 1",
                                      "PART II ITEM 1A", "PART II ITEM 6"]
