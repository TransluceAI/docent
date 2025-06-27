import re
from typing import Optional, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from docent_core._llm_util.data_models.llm_output import LLMOutput
from docent_core._llm_util.prod_llms import get_llm_completions_async
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES
from docent.data_models.agent_run import AgentRun
from docent.data_models.transcript import MULTI_RUN_CITE_INSTRUCTION


class ActionResult(BaseModel):
    """Represents whether an agent performed an action and optional explanation."""

    performed: bool
    explanation: Optional[str] = None


class SearchPairedInstance(BaseModel):
    """Represents a single instance of shared context and agent actions."""

    shared_context: str
    agent_1_action_1: ActionResult
    agent_1_action_2: ActionResult
    agent_2_action_1: ActionResult
    agent_2_action_2: ActionResult


class SearchPairedResult(BaseModel):
    """Represents a paired search result with metadata."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_run_1_id: str
    agent_run_2_id: str
    context: str
    action_1: str
    action_2: str
    instances: list[SearchPairedInstance] | None


class SearchPairedResultStreamingCallback(Protocol):
    """Supports batched streaming for paired search results."""

    async def __call__(
        self,
        search_results: list[SearchPairedResult] | None,
    ) -> None: ...


def _get_llm_streaming_callback_for_paired_search(
    context: str,
    action_1: str,
    action_2: str,
    paired_run_ids: list[tuple[str, str]],
    search_result_callback: SearchPairedResultStreamingCallback,
):
    async def _streaming_callback(batch_index: int, llm_output: LLMOutput):
        instances = (
            _parse_output(llm_output.first_text) if llm_output.first_text is not None else None
        )

        # Return nothing if the LLM call failed (hence None)
        if instances is None:
            await search_result_callback(None)
        else:
            agent_run_1_id, agent_run_2_id = paired_run_ids[batch_index]
            result = SearchPairedResult(
                agent_run_1_id=agent_run_1_id,
                agent_run_2_id=agent_run_2_id,
                context=context,
                action_1=action_1,
                action_2=action_2,
                instances=instances,
            )
            await search_result_callback([result])

    return _streaming_callback


SEARCH_PROMPT = f"""
I am trying to locate situations where two agents had similar contexts and goals but took different actions.

Here are a pair of agent runs:
<agent_run_1>
{{agent_run_1}}
</agent_run_1>
<agent_run_2>
{{agent_run_2}}
</agent_run_2>

Here is a specification of some shared context and two actions:
Context: {{context}}
Action 1: {{action_1}}
Action 2: {{action_2}}

Your task is to examine the two runs and:
- First locate ALL places where both runs share the specified context. If no instances exist, return N/A.
- For each location you find, determine whether each agent run took each action.

For each location, describe the shared context (with citations) and specify whether each agent performed each action. Your response MUST be in the following format:
<instance>
Shared context: ...
Agent 1 performed action 1: [Y/N] | [explanation if Y]
Agent 1 performed action 2: [Y/N] | [explanation if Y]
Agent 2 performed action 1: [Y/N] | [explanation if Y]
Agent 2 performed action 2: [Y/N] | [explanation if Y]
</instance>
...

{MULTI_RUN_CITE_INSTRUCTION}
""".strip()


async def execute_search_paired(
    paired_agent_runs: list[tuple[AgentRun, AgentRun]],
    context: str,
    action_1: str,
    action_2: str,
    search_result_callback: SearchPairedResultStreamingCallback | None = None,
):
    paired_run_ids = [(ar1.id, ar2.id) for ar1, ar2 in paired_agent_runs]

    llm_callback = (
        _get_llm_streaming_callback_for_paired_search(
            context, action_1, action_2, paired_run_ids, search_result_callback
        )
        if search_result_callback is not None
        else None
    )

    prompts = [
        SEARCH_PROMPT.format(
            agent_run_1=ar1.text,
            agent_run_2=ar2.text,
            context=context,
            action_1=action_1,
            action_2=action_2,
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
        PROVIDER_PREFERENCES.execute_search_paired,
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
        SearchPairedResult(
            agent_run_1_id=agent_run_1_id,
            agent_run_2_id=agent_run_2_id,
            context=context,
            action_1=action_1,
            action_2=action_2,
            instances=instances,
        )
        for instances, (agent_run_1_id, agent_run_2_id) in zip(instances_per_input, paired_run_ids)
    ]


def _parse_output(output: str) -> list[SearchPairedInstance]:
    if "N/A" in output.strip():
        return []

    # Extract all instance blocks
    instance_pattern = r"<instance>(.*?)</instance>"
    instance_matches = re.findall(instance_pattern, output, re.DOTALL)

    instances: list[SearchPairedInstance] = []

    for instance_text in instance_matches:
        try:
            # Extract shared context
            context_match = re.search(
                r"Shared context:\s*(.*?)$", instance_text.strip(), re.DOTALL | re.MULTILINE
            )
            if not context_match:
                continue
            shared_context = context_match.group(1).strip()
            print("shared_context", shared_context)

            # Extract agent action results
            print("instance_text", instance_text)
            action_pattern = r"Agent (\d+) performed action (\d+):\s*([YN])\s*(?:\|\s*([^\n]*))?$"
            action_matches = re.findall(action_pattern, instance_text, re.DOTALL | re.MULTILINE)
            print("action_matches", action_matches)

            # Initialize action results
            actions: dict[str, ActionResult] = {}
            for agent_num, action_num, yn, explanation in action_matches:
                performed = yn == "Y"
                explanation = explanation.strip() if explanation and explanation.strip() else None
                actions[f"agent_{agent_num}_action_{action_num}"] = ActionResult(
                    performed=performed, explanation=explanation
                )

            # Ensure we have all 4 required actions
            required_actions = [
                "agent_1_action_1",
                "agent_1_action_2",
                "agent_2_action_1",
                "agent_2_action_2",
            ]

            if all(action in actions for action in required_actions):
                instance = SearchPairedInstance(
                    shared_context=shared_context,
                    agent_1_action_1=actions["agent_1_action_1"],
                    agent_1_action_2=actions["agent_1_action_2"],
                    agent_2_action_1=actions["agent_2_action_1"],
                    agent_2_action_2=actions["agent_2_action_2"],
                )
                instances.append(instance)

        except Exception:
            # Skip malformed instances
            continue

    return instances
