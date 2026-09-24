"""Several scholarly sources behind one PaperProvider; deduplication merges their papers."""

import asyncio
import logging

from ..papers import PaperProvider, ProviderError, SearchParameters, SearchResult

logger = logging.getLogger(__name__)


class MultiSourceProvider:
    def __init__(self, providers: list[PaperProvider]):
        self.providers = providers
        self.name = "+".join(provider.name for provider in providers)

    async def search(self, parameters: SearchParameters) -> SearchResult:
        """Query every source; keep survivors, fail when no papers survived a failure."""
        outcomes = await asyncio.gather(
            *(provider.search(parameters) for provider in self.providers),
            return_exceptions=True,
        )
        results, failed, first_error = [], [], None
        for provider, outcome in zip(self.providers, outcomes, strict=True):
            if isinstance(outcome, ProviderError):
                # Never log the query text: it can contain the user's own words.
                logger.warning(
                    "Scholarly source failed source=%s code=%s", provider.name, outcome.code
                )
                failed.append(provider.name)
                first_error = first_error or outcome
            elif isinstance(outcome, BaseException):
                raise outcome
            else:
                results.append(outcome)
        if failed and sum(len(result.papers) for result in results) == 0:
            raise first_error
        return SearchResult(
            papers=[paper for result in results for paper in result.papers],
            totalFound=sum(result.totalFound for result in results),
            skippedCount=sum(result.skippedCount for result in results),
            failedSources=failed,
        )
