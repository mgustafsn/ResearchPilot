"""Deterministic k-means clustering of paper embeddings with an outlier bucket."""

import numpy as np

MAX_CLUSTERS = 8
MIN_CLUSTER_SIZE = 2
OUTLIER_Z = 3.5
KMEANS_ITERATIONS = 50


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1.0, norms)


def _kmeans(points: np.ndarray, k: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Lloyd's algorithm with seeded k-means++ initialization."""
    rng = np.random.default_rng(seed)
    centers = [points[rng.integers(len(points))]]
    for _ in range(1, k):
        distances = np.min([np.sum((points - center) ** 2, axis=1) for center in centers], axis=0)
        total = distances.sum()
        probabilities = distances / total if total else np.full(len(points), 1 / len(points))
        centers.append(points[rng.choice(len(points), p=probabilities)])
    centroids = np.array(centers)

    labels = np.zeros(len(points), dtype=int)
    for _ in range(KMEANS_ITERATIONS):
        assigned = np.argmin(
            np.linalg.norm(points[:, None, :] - centroids[None, :, :], axis=2), axis=1
        )
        if np.array_equal(assigned, labels):
            break
        labels = assigned
        for index in range(k):
            members = points[labels == index]
            if len(members):
                centroids[index] = members.mean(axis=0)
    return labels, centroids


def _pairwise(points: np.ndarray) -> np.ndarray:
    """Euclidean distances between L2-normalized rows, via the Gram matrix."""
    gram = points @ points.T
    return np.sqrt(np.maximum(0.0, 2.0 - 2.0 * gram))


def _silhouette(points: np.ndarray, labels: np.ndarray) -> float:
    distances = _pairwise(points)
    scores = []
    for index in range(len(points)):
        own = labels == labels[index]
        own[index] = False
        if not own.any():
            continue
        a = distances[index, own].mean()
        b = min(
            distances[index, labels == other].mean()
            for other in set(labels)
            if other != labels[index]
        )
        scores.append((b - a) / max(a, b) if max(a, b) else 0.0)
    return float(np.mean(scores)) if scores else -1.0


def cluster_papers(vectors: list[list[float]], *, seed: int = 0) -> list[int | None]:
    """Assign each vector a 0-based cluster id, or ``None`` when it is an outlier.

    Cluster count is chosen by mean silhouette. Clusters smaller than
    ``MIN_CLUSTER_SIZE`` and points far from their centroid become ``None``.
    Kept clusters are relabeled by descending size so the result is canonical.
    """
    count = len(vectors)
    if count == 0:
        return []
    points = _normalize(np.array(vectors, dtype=float))
    distinct = np.unique(points, axis=0)
    if count < 2 * MIN_CLUSTER_SIZE + 1 or len(distinct) < 2:
        return [0] * count

    max_k = min(MAX_CLUSTERS, count // MIN_CLUSTER_SIZE)
    best_labels, best_score = None, -np.inf
    for k in range(2, max_k + 1):
        labels, _ = _kmeans(points, k, seed)
        score = _silhouette(points, labels)
        if score > best_score:
            best_labels, best_score = labels, score
    labels = best_labels

    result: list[int | None] = [int(label) for label in labels]
    for cluster in set(labels):
        members = [i for i in range(count) if labels[i] == cluster]
        if len(members) < MIN_CLUSTER_SIZE:
            for i in members:
                result[i] = None
            continue
        centroid = points[members].mean(axis=0)
        spreads = np.linalg.norm(points[members] - centroid, axis=1)
        if len(members) >= 4:
            threshold = spreads.mean() + OUTLIER_Z * spreads.std()
            for i, spread in zip(members, spreads):
                if spread > threshold:
                    result[i] = None

    survivors = [label for label in result if label is not None]
    order = sorted(
        set(survivors),
        key=lambda c: (-survivors.count(c), result.index(c)),
    )
    remap = {old: new for new, old in enumerate(order)}
    remapped = [None if label is None else remap[label] for label in result]
    if remapped and all(label is None for label in remapped):
        return [0] * count
    return remapped
