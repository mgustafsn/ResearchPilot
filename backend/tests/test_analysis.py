from uuid import uuid4

from researchpilot.analysis import (
    deduplicate,
    filter_relevant,
    normalize_doi,
    normalize_title,
    rank_papers,
)
from researchpilot.papers import Paper


def paper(title=None, doi=None, source="OpenAlex", source_id=None, **values):
    source_id = source_id or f"https://example.test/{uuid4()}"
    return Paper(
        id=uuid4(),
        source=source,
        sourceId=source_id,
        sourceUrl="https://example.test/work",
        title=title,
        doi=doi,
        **values,
    )


def test_doi_normalization():
    assert normalize_doi(" HTTPS://DOI.ORG/10.1000/ABC ") == "10.1000/abc"
    assert normalize_doi("doi: 10.1000/ABC") == "10.1000/abc"
    assert normalize_doi("not-a-doi") is None


def test_title_normalization_is_deterministic():
    assert normalize_title("  Café-based: Research! ") == "cafe based research"
    assert normalize_title(None) is None


def test_deduplicate_priority_and_merge_metadata():
    first = paper("First title", "10.1000/SAME", citationCount=2)
    richer = paper(
        "Canonical title",
        "https://doi.org/10.1000/same",
        abstract="Full abstract",
        citationCount=10,
    )
    result, count = deduplicate([first, richer])
    assert count == 1
    assert result[0].doi == "10.1000/same"
    assert result[0].title == "Canonical title"
    assert result[0].abstract == "Full abstract"


def test_provider_identity_deduplicates_without_doi():
    identifier = "https://openalex.org/W123"
    result, count = deduplicate(
        [
            paper("Sparse", source_id=identifier),
            paper("Sparse", source_id=identifier, abstract="Metadata"),
        ]
    )
    assert count == 1
    assert result[0].abstract == "Metadata"


def test_normalized_title_is_final_fallback():
    result, count = deduplicate(
        [
            paper("Large-Language Models: a Survey", source="A"),
            paper("Large language models — A survey!", source="B", abstract="Abstract"),
        ]
    )
    assert count == 1
    assert result[0].abstract == "Abstract"


def test_conflicting_dois_are_not_merged_by_title():
    result, count = deduplicate(
        [paper("Shared title", "10.1000/one"), paper("Shared title", "10.1000/two")]
    )
    assert count == 0
    assert len(result) == 2


def test_no_title_or_doi_does_not_merge_unrelated_records():
    result, count = deduplicate([paper(), paper()])
    assert count == 0
    assert len(result) == 2


def test_deduplication_is_transitive():
    source_id = "https://openalex.org/W1"
    a = paper("Original", "10.1000/shared", source="A")
    b = paper("Bridge title", "10.1000/shared", source="B", source_id=source_id)
    c = paper("Bridge title", source="B", source_id=source_id, abstract="Filled")
    result, count = deduplicate([a, b, c])
    assert count == 2
    assert result[0].abstract == "Filled"


def test_relevance_prefers_title_then_abstract_then_venue():
    candidates = [
        paper("LLM software testing", abstract="unrelated"),
        paper("Unrelated", abstract="LLM software testing"),
        paper("Unrelated", venue="LLM software testing"),
        paper("Nothing here"),
    ]
    ranked = rank_papers(candidates, "LLM software testing", [])
    scores = {item.paper.id: item.relevance_score for item in ranked}
    assert scores[candidates[0].id] > scores[candidates[1].id] > scores[candidates[2].id] > 0
    assert scores[candidates[3].id] == 0
    assert [item.relevance_score for item in ranked] == sorted(
        [item.relevance_score for item in ranked], reverse=True
    )


def test_keywords_influence_relevance_and_scores_are_repeatable():
    testing = paper("Automated testing research")
    generation = paper("Code generation research")
    first = rank_papers([testing, generation], "software engineering", ["automated testing"])
    second = rank_papers([testing, generation], "software engineering", ["automated testing"])
    assert first == second
    assert first[0].paper.id == testing.id
    assert first[0].relevance_score > first[1].relevance_score
    assert all(0 <= item.relevance_score <= 1 for item in first)


def test_filter_relevant_removes_low_scoring_papers():
    papers = [paper("large language models"), paper("marine biology")]
    ranked = rank_papers(papers, "large language models", [])
    assert [item.paper.title for item in filter_relevant(ranked)] == ["large language models"]


def test_ties_have_stable_metadata_ordering():
    later = paper("Zulu", citationCount=1)
    cited = paper("Beta", citationCount=9)
    alpha = paper("Alpha", citationCount=1)
    ranked = rank_papers([later, alpha, cited], "missing term", [])
    assert [item.paper for item in ranked] == [cited, alpha, later]
