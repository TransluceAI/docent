import re

from docent.data_models.agent_run import AgentRun
from docent.data_models.transcript import SINGLE_RUN_CITE_INSTRUCTION
from docent_core._ai_tools.diffs.models import MessageState
from docent_core._llm_util.data_models.llm_output import LLMOutput
from docent_core._llm_util.prod_llms import get_llm_completions_async
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES


async def get_llm_output_for_transcript_to_message_summaries(
    transcript: AgentRun,
) -> str:
    prompt = f"""
Here is a sequence of actions an agent took to solve a task.
{transcript.transcripts["default"].to_str()}

Note that each message in the sequence can have one of several roles - system, user, assistant, or tool.

For each ASSISTANT message, perform the following procedure:
- Summarize the action taken in the message
- Summarize the goal of the agent's current action
- Provide a concise but specific summary of the agent's past actions that are relevant to the current goal. You are encouraged to cite evidence from the transcripts: {SINGLE_RUN_CITE_INSTRUCTION}

Do not mention non-assistant messages in your output.

Here are some examples of the level of specifity in which we'd like to describe the messages in.

Action: The agent uses grep to find the test.py file.
Goal: The agent is trying to explore the codebase and read code relevant to the task.
Relevant past actions: None, this is the first action taken by the agent.

Action: The agent is editing OAuth configuration settings in its test script.
Goal: The agent is trying to get its test script to run without errors.
Relevant past actions: The agent previously wrote a test script, but upon execution it produced an OutOfBoundsError. <further explanation and citations>

Action: The agent is writing a detailed test script that tests for many edge cases.
Goal: The agent is trying to test its solution to ensure correctness.
Relevant past actions: The agent previously implemented a solution that resolves the issue by modifying the function to use sets instead of lists. <further explanation and citations>

Format your output as follows:
[T0B<message_idx>]
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

    text = outputs[0].first_text or ""
    return text


def llm_output_to_message_summaries(text: str) -> list[MessageState]:
    blocks = [block.strip() for block in re.split(r"(?=\n\[B\d+\]\n)", text) if block.strip()]
    return [_parse_message_summary(block) for block in blocks]


def _parse_message_summary(block: str) -> MessageState:
    lines = block.split("\n")
    # Extract message index from the first line
    idx = int(lines[0].removeprefix("[T0B").removesuffix("]"))

    # Initialize variables with empty strings
    action = ""
    goal = ""
    past_actions = ""

    # Process remaining lines
    for line in lines[1:]:
        if line.startswith("Action:"):
            action = line.removeprefix("Action:").strip()
        elif line.startswith("Goal:"):
            goal = line.removeprefix("Goal:").strip()
        elif line.startswith("Relevant past actions:"):
            past_actions = line.removeprefix("Relevant past actions:").strip()

    return MessageState(idx, action, goal, past_actions)


async def compute_transcript_summaries(agent_run: AgentRun) -> list[MessageState]:
    output = await get_llm_output_for_transcript_to_message_summaries(agent_run)
    return llm_output_to_message_summaries(output)
