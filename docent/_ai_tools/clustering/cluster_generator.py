import re
from copy import deepcopy
from typing import TypedDict, cast

import numpy as np
import tiktoken

from docent._llm_util.prod_llms import get_llm_completions_async
from docent._llm_util.providers.preferences import PROVIDER_PREFERENCES


def truncate_to_token_limit(text: str, max_tokens: int, model: str = "gpt-4") -> str:
    """Truncate text to stay within the specified token limit."""
    encoding = tiktoken.encoding_for_model(model)
    tokens = encoding.encode(text)

    if len(tokens) <= max_tokens:
        return text

    return encoding.decode(tokens[:max_tokens])


CLUSTER_PROMPT = """
Here are some items:
{items}

Please generate {n_clusters} clusters from the provided list of items.

Guidelines:
- Clusters should contain exactly one idea/concept each.
- Clusters should be mutually exclusive: no two clusters should describe the same thing.
- Clusters should be collectively exhaustive: no item should be left out.
- Cluster descriptions should be specific enough such that a reader could guess the items in the cluster. Indicate exactly what you mean, and do NOT give vague descriptions that could be misinterpreted.
- Do NOT give examples of the items in the cluster, because that will overfit.
{extra_instructions}

In the output, each cluster should be on a new line, starting with a hyphen, as above. Return N/A if you can't find any clusters.

Structure each cluster in the form:
- <short description>: <elaboration>
For example:
- Missing Tools or Commands: Errors caused by essential tools or commands not being available in the environment.

The user may provide feedback on the clusters you propose; please take that into careful account.
""".strip()

# These lists are sampled, so duplicates indicate higher probability.
DEFAULT_N_CLUSTERS_LIST: list[int | str | None] = [
    # None,
    "between 1-5",
    "between 1-5",
    "between 1-5",
    "between 3-8",
    "between 5-10",
]
DEFAULT_EXTRA_INSTRUCTIONS_LIST: list[str | None] = [
    None,
    None,
    None,
    "Focus on the items you find most surprising or interesting.",
    "Focus on the items that seem to have the most related items.",
]


class ClusterFeedback(TypedDict):
    clusters: list[str]
    feedback: str


async def propose_clusters(
    items: list[str],
    n_clusters_list: list[int | str | None] = DEFAULT_N_CLUSTERS_LIST,
    extra_instructions_list: list[str | None] = DEFAULT_EXTRA_INSTRUCTIONS_LIST,
    feedback_list: list[ClusterFeedback] | None = None,
    k: int = 20,
    random_seed: int = 42,
):
    # Create a separate RNG for the outer sampling
    rng = np.random.RandomState(random_seed)

    # Sample k elements with replacement from both lists
    n_clusters_samples = cast(
        list[int | str | None], rng.choice(n_clusters_list, size=k, replace=True)  # type: ignore
    )
    extra_instructions_samples = cast(
        list[str | None], rng.choice(extra_instructions_list, size=k, replace=True)  # type: ignore
    )

    # Generate all prompts at once
    prompts: list[list[dict[str, str]]] = []
    for i, (_, extra_instructions) in enumerate(
        zip(n_clusters_samples, extra_instructions_samples)
    ):
        # Shuffle descriptions using a task-specific RNG
        task_rng = np.random.RandomState(random_seed + i)
        shuffled_items = deepcopy(items)
        task_rng.shuffle(shuffled_items)

        # Truncate items to 100k tokens
        all_items = "\n".join([f"- {d}" for d in shuffled_items])
        all_items = truncate_to_token_limit(all_items, 100_000)

        # Generate prompt
        prompt: list[dict[str, str]] = [
            {
                "role": "user",
                "content": CLUSTER_PROMPT.format(
                    # n_clusters=n_clusters or "an appropriate number of",
                    n_clusters=5,
                    extra_instructions=f"\n{extra_instructions}\n" if extra_instructions else "",
                    items=all_items,
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

        prompts.append(prompt)

    # Make a single batch call to get_llm_completions_async
    outputs = await get_llm_completions_async(
        prompts,
        PROVIDER_PREFERENCES.propose_clusters,
        max_new_tokens=4096,
        temperature=1.0,
        timeout=120.0,
        use_cache=True,
    )

    # Parse all results
    results = [parse_cluster_output(output.first_text or "<no response>") for output in outputs]

    return results


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
