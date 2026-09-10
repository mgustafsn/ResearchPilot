import numpy as np

from researchpilot.clustering import cluster_papers


def _blob(rng, center, count, spread=0.02):
    center = np.array(center, dtype=float)
    return [(center + rng.normal(0, spread, size=center.shape)).tolist() for _ in range(count)]


def _grouping(labels):
    """Map each non-None label to the frozenset of indices that share it."""
    groups = {}
    for index, label in enumerate(labels):
        if label is not None:
            groups.setdefault(label, set()).add(index)
    return {frozenset(indices) for indices in groups.values()}


def test_separated_blobs_recover_their_groups():
    rng = np.random.default_rng(0)
    vectors = _blob(rng, [5, 0, 0], 5) + _blob(rng, [0, 5, 0], 5) + _blob(rng, [0, 0, 5], 5)
    labels = cluster_papers(vectors)
    assert None not in labels
    assert _grouping(labels) == {
        frozenset(range(0, 5)),
        frozenset(range(5, 10)),
        frozenset(range(10, 15)),
    }


def test_silhouette_picks_the_natural_cluster_count():
    rng = np.random.default_rng(1)
    vectors = (
        _blob(rng, [9, 0, 0, 0], 4)
        + _blob(rng, [0, 9, 0, 0], 4)
        + _blob(rng, [0, 0, 9, 0], 4)
        + _blob(rng, [0, 0, 0, 9], 4)
    )
    labels = cluster_papers(vectors)
    assert set(labels) == {0, 1, 2, 3}


def test_far_outlier_is_uncategorized():
    rng = np.random.default_rng(2)
    vectors = _blob(rng, [4, 0, 0], 6) + _blob(rng, [0, 4, 0], 6) + [[0.0, 0.0, 40.0]]
    labels = cluster_papers(vectors)
    assert labels[-1] is None
    assert all(label is not None for label in labels[:-1])
    assert len(_grouping(labels)) == 2


def test_labels_are_ordered_by_descending_cluster_size():
    rng = np.random.default_rng(3)
    vectors = _blob(rng, [6, 0, 0], 3) + _blob(rng, [0, 6, 0], 8)
    labels = cluster_papers(vectors)
    assert labels[0] == 1  # small blob comes first in the input, larger label
    assert labels[-1] == 0  # larger blob owns label 0
    assert sorted(labels) == [0] * 8 + [1] * 3


def test_result_is_deterministic():
    rng = np.random.default_rng(4)
    vectors = _blob(rng, [3, 0], 7) + _blob(rng, [0, 3], 7) + _blob(rng, [3, 3], 7)
    assert cluster_papers(vectors) == cluster_papers(vectors)


def test_handles_a_project_sized_batch():
    rng = np.random.default_rng(9)
    vectors = [v for i in range(6) for v in _blob(rng, list(rng.normal(0, 5, size=48)), 50)]
    labels = cluster_papers(vectors)
    assert len(labels) == 300
    assert 2 <= len({label for label in labels if label is not None}) <= 8
    assert cluster_papers(vectors) == labels


def test_empty_input_returns_empty_list():
    assert cluster_papers([]) == []


def test_too_few_papers_form_a_single_cluster():
    assert cluster_papers([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]) == [0, 0]


def test_identical_vectors_form_a_single_cluster():
    assert cluster_papers([[1.0, 2.0, 3.0]] * 9) == [0] * 9
