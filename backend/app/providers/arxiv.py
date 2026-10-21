from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import httpx

from .openalex import Work


ARXIV_ID_RE = re.compile(r"(?:arxiv:\s*|arxiv\.org/(?:abs|pdf)/)?([a-z-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?", re.I)
ATOM = {"atom": "http://www.w3.org/2005/Atom"}
SEARCH_NS = {**ATOM, "opensearch": "http://a9.com/-/spec/opensearch/1.1/"}


def _arxiv_boolean_query(value: str) -> str:
    tokens = re.findall(r'"[^"]+"|\(|\)|\bAND\b|\bOR\b|\bNOT\b|[^\s()]+', value, re.I)
    converted = []
    for token in tokens:
        upper = token.upper()
        if token in {"(", ")"} or upper in {"AND", "OR"}:
            converted.append(upper if upper in {"AND", "OR"} else token)
        elif upper == "NOT":
            converted.append("ANDNOT")
        else:
            converted.append(f"all:{token}")
    return " ".join(converted)


def search_arxiv(
    query: str, min_year: int, max_year: int, limit: int, consume_request,
    timeout: float = 20.0, transport=None,
) -> tuple[list[Work], dict]:
    consume_request()
    scoped_query = (
        f"({_arxiv_boolean_query(query)}) AND "
        f"submittedDate:[{min_year}01010000 TO {max_year}12312359]"
    )
    with httpx.Client(transport=transport, timeout=timeout, headers={"User-Agent": "Citation-Grapher/0.1"}) as client:
        response = client.get(
            "https://export.arxiv.org/api/query",
            params={"search_query": scoped_query, "start": 0, "max_results": limit,
                    "sortBy": "relevance", "sortOrder": "descending"},
        )
        response.raise_for_status()
    root = ET.fromstring(response.text)
    total_text = root.findtext("opensearch:totalResults", "0", SEARCH_NS)
    known_total = int(total_text) if total_text.isdigit() else None
    works: list[Work] = []
    for entry in root.findall("atom:entry", SEARCH_NS):
        raw_id = entry.findtext("atom:id", "", SEARCH_NS).rstrip("/").rsplit("/", 1)[-1]
        arxiv_id = re.sub(r"v\d+$", "", raw_id)
        published = entry.findtext("atom:published", "", SEARCH_NS)
        year = int(published[:4]) if published[:4].isdigit() else None
        if year is None or not min_year <= year <= max_year:
            continue
        title = " ".join(entry.findtext("atom:title", "Untitled", SEARCH_NS).split())
        abstract = " ".join(entry.findtext("atom:summary", "", SEARCH_NS).split()) or None
        authors = [node.findtext("atom:name", "", SEARCH_NS) for node in entry.findall("atom:author", SEARCH_NS)]
        doi = f"10.48550/arxiv.{arxiv_id.lower()}"
        works.append(Work(
            canonical_id=f"doi:{doi}", openalex_id=None, doi=doi, arxiv_id=arxiv_id,
            title=title, authors=authors, year=year, venue="arXiv", abstract=abstract,
            url=f"https://arxiv.org/abs/{arxiv_id}", citation_count=None,
            raw={"provider": "arxiv", "topic_search_query": query},
            resolution_method="topic_search:arxiv",
        ))
    capped = known_total is not None and known_total > len(works)
    return works, {
        "retrieved": len(works), "known_total": known_total, "pages": 1,
        "capped": capped, "reason": "topic_search_limit" if capped else None,
    }


def resolve_arxiv(value: str, consume_request, timeout: float = 20.0) -> dict | None:
    match = ARXIV_ID_RE.search(value)
    if not match:
        return None
    arxiv_id = match.group(1)
    consume_request()
    response = httpx.get(
        "https://export.arxiv.org/api/query",
        params={"id_list": arxiv_id},
        timeout=timeout,
        headers={"User-Agent": "Citation-Grapher/0.1"},
    )
    response.raise_for_status()
    root = ET.fromstring(response.text)
    entry = root.find("atom:entry", ATOM)
    if entry is None:
        return None
    title = " ".join((entry.findtext("atom:title", "", ATOM)).split())
    abstract = " ".join((entry.findtext("atom:summary", "", ATOM)).split())
    published = entry.findtext("atom:published", "", ATOM)
    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "abstract": abstract,
        "year": int(published[:4]) if published[:4].isdigit() else None,
        "authors": [node.findtext("atom:name", "", ATOM) for node in entry.findall("atom:author", ATOM)],
        "url": f"https://arxiv.org/abs/{arxiv_id}",
    }

