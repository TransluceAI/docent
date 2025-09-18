import re
from typing import Literal, Protocol, TypedDict

from docent.data_models.citation import Citation, parse_citations
from docent.data_models.transcript import (
    BLOCK_CITE_INSTRUCTION,
    Transcript,
)
from docent_core._llm_util.data_models.llm_output import LLMOutput
from docent_core._llm_util.prod_llms import get_llm_completions_async
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES

USER_BACKGROUND = "a general (not domain-specific) CS background"


class LowLevelAction(TypedDict):
    action_unit_idx: int
    title: str
    summary: str
    citations: list[Citation]


class SummarizeLowLevelActionsStreamingCallback(Protocol):
    async def __call__(self, actions: list[LowLevelAction]) -> None: ...


def _get_llm_callback(
    streaming_callback: SummarizeLowLevelActionsStreamingCallback | None,
):
    if streaming_callback is None:
        return None

    async def callback(batch_index: int, llm_output: LLMOutput):
        await streaming_callback(
            _parse_title_summary_pairs(llm_output.first_text) if llm_output.first_text else []
        )

    return callback


async def summarize_agent_actions(
    transcript: Transcript,
    streaming_callback: SummarizeLowLevelActionsStreamingCallback | None = None,
    completion_callback: SummarizeLowLevelActionsStreamingCallback | None = None,
) -> list[LowLevelAction]:
    prompt = f"""
Transcript:
{transcript.to_str(use_action_units=True)[0]}

For each action unit in the transcript, provide a title and concise but specific summary of important details. Your summary should be understandable standalone; do not drop context.
Tailor your response to a user with: {USER_BACKGROUND}. Also assume that they aren't familiar with the task, so include specific relevant context.

The format should be:
<index>integer action unit index</index>
<title>
...
</title>
<summary>
...
</summary>

Any references to the transcript must be accompanied by a citation to the relevant transcript blocks.
Follow these guidelines: {BLOCK_CITE_INSTRUCTION}. The citation should be as close to the specific reference as possible (e.g., not at the very end).
        """.strip()

    llm_streaming_callback = _get_llm_callback(streaming_callback)
    llm_completion_callback = _get_llm_callback(completion_callback)
    output = await get_llm_completions_async(
        [
            [
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
        ],
        PROVIDER_PREFERENCES.summarize_agent_actions,
        max_new_tokens=8192,
        timeout=180.0,
        streaming_callback=llm_streaming_callback,
        completion_callback=llm_completion_callback,
        use_cache=True,
    )

    text = output[0].first_text
    return _parse_title_summary_pairs(text) if text else []


def _parse_title_summary_pairs(text: str) -> list[LowLevelAction]:
    # Pattern to match: action unit index, title, and summary
    # The pattern should account for newlines between the index, title tags, and summary tags
    pattern = r"<index>\s*(\d+)\s*</index>\s*\n?\s*<title>\s*([\s\S]+?)\s*</title>\s*\n?\s*<summary>\s*([\s\S]+?)\s*</summary>"
    matches = re.finditer(pattern, text, re.DOTALL | re.IGNORECASE)
    triples = [
        (int(match.group(1)), match.group(2).strip(), match.group(3).strip()) for match in matches
    ]

    actions: list[LowLevelAction] = []
    for idx, title, summary in triples:
        cleaned_summary, citations = parse_citations(summary)
        actions.append(
            LowLevelAction(
                action_unit_idx=idx,
                title=title,
                summary=cleaned_summary,
                citations=citations,
            )
        )

    return actions


class HighLevelAction(TypedDict):
    step_idx: int
    title: str
    summary: str
    action_unit_indices: list[int]
    first_block_idx: int | None
    citations: list[Citation]


class SummarizeHighLevelActionsStreamingCallback(Protocol):
    async def __call__(self, actions: list[HighLevelAction]) -> None: ...


def _get_high_level_actions_llm_callback(
    streaming_callback: SummarizeHighLevelActionsStreamingCallback | None,
    transcript: Transcript,
):
    if streaming_callback is None:
        return None

    async def callback(batch_index: int, llm_output: LLMOutput):
        await streaming_callback(
            _parse_high_level_steps(llm_output.first_text, transcript)
            if llm_output.first_text
            else []
        )

    return callback


async def group_actions_into_high_level_steps(
    action_summaries: list[LowLevelAction],
    transcript: Transcript,
    streaming_callback: SummarizeHighLevelActionsStreamingCallback | None = None,
) -> list[HighLevelAction]:
    """
    Groups action unit summaries into high-level steps.

    Args:
        action_summaries: List of action unit summaries
        transcript: The transcript
        streaming_callback: Optional callback for streaming results
        completion_callback: Optional callback for completion

    Returns:
        A list of high-level steps, each containing a title, summary, and the action unit indices it encompasses
    """
    # Format the action summaries for the prompt
    action_summaries_text = "\n\n".join(
        [
            f"Action Unit {action['action_unit_idx']}:\nTitle: {action['title']}\nSummary: {action['summary']}"
            for action in action_summaries
        ]
    )

    prompt = f"""
Transcript:
{transcript.to_str(use_action_units=True)[0]}

Action Unit Summaries:
{action_summaries_text}

Group the provided action unit summaries into logical high-level steps. Avoid proposing vague high-level steps that encompass very different steps.
For each high-level step, provide:
1. A clear, descriptive title
2. A concise but specific summary of what was accomplished. Tailor your response to a user with: {USER_BACKGROUND}. Also assume that they aren't familiar with the task, so include specific relevant context. The user should be able to mentally reconstruct what happened given your summary.
3. The exact list of action unit indices included in this step

IMPORTANT: Every action unit must be accounted for in exactly one high-level step. Do NOT omit any action units.

The format should be:
<step>1</step>
<title>
...
</title>
<summary>
...
</summary>
<action_units>
comma-separated list of action unit indices
</action_units>
    """.strip()

    llm_streaming_callback = _get_high_level_actions_llm_callback(streaming_callback, transcript)

    output = await get_llm_completions_async(
        [
            [
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
        ],
        PROVIDER_PREFERENCES.group_actions_into_high_level_steps,
        max_new_tokens=8192,
        timeout=180.0,
        streaming_callback=llm_streaming_callback,
        use_cache=True,
    )

    text = output[0].first_text
    return _parse_high_level_steps(text, transcript) if text else []


def _parse_high_level_steps(text: str, transcript: Transcript) -> list[HighLevelAction]:
    # Pattern to match: step index, title, summary, and action units
    pattern = r"<step>\s*(\d+)\s*</step>\s*\n?\s*<title>\s*([\s\S]+?)\s*</title>\s*\n?\s*<summary>\s*([\s\S]+?)\s*</summary>\s*\n?\s*<action_units>\s*([\s\S]+?)\s*</action_units>"
    matches = re.finditer(pattern, text, re.DOTALL | re.IGNORECASE)

    steps: list[HighLevelAction] = []
    for match in matches:
        step_idx = int(match.group(1))
        title = match.group(2).strip()
        summary = match.group(3).strip()

        # Parse the action unit indices
        action_units_text = match.group(4).strip()
        # Handle different formats: comma-separated list, range, or individual numbers
        action_unit_indices: list[int] = []
        for item in re.split(r",\s*", action_units_text):
            item = item.strip()
            if not item:
                continue

            # Check if it's a range (e.g., "1-3")
            range_match = re.match(r"(\d+)\s*-\s*(\d+)", item)
            if range_match:
                start, end = int(range_match.group(1)), int(range_match.group(2))
                action_unit_indices.extend(list(range(start, end + 1)))
            else:
                # It's a single number
                try:
                    action_unit_indices.append(int(item))
                except ValueError:
                    # Skip if it's not a valid integer
                    pass

        steps.append(
            HighLevelAction(
                step_idx=step_idx,
                title=title,
                summary=summary,
                action_unit_indices=action_unit_indices,
                first_block_idx=(
                    transcript.get_first_block_in_action_unit(action_unit_indices[0])
                    if action_unit_indices
                    else None
                ),
                citations=parse_citations(summary)[1],
            )
        )

    # Sort by step index
    steps.sort(key=lambda step: step["step_idx"])
    return steps


# New code for agent observations

ObservationCategory = Literal[
    "mistake", "critical_insight", "near_miss", "weird_behavior", "cheating"
]


class ObservationType(TypedDict):
    category: ObservationCategory
    description: str
    action_unit_idx: int


class SummarizeAgentObservationsStreamingCallback(Protocol):
    async def __call__(self, observations: list[ObservationType]) -> None: ...


def _get_observations_llm_callback(
    streaming_callback: SummarizeAgentObservationsStreamingCallback | None,
):
    if streaming_callback is None:
        return None

    async def callback(batch_index: int, llm_output: LLMOutput):
        await streaming_callback(
            _parse_agent_observations(llm_output.first_text) if llm_output.first_text else []
        )

    return callback


async def interesting_agent_observations(
    transcript: Transcript,
    streaming_callback: SummarizeAgentObservationsStreamingCallback | None = None,
    completion_callback: SummarizeAgentObservationsStreamingCallback | None = None,
) -> list[ObservationType]:
    prompt = f"""
Transcript:
{transcript.to_str(use_action_units=True)[0]}

Analyze the transcript and make notable observations about the agent's behavior. Look specifically for:
1. Mistakes or missteps
2. Critical insights, observations, or actions that helped make the agent progress
3. Near misses: an action or insight that was nearly correct but slightly off
4. Weird behaviors: anything interesting or strange about what the agent did
5. Evidence of cheating: where the agent bypassed the spirit of the task; e.g., memorizing the correct answer, reading a file it shouldn't have had access to.

For each observation, specify:
- The category (one of: "mistake", "critical_insight", "near_miss", "weird_behavior", "cheating")
- A concise but specific description of the observation
- The relevant action unit index. Note that each observation must be associated with exactly one action unit index.

If you do not find anything interesting, return "N/A". Do not report _not_ finding something.

The format for each observation should be:
<observation>
<category>category name</category>
<description>
...
</description>
<action_unit>integer action unit index</action_unit>
</observation>
    """.strip()

    llm_streaming_callback = _get_observations_llm_callback(streaming_callback)
    llm_completion_callback = _get_observations_llm_callback(completion_callback)

    output = await get_llm_completions_async(
        [
            [
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
        ],
        PROVIDER_PREFERENCES.interesting_agent_observations,
        max_new_tokens=8192,
        timeout=180.0,
        streaming_callback=llm_streaming_callback,
        completion_callback=llm_completion_callback,
        use_cache=True,
    )

    text = output[0].first_text
    return _parse_agent_observations(text) if text else []


def _parse_agent_observations(text: str) -> list[ObservationType]:
    """
    Parses the LLM output to extract structured observations.

    Args:
        text: The raw text output from the LLM

    Returns:
        A list of structured observations
    """
    # Updated pattern to handle indentation and multiple AU references
    pattern = r"<observation>\s*\n?\s*<category>\s*(mistake|critical_insight|near_miss|weird_behavior|cheating)\s*</category>\s*\n?\s*<description>\s*([\s\S]+?)\s*</description>\s*\n?\s*<action_unit>\s*([\s\S]+?)\s*</action_unit>\s*\n?\s*</observation>"

    matches = re.finditer(pattern, text, re.DOTALL | re.IGNORECASE)

    observations: list[ObservationType] = []
    for match in matches:
        category_str = match.group(1).lower()

        # Map the category string to the Literal type
        if category_str == "mistake":
            category: ObservationCategory = "mistake"
        elif category_str == "critical_insight":
            category: ObservationCategory = "critical_insight"
        elif category_str == "near_miss":
            category: ObservationCategory = "near_miss"
        elif category_str == "weird_behavior":
            category: ObservationCategory = "weird_behavior"
        elif category_str == "cheating":
            category: ObservationCategory = "cheating"
        else:
            raise ValueError(f"Invalid category: {category_str}")

        description = match.group(2).strip()

        # Parse AU references which might be comma-separated or include ranges
        action_unit_text = match.group(3).strip()

        # Extract the first AU reference for the action_unit_idx field
        action_unit_match = re.search(r"(\d+)", action_unit_text)
        action_unit_idx = int(action_unit_match.group(1)) if action_unit_match else 0

        observations.append(
            ObservationType(
                category=category,
                description=description,
                action_unit_idx=action_unit_idx,
            )
        )

    return observations
