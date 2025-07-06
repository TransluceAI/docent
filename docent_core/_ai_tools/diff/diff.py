import re
import traceback
import xml.etree.ElementTree as ET
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.citation import parse_citations_multi_run
from docent.data_models.shared_types import EvidenceWithCitation
from docent.data_models.transcript import MULTI_RUN_CITE_INSTRUCTION
from docent_core._llm_util.data_models.llm_output import LLMOutput
from docent_core._llm_util.prod_llms import get_llm_completions_async
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES

logger = get_logger(__name__)

# - Cases where the two agents have different goals or context and take different actions may also be relevant, if the difference in actions is very interesting. In this case, you should mention the shared context/goals between the two agents, and also point out differences in the context/goals that may have caused the difference in observed actions.
# - We care about instances where the two agents take different actions.

DIFF_PROMPT = f"""
Here are two different sequences of actions an agent took to solve a task.

First agent:
{{agent_run_1}}
Second agent:
{{agent_run_2}}

Your job is to note the interesting differences in the actions of two agents. Here are some criteria:
- We are ONLY interested in cases where two agents have the same immediate goal and context, but take different actions. This implies that the difference in actions stems solely from a difference in the agents themselves.
- We are looking for context-action pairs that are *local*. It does not count if the action is very far after the context.
{{focus_text}}

List the major differences in actions between the two agents. Use these guidelines for citations: {MULTI_RUN_CITE_INSTRUCTION}

Format each entry in your final list of claims follows:
<claim>
<summary>
High level description of the difference
</summary>
<shared_context>
Shared context between the two agents
</shared_context>
<agent_1_action>
Action taken by agent 1
</agent_1_action>
<agent_1_evidence>
Evidence for the action taken by agent 1
</agent_1_evidence>
<agent_2_action>
Action taken by agent 2
</agent_2_action>
<agent_2_evidence>
Evidence for the action taken by agent 2
</agent_2_evidence>
</claim>

- Do not respond with any other text than the list of claims and evidence.
- Always refer to the first agent as "Agent 1" and the second as "Agent 2".
- Explicitly mention the different actions each agents took. Explicitly qualify claims by stating which context and goals are shared between the agents, and which are different (and how they are different).
- Ensure that your output is valid XML and closes all tags.
- If you cannot find any differences, respond with "N/A".
""".strip()


class DiffQuery(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    grouping_md_fields: list[str]
    md_field_value_1: tuple[str, Any]
    md_field_value_2: tuple[str, Any]

    # Allow focusing on particular aspects
    focus: str | None


class DiffInstance(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))

    summary: str
    shared_context: str
    agent_1_action: str
    agent_1_evidence: EvidenceWithCitation
    agent_2_action: str
    agent_2_evidence: EvidenceWithCitation

    def to_cleaned_dict(self) -> dict[str, Any]:
        d = self.model_dump(exclude={"id"})
        d["agent_1_evidence"] = self.agent_1_evidence["evidence"]
        d["agent_2_evidence"] = self.agent_2_evidence["evidence"]
        return d


class DiffResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_run_1_id: str
    agent_run_2_id: str
    instances: list[DiffInstance] | None


class DiffResultStreamingCallback(Protocol):
    async def __call__(
        self,
        diff_results: list[DiffResult],
    ) -> None: ...


def _get_llm_streaming_callback_for_diff(
    paired_agent_runs: list[tuple[AgentRun, AgentRun]],
    diff_result_callback: DiffResultStreamingCallback,
):
    async def _streaming_callback(batch_index: int, llm_output: LLMOutput):
        instances = (
            _parse_output(llm_output.first_text) if llm_output.first_text is not None else None
        )

        result = DiffResult(
            agent_run_1_id=paired_agent_runs[batch_index][0].id,
            agent_run_2_id=paired_agent_runs[batch_index][1].id,
            instances=instances,  # Is None if the LLM call failed
        )
        await diff_result_callback([result])

    return _streaming_callback


# Extract text content with fallback to empty string
def _get_text(element: ET.Element, tag_name: str) -> str:
    elem = element.find(tag_name)
    return elem.text.strip() if elem is not None and elem.text else ""


def _parse_output(output: str):
    """
    Parse the LLM output into a list of DiffInstance objects.

    Args:
        output: The LLM output string containing claims in XML-like format
        agent_run_1_id: ID of the first agent run
        agent_run_2_id: ID of the second agent run

    Returns:
        A list of DiffInstance objects containing the parsed claims
    """

    diffs: list[DiffInstance] = []

    # Use regex to find all claim blocks
    claim_pattern = r"<claim>(.*?)</claim>"
    claim_matches = re.findall(claim_pattern, output, re.DOTALL)

    for claim_content in claim_matches:
        # Parse each claim individually
        claim_xml = f"<claim>{claim_content}</claim>"
        try:
            claim_element = ET.fromstring(claim_xml)

            summary = _get_text(claim_element, "summary")
            shared_context = _get_text(claim_element, "shared_context")
            agent_1_action = _get_text(claim_element, "agent_1_action")
            agent_1_evidence = _get_text(claim_element, "agent_1_evidence")
            agent_2_action = _get_text(claim_element, "agent_2_action")
            agent_2_evidence = _get_text(claim_element, "agent_2_evidence")

            claim = DiffInstance(
                summary=summary,
                shared_context=shared_context,
                agent_1_action=agent_1_action,
                agent_1_evidence=EvidenceWithCitation(
                    evidence=agent_1_evidence,
                    citations=parse_citations_multi_run(agent_1_evidence),
                ),
                agent_2_action=agent_2_action,
                agent_2_evidence=EvidenceWithCitation(
                    evidence=agent_2_evidence,
                    citations=parse_citations_multi_run(agent_2_evidence),
                ),
            )
            diffs.append(claim)
        except ET.ParseError:
            logger.error(
                f"Failed to parse individual claim XML:\n{claim_xml}\nTraceback:\n{traceback.format_exc()}"
            )
            # Continue processing other claims even if this one fails

    return diffs


async def execute_diff(
    paired_agent_runs: list[tuple[AgentRun, AgentRun]],
    focus: str | None,
    diff_result_callback: DiffResultStreamingCallback | None = None,
):
    llm_callback = (
        _get_llm_streaming_callback_for_diff(paired_agent_runs, diff_result_callback)
        if diff_result_callback is not None
        else None
    )

    prompts = [
        DIFF_PROMPT.format(
            agent_run_1=ar1.text,
            agent_run_2=ar2.text,
            focus_text=f"Focus your observations specifically on: {focus}" if focus else "",
        )
        for ar1, ar2 in paired_agent_runs
    ]
    outputs = await get_llm_completions_async(
        [
            [
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
            for prompt in prompts
        ],
        PROVIDER_PREFERENCES.execute_diff,
        max_new_tokens=8192,
        timeout=180.0,
        use_cache=True,
        completion_callback=llm_callback,
    )

    instances_per_input = [
        _parse_output(output.first_text) if output.first_text is not None else None
        for output in outputs
    ]
    return [
        DiffResult(
            agent_run_1_id=paired_agent_runs[i][0].id,
            agent_run_2_id=paired_agent_runs[i][1].id,
            instances=instances,
        )
        for i, instances in enumerate(instances_per_input)
    ]
