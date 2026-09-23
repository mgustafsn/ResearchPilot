"""Helpers for measurable NFR tests (docs/requirements.md §31)."""

import time
from contextlib import contextmanager

from fakes import RecordingEmbeddingProvider

BUDGET_FACTOR = 3
SIX_GROUPS = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot")


def check_budget(record_property, nfr_id, target_s, measured_s):
    ceiling_s = target_s * BUDGET_FACTOR
    record_property(f"{nfr_id} measured_s", round(measured_s, 4))
    record_property(f"{nfr_id} target_s", target_s)
    record_property(f"{nfr_id} ceiling_s", ceiling_s)
    assert measured_s <= ceiling_s, (
        f"{nfr_id}: {measured_s:.3f}s exceeds the CI ceiling {ceiling_s:.3f}s "
        f"(target {target_s:.3f}s)"
    )


@contextmanager
def budget(record_property, nfr_id, target_s):
    started = time.perf_counter()
    yield
    check_budget(record_property, nfr_id, target_s, time.perf_counter() - started)


class SixGroupEmbeddingProvider(RecordingEmbeddingProvider):
    """Each group marker gets its own axis plus the shared on-topic axis 7."""

    def _vector(self, text):
        vector = [0.0] * self.dimension
        for index, marker in enumerate(SIX_GROUPS):
            if marker in text:
                vector[index] = 10.0
                vector[7] = 10.0
                return vector
        return [1.0] * self.dimension
