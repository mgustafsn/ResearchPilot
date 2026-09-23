"""Deterministic paper deduplication and lexical relevance ranking."""

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from .papers import Paper

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "http://dx.doi.org/")


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    for prefix in DOI_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    if normalized.startswith("doi:"):
        normalized = normalized[4:].strip()
    return normalized if normalized.startswith("10.") and "/" in normalized else None


def normalize_title(value: str | None) -> str | None:
    if not value:
        return None
    ascii_title = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = " ".join(TOKEN_PATTERN.findall(ascii_title.casefold()))
    return normalized or None


def tokens(value: str | None) -> list[str]:
    return TOKEN_PATTERN.findall(unicodedata.normalize("NFKC", value or "").casefold())


def _richness(paper: Paper) -> tuple[int, int, int]:
    values = paper.model_dump(exclude={"id", "source", "sourceId", "sourceUrl"})
    populated = sum(value not in (None, "", [], {}) for value in values.values())
    return populated, len(paper.abstract or ""), len(paper.authors)


def _merge(primary: Paper, secondary: Paper) -> Paper:
    """Fill gaps only; authoritative values from the richer record remain stable."""
    if _richness(secondary) > _richness(primary):
        primary, secondary = secondary, primary
    values = primary.model_dump()
    other = secondary.model_dump()
    for field, value in values.items():
        if value in (None, "", [], {}) and other[field] not in (None, "", [], {}):
            values[field] = other[field]
    values["doi"] = normalize_doi(values["doi"])
    return Paper.model_validate(values)


def deduplicate(papers: list[Paper]) -> tuple[list[Paper], int]:
    """Merge DOI, provider-identity, then normalized-title duplicates transitively."""
    groups: list[Paper] = []
    doi_groups: dict[str, int] = {}
    source_groups: dict[tuple[str, str], int] = {}
    title_groups: dict[str, int] = {}

    for paper in papers:
        doi = normalize_doi(paper.doi)
        source = (paper.source.casefold(), paper.sourceId.casefold())
        title = normalize_title(paper.title)
        doi_match = doi_groups.get(doi) if doi else None
        source_match = source_groups.get(source)
        title_match = title_groups.get(title) if title else None
        # Explicit, conflicting DOIs outweigh an identical normalized title.
        if title_match is not None and doi:
            existing_doi = normalize_doi(groups[title_match].doi)
            if existing_doi and existing_doi != doi:
                title_match = None
        matches = {index for index in (doi_match, source_match, title_match) if index is not None}
        if not matches:
            index = len(groups)
            groups.append(paper.model_copy(update={"doi": doi}))
        else:
            index = min(matches)
            groups[index] = _merge(groups[index], paper)
            # If identifiers bridge existing groups, merge those groups transitively.
            for duplicate_index in sorted(matches - {index}, reverse=True):
                groups[index] = _merge(groups[index], groups[duplicate_index])
                groups.pop(duplicate_index)
                for mapping in (doi_groups, source_groups, title_groups):
                    for key, value in list(mapping.items()):
                        if value == duplicate_index:
                            mapping[key] = index
                        elif value > duplicate_index:
                            mapping[key] = value - 1
        merged = groups[index]
        merged_doi = normalize_doi(merged.doi)
        merged_title = normalize_title(merged.title)
        if merged_doi:
            doi_groups[merged_doi] = index
        source_groups[(merged.source.casefold(), merged.sourceId.casefold())] = index
        if merged_title:
            title_groups[merged_title] = index
        if doi:
            doi_groups[doi] = index
        source_groups[source] = index
        if title:
            title_groups[title] = index
    return groups, len(papers) - len(groups)


@dataclass(frozen=True)
class RankedPaper:
    paper: Paper
    relevance_score: float


RELEVANCE_THRESHOLD = 0.10


def filter_relevant(ranked: list[RankedPaper], threshold: float = RELEVANCE_THRESHOLD):
    """Keep papers with enough lexical evidence for the original research question."""
    return [item for item in ranked if item.relevance_score >= threshold]


def rank_papers(papers: list[Paper], question: str, keywords: list[str]) -> list[RankedPaper]:
    """Rank by explainable weighted term coverage; corpus IDF rewards discriminating terms."""
    query_terms = Counter(tokens(question))
    keyword_terms = Counter(term for keyword in keywords for term in tokens(keyword))
    all_terms = set(query_terms) | set(keyword_terms)
    if not all_terms:
        return [RankedPaper(paper, 0.0) for paper in papers]

    documents = []
    frequencies = Counter()
    for paper in papers:
        fields = {
            "title": set(tokens(paper.title)),
            "abstract": set(tokens(paper.abstract)),
            "venue": set(tokens(" ".join(filter(None, [paper.venue, paper.journal])))),
        }
        documents.append(fields)
        present = set().union(*fields.values())
        frequencies.update(term for term in all_terms if term in present)

    size = max(1, len(papers))
    weights = {
        term: (1.0 + math.log((size + 1) / (frequencies[term] + 1)))
        * (1.4 if term in keyword_terms else 1.0)
        * (1.0 + 0.1 * min(query_terms[term] + keyword_terms[term] - 1, 3))
        for term in all_terms
    }
    denominator = sum(weights.values()) * 3.0
    normalized_question = normalize_title(question) or ""
    ranked = []
    for paper, fields in zip(papers, documents, strict=True):
        score = 0.0
        for term, weight in weights.items():
            field_weight = (
                3.0
                if term in fields["title"]
                else 1.5
                if term in fields["abstract"]
                else 0.5
                if term in fields["venue"]
                else 0.0
            )
            score += weight * field_weight
        title = normalize_title(paper.title) or ""
        if normalized_question and len(normalized_question) >= 8 and normalized_question in title:
            score += denominator * 0.15
        ranked.append(RankedPaper(paper, round(min(1.0, score / denominator), 6)))
    return sorted(
        ranked,
        key=lambda item: (
            -item.relevance_score,
            -(item.paper.citationCount or 0),
            normalize_title(item.paper.title) or "",
            str(item.paper.id),
        ),
    )
