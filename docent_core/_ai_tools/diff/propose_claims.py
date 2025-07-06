import re
import traceback
import xml.etree.ElementTree as ET
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
<shared_context>...</shared_context>
<action_1>...</action_1>
<action_2>...</action_2>
</claim>

- Do not respond with any other text than the list of claims.
- Ensure that your output is valid XML and closes all tags.
""".strip()


class DiffClaimsResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    diff_query_id: str
    instances: list[SearchPairedQuery]


def _get_text(element: ET.Element, tag_name: str) -> str:
    """Extract text content with fallback to empty string"""
    elem = element.find(tag_name)
    return elem.text.strip() if elem is not None and elem.text else ""


def _parse_claims_output(output: str, diff_query: DiffQuery) -> list[SearchPairedQuery]:
    """
    Parse the LLM output into a list of ClaimsInstance objects.

    Args:
        output: The LLM output string containing claims in XML-like format

    Returns:
        A list of ClaimsInstance objects containing the parsed claims
    """
    claims: list[SearchPairedQuery] = []

    # Use regex to find all claim blocks
    claim_pattern = r"<claim>(.*?)</claim>"
    claim_matches = re.findall(claim_pattern, output, re.DOTALL)

    for claim_content in claim_matches:
        # Parse each claim individually
        claim_xml = f"<claim>{claim_content}</claim>"
        try:
            claim_element = ET.fromstring(claim_xml)

            shared_context = _get_text(claim_element, "shared_context")
            action_1 = _get_text(claim_element, "action_1")
            action_2 = _get_text(claim_element, "action_2")

            claim = SearchPairedQuery(
                grouping_md_fields=diff_query.grouping_md_fields,
                md_field_value_1=diff_query.md_field_value_1,
                md_field_value_2=diff_query.md_field_value_2,
                context=shared_context,
                action_1=action_1,
                action_2=action_2,
            )
            claims.append(claim)
        except ET.ParseError:
            logger.error(
                f"Failed to parse individual claim XML:\n{claim_xml}\nTraceback:\n{traceback.format_exc()}"
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
