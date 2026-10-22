import httpx
import pytest

from app.providers.openalex import (
    OpenAlexClient, ProviderRateLimited, _ArxivBibliographyParser, parse_work,
)


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


def test_forward_falls_back_to_semantic_scholar_when_openalex_is_empty():
    def handler(request):
        if request.url.host == "api.test":
            return httpx.Response(200, json={
                "meta": {"count": 0, "next_cursor": None}, "results": [],
            })
        assert request.url.host == "api.semanticscholar.org"
        assert "/paper/DOI:10.1%2Fexample/citations" in str(request.url)
        return httpx.Response(200, json={
            "offset": 0,
            "data": [{"citingPaper": {
                "paperId": "s2-citing", "externalIds": {"ArXiv": "2605.12345"},
                "title": "A verified citing paper", "authors": [{"name": "Ada Author"}],
                "year": 2026, "venue": "arXiv", "abstract": "Citation evidence",
                "url": "https://www.semanticscholar.org/paper/s2-citing", "citationCount": 0,
            }}],
        })

    client = OpenAlexClient("https://api.test", transport=httpx.MockTransport(handler))
    used = 0
    def consume():
        nonlocal used
        used += 1
    try:
        works, report = client.forward(parse_work(payload()), 2024, 2026, 1, 5, consume)
    finally:
        client.close()

    assert [work.canonical_id for work in works] == ["doi:10.48550/arxiv.2605.12345"]
    assert works[0].raw["provider"] == "semantic_scholar"
    assert report["provider"] == "semantic_scholar"
    assert report["fallback_from"] == "openalex"
    assert [attempt["provider"] for attempt in report["provider_attempts"]] == [
        "openalex", "semantic_scholar",
    ]
    assert used == 2


def test_forward_reports_keyless_semantic_scholar_throttling():
    def handler(request):
        if request.url.host == "api.test":
            return httpx.Response(200, json={
                "meta": {"count": 0, "next_cursor": None}, "results": [],
            })
        return httpx.Response(429, json={"message": "Too Many Requests"})

    client = OpenAlexClient(
        "https://api.test", transport=httpx.MockTransport(handler), max_retries=0,
    )
    try:
        works, report = client.forward(parse_work(payload()), 2024, 2026, 1, 5, lambda: None)
    finally:
        client.close()

    assert works == []
    assert report["failed"] is True
    assert report["provider"] == "semantic_scholar"
    assert report["reason"] == "provider_rate_limited"


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


def test_bibliography_parser_extracts_unlinked_title_and_real_first_author():
    parser = _ArxivBibliographyParser()
    parser.feed('''
      <li id="bib.bib2" class="ltx_bibitem">
        <span class="ltx_tag_bibitem">Cao and Yang (2015)</span>
        <span class="ltx_bibblock">Yinzhi Cao and Junfeng Yang. 2015.</span>
        <span class="ltx_bibblock">Towards making systems forget with machine unlearning.</span>
        <span class="ltx_bibblock">In <em>IEEE symposium on security and privacy</em>.</span>
      </li>
    ''')

    [reference] = parser.references
    assert reference["title"] == "Towards making systems forget with machine unlearning"
    assert reference["first_author"] == "Yinzhi Cao"
    assert reference["position"] == 1


def test_backward_retains_all_five_and_uses_native_arxiv_fallback(monkeypatch):
    html = '''
    <section id="bib"><ul>
      <li id="bib.bib1"><span class="ltx_tag_bibitem">Bao et al. (2025)</span>
        <span class="ltx_bibblock">Guangsheng Bao et al. 2025.</span>
        <span class="ltx_bibblock"><a href="https://aclanthology.org/2025.coling-main.524/">How likely do LLMs with CoT mimic human reasoning?</a></span></li>
      <li id="bib.bib2"><span class="ltx_tag_bibitem">Cao and Yang (2015)</span>
        <span class="ltx_bibblock">Yinzhi Cao and Junfeng Yang. 2015.</span>
        <span class="ltx_bibblock">Towards making systems forget with machine unlearning.</span></li>
      <li id="bib.bib3"><span class="ltx_tag_bibitem">Chen et al. (2024)</span>
        <span class="ltx_bibblock">Kongyang Chen et al. 2024.</span>
        <span class="ltx_bibblock"><a href="https://arxiv.org/abs/2404.16841">Machine unlearning in large language models</a>.</span></li>
      <li id="bib.bib4"><span class="ltx_tag_bibitem">DeepSeek-AI (2024)</span>
        <span class="ltx_bibblock">DeepSeek-AI. 2024.</span>
        <span class="ltx_bibblock"><a href="https://arxiv.org/abs/2412.19437">Deepseek-v3 technical report</a>.</span></li>
      <li id="bib.bib5"><span class="ltx_tag_bibitem">DeepSeek-AI (2025)</span>
        <span class="ltx_bibblock">DeepSeek-AI. 2025.</span>
        <span class="ltx_bibblock"><a href="https://arxiv.org/abs/2501.12948">Deepseek-r1: Incentivizing reasoning capability in llms via reinforcement learning</a>.</span></li>
    </ul></section>
    '''

    def cited(identifier, doi, title, year, author):
        item = payload(identifier, year, 1)
        item.update({
            "doi": f"https://doi.org/{doi}", "title": title,
            "publication_year": year,
            "authorships": [{"author": {"display_name": author}}],
        })
        return item

    def handler(request):
        if request.url.host == "arxiv.org":
            return httpx.Response(200, text=html)
        if request.url.host == "aclanthology.org":
            return httpx.Response(200, text=(
                '<meta name="citation_title" content="How likely do LLMs with CoT mimic human reasoning?">'
                '<meta name="citation_author" content="Guangsheng Bao">'
                '<meta name="citation_publication_date" content="2025">'
            ))
        if "filter" in request.url.params:
            return httpx.Response(200, json={"results": [
                cited("W3", "10.48550/arxiv.2404.16841", "Machine Unlearning in Large Language Models", 2024, "Kongyang Chen"),
                cited("W4", "10.48550/arxiv.2412.19437", "DeepSeek-V3 Technical Report", 2024, "DeepSeek-AI"),
            ]})
        if "search.exact" in request.url.params:
            return httpx.Response(200, json={"results": [
                cited("W2", "10.1109/sp.2015.35", "Towards Making Systems Forget with Machine Unlearning", 2015, "Yinzhi Cao"),
            ]})
        # ACL-to-OpenAlex enrichment may fail; the authoritative ACL record is
        # still a resolved identity and the question mark must not abort BFS.
        return httpx.Response(400, json={"error": "invalid search punctuation"})

    monkeypatch.setattr("app.providers.arxiv.resolve_arxiv", lambda value, consume: (
        consume() or {
            "arxiv_id": value, "title": "DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning",
            "authors": ["DeepSeek-AI"], "year": 2025, "abstract": "Reasoning model",
            "url": f"https://arxiv.org/abs/{value}",
        }
    ))
    client = OpenAlexClient("https://api.test", transport=httpx.MockTransport(handler), max_retries=0)
    seed = parse_work(payload("WSEED", 2026, 0))
    seed.canonical_id = "doi:10.48550/arxiv.2604.15847"
    seed.doi = "10.48550/arxiv.2604.15847"
    seed.arxiv_id = "2604.15847"
    seed.referenced_works = []
    used = 0
    def consume():
        nonlocal used
        used += 1
    try:
        works, report = client.backward(seed, 5, consume)
    finally:
        client.close()

    assert len(works) == 5
    assert {item.canonical_id for item in works} == {
        "acl:2025.coling-main.524", "doi:10.1109/sp.2015.35",
        "doi:10.48550/arxiv.2404.16841", "doi:10.48550/arxiv.2412.19437",
        "doi:10.48550/arxiv.2501.12948",
    }
    assert report["retrieved"] == 5
    assert report["unresolved"] == 0
    assert report["provisional"] == 0
    assert report["failed"] is False


def test_backward_lookup_failure_isolated_and_retained_as_provisional():
    html = '''
      <li id="bib.bib1"><span class="ltx_tag_bibitem">One (2024)</span>
        <span class="ltx_bibblock">Ada One. 2024.</span><span class="ltx_bibblock">Bad query?</span></li>
      <li id="bib.bib2"><span class="ltx_tag_bibitem">Two (2023)</span>
        <span class="ltx_bibblock">Bob Two. 2023.</span><span class="ltx_bibblock">Resolvable paper</span></li>
    '''
    search_calls = 0
    def handler(request):
        nonlocal search_calls
        if request.url.host == "arxiv.org":
            return httpx.Response(200, text=html)
        search_calls += 1
        if search_calls == 1:
            return httpx.Response(400, json={"error": "bad query"})
        item = payload("WOK", 2023, 0)
        item.update({
            "doi": "https://doi.org/10.1/resolved", "title": "Resolvable paper",
            "authorships": [{"author": {"display_name": "Bob Two"}}],
        })
        return httpx.Response(200, json={"results": [item]})

    client = OpenAlexClient("https://api.test", transport=httpx.MockTransport(handler), max_retries=0)
    seed = parse_work(payload("WSEED", 2025, 0))
    seed.arxiv_id = "2501.00001"
    seed.referenced_works = []
    try:
        works, report = client.backward(seed, 2, lambda: None)
    finally:
        client.close()

    assert len(works) == 2
    provisional = next(item for item in works if item.canonical_id.startswith("bibliography:"))
    assert provisional.raw["resolution_status"] == "source_attested_unresolved"
    assert any(item.canonical_id == "doi:10.1/resolved" for item in works)
    assert report["unresolved"] == 1
    assert report["provisional"] == 1
    assert report["lookup_failures"] == 1

