"""Repeatability and input-order invariants without external embeddings."""

from copy import deepcopy

import numpy as np
import pytest

from researchpilot.clustering import cluster_papers


def partition(labels, identities):
    groups = {}
    outliers = set()
    for identity, label in zip(identities, labels, strict=True):
        if label is None:
            outliers.add(identity)
        else:
            groups.setdefault(label, set()).add(identity)
    return {frozenset(group) for group in groups.values()}, outliers


def separated_vectors():
    return (
        [[1.0, i / 100, 0.0] for i in range(5)]
        + [[0.0, 1.0, i / 100] for i in range(5)]
        + [[i / 100, 0.0, 1.0] for i in range(5)]
    )


@pytest.mark.parametrize(
    "vectors, expected",
    [
        ([], []),
        ([[1.0, 0.0]], [0]),
        ([[0.0, 0.0]], [0]),
        ([[1.0, 0.0], [0.0, 1.0]], [0, 0]),
        ([[1.0, 0.0], [-1.0, 0.0]], [0, 0]),
        ([[0.0, 0.0], [0.0, 0.0]], [0, 0]),
    ],
)
def test_zero_one_and_two_paper_inputs(vectors, expected):
    original = deepcopy(vectors)
    assert cluster_papers(vectors) == expected
    assert cluster_papers(vectors, seed=17) == expected
    assert vectors == original


@pytest.mark.parametrize("seed", [0, 1, 17])
def test_repeated_runs_do_not_mutate_vectors(seed):
    vectors = separated_vectors()
    original = deepcopy(vectors)
    first = cluster_papers(vectors, seed=seed)
    expected = ({frozenset(range(i, i + 5)) for i in (0, 5, 10)}, set())
    assert partition(first, range(15)) == expected
    for _ in range(3):
        assert cluster_papers(vectors, seed=seed) == first
    assert vectors == original


@pytest.mark.parametrize(
    "order", [list(reversed(range(15))), list(range(0, 15, 2)) + list(range(1, 15, 2))]
)
def test_input_order_preserves_separated_cluster_membership(order):
    vectors = separated_vectors()
    expected = ({frozenset(range(i, i + 5)) for i in (0, 5, 10)}, set())
    # Compare memberships, not arbitrary labels of equal-sized clusters.
    assert partition(cluster_papers([vectors[i] for i in order]), order) == expected


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Clustering initialization depends on input order, changing memberships and outliers.",
)
def test_input_permutation_preserves_membership_for_less_separated_vectors():
    vectors = np.random.default_rng(1).normal(size=(12, 3)).tolist()
    order = list(reversed(range(len(vectors))))
    original = partition(cluster_papers(vectors), range(len(vectors)))
    reordered = partition(cluster_papers([vectors[i] for i in order]), order)
    assert reordered == original
