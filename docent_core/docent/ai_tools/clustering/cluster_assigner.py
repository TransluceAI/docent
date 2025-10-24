import re
from abc import abstractmethod
from typing import Callable, Protocol

from docent._llm_util.data_models.llm_output import LLMOutput
from docent._llm_util.llm_svc import MessagesInput
from docent._llm_util.providers.preference_types import ModelOption
from docent._log_util import get_logger
from docent_core.docent.services.llms import PROVIDER_PREFERENCES, LLMService

logger = get_logger(__name__)

ASSIGNMENT_PROMPT = """
You are given a detailed item A and a broader item B.
Your task is to perform membership testing: determine whether the description of A matches B.

Return two lines in the following exact format:
- ANSWER: <YES/NO>
- EXPLANATION: <concise but specific explanation; no more than a few high-information words>

Here is your input:
A: {item}
B: {cluster}
""".strip()


class AssignmentStreamingCallback(Protocol):
    async def __call__(
        self,
        batch_index: int,
        assignment: tuple[bool, str] | None,
    ) -> None: ...


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
    def __init__(self, name: str):
        logger.info(f"Initializing assigner: {name}")
        self.name = name

    @abstractmethod
    async def skip_queries(self, items: list[str], cluster: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def assign(
        self,
        items: list[str],
        clusters: list[str],
        llm_svc: LLMService,
        assignment_callback: AssignmentStreamingCallback | None = None,
    ) -> list[tuple[bool, str] | None]:
        """For each (item, cluster, attribute), determines whether
            `item` fits under `cluster` where `cluster` describes some `attribute` of `item`

        Args:
            items: The list of items to assign to clusters.
            clusters: The list of cluster descriptions (i.e., centroids).
        Returns:
            A list of boolean values indicating whether each item fits under each cluster.
        """

        raise NotImplementedError


class LlmApiClusterAssigner(ClusterAssigner):
    def __init__(
        self,
        system_prompt: str | None,
        model_options: list[ModelOption],
        max_new_tokens: int,
        temperature: float,
        assign_prompt_fn: Callable[[str, str], str] | None = None,
    ) -> None:
        super().__init__(f"llm-api-{'/'.join([o.model_name for o in model_options])}")
        self.system_prompt = system_prompt
        self.assign_prompt_fn = assign_prompt_fn
        self.model_options = model_options
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature

    @classmethod
    def from_o4_mini(cls, assign_prompt_fn: Callable[[str, str], str] | None = None):
        return cls(
            system_prompt=None,
            max_new_tokens=8192,
            temperature=1,
            model_options=PROVIDER_PREFERENCES.cluster_assign_o4_mini,
            assign_prompt_fn=assign_prompt_fn,
        )

    async def assign(
        self,
        items: list[str],
        clusters: list[str],
        llm_svc: LLMService,
        assignment_callback: AssignmentStreamingCallback | None = None,
    ) -> list[tuple[bool, str] | None]:
        assert len(items) == len(
            clusters
        ), "Items, clusters, and attributes must be the same length"

        queries: list[MessagesInput] = [
            [
                *(
                    [{"role": "system", "content": self.system_prompt}]
                    if self.system_prompt
                    else []
                ),
                {
                    "role": "user",
                    "content": (
                        self.assign_prompt_fn(item, cluster)
                        if self.assign_prompt_fn
                        else ASSIGNMENT_PROMPT.format(item=item, cluster=cluster)
                    ),
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

        outputs = await llm_svc.get_completions(
            inputs=queries,
            model_options=self.model_options,
            max_new_tokens=self.max_new_tokens,
            temperature=self.temperature,
            timeout=30,
            completion_callback=llm_callback,
            use_cache=True,
        )
        return [_parse_llm_output(output) for output in outputs]


############
# Defaults #
############


async def assign(
    items: list[str],
    clusters: list[str],
    llm_svc: LLMService,
    assignment_callback: AssignmentStreamingCallback | None = None,
) -> list[tuple[bool, str] | None]:
    assigner = LlmApiClusterAssigner.from_o4_mini()
    return await assigner.assign(items, clusters, llm_svc, assignment_callback)
