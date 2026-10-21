from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx


TEI = {"tei": "http://www.tei-c.org/ns/1.0"}


def identify_pdf(pdf: bytes, base_url: str, timeout: float = 60.0) -> dict:
    """Extract a conservative seed identifier and display metadata from a PDF."""
    response = httpx.post(
        f"{base_url.rstrip('/')}/api/processHeaderDocument",
        files={"input": ("paper.pdf", pdf, "application/pdf")},
        timeout=timeout,
    )
    response.raise_for_status()
    root = ET.fromstring(response.text)
    title_node = root.find(".//tei:titleStmt/tei:title", TEI)
    doi_node = root.find(".//tei:idno[@type='DOI']", TEI)
    date_node = root.find(".//tei:publicationStmt/tei:date", TEI)
    authors = []
    for author in root.findall(".//tei:sourceDesc//tei:author", TEI):
        name = " ".join("".join(author.itertext()).split())
        if name:
            authors.append(name)
    title = " ".join("".join(title_node.itertext()).split()) if title_node is not None else None
    doi = doi_node.text.strip().lower() if doi_node is not None and doi_node.text else None
    year = (date_node.get("when") or "")[:4] if date_node is not None else None
    if not doi and not title:
        raise ValueError("The PDF did not contain enough metadata to identify a paper")
    return {"identifier": f"doi:{doi}" if doi else title, "doi": doi, "title": title,
            "authors": authors, "year": int(year) if year and year.isdigit() else None}


def extract_pdf_references(pdf: bytes, base_url: str, timeout: float = 60.0) -> list[dict]:
    """Extract backward reference strings with a local GROBID service."""
    response = httpx.post(
        f"{base_url.rstrip('/')}/api/processReferences",
        files={"input": ("paper.pdf", pdf, "application/pdf")},
        timeout=timeout,
    )
    response.raise_for_status()
    root = ET.fromstring(response.text)
    references: list[dict] = []
    for item in root.findall(".//tei:biblStruct", TEI):
        title_node = item.find(".//tei:title[@level='a']", TEI) or item.find(".//tei:title", TEI)
        doi_node = item.find(".//tei:idno[@type='DOI']", TEI)
        date_node = item.find(".//tei:date", TEI)
        references.append(
            {
                "title": " ".join("".join(title_node.itertext()).split()) if title_node is not None else None,
                "doi": doi_node.text.strip() if doi_node is not None and doi_node.text else None,
                "year": (date_node.get("when") or "")[:4] if date_node is not None else None,
            }
        )
    return references

