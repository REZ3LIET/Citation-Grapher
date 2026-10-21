from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import quote

import httpx


DOI_RE = re.compile(r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/[-._;()/:A-Z0-9]+)$", re.I)
ARXIV_RE = re.compile(r"(?:https?://arxiv\.org/(?:abs|pdf)/|arxiv:\s*)?([a-z-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?$", re.I)
OPENALEX_RE = re.compile(r"(?:https?://openalex\.org/)?(W\d+)$", re.I)
ACL_RE = re.compile(r"https?://(?:www\.)?aclanthology\.org/([^/?#]+)/?", re.I)


class ProviderBudgetExceeded(RuntimeError):
    pass


class ProviderRateLimited(RuntimeError):
    def __init__(self, retry_after_seconds: float | None, daily_budget_exhausted: bool = False):
        self.retry_after_seconds = retry_after_seconds
        self.daily_budget_exhausted = daily_budget_exhausted
        reason = "daily keyless budget exhausted" if daily_budget_exhausted else "request rate limited"
        retry = f"; retry after {int(retry_after_seconds)} seconds" if retry_after_seconds else ""
        super().__init__(f"Provider {reason}{retry}")


@dataclass(slots=True)
class Work:
    canonical_id: str
    openalex_id: str | None
    doi: str | None
    arxiv_id: str | None
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    abstract: str | None
    url: str | None
    citation_count: int | None
    referenced_works: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    resolution_method: str | None = None


class _CitationMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta":
            return
        attributes = {key.lower(): value for key, value in attrs if value is not None}
        name = attributes.get("name", "").lower()
        content = attributes.get("content")
        if name.startswith("citation_") and content:
            self.values.setdefault(name, []).append(content.strip())


class _ArxivBibliographyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[dict] = []
        self.current: dict | None = None
        self.current_anchor: dict | None = None
        self.in_tag = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value for key, value in attrs if value is not None}
        classes = set(attributes.get("class", "").split())
        if tag.lower() == "li" and attributes.get("id", "").startswith("bib.bib"):
            self.current = {"text_parts": [], "anchors": [], "tag_parts": []}
        elif self.current is not None and tag.lower() == "a":
            self.current_anchor = {"href": attributes.get("href", ""), "text_parts": []}
        elif self.current is not None and tag.lower() == "span" and "ltx_tag_bibitem" in classes:
            self.in_tag = True

    def handle_data(self, data: str) -> None:
        if self.current is None:
            return
        self.current["text_parts"].append(data)
        if self.current_anchor is not None:
            self.current_anchor["text_parts"].append(data)
        if self.in_tag:
            self.current["tag_parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.current is None:
            return
        if tag.lower() == "a" and self.current_anchor is not None:
            self.current_anchor["text"] = " ".join("".join(
                self.current_anchor.pop("text_parts")
            ).split())
            self.current["anchors"].append(self.current_anchor)
            self.current_anchor = None
        elif tag.lower() == "span" and self.in_tag:
            self.in_tag = False
        elif tag.lower() == "li":
            raw = " ".join("".join(self.current.pop("text_parts")).split())
            tag_text = " ".join("".join(self.current.pop("tag_parts")).split())
            anchors = self.current.get("anchors", [])
            title = max((item.get("text", "") for item in anchors), key=len, default=None)
            combined = " ".join([raw, *(item.get("href", "") for item in anchors)])
            doi_match = re.search(r"10\.\d{4,9}/[^\s\"<>?#]+", combined, re.I)
            arxiv_match = re.search(r"(?:arxiv[:./ ]+|arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5})", combined, re.I)
            year_match = re.search(r"\b((?:19|20)\d{2})\b", raw)
            author_label = re.sub(r"\s*\((?:19|20)\d{2}[a-z]?\).*", "", tag_text, flags=re.I)
            first_author = re.split(r"\s+(?:et\s+al\.|and|&)\s+", author_label, maxsplit=1, flags=re.I)[0]
            self.references.append({
                "title": title, "doi": doi_match.group(0).rstrip(".,;)") if doi_match else None,
                "arxiv_id": arxiv_match.group(1) if arxiv_match else None,
                "year": int(year_match.group(1)) if year_match else None,
                "first_author": first_author or None, "raw": raw,
            })
            self.current = None


def _normalized_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", decomposed))


def _conservative_metadata_match(payload: dict, title: str, authors: list[str], year: int | None) -> bool:
    candidate = parse_work(payload)
    if _normalized_text(candidate.title) != _normalized_text(title):
        return False
    if year is not None and candidate.year != year:
        return False
    candidate_authors = {_normalized_text(author) for author in candidate.authors}
    expected_authors = {_normalized_text(author) for author in authors}
    return bool(expected_authors) and expected_authors.issubset(candidate_authors)


def _conservative_reference_match(payload: dict, reference: dict) -> bool:
    candidate = parse_work(payload)
    title = reference.get("title")
    if not title or _normalized_text(candidate.title) != _normalized_text(title):
        return False
    year = reference.get("year")
    if year is not None and candidate.year != year:
        return False
    first_author = _normalized_text(reference.get("first_author") or "")
    if not first_author or not candidate.authors:
        return False
    expected_surname = first_author.split()[-1]
    return expected_surname in _normalized_text(candidate.authors[0]).split()


def _abstract_from_inverted(index: dict | None) -> str | None:
    if not index:
        return None
    positioned = [(position, word) for word, positions in index.items() for position in positions]
    return " ".join(word for _, word in sorted(positioned)) or None


def _short_openalex_id(value: str | None) -> str | None:
    if not value:
        return None
    return value.rstrip("/").rsplit("/", 1)[-1].upper()


def parse_work(payload: dict, resolution_method: str | None = None) -> Work:
    openalex_id = _short_openalex_id(payload.get("id"))
    doi = payload.get("doi")
    if doi:
        doi = doi.lower().removeprefix("https://doi.org/")
    ids = payload.get("ids") or {}
    arxiv_id = ids.get("arxiv")
    if arxiv_id:
        arxiv_id = arxiv_id.rstrip("/").rsplit("/", 1)[-1]
    elif doi and doi.startswith("10.48550/arxiv."):
        arxiv_id = doi.removeprefix("10.48550/arxiv.")
    canonical = f"doi:{doi}" if doi else f"openalex:{openalex_id}"
    primary = payload.get("primary_location") or {}
    source = primary.get("source") or {}
    return Work(
        canonical_id=canonical,
        openalex_id=openalex_id,
        doi=doi,
        arxiv_id=arxiv_id,
        title=(payload.get("title") or "Untitled").strip(),
        authors=[
            entry.get("author", {}).get("display_name", "").strip()
            for entry in payload.get("authorships") or []
            if entry.get("author", {}).get("display_name")
        ],
        year=payload.get("publication_year"),
        venue=source.get("display_name"),
        abstract=_abstract_from_inverted(payload.get("abstract_inverted_index")),
        url=primary.get("landing_page_url") or (f"https://doi.org/{doi}" if doi else payload.get("id")),
        citation_count=payload.get("cited_by_count"),
        referenced_works=[_short_openalex_id(item) for item in payload.get("referenced_works") or []],
        raw=payload,
        resolution_method=resolution_method,
    )


class OpenAlexClient:
    def __init__(
        self, base_url: str, timeout: float = 20.0, transport=None, *,
        max_retries: int = 3, retry_base_seconds: float = 0.5,
        retry_max_seconds: float = 8.0, sleeper=time.sleep,
    ):
        self.max_retries = max_retries
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self.sleeper = sleeper
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": "Citation-Grapher/0.1 (keyless literature discovery)"},
        )

    def close(self) -> None:
        self.client.close()

    def _request(self, path: str, params: dict | None, consume_request) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            consume_request()
            response = self.client.get(path, params=params)
            if response.status_code not in {429, 500, 502, 503, 504}:
                response.raise_for_status()
                return response
            retry_after = response.headers.get("Retry-After", "")
            try:
                delay = float(retry_after)
            except ValueError:
                delay = self.retry_base_seconds * (2 ** attempt)
            if response.status_code == 429 and (
                delay > self.retry_max_seconds or attempt == self.max_retries
            ):
                raise ProviderRateLimited(
                    delay if retry_after else None,
                    daily_budget_exhausted=response.headers.get("X-RateLimit-Remaining") == "0",
                )
            if attempt == self.max_retries:
                response.raise_for_status()
            self.sleeper(min(max(0.0, delay), self.retry_max_seconds))
        raise RuntimeError("Provider retry loop ended unexpectedly")

    def _get(self, path: str, params: dict | None, consume_request) -> dict:
        return self._request(path, params, consume_request).json()

    def resolve(self, value: str, consume_request) -> Work | None:
        cleaned = value.strip()
        doi_match = DOI_RE.search(cleaned)
        openalex_match = OPENALEX_RE.search(cleaned)
        arxiv_match = ARXIV_RE.search(cleaned)
        try:
            if doi_match:
                payload = self._get(f"/works/https://doi.org/{quote(doi_match.group(1), safe='')}", None, consume_request)
                return parse_work(payload, "provider_identifier:doi")
            if openalex_match:
                payload = self._get(f"/works/{openalex_match.group(1).upper()}", None, consume_request)
                return parse_work(payload, "provider_identifier:openalex")
            if arxiv_match:
                arxiv_id = arxiv_match.group(1)
                doi = f"10.48550/arXiv.{arxiv_id}"
                payload = self._get(f"/works/https://doi.org/{quote(doi, safe='')}", None, consume_request)
                work = parse_work(payload, "provider_identifier:arxiv_doi")
                work.arxiv_id = arxiv_id
                return work
            acl_match = ACL_RE.fullmatch(cleaned)
            if acl_match:
                return self._resolve_acl(cleaned, acl_match.group(1), consume_request)
            # An arbitrary URL path is not paper metadata. Searching it and
            # accepting the first result can silently substitute another paper.
            return None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

    def _resolve_acl(self, url: str, anthology_id: str, consume_request) -> Work | None:
        response = self._request(url, None, consume_request)
        parser = _CitationMetaParser()
        parser.feed(response.text)
        title = next(iter(parser.values.get("citation_title", [])), None)
        authors = parser.values.get("citation_author", [])
        publication_date = next(iter(parser.values.get("citation_publication_date", [])), "")
        year_match = re.match(r"(\d{4})", publication_date)
        year = int(year_match.group(1)) if year_match else None
        if not title or not authors:
            return None

        # The ACL identifier and page metadata are independently sufficient to
        # preserve the seed even when OpenAlex has not indexed an equivalent.
        acl_work = Work(
            canonical_id=f"acl:{anthology_id.lower()}", openalex_id=None, doi=None,
            arxiv_id=None, title=title, authors=authors, year=year,
            venue=next(iter(parser.values.get("citation_conference_title", [])), None),
            abstract=None, url=url, citation_count=None, referenced_works=[],
            raw={"provider": "acl_anthology", "anthology_id": anthology_id},
            resolution_method="provider_identifier:acl_anthology",
        )
        try:
            payload = self._get("/works", {"search": title, "per-page": 5}, consume_request)
        except (httpx.HTTPError, ProviderBudgetExceeded):
            return acl_work
        for result in payload.get("results") or []:
            if _conservative_metadata_match(result, title, authors, year):
                work = parse_work(result, "conservative_title_author_match:acl_to_openalex")
                work.raw.setdefault("seed_source", {"provider": "acl_anthology", "id": anthology_id})
                return work
        return acl_work

    def works_by_ids(self, ids: list[str], consume_request) -> list[Work]:
        works: list[Work] = []
        for start in range(0, len(ids), 50):
            batch = [item for item in ids[start : start + 50] if item]
            if not batch:
                continue
            payload = self._get(
                "/works",
                {"filter": f"openalex_id:{'|'.join(batch)}", "per-page": 100},
                consume_request,
            )
            works.extend(parse_work(item) for item in payload.get("results") or [])
        return works

    def search(
        self, query: str, min_year: int, max_year: int, limit: int, consume_request
    ) -> tuple[list[Work], dict]:
        payload = self._get(
            "/works",
            {
                "search": query,
                "filter": f"from_publication_date:{min_year}-01-01,to_publication_date:{max_year}-12-31",
                "per-page": min(100, limit),
            },
            consume_request,
        )
        meta = payload.get("meta") or {}
        works = [parse_work(item, "topic_search") for item in payload.get("results") or []]
        works = [work for work in works if work.year is not None and min_year <= work.year <= max_year]
        known_total = meta.get("count")
        capped = known_total is not None and int(known_total) > len(works)
        return works[:limit], {
            "retrieved": min(len(works), limit),
            "known_total": known_total,
            "pages": 1,
            "capped": capped,
            "reason": "topic_search_limit" if capped else None,
        }

    def backward(self, work: Work, limit: int, consume_request) -> tuple[list[Work], dict]:
        if not work.referenced_works and work.arxiv_id:
            return self._backward_from_arxiv(work, limit, consume_request)
        ids = work.referenced_works[:limit]
        works = self.works_by_ids(ids, consume_request)
        capped = len(work.referenced_works) > limit
        return works, {
            "retrieved": len(works),
            "known_total": len(work.referenced_works),
            "capped": capped,
            "reason": "candidate_budget" if capped else None,
        }

    def _backward_from_arxiv(
        self, work: Work, limit: int, consume_request
    ) -> tuple[list[Work], dict]:
        response = self._request(f"https://arxiv.org/html/{work.arxiv_id}", None, consume_request)
        parser = _ArxivBibliographyParser()
        parser.feed(response.text)
        references = parser.references
        works: list[Work] = []
        unresolved = 0
        provider_failed = False
        seen: set[str] = set()
        limited = references[:limit]
        by_doi: dict[str, dict] = {}
        for reference in limited:
            doi = reference.get("doi")
            if not doi and reference.get("arxiv_id"):
                doi = f"10.48550/arxiv.{reference['arxiv_id']}"
            if doi:
                by_doi[doi.lower()] = reference

        resolved_dois: set[str] = set()
        doi_values = list(by_doi)
        for start in range(0, len(doi_values), 50):
            try:
                batch = doi_values[start : start + 50]
                payload = self._get(
                    "/works", {"filter": f"doi:{'|'.join(batch)}", "per-page": 100},
                    consume_request,
                )
                for item in payload.get("results") or []:
                    resolved = parse_work(item, "bibliography_identifier")
                    if not resolved.doi or resolved.doi not in by_doi:
                        continue
                    resolved_dois.add(resolved.doi)
                    if resolved.canonical_id in seen or resolved.canonical_id == work.canonical_id:
                        continue
                    seen.add(resolved.canonical_id)
                    reference = by_doi[resolved.doi]
                    resolved.raw.setdefault("bibliography_evidence", {
                        "source_arxiv_id": work.arxiv_id,
                        "raw_reference": reference.get("raw"),
                    })
                    works.append(resolved)
            except (httpx.HTTPError, ProviderBudgetExceeded):
                provider_failed = True
                break
        unresolved += len(set(doi_values) - resolved_dois)

        for reference in limited:
            if provider_failed:
                break
            if reference.get("doi") or reference.get("arxiv_id"):
                continue
            payload = None
            try:
                if reference.get("title"):
                    search = self._get(
                        "/works", {"search": reference["title"], "per-page": 5}, consume_request
                    )
                    payload = next((
                        item for item in search.get("results") or []
                        if _conservative_reference_match(item, reference)
                    ), None)
            except (httpx.HTTPError, ProviderBudgetExceeded):
                provider_failed = True
                break
            if payload is None:
                unresolved += 1
                continue
            resolved = parse_work(payload, "bibliography_identifier_or_exact_match")
            if resolved.canonical_id in seen or resolved.canonical_id == work.canonical_id:
                continue
            seen.add(resolved.canonical_id)
            resolved.raw.setdefault("bibliography_evidence", {
                "source_arxiv_id": work.arxiv_id, "raw_reference": reference.get("raw"),
            })
            works.append(resolved)
        capped = len(references) > limit
        return works, {
            "retrieved": len(works), "known_total": len(references),
            "bibliography_total": len(references), "unresolved": unresolved,
            "source": "arxiv_html_bibliography", "capped": capped,
            "failed": provider_failed,
            "reason": (
                "provider_failure" if provider_failed else
                "candidate_budget" if capped else
                "unresolved_bibliography_entries" if unresolved else None
            ),
        }

    def forward(
        self,
        work: Work,
        min_year: int,
        max_year: int,
        max_pages: int,
        candidate_limit: int,
        consume_request,
        start_cursor: str = "*",
    ) -> tuple[list[Work], dict]:
        if not work.openalex_id:
            return [], {"retrieved": 0, "unsupported": True, "reason": "missing_openalex_id"}
        cursor = start_cursor
        works: list[Work] = []
        pages = 0
        known_total = None
        while cursor and pages < max_pages and len(works) < candidate_limit:
            payload = self._get(
                "/works",
                {
                    "filter": f"cites:{work.openalex_id},from_publication_date:{min_year}-01-01,to_publication_date:{max_year}-12-31",
                    "per-page": min(100, candidate_limit - len(works)),
                    "cursor": cursor,
                },
                consume_request,
            )
            pages += 1
            known_total = (payload.get("meta") or {}).get("count", known_total)
            works.extend(parse_work(item) for item in payload.get("results") or [])
            next_cursor = (payload.get("meta") or {}).get("next_cursor")
            if not next_cursor or not payload.get("results"):
                cursor = None
                break
            cursor = next_cursor
        capped = bool(cursor) and (pages >= max_pages or len(works) >= candidate_limit)
        return works[:candidate_limit], {
            "retrieved": min(len(works), candidate_limit),
            "known_total": known_total,
            "pages": pages,
            "next_cursor": cursor if capped else None,
            "capped": capped,
            "reason": "page_or_candidate_budget" if capped else None,
        }

