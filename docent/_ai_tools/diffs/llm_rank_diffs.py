from docent._ai_tools.diffs.models import Claim
from docent._llm_util.data_models.llm_output import LLMOutput
from docent._llm_util.providers.preferences import PROVIDER_PREFERENCES
from docent._llm_util.prod_llms import get_llm_completions_async
from typing import List, Tuple

# Baseline
PROMPT_TEMPLATE_1 = """
You are an expert scientific assistant. Below are several claims about differences between agent runs, each describing a difference in approach, behavior, or outcome between two agents attempting the same task.

For each claim, rate its "interestingness" for a scientist or engineer analyzing agent behavior. Consider:
- Novelty: Is the difference surprising or unexpected?
- Impact: Does it affect correctness, safety, or performance?
- Informativeness: Does it reveal a new failure mode, insight, or hypothesis?

For each claim, provide:
- A score from 1 (not interesting) to 10 (extremely interesting)
- A brief justification for your score

Format your response as follows:
<rankings>
1. Score: [1-10]
   Justification: [short explanation]
2. Score: [1-10]
   Justification: [short explanation]
...
</rankings>

Here are the claims:
{claims_block}
"""

# 1-100 scale
PROMPT_TEMPLATE_2 = """
You are an expert scientific assistant. Below are several claims about differences between agent runs, each describing a difference in approach, behavior, or outcome between two agents attempting the same task.

For each claim, rate its "interestingness" for a scientist or engineer analyzing agent behavior. Consider:
- Novelty: Is the difference surprising or unexpected?
- Impact: Does it affect correctness, safety, or performance?
- Informativeness: Does it reveal a new failure mode, insight, or hypothesis?

For each claim, provide:
- A score from 1 (not interesting) to 100 (extremely interesting)
- A brief justification for your score

Format your response as follows:
<rankings>
1. Score: [1-100]
   Justification: [short explanation]
2. Score: [1-100]
   Justification: [short explanation]
...
</rankings>

Here are the claims:
{claims_block}
"""

def format_claims_for_prompt(claims: List[Claim]) -> str:
    out: List[str] = []
    for i, claim in enumerate(claims, 1):
        block = f"{i}. {claim.claim_summary}\n"
        if claim.shared_context:
            block += f"   Shared context: {claim.shared_context}\n"
        if claim.agent_1_action:
            block += f"   Agent 1: {claim.agent_1_action}\n"
        if claim.agent_2_action:
            block += f"   Agent 2: {claim.agent_2_action}\n"
        if claim.evidence:
            block += f"   Evidence: {claim.evidence}\n"
        out.append(block)
    return "".join(out)

import re

def parse_llm_rankings_output(output: str) -> List[Tuple[int, str]]:
    # Returns list of (score, justification)
    print(output)
    rankings: List[Tuple[int, str]] = []
    pattern = re.compile(r"\d+\.\s*Score:\s*(\d+)\s*Justification:\s*(.*?)(?=\n\d+\.|\n</rankings>|$)", re.DOTALL)
    for match in pattern.finditer(output):
        score = int(match.group(1))
        justification = match.group(2).strip()
        rankings.append((score, justification))
    return rankings

async def rank_claims_by_interestingness(claims: List[Claim]) -> List[Tuple[int, str]]:
    claims_block = format_claims_for_prompt(claims)
    prompt = PROMPT_TEMPLATE_2.format(claims_block=claims_block)
    result = ""
    async def _streaming_callback(batch_index: int, llm_output: LLMOutput):
        nonlocal result
        result = llm_output.completions[0].text
    outputs = await get_llm_completions_async(
        [
            [
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
        ],
        PROVIDER_PREFERENCES.compare_transcripts[0:1],
        max_new_tokens=2048,
        timeout=120.0,
        use_cache=True,
        streaming_callback=_streaming_callback,
    )
    text = outputs[0].first_text or result
    print(text)
    return parse_llm_rankings_output(text) 