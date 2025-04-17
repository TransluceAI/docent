import re
from typing import Literal, Protocol, TypedDict

from frames.transcript import (
    MULTI_BLOCK_CITE_INSTRUCTION,
    Citation,
    Transcript,
    parse_citations_multi_transcript,
)
from llm_util.prod_llms import get_llm_completions_async
from llm_util.types import LLMApiKeys, LLMOutput

USER_BACKGROUND = "a general CS background"


class MatchInfo(TypedDict):
    index: int
    match_type: Literal["exact", "near"]
    explanation: str


class DiffResult(TypedDict):
    matches: list[MatchInfo]
    no_match_explanation: str | None


class ComparisonResult(TypedDict):
    text: str
    citations: list[Citation]


class DiffTranscriptsStreamingCallback(Protocol):
    async def __call__(self, batch_index: int, results: list[DiffResult | None]) -> None: ...


def _get_llm_callback(
    streaming_callback: DiffTranscriptsStreamingCallback | None,
):
    if streaming_callback is None:
        return None

    async def callback(batch_index: int, llm_output: LLMOutput):
        await streaming_callback(batch_index, [_parse_diff_result(llm_output)])

    return callback


async def diff_transcripts(
    transcript_1: Transcript,
    transcript_2: Transcript,
    streaming_callback: DiffTranscriptsStreamingCallback | None = None,
    completion_callback: DiffTranscriptsStreamingCallback | None = None,
    api_keys: LLMApiKeys | None = None,
):
    prompts = [
        f"""
Here are two different sequences of actions an agent took to solve a task.

S1:
{transcript_1.to_str(metadata_fields=None, highlight_action_unit=action_unit_idx)}

S2:
{transcript_2.to_str(metadata_fields=None)}

I am _specifically_ interested in index {action_unit_idx}. Determine whether the agent's actions in the highlighted action unit {action_unit_idx} of S1 match actions in S2.

There are three possibilities:
- Exact match: the core actions attempted are the same, modulo unimportant implementation details.
- Near match: the core actions attempted are the same, but there are important differences in the details of the action.
- No match: the actions are different.

Enumerate all matching action unit indices in S2, and include a very short and concise explanation for each. The final output should be in the format (can be repeated for any number of matching action units):
Index: <integer action unit index in S2>, <E for exact match, N for near match>
Explanation: <if N, only explain the difference; if E, the reason why the actions are the same>
...

If the action unit does not show up, return in the following format:
Index: N/A
Explanation: <explanation>
        """.strip()
        for action_unit_idx in range(len(transcript_1.units_of_action))
    ]

    llm_streaming_callback = _get_llm_callback(streaming_callback)
    llm_completion_callback = _get_llm_callback(completion_callback)
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
        model_category="reasoning_smart",
        reasoning_effort="medium",
        max_new_tokens=8192,
        timeout=180.0,
        streaming_callback=llm_streaming_callback,
        completion_callback=llm_completion_callback,
        use_cache=True,
        llm_api_keys=api_keys,
    )

    return [_parse_diff_result(output) for output in outputs]


def _parse_diff_result(output: LLMOutput) -> DiffResult | None:
    if (text := output.first_text) is None:
        return None

    result: DiffResult = {"matches": [], "no_match_explanation": None}

    # Split the text into sections by "Index:" pattern
    sections = re.split(r"(?=Index:)", text)

    for section in sections:
        if not section.strip():
            continue

        # Only process complete patterns (has both Index and Explanation)
        if "Index:" not in section or "Explanation:" not in section:
            continue

        # Check for N/A case (no match)
        if "Index: N/A" in section:
            explanation_match = re.search(
                r"Explanation:\s*(.*?)(?=$|\n\n|\nIndex:)", section, re.DOTALL
            )
            if explanation_match:
                result["no_match_explanation"] = explanation_match.group(1).strip()
            continue

        # Extract index and match type
        index_match = re.search(r"Index:\s*(\d+),\s*([EN])", section)
        if not index_match:
            continue

        try:
            index = int(index_match.group(1))
            match_type = "exact" if index_match.group(2) == "E" else "near"

            # Extract explanation
            explanation_match = re.search(
                r"Explanation:\s*(.*?)(?=$|\n\n|\nIndex:)", section, re.DOTALL
            )
            explanation = explanation_match.group(1).strip() if explanation_match else ""

            result["matches"].append(
                {"index": index, "match_type": match_type, "explanation": explanation}
            )
        except (ValueError, IndexError):
            # Skip this section if we can't parse the index or match type
            continue

    # If we have no matches and no explanation, it might be incomplete
    if not result["matches"] and result["no_match_explanation"] is None:
        # Check if we have a complete response
        if not (re.search(r"Index:.*Explanation:", text, re.DOTALL)):
            return None

    return result


class ComparisonStreamingCallback(Protocol):
    async def __call__(self, batch_index: int, results: ComparisonResult) -> None: ...


def _get_strategy_comparison_callback(
    streaming_callback: ComparisonStreamingCallback | None,
    transcript_1: Transcript,
    transcript_2: Transcript,
):
    if streaming_callback is None:
        return None

    async def callback(batch_index: int, llm_output: LLMOutput):
        await streaming_callback(
            batch_index, _parse_comparison_result(llm_output, transcript_1, transcript_2)
        )

    return callback


async def compare_transcripts(
    transcript_1: Transcript,
    transcript_2: Transcript,
    streaming_callback: ComparisonStreamingCallback | None = None,
) -> ComparisonResult:
    prompt = f"""
Here are two different sequences of actions an agent took to solve a task.

First transcript:
{transcript_1.to_str(transcript_idx_label=0)}

Second transcript:
{transcript_2.to_str(transcript_idx_label=1)}

Provide a concise summary of key differences between the two transcripts. Do not re-explain individual transcripts.
If there is a correct and incorrect sequence being compared (you can see this in the metadata), specifically note specific actions in the correct approach that led to success, versus critical mistakes or misconceptions in the incorrect approach.

You may also focus on:
- High-level strategic differences in how the problem was approached
- Important decision points where the approaches diverged
- Any other significant differences you deem important

Avoid repeating yourself in the output.
Format your output in markdown. You are encouraged to cite evidence from the transcripts: {MULTI_BLOCK_CITE_INSTRUCTION}
    """.strip()

    llm_streaming_callback = _get_strategy_comparison_callback(
        streaming_callback, transcript_1, transcript_2
    )

    outputs = await get_llm_completions_async(
        [
            [
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
        ],
        model_category="reasoning_smart",
        reasoning_effort="medium",
        max_new_tokens=8192 * 2,
        timeout=180.0,
        streaming_callback=llm_streaming_callback,
        use_cache=True,
    )

    return _parse_comparison_result(outputs[0], transcript_1, transcript_2)


def _parse_comparison_result(
    output: LLMOutput, transcript_0: Transcript, transcript_1: Transcript
) -> ComparisonResult:
    if (text := output.first_text) is None:
        return {"text": "", "citations": []}

    citations = parse_citations_multi_transcript(text)
    for citation in citations:
        if citation["transcript_idx"] == 0:
            citation["action_unit_idx"] = transcript_0.get_action_unit_for_block(
                citation["block_idx"]
            )
        else:
            citation["action_unit_idx"] = transcript_1.get_action_unit_for_block(
                citation["block_idx"]
            )

    return {"text": text, "citations": citations}
