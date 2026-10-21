import httpx
import pytest

from app.providers.openalex import OpenAlexClient, ProviderRateLimited, parse_work


def payload(identifier="W1", year=2024, cited=4):
    return {
        "id": f"https://openalex.org/{identifier}", "doi": "https://doi.org/10.1/example",
        "title": "A Paper", "publication_year": year, "cited_by_count": cited,
        "authorships": [{"author": {"display_name": "Ada Author"}}],
        "primary_location": {"landing_page_url": "https://example.test/paper", "source": {"display_name": "Journal"}},
        "abstract_inverted_index": {"hello": [0], "world": [1]},
        "referenced_works": ["https://openalex.org/W2"], "ids": {},
    }


def test_parse_work_normalizes_identity_and_abstract():
    work = parse_work(payload())
    assert work.canonical_id == "doi:10.1/example"
    assert work.openalex_id == "W1"
    assert work.abstract == "hello world"
    assert work.referenced_works == ["W2"]


def test_forward_collection_stops_at_page_budget_and_reports_cursor():
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        body = {"meta": {"count": 600, "next_cursor": f"cursor-{calls}"},
                "results": [payload(f"W{calls}")]}
        return httpx.Response(200, json=body)
    client = OpenAlexClient("https://api.test", transport=httpx.MockTransport(handler))
    used = 0
    def consume():
        nonlocal used
        used += 1
    try:
        works, report = client.forward(parse_work(payload()), 2020, 2025, 2, 600, consume)
    finally:
        client.close()
    assert len(works) == 2
    assert used == 2
    assert report["capped"] is True
    assert report["next_cursor"] == "cursor-2"


def test_provider_retries_throttled_requests_and_counts_each_attempt():
    calls = 0
    delays = []
    def handler(_request):
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(429, headers={"Retry-After": "0.25"})
        return httpx.Response(200, json=payload())
    client = OpenAlexClient(
        "https://api.test", transport=httpx.MockTransport(handler),
        max_retries=3, sleeper=delays.append,
    )
    used = 0
    def consume():
        nonlocal used
        used += 1
    try:
        work = client.resolve("W1", consume)
    finally:
        client.close()
    assert work is not None
    assert calls == used == 3
    assert delays == [0.25, 0.25]


def test_provider_does_not_sleep_or_retry_a_long_daily_limit():
    calls = 0
    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={
            "Retry-After": "24000", "X-RateLimit-Remaining": "0",
        })
    client = OpenAlexClient(
        "https://api.test", transport=httpx.MockTransport(handler), sleeper=lambda _: None,
    )
    with pytest.raises(ProviderRateLimited) as caught:
        client.resolve("W1", lambda: None)
    client.close()
    assert calls == 1
    assert caught.value.daily_budget_exhausted is True
    assert caught.value.retry_after_seconds == 24000


def test_topic_search_is_bounded_and_reports_coverage():
    def handler(request):
        assert request.url.params["search"] == "unlearning AND (causal OR counterfactual)"
        assert "from_publication_date:2022-01-01" in request.url.params["filter"]
        return httpx.Response(200, json={
            "meta": {"count": 42},
            "results": [payload("WSEARCH", 2025, 7)],
        })
    client = OpenAlexClient("https://api.test", transport=httpx.MockTransport(handler))
    used = 0
    def consume():
        nonlocal used
        used += 1
    try:
        works, report = client.search(
            "unlearning AND (causal OR counterfactual)", 2022, 2026, 25, consume,
        )
    finally:
        client.close()
    assert [work.openalex_id for work in works] == ["WSEARCH"]
    assert report == {
        "retrieved": 1, "known_total": 42, "pages": 1,
        "capped": True, "reason": "topic_search_limit",
    }
    assert used == 1


def test_exact_arxiv_url_resolves_through_canonical_doi():
    def handler(request):
        assert str(request.url).endswith("10.48550%2FarXiv.2604.15847")
        result = payload("W2604", 2026, 0)
        result.update({
            "doi": "https://doi.org/10.48550/arxiv.2604.15847",
            "title": "CiPO: Counterfactual Unlearning for Large Reasoning Models through Iterative Preference Optimization",
            "authorships": [
                {"author": {"display_name": "Junyi Li"}},
                {"author": {"display_name": "Yongqiang Chen"}},
                {"author": {"display_name": "Ningning Ding"}},
            ],
            "referenced_works": [],
        })
        return httpx.Response(200, json=result)

    client = OpenAlexClient("https://api.test", transport=httpx.MockTransport(handler))
    used = 0
    def consume():
        nonlocal used
        used += 1
    try:
        work = client.resolve("https://arxiv.org/abs/2604.15847", consume)
    finally:
        client.close()

    assert work is not None
    assert work.canonical_id == "doi:10.48550/arxiv.2604.15847"
    assert work.resolution_method == "provider_identifier:arxiv_doi"
    assert used == 1


def test_acl_url_uses_conservative_title_author_match_not_first_search_result():
    title = "SHA256 at SemEval-2025 Task 4: Selective Amnesia – Constrained Unlearning for Large Language Models via Knowledge Isolation"
    acl_html = (
        f'<meta content="{title}" name="citation_title">'
        '<meta content="Saransh Agrawal" name="citation_author">'
        '<meta content="Kuan-Hao Huang" name="citation_author">'
        '<meta content="2025/7" name="citation_publication_date">'
    )
    wrong = payload("WRONG", 2020, 100)
    right = payload("W2504", 2025, 0)
    right.update({
        "doi": "https://doi.org/10.48550/arxiv.2504.12996",
        "title": title.replace("–", "--"),
        "authorships": [
            {"author": {"display_name": "Saransh Agrawal"}},
            {"author": {"display_name": "Kuan-Hao Huang"}},
        ],
        "referenced_works": [],
    })

    def handler(request):
        if request.url.host == "aclanthology.org":
            return httpx.Response(200, text=acl_html)
        assert request.url.path == "/works"
        return httpx.Response(200, json={"results": [wrong, right]})

    client = OpenAlexClient("https://api.test", transport=httpx.MockTransport(handler))
    used = 0
    def consume():
        nonlocal used
        used += 1
    try:
        work = client.resolve("https://aclanthology.org/2025.semeval-1.308/", consume)
    finally:
        client.close()

    assert work is not None
    assert work.canonical_id == "doi:10.48550/arxiv.2504.12996"
    assert work.openalex_id == "W2504"
    assert work.resolution_method == "conservative_title_author_match:acl_to_openalex"
    assert used == 2


def test_backward_uses_arxiv_bibliography_when_openalex_references_are_empty():
    html = '''
    <section id="bib"><ul>
      <li id="bib.bib1" class="ltx_bibitem">
        <span class="ltx_tag_bibitem">Author et al. (2024)</span>
        Author et al. 2024. <a href="https://doi.org/10.1000/first">First cited paper</a>.
      </li>
      <li id="bib.bib2" class="ltx_bibitem">
        <span class="ltx_tag_bibitem">Writer et al. (2023)</span>
        Writer et al. 2023. <a href="https://arxiv.org/abs/2301.12345">Second cited paper</a>.
      </li>
    </ul></section>
    '''

    def handler(request):
        if request.url.host == "arxiv.org":
            return httpx.Response(200, text=html)
        assert request.url.path == "/works"
        first = payload("WREF1", 2024, 2)
        first["doi"] = "https://doi.org/10.1000/first"
        first["title"] = "First cited paper"
        second = payload("WREF2", 2023, 3)
        second["doi"] = "https://doi.org/10.48550/arxiv.2301.12345"
        second["title"] = "Second cited paper"
        return httpx.Response(200, json={"results": [first, second]})

    client = OpenAlexClient("https://api.test", transport=httpx.MockTransport(handler))
    seed = parse_work(payload("WSEED", 2025, 0))
    seed.doi = "10.48550/arxiv.2504.12996"
    seed.canonical_id = f"doi:{seed.doi}"
    seed.arxiv_id = "2504.12996"
    seed.referenced_works = []
    used = 0
    def consume():
        nonlocal used
        used += 1
    try:
        works, report = client.backward(seed, 50, consume)
    finally:
        client.close()

    assert {work.canonical_id for work in works} == {
        "doi:10.1000/first", "doi:10.48550/arxiv.2301.12345",
    }
    assert report["bibliography_total"] == 2
    assert report["unresolved"] == 0
    assert report["source"] == "arxiv_html_bibliography"
    assert used == 2

