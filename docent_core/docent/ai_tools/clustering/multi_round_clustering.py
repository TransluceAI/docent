import random
from typing import Any, Callable, Coroutine

from docent._log_util import get_logger
from docent_core.docent.ai_tools.clustering.cluster_assigner import LlmApiClusterAssigner
from docent_core.docent.ai_tools.clustering.cluster_generator import (
    parse_cluster_output,
    propose_clusters,
)

logger = get_logger(__name__)


class Cluster:
    def __init__(self, centroid: str, indices: set[int]):
        self.centroid = centroid
        self.indices = indices
        self.metadata: dict[str, list[int]] = {}

    def __len__(self) -> int:
        return len(self.indices)

    def overlap_ratio(self, other: "Cluster") -> float:
        if not self.indices:
            return 0.0
        return len(self.indices & other.indices) / len(self.indices)


class ClusterProcessor:
    def __init__(self, assigner: LlmApiClusterAssigner):
        self.assigner = assigner
        self.SUBSET_THRESHOLD = 300

    async def run_attributes_through_clusters(
        self,
        attribs: list[str],
        cluster_centroids: list[str],
    ) -> list[Cluster]:
        logger.info(f"Running {len(attribs)} attributes through {len(cluster_centroids)} clusters")
        full_items: list[str] = []
        full_centroids: list[str] = []
        for _ in range(len(cluster_centroids)):
            full_items.extend(attribs)
        for centroid in cluster_centroids:
            full_centroids.extend([centroid] * len(attribs))

        results = await self.assigner.assign(
            full_items,
            full_centroids,
        )

        clusters: list[Cluster] = []
        for i, centroid in enumerate(cluster_centroids):
            indices: set[int] = set()
            start_idx = i * len(results) // len(cluster_centroids)
            end_idx = (i + 1) * len(results) // len(cluster_centroids)
            for j, res in enumerate(results[start_idx:end_idx]):
                if res is not None and res[0]:
                    indices.add(j)
            clusters.append(Cluster(centroid=centroid, indices=indices))
        return clusters

    def find_high_overlap_pairs(
        self, clusters: list[Cluster], exclusive_threshold: float
    ) -> list[tuple[float, Cluster, Cluster]]:
        bad_pairs: list[tuple[float, Cluster, Cluster]] = []

        for i, cluster1 in enumerate(clusters):
            for j, cluster2 in enumerate(clusters):
                if i == j:
                    continue

                if not cluster1.indices:
                    continue

                ratio = cluster1.overlap_ratio(cluster2)
                if ratio < exclusive_threshold:
                    continue
                if len(cluster1) > len(cluster2):
                    continue

                bad_pairs.append((ratio, cluster1, cluster2))

        return bad_pairs

    def prune_clusters_of_high_overlap(
        self, clusters: list[Cluster], exclusive_threshold: float = 0.5
    ) -> list[Cluster]:
        while True:
            bad_pairs = self.find_high_overlap_pairs(clusters, exclusive_threshold)
            if not bad_pairs:
                break

            bad_pairs.sort(key=lambda x: x[0], reverse=True)
            centroid_counts: dict[str, int] = {}
            for bad_pair in bad_pairs:
                _, cluster1, cluster2 = bad_pair
                centroid_counts[cluster1.centroid] = centroid_counts.get(cluster1.centroid, 0) + 1
                centroid_counts[cluster2.centroid] = centroid_counts.get(cluster2.centroid, 0) + 1

            for centroid, count in centroid_counts.items():
                if count > 1:
                    cluster = next(c for c in clusters if c.centroid == centroid)
                    clusters.remove(cluster)
                    logger.info(f"Removed {cluster.centroid} due to high overlap")
                    break
            else:
                ratio, cluster1, cluster2 = bad_pairs[0]
                clusters.remove(cluster1)
                logger.info(
                    f"Removed {cluster1.centroid} due to high overlap ({ratio:.2f}) with {cluster2.centroid}"
                )

        return clusters

    def display_cluster_overlap_info(self, clusters: list[Cluster]) -> None:
        counts: dict[int, int] = {}
        for cluster in clusters:
            for i in cluster.indices:
                counts[i] = counts.get(i, 0) + 1

        for cluster in clusters:
            total_indices = len(cluster.indices)
            if total_indices == 0:
                continue
            excluded_indices = sum(1 for i in cluster.indices if counts[i] == 1)
            logger.info(
                f"{cluster.centroid}: {excluded_indices / total_indices:.2f}, {total_indices}"
            )

    def get_residuals(
        self, clusters: list[Cluster], attribs: list[str]
    ) -> tuple[list[str], list[str], list[int]]:
        all_indices: set[int] = set()
        for cluster in clusters:
            all_indices.update(cluster.indices)
        excluded_indices = [i for i in range(len(attribs)) if i not in all_indices]

        new_residuals = [attribs[i] for i in excluded_indices]
        finished = [attribs[i] for i in all_indices]
        return new_residuals, finished, excluded_indices

    def prune_small_clusters(
        self,
        clusters: list[Cluster],
        exclusive_threshold: float = 0.5,
    ) -> list[Cluster]:

        while True:
            bad_pairs = self.find_high_overlap_pairs(clusters, exclusive_threshold)
            if not bad_pairs:
                break

            bad_pairs.sort(key=lambda x: x[0], reverse=True)
            ratio, cluster1, cluster2 = bad_pairs[0]
            clusters.remove(cluster1)
            logger.info(
                f"Removed {cluster1.centroid} due to high overlap ({ratio:.2f}) with {cluster2.centroid}"
            )

        return clusters

    async def multiround_cluster(
        self,
        attribs: list[str],
        attribute: str,
        prune_fn: Callable[
            [list[Cluster], list[str], LlmApiClusterAssigner], Coroutine[Any, Any, list[Cluster]]
        ],
        num_rounds: int = 1,
        clustering_prompt_fn: Callable[[str, list[str]], str] | None = None,
        output_extractor: Callable[[str], list[str]] = parse_cluster_output,
    ) -> list[Cluster]:
        if not attribs:
            return []

        cluster_centroids: list[str] = await propose_clusters(
            attribs,
            extra_instructions_list=[f"Specifically focus on the following attribute: {attribute}"],
            feedback_list=[],
            clustering_prompt_fn=clustering_prompt_fn,
            output_extractor=output_extractor,
        )

        all_finished: list[str] = []
        all_clusters: list[Cluster] = []
        large = len(attribs) > self.SUBSET_THRESHOLD

        if large:
            logger.info(
                f"Using subset of {self.SUBSET_THRESHOLD} attributes for initial clustering due to large input size"
            )
            attribs_subset = random.sample(attribs, self.SUBSET_THRESHOLD)
        else:
            attribs_subset = attribs

        clusters = await self.run_attributes_through_clusters(attribs_subset, cluster_centroids)
        print(clusters)
        clusters = await prune_fn(clusters, attribs_subset, self.assigner)
        clusters = self.prune_clusters_of_high_overlap(clusters, exclusive_threshold=0.4)

        running_centroids = [cluster.centroid for cluster in clusters]
        logger.info(
            f"After pruning: kept {len(clusters)} clusters, removed {len(cluster_centroids) - len(clusters)}"
        )

        if large:
            clusters = await self.run_attributes_through_clusters(attribs, running_centroids)

        self.display_cluster_overlap_info(clusters)
        new_residuals, finished, indices_map = self.get_residuals(clusters, attribs)
        all_finished.extend(finished)
        all_clusters.extend(clusters)

        logger.info(
            f"-------done with stage {num_rounds} of clustering, {len(new_residuals)} / {len(attribs)} residuals remaining-------"
        )

        while True:
            num_rounds -= 1
            new_centroids = await propose_clusters(
                new_residuals,
                extra_instructions_list=[
                    f"Specifically focus on the following attribute: {attribute}. In addition, try your best to avoid suggesting things similar to the following list which someone else already suggested: {running_centroids}"
                ],
                feedback_list=None,
                clustering_prompt_fn=clustering_prompt_fn,
                output_extractor=output_extractor,
            )

            assert new_centroids is not None
            logger.info(f"Proposed {len(new_centroids)} new centroids for round {num_rounds}")

            large = len(new_residuals) > self.SUBSET_THRESHOLD
            if large:
                new_residuals_subset = random.sample(new_residuals, self.SUBSET_THRESHOLD)
            else:
                new_residuals_subset = new_residuals

            new_clusters = await self.run_attributes_through_clusters(
                new_residuals_subset, new_centroids
            )
            print(new_clusters)
            new_clusters = await prune_fn(new_clusters, new_residuals_subset, self.assigner)
            new_clusters = self.prune_small_clusters(
                new_clusters,
                exclusive_threshold=0.5,
            )

            running_new_centroids = [cluster.centroid for cluster in new_clusters]

            # Skip queries for already finished items if using HybridClusterAssigner
            for centroid in running_new_centroids:
                await self.assigner.skip_queries(all_finished, centroid)

            if large:
                new_clusters = await self.run_attributes_through_clusters(
                    new_residuals, running_new_centroids
                )

            self.display_cluster_overlap_info(new_clusters)
            new_residuals, finished, indices_map_update = self.get_residuals(
                new_clusters, new_residuals
            )
            for cluster in new_clusters:
                cluster.indices = {indices_map[i] for i in cluster.indices}
                cluster.metadata = {
                    k: [indices_map[i] for i in v] for k, v in cluster.metadata.items()
                }
            all_clusters.extend(new_clusters)
            all_finished.extend(finished)
            indices_map = [indices_map[i] for i in indices_map_update]

            logger.info(
                f"-------done with stage {num_rounds} of clustering, {len(new_residuals)} / {len(attribs)} residuals remaining---------"
            )

            running_centroids.extend(running_new_centroids)

            if num_rounds == 0 or len(new_residuals) < 0.05 * len(attribs):
                logger.info(
                    f"Terminating clustering: residuals_ratio={len(new_residuals)/len(attribs):.3f}"
                )
                break

        logger.info(f"Clustering completed with {len(all_clusters)} total clusters")
        return all_clusters


async def cluster_from_initial_proposal(
    attribs: list[str],
    attribute: str,
    assigner: LlmApiClusterAssigner,
    prune_fn: Callable[
        [list[Cluster], list[str], LlmApiClusterAssigner], Coroutine[Any, Any, list[Cluster]]
    ],
    num_rounds: int = 1,
    clustering_prompt_fn: Callable[[str, list[str]], str] | None = None,
    output_extractor: Callable[[str], list[str]] = parse_cluster_output,
) -> list[Cluster]:
    processor = ClusterProcessor(assigner)
    return await processor.multiround_cluster(
        attribs,
        attribute,
        prune_fn=prune_fn,
        num_rounds=num_rounds,
        clustering_prompt_fn=clustering_prompt_fn,
        output_extractor=output_extractor,
    )
