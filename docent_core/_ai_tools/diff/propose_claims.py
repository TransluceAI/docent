import re
import traceback
from uuid import uuid4

import yaml
from pydantic import BaseModel, Field

from docent._log_util import get_logger
from docent_core._ai_tools.diff.diff import DiffQuery, DiffResult
from docent_core._ai_tools.search_paired import SearchPairedQuery
from docent_core._llm_util.prod_llms import get_llm_completions_async
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES

logger = get_logger(__name__)

PROPOSE_CLAIMS_PROMPT = """
We previously ran a diffing process to find specific cases where two agents had the same goals and context but took different actions.

Your task is to aggregate these low-level diffs into high-level claims about how models behave generally.

Here are the diffs:
{diffs}

A high-level claim consists of three parts:
- Shared context: this eliminates confounders by filtering to cases where the agents were trying to do the same thing
- Action 1: what agent 1 generally does in response to the shared context
- Action 2: what agent 2 generally does in response to the shared context
You are NOT allowed to explicitly mention agent 1 or 2 in your claim; that way we can verify it without biases.

Each part must be specified carefully enough to be checkable, yet broadly applicable across the dataset.

Output claims in the following format:
<claim>
Shared context: ...
Action 1: ...
Action 2: ...
</claim>

- Do not respond with any other text than the list of claims.
- Ensure that your output is valid XML and closes all tags.
""".strip()


class DiffClaimsResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    diff_query_id: str
    instances: list[SearchPairedQuery]


def _parse_claims_output(output: str, diff_query: DiffQuery) -> list[SearchPairedQuery]:
    """
    Parse the LLM output into a list of SearchPairedQuery objects.

    Args:
        output: The LLM output string containing claims in line-based format

    Returns:
        A list of SearchPairedQuery objects containing the parsed claims
    """
    claims: list[SearchPairedQuery] = []

    # Use regex to find all claim blocks
    claim_pattern = r"<claim>(.*?)</claim>"
    claim_matches = re.findall(claim_pattern, output, re.DOTALL)

    for claim_content in claim_matches:
        try:
            # Use regex to extract each field
            shared_context_match = re.search(
                r"Shared context:\s*(.+)", claim_content, re.IGNORECASE
            )
            action_1_match = re.search(r"Action 1:\s*(.+)", claim_content, re.IGNORECASE)
            action_2_match = re.search(r"Action 2:\s*(.+)", claim_content, re.IGNORECASE)

            # Extract the matched text or use empty string as fallback
            shared_context = shared_context_match.group(1).strip() if shared_context_match else ""
            action_1 = action_1_match.group(1).strip() if action_1_match else ""
            action_2 = action_2_match.group(1).strip() if action_2_match else ""

            if not shared_context:
                logger.warning("Missing shared context")
            if not action_1:
                logger.warning("Missing action 1")
            if not action_2:
                logger.warning("Missing action 2")

            claim = SearchPairedQuery(
                grouping_md_fields=diff_query.grouping_md_fields,
                md_field_value_1=diff_query.md_field_value_1,
                md_field_value_2=diff_query.md_field_value_2,
                context=shared_context,
                action_1=action_1,
                action_2=action_2,
            )
            claims.append(claim)
        except Exception as e:
            logger.error(
                f"Failed to parse claim content:\n{claim_content}\nError: {e}\nTraceback:\n{traceback.format_exc()}"
            )
            # Continue processing other claims even if this one fails

    return claims


async def execute_propose_claims(
    diff_results: list[DiffResult],
    diff_query: DiffQuery,
) -> DiffClaimsResult:
    # Format all diff results into a single prompt
    formatted_diffs = yaml.dump(
        [
            instance.to_cleaned_dict()
            for result in diff_results
            for instance in (result.instances or [])
        ],
        width=float("inf"),
    )

    if not formatted_diffs:
        # No valid instances to process
        return DiffClaimsResult(diff_query_id=diff_query.id, instances=[])

    prompt = PROPOSE_CLAIMS_PROMPT.format(diffs=formatted_diffs)

    # Single LLM call for all diff results
    outputs = await get_llm_completions_async(
        [
            [
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
        ],
        PROVIDER_PREFERENCES.execute_diff,  # Reuse the same provider preference
        max_new_tokens=8192,
        timeout=180.0,
        use_cache=True,
        # completion_callback=llm_callback,
    )

    # Parse the single output
    instances = (
        _parse_claims_output(outputs[0].first_text, diff_query)
        if outputs[0].first_text is not None
        else []
    )

    return DiffClaimsResult(diff_query_id=diff_query.id, instances=instances)
