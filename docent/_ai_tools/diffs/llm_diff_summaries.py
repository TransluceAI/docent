from uuid import uuid4

from docent._ai_tools.diff import (
    MULTI_RUN_CITE_INSTRUCTION,
    format_transcript_messages_and_states,
)
from docent._ai_tools.diffs.llm_message_summaries import compute_transcript_summaries
from docent._ai_tools.diffs.models import Claim, MessageState, TranscriptDiff
from docent._llm_util.data_models.llm_output import LLMOutput
from docent._llm_util.prod_llms import get_llm_completions_async
from docent._llm_util.providers.preferences import PROVIDER_PREFERENCES
from docent.data_models.agent_run import AgentRun
from docent.data_models.citation import parse_citations_multi_run
from docent.data_models.shared_types import EvidenceWithCitation

""" Vincent's original implementation"""


async def compare_transcript_states(
    transcript_1: AgentRun,
    transcript_2: AgentRun,
    states_1: list[MessageState],
    states_2: list[MessageState],
) -> str:
    prompt = f"""
Here are two different sequences of actions an agent took to solve a task. For each transcript, you will be given messages in the following format:

<message_idx_label>
Goal: [goal of the current action]
Relevant past actions: [summary of past actions that are relevant to the current goal, with citations]
Action: [a summary of the action taken]
Raw message: [raw message containing the action]
--------------------------------

First transcript:
{format_transcript_messages_and_states(transcript_1, states_1, 0)}
Second transcript:
{format_transcript_messages_and_states(transcript_2, states_2, 1)}

We care about instances where the two agents take different actions.
We are especially interested in cases where two agents have the same goal and context but take different actions (because that implies the difference in actions stems solely from a difference in the agents themselves), in which case you should mention the shared goals and context explicitly.
Cases where the two agents have different goals or context and take different actions may also be relevant, if the difference in actions is very interesting. In this case, you should mention the shared context/goals between the two agents, and also point out differences in the context/goals that may have caused the difference in observed actions.
Note that the ground truth is always the raw message, which shows the action the agent actually took; the summaries are provided to give you context, but we only wish to surface differences in the actual agent behaviors (rather than differences in provided summaries).

Here are some examples of differences, and the level of specifity in which we'd like them to be described:
<claim>
Both agents have read the task description and are trying to locate the test.py file, but agent 1 uses grep and succeeds while agent 2 uses tool calls and fails
</claim>
<claim>
Both models are trying to test their solutions, and agent 1 writes much more detailed tests than agent 2. However, this may partially be explained by the fact that agent 1's solution is more complex than agent 2's solution.
</claim>

Look through the transcripts and list the major differences in actions between the two agents. If there are no major differences, minor differences are also fine.

Use these guidelines for citations: {MULTI_RUN_CITE_INSTRUCTION}

Format your final list as follows:
<claim>
both agents have similar context W and want to accomplish X, but agent 1 does Y while agent 2 does Z
</claim>
<evidence>
explain W, X, Y, Z, with citations
</evidence>
<claim>
both agents want to accomplish X, but agent 1 does Y while agent 2 does Z. however, this difference may be partially explained by agent 1 having context W, while agent 2 has context W'
</claim>
<evidence>
explain X, Y, Z, W, W', with citations
</evidence>
...

Do not respond with any other text than the list of claims and evidence.
Always refer to the first transcript as "Agent 1" and the second as "Agent 2".
Explicitly mention the different actions each agents took. Explicitly qualify claims by stating which context and goals are shared between the agents, and which are different (and how they are different).
    """.strip()

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
        max_new_tokens=8192 * 5,
        timeout=240.0,
        use_cache=True,
        streaming_callback=_streaming_callback,
    )

    text = outputs[0].first_text
    if text is None:
        return ""
    return text


async def get_llm_output_compare_transcript_states_v2(
    transcript_1: AgentRun,
    transcript_2: AgentRun,
    states_1: list[MessageState],
    states_2: list[MessageState],
) -> str:
    prompt = f"""
Here are two different sequences of actions an agent took to solve a task. For each transcript, you will be given messages in the following format:

<message_idx_label>
Goal: [goal of the current action]
Relevant past actions: [summary of past actions that are relevant to the current goal, with citations]
Action: [a summary of the action taken]
Raw message: [raw message containing the action]
--------------------------------

First transcript:
{format_transcript_messages_and_states(transcript_1, states_1, 0)}
Second transcript:
{format_transcript_messages_and_states(transcript_2, states_2, 1)}

Your job is to note the interesting differences between the approaches taken by the two agents, as indicated by their transcripts and message summaries.

We care about instances where the two agents take different actions.
We are especially interested in cases where two agents have the same goal and context, but take different actions (because that implies the difference in actions stems solely from a difference in the agents themselves), in which case you should mention the shared goals and context explicitly.
Cases where the two agents have different goals or context and take different actions may also be relevant, if the difference in actions is very interesting. In this case, you should mention the shared context/goals between the two agents, and also point out differences in the context/goals that may have caused the difference in observed actions.
Note that the ground truth is always the raw message, which shows the action the agent actually took; the summaries are provided to give you context, but we only wish to surface differences in the actual agent behaviors (rather than differences in provided summaries).

Here are some examples of differences, and the level of specifity in which we'd like them to be described:

<claim>
    Agent 1 succeeds in locating the test.py file with grep, while Agent 2 fails.
    <shared_context>
        Both agents have read the task description and are trying to locate the test.py file.
    </shared_context>
    <agent_1_action>
        Uses grep and succeeds
    </agent_1_action>
    <agent_2_action>
        Uses tool calls and fails
    </agent_2_action>
    <evidence>
        Agent 1 uses grep successfully [T0B40].
        Agent 2, tries multiple tool calls and fails [T1B41][T1B43]
    </evidence>
</claim>

<claim>
    Agent 1 writes much more detailed tests, but this may partially be explained by agent 1 having more complex solution.
    <shared_context>
        Both models are trying to test their solutions
    </shared_context>
    <agent_1_action>
        Writes tests for each helper function, and tests edge cases.
    </agent_1_action>
    <agent_2_action>
    </agent_2_action>
</claim>

<claim>
    Agent 1 requests clarification while Agent 2 makes assumptions about ambiguous requirements.
    <shared_context>
        Both agents encounter unclear specification about edge case handling.
    </shared_context>
    <agent_1_action>
        Explicitly asks user to clarify expected behavior for empty input
    </agent_1_action>
    <agent_2_action>
        Implements default behavior without asking, assumes empty returns empty
    </agent_2_action>
    <evidence>
        Agent 1's clarification request [T0B08]. Agent 2's assumption [T1B07]
    </evidence>
</claim>

<claim>
    Agent 1 handles errors gracefully while Agent 2 allows exceptions to propagate.
    <shared_context>
        Both agents implement file reading functionality knowing files may not exist.
    </shared_context>
    <agent_1_action>
        Wraps file operations in try-catch, returns meaningful error messages
    </agent_1_action>
    <agent_2_action>
        Calls file operations directly, lets FileNotFoundError bubble up
    </agent_2_action>
    <evidence>
        Agent 1's error handling [T0B31]. Agent 2's direct calls [T1B28]
    </evidence>
</claim>

Look through the transcripts and list the major differences in actions between the two agents. If there are no major differences, minor differences are also fine.

Use these guidelines for citations: {MULTI_RUN_CITE_INSTRUCTION}

Format each entry in your final list of claims follows:
<claim>
    {{High level description of the difference}}
    <shared_context>
        {{Shared context between the two agents}}
    </shared_context>
    <agent_1_action>
        {{Action taken by agent 1}}
    </agent_1_action>
    <agent_2_action>
        {{Action taken by agent 2}}
    </agent_2_action>
    <evidence>
        {{Citations for the action taken by agent 1}}
        {{Citations for the action taken by agent 2}}
    </evidence>
</claim>


Do not respond with any other text than the list of claims and evidence.
Always refer to the first transcript as "Agent 1" and the second as "Agent 2".
Explicitly mention the different actions each agents took. Explicitly qualify claims by stating which context and goals are shared between the agents, and which are different (and how they are different).
    """.strip()

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
        max_new_tokens=8192 * 5,
        timeout=240.0,
        use_cache=True,
        streaming_callback=_streaming_callback,
    )

    text = outputs[0].first_text
    if text is None:
        return ""
    return text


def _parse_llm_output_to_claims(output: str) -> list[Claim]:
    """
    Parse the LLM output into a TranscriptDiff object.

    Args:
        output: The LLM output string containing claims and evidence
        agent_run_1_id: The ID of the first agent run
        agent_run_2_id: The ID of the second agent run

    Returns:
        A TranscriptDiff object containing the parsed claims
    """
    claims: list[Claim] = []
    curr_index: int = 0

    while True:
        # Find the next claim block
        start_claim_index = output.find("<claim>", curr_index)
        if start_claim_index == -1:
            break

        end_claim_index = output.find("</claim>", start_claim_index)
        if end_claim_index == -1:
            break

        # Extract the claim content
        claim_content = output[start_claim_index + len("<claim>") : end_claim_index].strip()

        # Parse the claim content into its components
        claim_summary = ""
        shared_context = None
        agent_1_action = ""
        agent_2_action = ""
        evidence = ""

        # Extract shared context if present
        shared_context_start = claim_content.find("<shared_context>")
        if shared_context_start != -1:
            shared_context_end = claim_content.find("</shared_context>", shared_context_start)
            if shared_context_end != -1:
                shared_context = claim_content[
                    shared_context_start + len("<shared_context>") : shared_context_end
                ].strip()

        # Extract agent actions
        agent_1_start = claim_content.find("<agent_1_action>")
        if agent_1_start != -1:
            agent_1_end = claim_content.find("</agent_1_action>", agent_1_start)
            if agent_1_end != -1:
                agent_1_action = claim_content[
                    agent_1_start + len("<agent_1_action>") : agent_1_end
                ].strip()

        agent_2_start = claim_content.find("<agent_2_action>")
        if agent_2_start != -1:
            agent_2_end = claim_content.find("</agent_2_action>", agent_2_start)
            if agent_2_end != -1:
                agent_2_action = claim_content[
                    agent_2_start + len("<agent_2_action>") : agent_2_end
                ].strip()

        # Extract evidence
        evidence_start = claim_content.find("<evidence>")
        if evidence_start != -1:
            evidence_end = claim_content.find("</evidence>", evidence_start)
            if evidence_end != -1:
                evidence = claim_content[evidence_start + len("<evidence>") : evidence_end].strip()

        # Extract claim summary - it's the text before any of the XML-style tags
        first_tag_index = min(
            i
            for i in [
                shared_context_start if shared_context_start != -1 else float("inf"),
                agent_1_start if agent_1_start != -1 else float("inf"),
                agent_2_start if agent_2_start != -1 else float("inf"),
                evidence_start if evidence_start != -1 else float("inf"),
            ]
        )
        if first_tag_index != float("inf"):
            claim_summary = claim_content[:first_tag_index].strip()
        else:
            claim_summary = claim_content.strip()

        # Create the Claim object
        claim = Claim(
            id=str(uuid4()),
            idx=len(claims),
            claim_summary=claim_summary,
            shared_context=shared_context,
            agent_1_action=agent_1_action,
            agent_2_action=agent_2_action,
            evidence=evidence,
            evidence_with_citations=EvidenceWithCitation(
                evidence=evidence, citations=parse_citations_multi_run(evidence)
            ),
        )
        claims.append(claim)

        curr_index = end_claim_index + len("</claim>")
    return claims


async def llm_summarize_transcript_title(transcript_1: AgentRun, transcript_2: AgentRun) -> str:

    def format_transcript(transcript: AgentRun) -> str:
        return "\n".join([m.text for m in transcript.transcripts["default"].messages[0:5]])

    prompt = f"""
Here are two different sequences of actions an agent took to solve a task.
First transcript:
{format_transcript(transcript_1)}
Second transcript:
{format_transcript(transcript_2)}
Examine the transcripts, and summarize the title of the task that the agents are trying to solve.

Format your response as a single phrase.

Example:
CheckConstraint with OR operator generates incorrect SQL on SQLite and Oracle.
Management command subparsers don't retain error formatting

""".strip()

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
        max_new_tokens=8192 * 5,
        timeout=240.0,
        use_cache=True,
        streaming_callback=_streaming_callback,
    )

    text = outputs[0].first_text
    if text is None:
        return ""
    return text


async def compute_transcript_diff(
    transcript_1: AgentRun, transcript_2: AgentRun, diffs_report_id: str
) -> TranscriptDiff:
    summaries_1: list[MessageState] = await compute_transcript_summaries(transcript_1)
    summaries_2: list[MessageState] = await compute_transcript_summaries(transcript_2)
    llm_diff_output = await get_llm_output_compare_transcript_states_v2(
        transcript_1, transcript_2, summaries_1, summaries_2
    )
    claims = _parse_llm_output_to_claims(llm_diff_output)
    title = await llm_summarize_transcript_title(transcript_1, transcript_2)
    diff = TranscriptDiff(
        id=str(uuid4()),
        diffs_report_id=diffs_report_id,
        agent_run_1_id=transcript_1.id,
        agent_run_2_id=transcript_2.id,
        title=title,
        claims=claims,
    )
    return diff
