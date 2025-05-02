"""Defaults are defined at the bottom of the file."""

import os
import re
from abc import abstractmethod
from typing import Literal, cast

import torch
from docent._frames.types import AssignmentStreamingCallback
from llm_util.prod_llms import get_llm_completions_async
from llm_util.provider_preferences import PROVIDER_PREFERENCES
from llm_util.types import LLMApiKeys, LLMOutput
from log_util import get_logger
from tqdm.auto import tqdm
from transformers import (
    AutoTokenizer,
    ModernBertForSequenceClassification,
    PreTrainedTokenizer,
    PreTrainedTokenizerFast,
)

logger = get_logger(__name__)

ASSIGNMENT_PROMPT = """
You are given a cluster label C of an item I.
Your task is to perform membership testing: determine whether the description of C matches I.

The cluster label may come with examples, which you shouldn't treat as requirements; they simply give a feel for items that would belong.

Return two lines in the following exact format:
- ANSWER: <YES/NO>
- EXPLANATION: <concise but specific explanation; no more than a few high-information words>

Here is your input:
C: {cluster}
I: {item}
""".strip()


def _parse_llm_output(output: LLMOutput):
    pattern = r"(?i)\s*-?\s*ANSWER:\s*(YES|NO)\s*\n\s*-?\s*EXPLANATION:\s*(.*)"
    match = re.search(pattern, output.first_text or "")

    if match:
        answer, explanation = match.groups()
        return (answer.strip().upper() == "YES", explanation.strip())

    return None


def _get_llm_streaming_callback(
    assignment_streaming_callback: AssignmentStreamingCallback,
):
    async def _streaming_callback(batch_index: int, llm_output: LLMOutput):
        assignment = _parse_llm_output(llm_output)
        await assignment_streaming_callback(batch_index, assignment)

    return _streaming_callback


class ClusterAssigner:
    @abstractmethod
    async def assign(
        self,
        items: list[str],
        clusters: list[str],
        assignment_callback: AssignmentStreamingCallback | None = None,
        llm_api_keys: LLMApiKeys | None = None,
    ) -> list[tuple[bool, str] | None]:
        raise NotImplementedError


class ClusterAssignerFromLLM(ClusterAssigner):
    def __init__(
        self,
        system_prompt: str | None,
        model_name: str,
        max_new_tokens: int = 512,
        temperature: float = 0.25,
    ) -> None:
        super().__init__()
        self.system_prompt = system_prompt
        self.model_name = model_name
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        assert (
            model_name in PROVIDER_PREFERENCES.cluster_assignment
        ), f"Model name {model_name} not found in PROVIDER_PREFERENCES.cluster_assignment"

    @classmethod
    def from_o3_mini(cls):
        return cls(
            system_prompt=None,
            max_new_tokens=8192,
            temperature=1,
            model_name="o3-mini",
        )

    @classmethod
    def from_sonnet_37_thinking(cls):
        return cls(
            system_prompt=None,
            max_new_tokens=4096,
            temperature=1.0,
            model_name="sonnet-37-thinking",
        )

    async def assign(
        self,
        items: list[str],
        clusters: list[str],
        assignment_callback: AssignmentStreamingCallback | None = None,
        llm_api_keys: LLMApiKeys | None = None,
    ) -> list[tuple[bool, str] | None]:
        """
        For each (item, cluster, attribute), determines whether:
            - `item` fits under `cluster` where `cluster` describes some `attribute` of `item`

        Args:
            items: The list of items to assign to clusters.
            clusters: The list of cluster descriptions (i.e., centroids).
        Returns:
            A list of boolean values indicating whether each item fits under each cluster.
        """

        assert len(items) == len(
            clusters
        ), "Items, clusters, and attributes must be the same length"

        queries: list[list[dict[str, str]]] = [
            [
                *(
                    [{"role": "system", "content": self.system_prompt}]
                    if self.system_prompt
                    else []
                ),
                {
                    "role": "user",
                    "content": ASSIGNMENT_PROMPT.format(item=item, cluster=cluster),
                },
            ]
            for item, cluster in zip(items, clusters, strict=True)
        ]

        # Get the LLM callback if we're streaming
        llm_callback = (
            _get_llm_streaming_callback(assignment_callback)
            if assignment_callback is not None
            else None
        )

        outputs = await get_llm_completions_async(
            queries,
            **PROVIDER_PREFERENCES.cluster_assignment[self.model_name].create_shallow_dict(),
            max_new_tokens=self.max_new_tokens,
            temperature=self.temperature,
            timeout=30,
            completion_callback=llm_callback,
            use_cache=True,
            llm_api_keys=llm_api_keys,
        )
        return [_parse_llm_output(output) for output in outputs]


FINETUNED_ASSIGNMENT_PROMPT = """
Task: Determine if the following text describes {cluster_description}.\n\nText: {text}. Reply with only "Yes." or "No." \n\nAnswer:
""".strip()


class FinetunedModernBertClusterAssigner(ClusterAssigner):
    def __init__(
        self,
        model_path: str,
        device_id: int | Literal["MODAL"] = 0,
    ) -> None:
        super().__init__()
        if device_id != "MODAL":
            # assert there is a file at model_path
            assert os.path.exists(
                model_path
            ), f"Model file does not exist: {model_path}. Maybe you need to download an artifact?"
        self.model_path = model_path
        self._model: ModernBertForSequenceClassification | None = None
        self._tokenizer: PreTrainedTokenizer | PreTrainedTokenizerFast | None = None
        self.device = f"cuda:{device_id}" if device_id != "MODAL" else "MODAL"
        self.batch_size = 200  # vincent: empirically a good value for GPU utilization
        self._queries_to_skip: set[tuple[str, str]] = set()

    @property
    def tokenizer(self):
        if self._tokenizer is None:
            self._tokenizer = AutoTokenizer.from_pretrained("answerdotai/ModernBERT-large")  # type: ignore
        return self._tokenizer

    @property
    def model(self):
        if self._model is None:
            logger.info(f"Loading finetuned assignment model from {self.model_path}...")
            self._model = ModernBertForSequenceClassification.from_pretrained(self.model_path)  # type: ignore
            self._model.to(torch.bfloat16).to(self.device)  # type: ignore
            self._model.eval()
            logger.info("Finetuned assignment model loaded")
        return self._model

    def skip_queries(self, items: list[str], cluster: str):
        for i in items:
            self._queries_to_skip.add((i, cluster))

    def should_skip(self, item: str, cluster: str) -> bool:
        return (item, cluster) in self._queries_to_skip

    async def assign(
        self,
        items: list[str],
        clusters: list[str],
        assignment_callback: AssignmentStreamingCallback | None = None,
        llm_api_keys: LLMApiKeys | None = None,
    ) -> list[tuple[bool, str] | None]:
        """
        For each (item, cluster), determines whether item fits under cluster using a local fine-tuned model.

        Args:
            items: The list of items to assign to clusters.
            clusters: The list of cluster descriptions (i.e., centroids).
        Returns:
            A list of boolean values indicating whether each item fits under each cluster.
        """
        assert len(items) == len(clusters), "Items and clusters must be the same length"

        # Check cache first and collect uncached items
        results: list[tuple[bool, str] | None] = [None] * len(items)

        uncached_items: list[str] = []
        uncached_clusters: list[str] = []
        uncached_to_original_indices: list[int] = []

        for i in range(len(items)):
            if self.should_skip(items[i], clusters[i]):
                results[i] = (False, "Skipping this comparison as item has already been assigned")
            else:
                uncached_items.append(items[i])
                uncached_clusters.append(clusters[i])
                uncached_to_original_indices.append(i)

        # Process items in batches
        for start_idx in tqdm(
            range(0, len(uncached_items), self.batch_size), desc="ModernBERT inference"
        ):
            batch_items = uncached_items[start_idx : start_idx + self.batch_size]
            batch_clusters = uncached_clusters[start_idx : start_idx + self.batch_size]

            # Tokenize batch
            encoded_inputs = self.tokenizer(
                batch_clusters,
                batch_items,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=1024,
            )

            if self.device == "MODAL":
                import modal

                cls = modal.Cls.from_name("cluster-assigner", "ModalClusterAssigner")
                obj = cls()
                try:
                    batch_predictions, batch_probs = obj.assign.remote(encoded_inputs)
                except modal.exception.AuthError:
                    logger.warning(
                        f"Modal credentials not configured, falling back to other models"
                    )
                    return [
                        None,
                    ] * len(items)
            else:
                encoded_inputs.to(self.device)
                # Get model predictions
                with torch.no_grad():
                    outputs = self.model(**encoded_inputs)
                    logits = outputs.logits

                    # Get prediction and confidence
                    batch_probs = torch.softmax(logits, dim=1)
                    batch_predictions = torch.argmax(logits, dim=1)

            # Process batch predictions
            for batch_idx, (prediction, probabilities) in enumerate(
                zip(batch_predictions, batch_probs, strict=True)
            ):
                is_match = bool(prediction.item())
                confidence = probabilities[prediction].item()
                explanation = f"Confidence: {confidence:.2f}"
                result = (is_match, explanation)

                # Stream intermediate results if requested
                if assignment_callback is not None:
                    await assignment_callback(
                        uncached_to_original_indices[start_idx + batch_idx], (is_match, explanation)
                    )

                # Set result in return array
                results[uncached_to_original_indices[start_idx + batch_idx]] = result

        return results


BASE_ASSIGNERS = {
    "o3-mini": ClusterAssignerFromLLM.from_o3_mini(),
    "sonnet-37-thinking": ClusterAssignerFromLLM.from_sonnet_37_thinking(),
    "finetuned": FinetunedModernBertClusterAssigner(
        model_path="/home/ubuntu/artifacts/vincent/checkpoints/cluster_assignment_032225",
        device_id="MODAL",
    ),
}


class HybridClusterAssigner(ClusterAssigner):
    def __init__(
        self,
        finetuned_path: str,
        backup_model: str,
        device_id: int | Literal["MODAL"] = 0,
    ):
        self.primary = FinetunedModernBertClusterAssigner(finetuned_path, device_id=device_id)
        self.backup = cast(ClusterAssignerFromLLM, BASE_ASSIGNERS[backup_model])

    async def assign(
        self,
        items: list[str],
        clusters: list[str],
        assignment_callback: AssignmentStreamingCallback | None = None,
        llm_api_keys: LLMApiKeys | None = None,
    ) -> list[tuple[bool, str] | None]:
        # First, run everything through primary assigner
        # WARN: Do NOT pass assignment_callback, so judgments don't get incorrectly streamed
        # We only immediately stream NOs.
        results = await self.primary.assign(items, clusters, llm_api_keys=llm_api_keys)

        # For things assigned YES, we feed through o1 as we have a high recall primary model
        reassign_indices: list[int] = []
        for i, result in enumerate(results):
            # If it's a YES, reassign it
            if result is None or result[0]:
                reassign_indices.append(i)
            # If it's a NO, stream the result if requested; it will not be re-assigned
            elif not result[0]:
                if assignment_callback is not None:
                    await assignment_callback(i, result)

        # If we have any low confidence results, process them with backup
        if reassign_indices:
            logger.info(
                f"Falling back to {self.backup.model_name} LLM for {len(reassign_indices)}/{len(items)} items marked YES by BERT"
            )

            # Compute assignments
            backup_items = [items[i] for i in reassign_indices]
            backup_clusters = [clusters[i] for i in reassign_indices]

            async def _adjusted_assignment_callback(
                batch_index: int, assignment: tuple[bool, str] | None
            ):
                """Modified assignment callback that maps batch indices to original indices."""
                if assignment_callback is not None:
                    await assignment_callback(reassign_indices[batch_index], assignment)

            backup_results = await self.backup.assign(
                backup_items,
                backup_clusters,
                assignment_callback=_adjusted_assignment_callback,
                llm_api_keys=llm_api_keys,
            )

            # Replace low confidence results with backup results
            for idx, backup_result in zip(reassign_indices, backup_results, strict=True):
                results[idx] = backup_result

        return results


############
# Defaults #
############


ASSIGNERS: dict[str, ClusterAssigner] = {
    **BASE_ASSIGNERS,
    "hybrid": HybridClusterAssigner(
        finetuned_path="/home/ubuntu/artifacts/vincent/checkpoints/cluster_assignment_032225",
        backup_model=PROVIDER_PREFERENCES.assignment_model,
        device_id="MODAL",
    ),
}

DEFAULT_ASSIGNER = "hybrid"
AssignerType = Literal["o3-mini", "sonnet-37-thinking", "finetuned", "hybrid"]
