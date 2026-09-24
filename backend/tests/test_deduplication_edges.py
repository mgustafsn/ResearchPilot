"""Identifier chains and metadata preservation, using fixed provider-neutral papers."""

from itertools import permutations
from uuid import UUID

import pytest

from researchpilot.analysis import _merge, deduplicate, normalize_doi
from researchpilot.papers import Author, Paper


def paper(number, **fields):
    return Paper(
        id=UUID(int=number),
        source="Local",
        sourceId=str(number),
        sourceUrl=f"https://example.test/{number}",
        **fields,
    )


@pytest.mark.parametrize("order", list(permutations(range(4))))
def test_transitive_doi_source_and_title_chain_in_any_order(order):
    records = [
        paper(1, doi="10.1234/shared", title="Original", publisher="Publisher"),
        paper(2, doi="doi:10.1234/SHARED", title="Intermediate", journal="Journal"),
        paper(3, title="Final title", abstract="An abstract").model_copy(update={"sourceId": "2"}),
        paper(4, title="FINAL-TITLE!", publicationYear=2024),
    ]
    originals = [record.model_dump() for record in records]
    merged, removed = deduplicate([records[i] for i in order])
    assert removed == 3
    assert len(merged) == 1
    assert merged[0].doi == "10.1234/shared"
    assert merged[0].publisher == "Publisher"
    assert merged[0].journal == "Journal"
    assert merged[0].abstract == "An abstract"
    assert merged[0].publicationYear == 2024
    assert [record.model_dump() for record in records] == originals


def test_bridging_existing_groups_preserves_unrelated_group_indexes_and_aliases():
    records = [
        paper(1, doi="10.1234/one", title="First"),
        paper(2, doi="10.1234/other", title="Unrelated"),
        paper(3, title="Third", journal="Journal"),
        paper(4, title="Fourth", abstract="Abstract"),
        paper(5, doi="10.1234/one", title="Fourth").model_copy(update={"sourceId": "3"}),
        paper(6, title="Third", publisher="Publisher"),
        paper(7, doi="10.1234/other", title="Unrelated", publicationYear=2025),
    ]
    merged, removed = deduplicate(records)
    assert removed == 5
    assert len(merged) == 2
    by_doi = {item.doi: item for item in merged}
    assert by_doi["10.1234/one"].journal == "Journal"
    assert by_doi["10.1234/one"].abstract == "Abstract"
    assert by_doi["10.1234/one"].publisher == "Publisher"
    assert by_doi["10.1234/other"].publicationYear == 2025


@pytest.mark.parametrize("order", list(permutations(range(3))))
def test_conflicting_dois_stay_separate_even_with_a_duplicate(order):
    records = [
        paper(1, title="Shared title", doi="10.1234/one"),
        paper(2, title="SHARED-TITLE", doi="10.1234/two"),
        paper(3, title="Shared title", doi="https://doi.org/10.1234/ONE", abstract="Only one"),
    ]
    merged, removed = deduplicate([records[i] for i in order])
    assert removed == 1
    assert len(merged) == 2
    by_doi = {item.doi: item for item in merged}
    assert by_doi["10.1234/one"].abstract == "Only one"
    assert by_doi["10.1234/two"].abstract is None


@pytest.mark.parametrize(
    "variant",
    [
        "doi:10.1234/AbC",
        " DOI: 10.1234/ABC ",
        "http://dx.doi.org/10.1234/AbC",
        "HTTP://DX.DOI.ORG/10.1234/ABC",
        "https://doi.org/10.1234/ABC",
        "http://doi.org/10.1234/ABC",
        " 10.1234/AbC ",
    ],
)
def test_doi_variants_normalize_and_merge_without_title_or_source_matches(variant):
    assert normalize_doi(variant) == "10.1234/abc"
    merged, removed = deduplicate(
        [
            paper(1, title="First", doi=variant),
            paper(2, title="Different", doi="10.1234/abc", abstract="Preserved"),
        ]
    )
    assert removed == 1
    assert len(merged) == 1
    assert merged[0].doi == "10.1234/abc"
    assert merged[0].abstract == "Preserved"


@pytest.mark.parametrize("reverse", [False, True])
def test_merge_preserves_richer_values_fills_gaps_and_does_not_mutate(reverse):
    rich = paper(
        1,
        title="Authoritative",
        doi="DOI:10.1234/ABC",
        abstract="Detailed abstract",
        authors=[Author(name="Author")],
        citationCount=0,
        isOpenAccess=False,
    )
    sparse = paper(2, title="Other title", doi="10.1234/abc", publisher="Publisher")
    before = [rich.model_dump(), sparse.model_dump()]
    result = _merge(sparse, rich) if reverse else _merge(rich, sparse)
    assert result.id == rich.id
    assert result.title == "Authoritative"
    assert result.doi == "10.1234/abc"
    assert result.publisher == "Publisher"
    assert result.authors == [Author(name="Author")]
    assert result.citationCount == 0
    assert result.isOpenAccess is False
    assert [rich.model_dump(), sparse.model_dump()] == before
