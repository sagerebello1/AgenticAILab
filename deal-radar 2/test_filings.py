"""Filing-index and offer-parser checks. No network."""
import edgar
import terms

INDEX = """
<table class="tableFile" summary="Document Format Files">
<tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
<tr>
  <td>1</td><td></td>
  <td><a href="/Archives/edgar/data/95029/000119380526001376/e665843_sctota-src.htm">e665843_sctota-src.htm</a></td>
  <td>SC TO-T/A</td><td>100</td>
</tr>
<tr>
  <td>2</td><td>PRESS RELEASE</td>
  <td><a href="/Archives/edgar/data/95029/000119380526001376/e665843_ex99-a5v.htm">e665843_ex99-a5v.htm</a></td>
  <td>EX-99.(A)(5)(V)</td><td>100</td>
</tr>
<tr>
  <td></td><td>Complete submission text file</td>
  <td><a href="/Archives/edgar/data/95029/000119380526001376/0001193805-26-001376.txt">0001193805-26-001376.txt</a></td>
  <td>&nbsp;</td><td>100</td>
</tr>
</table>
"""


def test_index_keeps_the_press_release_ahead_of_the_form():
    page = "https://www.sec.gov/Archives/edgar/data/95029/000119380526001376/0001193805-26-001376-index.htm"
    docs = edgar.parse_index(INDEX, page)
    assert [d["type"] for d in docs] == ["SC TO-T/A", "EX-99.(A)(5)(V)"]
    ordered = edgar.supporting_documents(docs, skip_url=docs[0]["url"])
    assert ordered[0]["type"].startswith("EX-99")
    assert ordered[0]["url"].endswith("e665843_ex99-a5v.htm")


def test_par_value_is_not_the_offer_and_cash_price_is():
    text = "Common Stock, Par Value $1.00 per share. The offer is $44.80 per share in cash."
    price, sentence = terms.best_offer(text)
    assert price == 44.80
    assert "44.80" in sentence
    assert "in cash" in sentence.lower()


def test_issue_price_of_the_buyer_stock_is_not_an_offer():
    text = "additional shares at the issue price of $27.21 per share."
    assert terms.best_offer(text) == (None, None)


def test_gap_explanations_follow_the_filing_text():
    assert "ends a merger" in terms.explain_missing_offer("the parties agreed to mutually terminate the Merger Agreement")
    assert "already closed" in terms.explain_missing_offer("the Company completed its previously announced merger")
    assert "amends an earlier" in terms.explain_missing_offer("AMENDMENT NO. 4 TO AGREEMENT AND PLAN OF MERGER")
    assert "stock consideration" in terms.explain_missing_offer("the Stock Consideration paid in accordance with the Merger Agreement")
    assert "another company" in terms.explain_missing_offer("Acquiror will pay a purchase price of $1.970 billion in cash")
    assert terms.filing_status("", None, "SEC returned HTTP 503", True)[0] == "retrieval_failed"
    assert terms.filing_status("   ", None, None, True)[0] == "parsing_failed"
    assert terms.filing_status("", None, None, False)[0] == "no_relevant_filing"
    status, note = terms.filing_status("mutually terminate the Merger Agreement", None, None, True)
    assert status == "terms_need_verification"
    assert "ends a merger" in note
    assert terms.filing_status("holders receive $44.80 per share in cash", 44.80, None, True)[0] == "extracted"


if __name__ == "__main__":
    test_index_keeps_the_press_release_ahead_of_the_form()
    test_par_value_is_not_the_offer_and_cash_price_is()
    test_issue_price_of_the_buyer_stock_is_not_an_offer()
    test_gap_explanations_follow_the_filing_text()
    print("ok")
