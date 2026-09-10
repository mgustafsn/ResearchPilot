import asyncio
import json
from pathlib import Path

import httpx
import pytest

from researchpilot.config import openalex_headers
from researchpilot.papers import ProviderError, SearchParameters
from researchpilot.providers.openalex import OpenAlexProvider, normalize_work, reconstruct_abstract

WORK = json.loads((Path(__file__).parent / "fixtures/openalex_work.json").read_text())


def test_normalize_real_provider_record():
    paper = normalize_work(WORK)
    assert paper.title == WORK["title"]
    assert paper.publicationYear == WORK["publication_year"]
    assert paper.sourceUrl == WORK["id"]
    assert paper.source == "OpenAlex"
    assert paper.citationCount == WORK["cited_by_count"]
    assert paper.authors[0].name == WORK["authorships"][0]["author"]["display_name"]
    assert paper.id == normalize_work(WORK).id
    if WORK["doi"]:
        assert paper.doiUrl == WORK["doi"]
        assert paper.doi == WORK["doi"].split("doi.org/")[1].lower()


def test_absent_optional_metadata_is_not_invented():
    paper = normalize_work({"id": WORK["id"]})
    assert paper.title is None
    assert paper.abstract is None
    assert paper.authors == []
    assert paper.publicationYear is None
    assert paper.citationCount is None
    assert paper.journal is None
    assert paper.doi is None
    assert paper.isOpenAccess is None


def test_repository_is_not_a_journal_or_publisher():
    paper = normalize_work(
        WORK
        | {
            "primary_location": {
                "source": {
                    "type": "repository",
                    "display_name": "University archive",
                    "host_organization": "https://openalex.org/I123",
                    "host_organization_name": "University",
                }
            }
        }
    )
    assert paper.venue == "University archive"
    assert paper.journal is None
    assert paper.publisher is None


def test_unsafe_and_invalid_optional_metadata():
    paper = normalize_work(
        WORK
        | {
            "doi": "javascript:alert(1)",
            "publication_year": True,
            "publication_date": "nonsense",
            "cited_by_count": -1,
            "open_access": {"is_oa": "true", "oa_url": "data:text/html,x"},
            "primary_location": {"landing_page_url": "https://user:secret@example.org"},
        }
    )
    assert paper.doiUrl is None
    assert paper.publicationUrl is None
    assert paper.openAccessUrl is None
    assert paper.publicationYear is None
    assert paper.publicationDate is None
    assert paper.citationCount is None
    assert paper.isOpenAccess is None


@pytest.mark.parametrize(
    "index",
    [
        None,
        {},
        {"bad": [-1]},
        {"bad": [True]},
        {"gap": [1]},
        {"a": [0], "b": [0]},
        {"huge": [10000000]},
        {"bad": "value"},
    ],
)
def test_malformed_abstract(index):
    assert reconstruct_abstract(index) is None


def test_abstract_positions():
    assert (
        reconstruct_abstract({"research": [1, 3], "Real": [0], "supports": [2]})
        == "Real research supports research"
    )


def retrieve(handler, parameters=None):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await OpenAlexProvider(client).search(
                parameters or SearchParameters(query="test")
            )

    return asyncio.run(run())


def test_pagination_filters_and_cap():
    calls = []

    def handler(request):
        calls.append(request)
        offset = 0 if len(calls) == 1 else 100
        return httpx.Response(
            200,
            json={
                "meta": {"count": 250, "next_cursor": "next"},
                "results": [
                    WORK | {"id": f"https://openalex.org/W{offset + i}"} for i in range(100)
                ],
            },
        )

    result = retrieve(
        handler,
        SearchParameters(
            query="large language models", yearFrom=2021, yearTo=2026, maxPaperCount=125
        ),
    )
    assert len(result.papers) == 125
    assert len(calls) == 2
    assert calls[0].url.params["filter"] == "publication_year:2021-2026"
    assert calls[0].url.params["search"] == "large language models"
    assert calls[0].url.params["per_page"] == "100"
    assert calls[1].url.params["cursor"] == "next"


@pytest.mark.parametrize(
    ("parameters", "expected"),
    [
        (SearchParameters(query="test", yearFrom=2020), "publication_year:2020-9999"),
        (SearchParameters(query="test", yearTo=2020), "publication_year:1-2020"),
        (SearchParameters(query="test"), None),
    ],
)
def test_open_ended_filters(parameters, expected):
    def handler(request):
        assert request.url.params.get("filter") == expected
        return httpx.Response(200, json={"meta": {"count": 0}, "results": []})

    assert retrieve(handler, parameters).papers == []


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (429, "RATE_LIMITED"),
        (401, "AUTHENTICATION"),
        (403, "AUTHENTICATION"),
        (503, "UNAVAILABLE"),
        (400, "QUERY_REJECTED"),
        (414, "QUERY_REJECTED"),
    ],
)
def test_http_failures_are_safe(status, code):
    with pytest.raises(ProviderError) as error:
        retrieve(lambda request: httpx.Response(status, text="secret upstream response"))
    assert error.value.code == code
    assert "secret" not in str(error.value)


def test_timeout():
    def handler(request):
        raise httpx.ReadTimeout("secret URL")

    with pytest.raises(ProviderError, match="timed out"):
        retrieve(handler)


@pytest.mark.parametrize(
    "payload",
    [
        {"results": {}},
        {"meta": {"count": 1}, "results": [None]},
        {"meta": {"count": "wrong"}, "results": []},
    ],
)
def test_invalid_response(payload):
    with pytest.raises(ProviderError) as error:
        retrieve(lambda request: httpx.Response(200, json=payload))
    assert error.value.code == "INVALID_RESPONSE"


def test_invalid_json():
    with pytest.raises(ProviderError) as error:
        retrieve(lambda request: httpx.Response(200, text="<html>bad</html>"))
    assert error.value.code == "INVALID_RESPONSE"


def test_skip_record_without_identity():
    result = retrieve(
        lambda request: httpx.Response(
            200, json={"meta": {"count": 2}, "results": [WORK, {"title": "not attributable"}]}
        )
    )
    assert len(result.papers) == 1
    assert result.skippedCount == 1


def test_api_key_uses_header(monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "test-secret")
    assert openalex_headers()["Authorization"] == "Bearer test-secret"
    monkeypatch.delenv("OPENALEX_API_KEY")
    assert "Authorization" not in openalex_headers()
