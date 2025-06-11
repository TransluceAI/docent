import asyncio
from typing import Any, Callable, Coroutine
from docent._ai_tools.clustering.cluster_assigner import LlmApiClusterAssigner
from docent._ai_tools.clustering.cluster_generator import propose_clusters
from docent._ai_tools.diffs.models import Claim, DiffTheme


def extract_fn(llm_output: str) -> list[DiffTheme]:
    import json
    from docent._ai_tools.diffs.models import DiffTheme

    try:
        print('-------------------------------- JSON extraction --------------------------------')
        print(llm_output)
        response = json.loads(llm_output)
        return [
            DiffTheme(
                name=theme["name"],
                description=theme["description"],
                claim_ids=theme["claim_ids"]
            )
            for theme in response["themes"]
        ]
    except json.JSONDecodeError:
        return []


CLAIM_FMT_2 = """
<claim>
    {{claim.claim_summary}}
    <claim_id>{{claim.id}}</claim_id>
    <shared_context>
        {{claim.shared_context}}
    </shared_context>
    <agent_1_action>
        {{claim.agent_1_action}}
    </agent_1_action>
    <agent_2_action>
        {{claim.agent_2_action}}
    </agent_2_action>
    <evidence>
        {{claim.evidence}}
    </evidence>
</claim>
"""


def prompt_build_fn(extra_instructions: str, diffs: list[str]) -> str:
    prompt = f"""You will be given a list of summaries of differences between two agents' performances on a variety of tasks. The list will be given in the following format:

            {CLAIM_FMT_2}

Based on this list, please propose a list of recurring themes where the first agent and the second agent consistently have different behaviors. Avoid repeating yourself in the output.
Try to choose recurring themes where the evidence for the theme clearly outweighs evidence in the reverse direction.

Themes should contain exactly one idea/concept each.
Themes should be mutually exclusive: no two themes should describe the same thing.
Themes should be collectively exhaustive: no item of the list should be left out.
Themes should include all the claims that are relevant to the theme; cite these by their claimIds.

Format the entirety of your output as a json object with the following format:
{{
    "themes": [
        {{
            "name": "Theme Name",
            "description": "Description of the theme and how it relates to the observed differences between agent 1 and agent 2",
            "claim_ids": ["claimId1", "claimId2", "claimId3"]
        }},
        ...
    ]
}}

Do NOT include any other text. Do NOT include ```json code fences or markdown blocks. Your entire response should be valid JSON.

{extra_instructions}

Here is the list of differences:

{'\n----------------\n'.join(diffs)}
    """.strip()

    print('-------------------------------- Prompt --------------------------------')
    print(prompt)
    return prompt


def format_transcript_diff_claim(claim: Claim) -> str:
    return f"""
<claim>
    {claim.claim_summary}
    <claim_id>{claim.id}</claim_id>
    <shared_context>
        {claim.shared_context}
    </shared_context>
    <agent_1_action>
        {claim.agent_1_action}
    </agent_1_action>
    <agent_2_action>
        {claim.agent_2_action}
    </agent_2_action>
    <evidence>
        {claim.evidence}
    </evidence>
</claim>
"""


async def cluster_diff_claims(
    claims: list[Claim],
) -> list[DiffTheme]:
    cluster_centroids: list[DiffTheme] = (
        await propose_clusters(
            [format_transcript_diff_claim(claim) for claim in claims],
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
- EXPLANATION: <leave this empty, another model will fill it in later>

Only reply yes if B is a direct example of C; if B and C are correlated but distinct behaviors, this does not count.

Here is your input:
C: {cluster}
B: {item}
""".strip()
    return ASSIGNMENT_PROMPT.format(cluster=cluster, item=item)


async def search_over_diffs(
    search_query: str,
    claims: list[str],
    search_result_callback: Callable[[tuple[str, int]], Coroutine[Any, Any, None]] | None = None,
) -> list[tuple[str, int]]:
    assigner = LlmApiClusterAssigner.from_sonnet_37_thinking(assign_prompt_fn)
    semaphore = asyncio.Semaphore(50)

    async def search_fn(claim: str) -> tuple[str, int]:
        async with semaphore:
            reverse_claim = (
                claim.replace("Agent 1", "Agent 3")
                .replace("Agent 2", "Agent 1")
                .replace("Agent 3", "Agent 2")
            )
            results = await assigner.assign(
                [claim, reverse_claim],
                [search_query, search_query],
            )
            is_match = results[0] is not None and results[0][0]
            is_reverse_match = results[1] is not None and results[1][0]
            if search_result_callback is not None:
                await search_result_callback((claim, is_match - is_reverse_match))
            return (claim, is_match - is_reverse_match)

    tasks: list[Coroutine[Any, Any, tuple[str, int]]] = []
    for claim in claims:
        tasks.append(search_fn(claim))
    results = await asyncio.gather(*tasks)
    return results

# async def assign_diff_claims_to_clusters(
#     claims: list[Claim],
#     clusters: list[str],
# ) -> list[str]:
#     return [cluster for cluster in clusters if cluster in claims]