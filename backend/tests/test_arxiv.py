import httpx

from app.providers.arxiv import search_arxiv


def test_arxiv_topic_search_preserves_boolean_logic_and_year_bounds():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
      <opensearch:totalResults>8</opensearch:totalResults>
      <entry><id>http://arxiv.org/abs/2501.12345v2</id><title>A causal unlearning paper</title>
      <summary>An abstract.</summary><published>2025-01-20T00:00:00Z</published>
      <author><name>Ada Author</name></author></entry>
    </feed>'''
    def handler(request):
        query = request.url.params["search_query"]
        assert "all:unlearning AND ( all:causal OR all:counterfactual )" in query
        assert "submittedDate:[2022" in query
        return httpx.Response(200, text=xml)
    used = 0
    def consume():
        nonlocal used
        used += 1
    works, report = search_arxiv(
        "unlearning AND (causal OR counterfactual)", 2022, 2026, 25, consume,
        transport=httpx.MockTransport(handler),
    )
    assert works[0].arxiv_id == "2501.12345"
    assert works[0].doi == "10.48550/arxiv.2501.12345"
    assert report["known_total"] == 8
    assert report["capped"] is True
    assert used == 1
