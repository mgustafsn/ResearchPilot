from uuid import uuid4

import pytest

from researchpilot.papers import Paper, access_status


@pytest.mark.parametrize(
    ("is_open_access", "open_access_url", "abstract", "expected"),
    [
        (True, None, None, "OPEN_ACCESS"),
        (False, "https://repo.example/paper.pdf", None, "OPEN_ACCESS"),
        (None, "https://repo.example/paper.pdf", "abs", "OPEN_ACCESS"),
        (False, None, "An abstract is present.", "ABSTRACT_ONLY"),
        (None, None, "An abstract is present.", "ABSTRACT_ONLY"),
        (False, None, None, "UNKNOWN"),
        (None, None, None, "UNKNOWN"),
    ],
)
def test_access_status(is_open_access, open_access_url, abstract, expected):
    assert access_status(is_open_access, open_access_url, abstract) == expected


def test_paper_exposes_access_status():
    paper = Paper(
        id=uuid4(),
        source="OpenAlex",
        sourceId="x",
        sourceUrl="https://openalex.org/W1",
        abstract="Something",
        isOpenAccess=True,
    )
    assert paper.model_dump()["accessStatus"] == "OPEN_ACCESS"
    assert paper.accessStatus == "OPEN_ACCESS"
