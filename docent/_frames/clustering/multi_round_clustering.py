import random

from docent._frames.clustering.cluster_assigner import ClusterAssigner, HybridClusterAssigner
from docent._frames.clustering.cluster_generator import propose_clusters
from docent._log_util import get_logger

logger = get_logger(__name__)


async def run_attributes_through_clusters(
    attribs: list[str],
    cluster_centroids: list[str],
    assigner: ClusterAssigner,
) -> list[tuple[bool, str] | None]:
    logger.info(f"Running {len(attribs)} attributes through {len(cluster_centroids)} clusters")
    full_items: list[str] = []
    full_centroids: list[str] = []
    for _ in range(len(cluster_centroids)):
        full_items.extend(attribs)
    for centroid in cluster_centroids:
        full_centroids.extend([centroid] * len(attribs))
    new_results = await assigner.assign(full_items, full_centroids)
    return new_results


def process_assignment_results(
    results: list[tuple[bool, str] | None], centroids: list[str], centroid_indices: list[int]
) -> dict[str, set[int]]:
    indices: dict[str, set[int]] = dict()
    for i in centroid_indices:
        centroid = centroids[i]
        indices[centroid] = set()
        for j, res in enumerate(
            results[i * len(results) // len(centroids) : (i + 1) * len(results) // len(centroids)]
        ):
            if res is not None and res[0]:
                indices[centroid].add(j)
    return indices


def remove_very_large_clusters(
    results: list[tuple[bool, str] | None], centroids: list[str], exclusive_threshold: float = 0.5
) -> list[int]:
    bad_indices: list[int] = []
    if len(centroids) > 3:
        for i, _ in enumerate(centroids):
            centroid_results = results[
                i * len(results) // len(centroids) : (i + 1) * len(results) // len(centroids)
            ]
            match_count = sum(1 for res in centroid_results if res is not None and res[0])
            match_threshold = exclusive_threshold * len(centroid_results)
            if match_count >= match_threshold:
                logger.info(
                    f"Found oversized cluster {i} with {match_count} >= {match_threshold} matches"
                )
                bad_indices.append(i)
    logger.info(f"Identified {len(bad_indices)} oversized clusters to remove")
    return bad_indices


def prune_clusters_of_high_overlap(
    results: list[tuple[bool, str] | None], centroids: list[str], exclusive_threshold: float = 0.4
) -> tuple[dict[str, set[int]], list[int]]:
    centroid_indices = list(range(len(centroids)))
    bad_indices = remove_very_large_clusters(results, centroids, exclusive_threshold=0.5)
    for index in bad_indices:
        centroid_indices.remove(index)
        logger.info(f"Removed {centroids[index]}")
    while True:
        indices_per_centroid = process_assignment_results(results, centroids, centroid_indices)
        cluster_pair_counts: dict[int, int] = dict()
        bad_pairs: list[tuple[float, int, int]] = []
        for c1 in centroid_indices:
            for c2 in centroid_indices:
                if c1 == c2:
                    continue
                if len(indices_per_centroid[centroids[c1]]) == 0:
                    continue
                ratio = len(
                    indices_per_centroid[centroids[c1]] & indices_per_centroid[centroids[c2]]
                ) / len(indices_per_centroid[centroids[c1]])
                if ratio < exclusive_threshold:
                    continue
                if len(indices_per_centroid[centroids[c1]]) > len(
                    indices_per_centroid[centroids[c2]]
                ):
                    continue
                cluster_pair_counts[c1] = cluster_pair_counts.get(c1, 0) + 1
                cluster_pair_counts[c2] = cluster_pair_counts.get(c2, 0) + 1
                bad_pairs.append((ratio, c1, c2))
        if len(bad_pairs) == 0:
            break
        bad_pairs.sort(key=lambda x: x[0], reverse=True)
        removed = False
        # remove large clusters that are in many high-overlap pairs
        for bad_pair in bad_pairs:
            if cluster_pair_counts[bad_pair[2]] > 1:
                centroid_indices.remove(bad_pair[2])
                removed = True
                logger.info(f"Removed {centroids[bad_pair[2]]}")
                break
        if removed:
            continue
        # remove small clusters that are in high-overlap pairs if the large cluster is fine
        for bad_pair in bad_pairs:
            centroid_indices.remove(bad_pair[1])
            logger.info(f"Removed {centroids[bad_pair[1]]}")
            break
    return indices_per_centroid, centroid_indices


def display_cluster_overlap_info(indices_per_centroid: dict[str, set[int]]) -> None:
    counts: dict[int, int] = dict()
    for c in indices_per_centroid:
        for i in indices_per_centroid[c]:
            counts[i] = counts.get(i, 0) + 1

    for centroid in indices_per_centroid:
        total_indices = len(indices_per_centroid[centroid])
        if total_indices == 0:
            continue
        excluded_indices = sum(1 for i in indices_per_centroid[centroid] if counts[i] == 1)
        logger.info(f"{centroid}: {excluded_indices / total_indices:.2f}, {total_indices}")


def get_residuals(
    indices_per_centroid: dict[str, set[int]], attribs: list[str]
) -> tuple[list[str], list[str]]:
    all_indices: set[int] = set()
    for c in indices_per_centroid:
        for i in indices_per_centroid[c]:
            all_indices.add(i)
    new_residuals = [attribs[i] for i in range(len(attribs)) if i not in all_indices]
    finished = [attribs[i] for i in range(len(attribs)) if i in all_indices]
    return new_residuals, finished


def prune_small_clusters(
    results: list[tuple[bool, str] | None],
    centroids: list[str],
    exclusive_threshold: float = 0.5,
    remove_majorities: bool = True,
) -> tuple[dict[str, set[int]], list[int]]:
    centroid_indices = list(range(len(centroids)))
    bad_indices = []
    if remove_majorities:
        bad_indices = remove_very_large_clusters(results, centroids, exclusive_threshold=0.5)
    for index in bad_indices:
        centroid_indices.remove(index)
        logger.info(f"Removed {centroids[index]}")
    while True:
        indices_per_centroid = process_assignment_results(results, centroids, centroid_indices)
        max_ratio = 0.0
        max_ratio_centroid = 0
        for c1 in centroid_indices:
            for c2 in centroid_indices:
                if c1 == c2:
                    continue
                if len(indices_per_centroid[centroids[c1]]) == 0:
                    continue
                ratio = len(
                    indices_per_centroid[centroids[c1]] & indices_per_centroid[centroids[c2]]
                ) / len(indices_per_centroid[centroids[c1]])
                if ratio < exclusive_threshold:
                    continue
                if ratio > max_ratio:
                    max_ratio = ratio
                    max_ratio_centroid = c1
        if max_ratio < exclusive_threshold:
            break
        centroid_indices.remove(max_ratio_centroid)
        logger.info(f"Removed {centroids[max_ratio_centroid]}")
    return indices_per_centroid, centroid_indices


async def cluster_from_initial_proposal(
    attribs: list[str],
    attribute: str,
    cluster_centroids: list[str],
    assigner: ClusterAssigner,
    num_rounds: int = 1,
) -> list[str]:
    if len(attribs) == 0:
        return []
    all_finished: list[str] = []
    SUBSET_THRESHOLD = 300
    large = len(attribs) > SUBSET_THRESHOLD
    if large:
        logger.info(
            f"Using subset of {SUBSET_THRESHOLD} attributes for initial clustering due to large input size"
        )
        attribs_subset = random.sample(attribs, SUBSET_THRESHOLD)
    else:
        attribs_subset = attribs
    initial_results = await run_attributes_through_clusters(
        attribs_subset, cluster_centroids, assigner
    )
    indices_per_centroid, centroid_indices = prune_clusters_of_high_overlap(
        initial_results, cluster_centroids, exclusive_threshold=0.4
    )

    running_centroids: list[str] = []
    removed_count = 0
    for i, _ in enumerate(cluster_centroids):
        if i not in centroid_indices:
            if cluster_centroids[i] in indices_per_centroid:
                del indices_per_centroid[cluster_centroids[i]]
                removed_count += 1
            continue
        running_centroids.append(cluster_centroids[i])
    logger.info(f"After pruning: kept {len(running_centroids)} centroids, removed {removed_count}")

    if large:
        initial_results = await run_attributes_through_clusters(
            attribs, running_centroids, assigner
        )
        indices_per_centroid = process_assignment_results(
            initial_results, running_centroids, list(range(len(running_centroids)))
        )
    display_cluster_overlap_info(indices_per_centroid)
    new_residuals, finished = get_residuals(indices_per_centroid, attribs)
    all_finished.extend(finished)
    logger.info(
        f"-------done with stage {num_rounds} of clustering, {len(new_residuals)} / {len(attribs)} residuals remaining-------"
    )
    final_round = False
    while True:
        num_rounds += 1
        proposed_centroids = await propose_clusters(
            new_residuals,
            n_clusters_list=[None],
            extra_instructions_list=[
                f"Specifically focus on the following attribute: {attribute}. In addition, try your best to avoid the following existing clusters: {running_centroids}"
            ],
            feedback_list=None,
            k=1,
        )
        new_centroids = proposed_centroids[0]
        assert new_centroids is not None
        logger.info(f"Proposed {len(new_centroids)} new centroids for round {num_rounds}")
        large = len(new_residuals) > SUBSET_THRESHOLD
        if large:
            new_residuals_subset = random.sample(new_residuals, SUBSET_THRESHOLD)
        else:
            new_residuals_subset = new_residuals
        new_results = await run_attributes_through_clusters(
            new_residuals_subset, new_centroids, assigner
        )
        new_indices_per_centroid, new_centroid_indices = prune_small_clusters(
            new_results,
            new_centroids,
            exclusive_threshold=0.5,
            remove_majorities=(not final_round) or num_rounds > 3,
        )
        running_new_centroids: list[str] = []
        for i, _ in enumerate(new_centroids):
            if i not in new_centroid_indices:
                if new_centroids[i] in new_indices_per_centroid:
                    del new_indices_per_centroid[new_centroids[i]]
                continue
            # for things that were already finished we can skip the new_centroids comparison
            if isinstance(assigner, HybridClusterAssigner):
                assigner.primary.skip_queries(all_finished, new_centroids[i])
            running_new_centroids.append(new_centroids[i])
        if large:
            new_results = await run_attributes_through_clusters(
                new_residuals, running_new_centroids, assigner
            )
            new_indices_per_centroid = process_assignment_results(
                new_results, running_new_centroids, list(range(len(running_new_centroids)))
            )
        display_cluster_overlap_info(new_indices_per_centroid)
        new_residuals, finished = get_residuals(new_indices_per_centroid, new_residuals)
        all_finished.extend(finished)
        logger.info(
            f"-------done with stage {num_rounds} of clustering, {len(new_residuals)} / {len(attribs)} residuals remaining---------"
        )
        running_centroids.extend(running_new_centroids)
        if final_round or len(new_residuals) < 0.05 * len(attribs):
            logger.info(
                f"Terminating clustering: final_round={final_round}, residuals_ratio={len(new_residuals)/len(attribs):.3f}"
            )
            break
        if len(new_residuals) < 0.1 * len(attribs) or num_rounds == 4:
            final_round = True
    logger.info(f"Clustering completed with {len(running_centroids)} total clusters")
    return running_centroids
