"""Several scholarly sources behind one PaperProvider."""

import asyncio
import logging

import pytest

from fakes import RecordingProvider, grouped_papers
from researchpilot.papers import ProviderError, SearchParameters
from researchpilot.providers.multi import MultiSourceProvider

PARAMETERS = SearchParameters(query="secret query text", maxPaperCount=10)


def source(name, papers=None, error=None):
    provider = RecordingProvider()
    provider.name = name
    provider.papers = grouped_papers(per_group=2) if papers is None else papers
    provider.error = error
    return provider


def run(provider):
    return asyncio.run(provider.search(PARAMETERS))


def test_combines_sources_and_joins_the_name():
    openalex, scopus = source("OpenAlex"), source("Scopus", grouped_papers(("alpha",), 1))
    multi = MultiSourceProvider([openalex, scopus])
    result = run(multi)
    assert multi.name == "OpenAlex+Scopus"
    assert len(result.papers) == 6 + 1
    assert result.totalFound == 7
    assert result.failedSources == []
    # Every source gets the full per-query budget.
    assert openalex.calls == [PARAMETERS] and scopus.calls == [PARAMETERS]


def test_partial_failure_keeps_survivors_and_names_the_failed_source(caplog):
    caplog.set_level(logging.WARNING)
    multi = MultiSourceProvider(
        [source("OpenAlex"), source("Scopus", error=ProviderError("RATE_LIMITED"))]
    )
    result = run(multi)
    assert len(result.papers) == 6
    assert result.failedSources == ["Scopus"]
    assert "source=Scopus code=RATE_LIMITED" in caplog.text
    assert "secret query text" not in caplog.text


def test_all_sources_failing_raises_the_first_error_in_order():
    multi = MultiSourceProvider(
        [
            source("OpenAlex", error=ProviderError("UNAVAILABLE")),
            source("Scopus", error=ProviderError("AUTHENTICATION")),
        ]
    )
    with pytest.raises(ProviderError) as error:
        run(multi)
    assert error.value.code == "UNAVAILABLE"


def test_failure_with_empty_survivors_raises():
    multi = MultiSourceProvider(
        [source("OpenAlex", papers=[]), source("Scopus", error=ProviderError("TIMEOUT"))]
    )
    with pytest.raises(ProviderError) as error:
        run(multi)
    assert error.value.code == "TIMEOUT"


def test_empty_results_without_failure_complete():
    result = run(MultiSourceProvider([source("OpenAlex", []), source("Scopus", [])]))
    assert result.papers == [] and result.failedSources == []


def test_programming_errors_propagate():
    multi = MultiSourceProvider([source("OpenAlex"), source("Scopus", error=KeyError("bug"))])
    with pytest.raises(KeyError):
        run(multi)
