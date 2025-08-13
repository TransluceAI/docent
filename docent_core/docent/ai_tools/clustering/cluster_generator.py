import re
from copy import deepcopy
from typing import Callable, TypedDict, TypeVar, cast

import numpy as np

from docent.data_models._tiktoken_util import truncate_to_token_limit
from docent_core._llm_util.prod_llms import get_llm_completions_async
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES

LARGE_CLUSTER_GUIDANCE = "Use as many clusters as you need to capture the variation in the items; we recommend generating between 5 and 10 clusters but sometimes more is necessary."

CLUSTER_PROMPT = """
Here are some items:
{items}

Please generate clusters from the provided list of items. {cluster_size_guidance}

Guidelines:
- Clusters should contain exactly one idea/concept each.
- Clusters should be mutually exclusive: no two clusters should describe the same thing.
- Clusters should be as close to collectively exhaustive as possible: ideally, no item should be left out.
- Cluster descriptions should be specific enough such that a reader could guess the items in the cluster. Indicate exactly what you mean, and do NOT give vague descriptions that could be misinterpreted.
- If a cluster description seems like it could pertain to a majority of the items, then it is too specific and should be broken up into multiple specific sub-clusters.
- If two clusters describe similar enough concepts such that they would overlap on over than half of their items, only mention the first cluster.
- If a cluster description only pertains to a single item, that does not count as a cluster and should not be used.
- Do NOT give examples of the items in the cluster, because that will overfit.
{extra_instructions}

In the output, each cluster should be on a new line, starting with a hyphen, as above. Return N/A if you can't find any clusters.

Structure each cluster in the form:
- <short description>: <elaboration>
For example:
- Missing Tools or Commands: Errors caused by essential tools or commands not being available in the environment.

The user may provide feedback on the clusters you propose; please take that into careful account.
""".strip()


class ClusterFeedback(TypedDict):
    clusters: list[str]
    feedback: str


def parse_cluster_output(raw_themes: str) -> list[str]:
    """
    Parse the raw output from the LLM into a list of cluster themes.

    Args:
        raw_themes: The raw text output from the LLM

    Returns:
        A list of extracted cluster themes
    """
    themes = re.findall(r"^-\s*(.+)", raw_themes, re.MULTILINE)
    return themes


T = TypeVar("T")  # ClusterType Object


async def propose_clusters(
    items: list[str],
    extra_instructions_list: list[str],
    feedback_list: list[ClusterFeedback] | None = None,
    random_seed: int = 42,
    clustering_prompt_fn: Callable[[str, list[str]], str] | None = None,
    output_extractor: Callable[[str], list[T]] = parse_cluster_output,
) -> list[T]:
    # Create a separate RNG for the outer sampling
    rng = np.random.RandomState(random_seed)

    # Sample k elements with replacement from both lists
    extra_instructions = cast(str, rng.choice(extra_instructions_list))  # type: ignore

    # Shuffle descriptions using a task-specific RNG
    task_rng = np.random.RandomState(random_seed)
    shuffled_items = deepcopy(items)
    task_rng.shuffle(shuffled_items)

    # Truncate items to 100k tokens
    all_items = "\n".join([f"- {d}" for d in shuffled_items])
    all_items = truncate_to_token_limit(all_items, 100_000)

    # Generate prompt
    prompt: list[dict[str, str]] = [
        {
            "role": "user",
            "content": (
                CLUSTER_PROMPT.format(
                    cluster_size_guidance=(
                        LARGE_CLUSTER_GUIDANCE
                        if len(items) > 20
                        else "You must generate between 3 and 6 clusters."
                    ),
                    extra_instructions=(f"\n{extra_instructions}\n" if extra_instructions else ""),
                    items=all_items,
                )
                if clustering_prompt_fn is None
                else clustering_prompt_fn(extra_instructions if extra_instructions else "", items)
            ),
        },
    ]

    # Add feedback if available
    for feedback in feedback_list or []:
        prompt.extend(
            [
                {
                    "role": "assistant",
                    "content": "\n".join([f"- {cluster}" for cluster in feedback["clusters"]]),
                },
                {
                    "role": "user",
                    "content": feedback["feedback"],
                },
            ]
        )

    # Make a single batch call to get_llm_completions_async
    outputs = await get_llm_completions_async(
        [prompt],
        PROVIDER_PREFERENCES.propose_clusters,
        max_new_tokens=8192,
        temperature=1.0,
        timeout=180.0,
        use_cache=True,
    )

    # Parse all results
    if outputs[0].first_text is None:
        raise ValueError("Could not propose clusters - no response from LLM")

    return output_extractor(outputs[0].first_text)
