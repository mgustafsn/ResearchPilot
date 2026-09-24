"""All provider flag/link/abstract availability combinations."""

from uuid import UUID

import pytest

from researchpilot.papers import Paper, access_status


@pytest.mark.parametrize("flag", [None, False, True])
@pytest.mark.parametrize("url", [None, "", "https://example.test/full-text"])
@pytest.mark.parametrize("abstract", [None, "", "An available abstract"])
def test_access_status_matrix_and_serialized_paper(flag, url, abstract):
    expected = {
        (False, False, False): "UNKNOWN",
        (False, False, True): "ABSTRACT_ONLY",
        (False, True, False): "OPEN_ACCESS",
        (False, True, True): "OPEN_ACCESS",
        (True, False, False): "OPEN_ACCESS",
        (True, False, True): "OPEN_ACCESS",
        (True, True, False): "OPEN_ACCESS",
        (True, True, True): "OPEN_ACCESS",
    }[bool(flag), bool(url), bool(abstract)]
    assert access_status(flag, url, abstract) == expected
    paper = Paper(
        id=UUID(int=1),
        source="Local",
        sourceId="one",
        sourceUrl="https://example.test/one",
        isOpenAccess=flag,
        openAccessUrl=url,
        abstract=abstract,
    )
    assert paper.accessStatus == expected
    assert paper.model_dump()["accessStatus"] == expected
