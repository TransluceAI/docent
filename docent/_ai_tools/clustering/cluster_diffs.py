import asyncio
from typing import Any, Coroutine
from docent._ai_tools.clustering.cluster_assigner import LlmApiClusterAssigner
from docent._ai_tools.clustering.cluster_generator import propose_clusters
from docent._ai_tools.diff import DiffAttribute


def extract_fn(llm_output: str) -> list[str]:
    results: list[str] = []
    start_index = llm_output.find("<theme_start>")
    index = 1
    while start_index != -1:
        end_index = llm_output.find("<theme_end>", start_index)
        substring = llm_output[start_index:end_index]
        substring = substring.removeprefix("<theme_start>")
        substring = substring.removeprefix("\n")
        substring = substring.removeprefix(f"Theme {index}:")
        results.append(substring.strip())
        start_index = llm_output.find("<theme_start>", end_index)
        index += 1
    return results


def prompt_build_fn(extra_instructions: str, diffs: list[str]) -> str:
    prompt = f"""You will be given a list of summaries of differences between two agents' performances on a variety of tasks. The list will be given in the following format:

<claim>
Agent 1 and agent 2 were both trying to accomplish X, but agent 1 did Y while agent 2 did Z.
</claim>
<evidence>
evidence for the claim, eg. specific examples where agent 1 is more of X than agent 2
</evidence>
----------------
<claim>
Agent 1 and agent 2 were both trying to accomplish X', but agent 1 did Y' while agent 2 did Z'.
</claim>
<evidence>
evidence for the claim, eg. specific examples where agent 1 is more of X' than agent 2
</evidence>
----------------
...

Based on this list, please propose a list of recurring themes where the first agent and the second agent consistently have different behaviors. Avoid repeating yourself in the output.
Try to choose recurring themes where the evidence for the theme clearly outweighs evidence in the reverse direction.

Themes should contain exactly one idea/concept each.
Themes should be mutually exclusive: no two themes should describe the same thing.
Themes should be collectively exhaustive: no item of the list should be left out.

Format your output in this format:

<theme_start>
Description of the theme and how it relates to agent 1 and agent 2
<theme_end>
<theme_start>
Description of the theme and how it relates to agent 1 and agent 2
<theme_end>
...

{extra_instructions}

Here is the list of differences:

{'\n----------------\n'.join(diffs)}
    """.strip()
    return prompt


def format_diff_attribute(diff: DiffAttribute) -> str:
    return f"""<claim>
{diff.claim}
</claim>
<evidence>
{diff.evidence}
</evidence>"""


async def cluster_diffs(
    all_diffs: list[DiffAttribute],
) -> list[str]:
    cluster_centroids: list[str] = (
        await propose_clusters(
            [format_diff_attribute(diff) for diff in all_diffs],
            n_clusters_list=[None],
            extra_instructions_list=[
                "Specifically focus on the following attribute: ways in which agent 1 and agent 2 differ"
            ],
            feedback_list=[],
            k=1,
            clustering_prompt_fn=prompt_build_fn,
            output_extractor=extract_fn,
        )
    )[0]
    return cluster_centroids


def assign_prompt_fn(item: str, cluster: str) -> str:
    ASSIGNMENT_PROMPT = """
You are given a claim C and a behavior B.
Your task is to determine whether B is a direct example of C.

The claim may come with examples, which you shouldn't treat as strict requirements.

Return two lines in the following exact format:
- ANSWER: <YES/NO>
- EXPLANATION: <concise but specific explanation; no more than a few high-information words>

Only reply yes if B is a direct example of C; if B and C are correlated but distinct behaviors, this does not count.

Here is your input:
C: {cluster}
B: {item}
""".strip()
    stripped_item = item.removeprefix("<claim>").split("</claim>")[0].strip()
    return ASSIGNMENT_PROMPT.format(cluster=cluster, item=stripped_item)


async def search_over_diffs(search_query: str, attributes: list[str]) -> list[tuple[bool, bool]]:
    assigner = LlmApiClusterAssigner.from_sonnet_37_thinking(assign_prompt_fn)
    # TODO(vincent): semaphore, each fn should compare both directions
    semaphore = asyncio.Semaphore(50)
    reverse_query = (
        search_query.replace("Agent 1", "Agent 3")
        .replace("Agent 2", "Agent 1")
        .replace("Agent 3", "Agent 2")
    )

    async def search_fn(attribute: str) -> tuple[bool, bool]:
        results = await assigner.assign(
            [attribute, attribute],
            [search_query, reverse_query],
        )
        return (
            results[0] is not None and results[0][0],
            results[1] is not None and results[1][0],
        )

    tasks: list[Coroutine[Any, Any, tuple[bool, bool]]] = []
    for attribute in attributes:
        async with semaphore:
            tasks.append(search_fn(attribute))
    results = await asyncio.gather(*tasks)
    return results
