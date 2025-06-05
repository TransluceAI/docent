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
