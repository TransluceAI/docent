from docent.data_models.transcript import (
    MULTI_BLOCK_CITE_INSTRUCTION,
    SINGLE_BLOCK_CITE_INSTRUCTION,
)
from docent.data_models.agent_run import AgentRun
from docent._llm_util.prod_llms import get_llm_completions_async
from docent._llm_util.providers.preferences import PROVIDER_PREFERENCES
from pydantic import BaseModel, Field
from uuid import uuid4
from docent._llm_util.data_models.llm_output import LLMOutput
from tqdm.asyncio import tqdm


class DiffAttribute(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    data_id_1: str
    data_id_2: str
    attribute: str = (
        ""  # unused for now. but will probably support diffing along some known axis later
    )
    attribute_idx: int | None = None
    claim: str | None = None
    evidence: str | None = None


async def extract_states(
    transcript: AgentRun,
) -> str:
    prompt = f"""
Here is a sequence of actions an agent took to solve a task.
{transcript.transcripts["default"].to_str()}

Note that each message in the sequence can have one of several roles - system, user, assistant, or tool.

For each ASSISTANT message, perform the following procedure:
- Summarize the action taken in the message
- Summarize the goal of the agent's current action
- Provide a concise but specific summary of the agent's past actions that are relevant to the current goal. You are encouraged to cite evidence from the transcripts: {SINGLE_BLOCK_CITE_INSTRUCTION}

Do not mention non-assistant messages in your output.

Here are some examples of the level of specifity in which we'd like to describe the messages in.

Action: The agent uses grep to find the test.py file.
Goal: The agent is trying to explore the codebase and read code relevant to the task.capitalize
Relevant past actions: None, this is the first action taken by the agent.

Action: The agent is editing OAuth configuration settings in its test script.
Goal: The agent is trying to get its test script to run without errors.
Relevant past actions: The agent previously wrote a test script, but upon execution it produced an OutOfBoundsError. <further explanation and citations>

Action: The agent is writing a detailed test script that tests for many edge cases.
Goal: The agent is trying to test its solution to ensure correctness.
Relevant past actions: The agent previously implemented a solution that resolves the issue by modifying the function to use sets instead of lists. <further explanation and citations>

Format your output as follows:
[B<message_idx>]
Action: [action taken]
Goal: [goal of the action]
Relevant past actions: [summary of past actions that are relevant to the current goal, with citations]
[B<message_idx>]
Action: [action taken]
Goal: [goal of the action]
Relevant past actions: [summary of past actions that are relevant to the current goal, with citations]
...
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
        PROVIDER_PREFERENCES.compare_transcripts,
        max_new_tokens=8192 * 4,
        timeout=240.0,
        use_cache=True,
        streaming_callback=_streaming_callback,
    )

    text = outputs[0].first_text
    if text is None:
        return ""
    return text


class MessageState:
    def __init__(self, message_idx: int, action: str, goal: str, past_actions: str):
        self.message_idx = message_idx
        self.action = action
        self.goal = goal
        self.past_actions = past_actions

    def __str__(self):
        return f"[B{self.message_idx}]\nAction: {self.action}\nGoal: {self.goal}\nRelevant past actions: {self.past_actions}"


def parse_output(output: str) -> list[MessageState]:
    result: list[MessageState] = []
    idx, action, goal, past_actions = -1, "", "", ""
    for line in output.split("\n"):
        if line.startswith("[B"):
            idx = int(line.removeprefix("[B").removesuffix("]"))
            action, goal, past_actions = "", "", ""
        elif line.startswith("Action:"):
            action = line.removeprefix("Action:").strip()
        elif line.startswith("Goal:"):
            goal = line.removeprefix("Goal:").strip()
        elif line.startswith("Relevant past actions:"):
            past_actions = line.removeprefix("Relevant past actions:").strip()
            result.append(MessageState(idx, action, goal, past_actions))
    return result


from docent.data_models.chat.message import AssistantMessage


def format_transcript_messages_and_states(
    transcript: AgentRun, states: list[MessageState], transcript_idx_label: int
):
    result = ""
    for state in states:
        message = transcript.transcripts["default"].messages[state.message_idx]
        if not isinstance(message, AssistantMessage):
            continue
        result += f"[T{transcript_idx_label}B{state.message_idx}]\n"
        result += f"Goal: {state.goal}\n"
        result += f"Relevant past actions: {state.past_actions}\n"
        result += f"Action: {state.action}\n"
        result += (
            "Raw message: "
            + transcript.transcripts["default"].messages[state.message_idx].text
            + "\n"
        )
        result += "-" * 32 + "\n"
    return result


async def compare_transcripts_6(
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

Use these guidelines for citations: {MULTI_BLOCK_CITE_INSTRUCTION}

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


def parse_diff_output(output: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    curr_index: int = 0
    # get lines between <claim> and </claim>
    while True:
        start_claim_index = output.find("<claim>", curr_index)
        if start_claim_index == -1:
            break
        end_claim_index = output.find("</claim>", start_claim_index)
        if end_claim_index == -1:
            break
        start_evidence_index = output.find("<evidence>", start_claim_index)
        if start_evidence_index == -1:
            break
        end_evidence_index = output.find("</evidence>", start_evidence_index)
        if end_evidence_index == -1:
            break
        result.append(
            (
                output[start_claim_index + len("<claim>") : end_claim_index].strip(),
                output[start_evidence_index + len("<evidence>") : end_evidence_index].strip(),
            )
        )
        curr_index = end_evidence_index + 1
    return result


async def extract_states_and_diffs_2(
    transcript_1: AgentRun,
    transcript_2: AgentRun,
) -> list[tuple[str, str]]:

    tasks = [extract_states(t) for t in [transcript_1, transcript_2]]
    results: list[str] = await tqdm.gather(*tasks)
    first_states = results[0]
    second_states = results[1]

    diff_result: str = await compare_transcripts_6(
        transcript_1,
        transcript_2,
        parse_output(first_states),
        parse_output(second_states),
    )
    return parse_diff_output(diff_result)


# NO_EVIDENCE_STR = "There is no evidence for this claim."


# async def get_evidence_for_claims(
#     transcript_1: Transcript,
#     transcript_2: Transcript,
#     claims: list[str],
# ) -> str:
#     if claims == []:
#         return ""
#     prompt = f"""
# Here are two different sequences of actions an agent took to solve a task.
# First transcript:
# {transcript_1.to_str(transcript_idx_label=0)}
# Second transcript:
# {transcript_2.to_str(transcript_idx_label=1)}
# Someone has proposed a list of differences between the two agents / transcripts. Many of these are unsubstantiated claims.
# For each difference, your job is to either provide evidence supporting the claim, or to say that the claim has no evidence.
# Always refer to the first transcript as "Agent 1" and the second as "Agent 2". Do not re-explain individual transcripts.
# You are encouraged to cite evidence from the transcripts: {MULTI_BLOCK_CITE_INSTRUCTION}.
# Avoid mentioning actions that both agents took, since that can never count as evidence for the two agents being different.
# You will be given claims in the following format:
# Claim 1: agent 1 exhibits more of feature X than agent 2
# Claim 2: agent 1 exhibits more of feature Y than agent 2
# ...
# Format your output as follows:
# Evidence 1: <if the claim does not ever seem to be true, write "{NO_EVIDENCE_STR}" and nothing else. Otherwise, explain ways in which agent 1 is more of X than agent 2, with citations; jump directly to the evidence with no additional commentary>
# Evidence 2: <if the claim does not ever seem to be true, write "{NO_EVIDENCE_STR}" and nothing else. Otherwise, explain ways in which agent 1 is more of Y than agent 2, with citations; jump directly to the evidence with no additional commentary>
# Here are the claims:
# {"\n".join(claims)}
#     """.strip()

#     outputs = await get_llm_completions_async(
#         [
#             [
#                 {
#                     "role": "user",
#                     "content": prompt,
#                 },
#             ]
#         ],
#         PROVIDER_PREFERENCES.compare_transcripts,
#         max_new_tokens=8192 * 2,
#         timeout=180.0,
#         use_cache=True,
#     )

#     text = outputs[0].first_text
#     if text is None:
#         return ""
#     return text


# def extract_claims_and_evidence(llm_output: str) -> tuple[list[str], list[str]]:
#     if llm_output == "":
#         return [], []
#     lines = llm_output.split("\n")
#     claims: list[str] = []
#     evidences: list[str] = []
#     for line in lines:
#         if line.startswith("Claim"):
#             claims.append(line.split(":")[1].strip())
#         elif line.startswith("Evidence"):
#             evidences.append(line.split(":")[1].strip())
#     return claims, evidences


# def swap_agent_indices_and_citations(evidence: str) -> str:
#     evidence = (
#         evidence.replace("Agent 1", "Agent 3")
#         .replace("Agent 2", "Agent 1")
#         .replace("Agent 3", "Agent 2")
#     )
#     # get [T0Bx], [T0Bx-T0By] and replace with [T1Bx], [T1Bx-T1By], vice versa
#     evidence = evidence.replace("T0B", "T2B").replace("T1B", "T0B").replace("T2B", "T1B")
#     return evidence


# def extract_reverse_evidence(llm_output: str) -> list[str]:
#     if llm_output == "":
#         return []
#     lines = llm_output.split("\n")
#     evidence_number = 1
#     evidences: list[str] = []
#     current_evidence = ""
#     for line in lines:
#         new_evidence_prefix = f"Evidence {evidence_number}: "
#         if line.startswith(new_evidence_prefix):
#             if evidence_number > 1:
#                 evidences.append(current_evidence)
#             current_evidence = line.removeprefix(new_evidence_prefix)
#             evidence_number += 1
#         else:
#             current_evidence += "\n" + line
#     evidences.append(current_evidence)
#     for i, evidence in enumerate(evidences):
#         if evidence.find(NO_EVIDENCE_STR) != -1:
#             evidences[i] = "There is no evidence for the reverse claim."
#         else:
#             current_evidence = evidence
#             # TODO(vincent): figure out how to prompt so this doesn't get said
#             if current_evidence.startswith("There is evidence for this claim. "):
#                 current_evidence = current_evidence.removeprefix(
#                     "There is evidence for this claim. "
#                 )
#             current_evidence = swap_agent_indices_and_citations(current_evidence)
#             evidences[i] = current_evidence
#     return evidences


# async def compute_diff_and_evidence(t1: Transcript, t2: Transcript) -> tuple[tuple[str, str], ...]:
#     initial_diff = await compare_transcripts(t1, t2)
#     claims, evidences = extract_claims_and_evidence(initial_diff)
#     min_length = min(len(claims), len(evidences))
#     return tuple(
#         (
#             claims[i],
#             evidences[i],
#         )
#         for i in range(min_length)
#     )
