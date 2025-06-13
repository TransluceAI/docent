import asyncio
import re
from typing import Protocol, cast
from uuid import uuid4

from pydantic import BaseModel, Field

from docent._llm_util.data_models.llm_output import LLMOutput
from docent._llm_util.prod_llms import get_llm_completions_async
from docent._llm_util.providers.preferences import PROVIDER_PREFERENCES
from docent._llm_util.util import get_token_count
from docent.data_models.agent_run import AgentRun
from docent.data_models.citation import Citation, parse_citations_single_transcript
from docent.data_models.transcript import SINGLE_BLOCK_CITE_INSTRUCTION

SEARCH_PROMPT = f"""
Your task is to check for instances of a search query in some text:
<text>
{{item}}
</text>
<query>
{{search_query}}
</query>

First think carefully about whether the text contains any instances of the query.

If not, return "N/A" only.

If so, for each instance of the attribute, describe how the text pertains to it. Be concise but detailed and specific. I should be able to maximally mentally reconstruct the item from your description. You should return all instances of the attribute in the following exact format:
<instance>
description
</instance>
...
<instance>
description
</instance>

{SINGLE_BLOCK_CITE_INSTRUCTION}
""".strip()


class SearchResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_run_id: str
    search_query: str
    search_result_idx: int | None = None
    value: str | None = None


class SearchResultWithCitations(SearchResult):
    citations: list[Citation] | None

    @classmethod
    def from_search_result(cls, result: SearchResult) -> "SearchResultWithCitations":
        return cls(
            **result.model_dump(),
            citations=(
                parse_citations_single_transcript(result.value)
                if result.value is not None
                else None
            ),
        )


class SearchResultStreamingCallback(Protocol):
    """Supports batched streaming for cases where many search results are pre-computed.
    This avoids invoking the callback separately for each datapoint.
    """

    async def __call__(
        self,
        search_results: list[SearchResult] | None,
    ) -> None: ...


def _get_llm_streaming_callback(
    search_result: str,
    datapoint_ids: list[str],
    search_result_callback: SearchResultStreamingCallback,
):
    async def _streaming_callback(batch_index: int, llm_output: LLMOutput):
        search_results = _parse_llm_output(llm_output)

        # Return nothing if the LLM call failed (hence None)
        if search_results is None:
            await search_result_callback(None)
        else:
            await search_result_callback(
                [
                    SearchResult(
                        agent_run_id=datapoint_ids[batch_index],
                        search_query=search_result,
                        search_result_idx=i,
                        value=value,
                    )
                    # If there were no matches, return a single None result
                    # Otherwise, return all results
                    for i, value in enumerate(search_results if len(search_results) > 0 else [None])
                ]
            )

    return _streaming_callback


def _get_llm_streaming_callback_for_sharded_search(
    search_result: str,
    datapoint_ids: list[str],
    search_result_callback: SearchResultStreamingCallback,
):
    async def _streaming_callback(batch_index: int, llm_outputs: list[LLMOutput]):
        search_results = [_parse_llm_output(llm_output) for llm_output in llm_outputs]

        # Return None if any LLM call failed, so that we know to retry later
        if any(search_result is None for search_result in search_results):
            await search_result_callback(None)
        else:
            flattened_search_results = [
                s for search_result in search_results for s in cast(list[str], search_result)
            ]
            await search_result_callback(
                [
                    SearchResult(
                        agent_run_id=datapoint_ids[batch_index],
                        search_query=search_result,
                        search_result_idx=i,
                        value=value,
                    )
                    # If there were no matches, return a single None result
                    # Otherwise, return all results
                    for i, value in enumerate(
                        flattened_search_results if len(flattened_search_results) > 0 else [None]
                    )
                ]
            )

    return _streaming_callback


def _parse_llm_output(output: LLMOutput) -> list[str] | None:
    if output.first_text is None:
        return None
    elif output.first_text.strip().upper() == "N/A":
        return []
    else:
        # Pattern matches text between <instance> and </instance> tags
        pattern = r"<instance>\n?(.*?)\n?</instance>"
        matches = re.finditer(pattern, output.first_text, re.DOTALL)
        return [str(match.group(1).strip()) for match in matches]


async def execute_search(
    agent_runs: list[AgentRun],
    search_query: str,
    search_result_callback: SearchResultStreamingCallback | None = None,
):
    """
    Searches over provided AgentRuns sequentially and uses streaming_callback to stream the results
    of each search. Results are returned in the same order as the provided AgentRuns, but you should
    not make any assumptions about streaming order.
    """
    ids = [ar.id for ar in agent_runs]
    texts = [ar.text for ar in agent_runs]

    # try to search over all short AgentRuns first, since we can stream those immediately

    short_indices = [i for i in range(len(texts)) if get_token_count(texts[i]) < 100_000]
    short_ids = [ids[i] for i in short_indices]
    short_texts = [texts[i] for i in short_indices]

    llm_callback = (
        _get_llm_streaming_callback(search_query, short_ids, search_result_callback)
        if search_result_callback is not None
        else None
    )

    prompts = [SEARCH_PROMPT.format(search_query=search_query, item=item) for item in short_texts]
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
        PROVIDER_PREFERENCES.execute_search,
        max_new_tokens=4096,
        timeout=180.0,
        use_cache=True,
        completion_callback=llm_callback,
    )

    ans: list[list[str] | None] = [
        None,
    ] * len(texts)
    for i, output in enumerate(outputs):
        ans[short_indices[i]] = _parse_llm_output(output)

    # next we search over long AgentRuns, which need to be sharded to within context length
    # these can't be streamed immediately since we need to search over all shards first

    long_indices = [i for i in range(len(texts)) if i not in short_indices]
    long_ids = [ids[i] for i in long_indices]
    long_texts = [agent_runs[i].to_text(100_000) for i in long_indices]
    flattened_long_texts = [text for run in long_texts for text in run]

    prompts = [
        SEARCH_PROMPT.format(search_query=search_query, item=item) for item in flattened_long_texts
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
        PROVIDER_PREFERENCES.execute_search,
        max_new_tokens=4096,
        timeout=180.0,
        use_cache=True,
    )

    grouped_outputs: list[list[LLMOutput]] = []
    index = 0
    for long_text in long_texts:
        grouped_outputs.append(outputs[index : index + len(long_text)])
        index += len(long_text)

    for i, output_group in enumerate(grouped_outputs):
        results = [_parse_llm_output(output) for output in output_group]
        if any(result is None for result in results):
            ans[long_indices[i]] = None
        else:
            flattened_results = [r for result in results for r in cast(list[str], result)]
            ans[long_indices[i]] = flattened_results

    if search_result_callback is not None:
        long_llm_callback = _get_llm_streaming_callback_for_sharded_search(
            search_query, long_ids, search_result_callback
        )
        callbacks = [
            long_llm_callback(i, output_group) for i, output_group in enumerate(grouped_outputs)
        ]
        await asyncio.gather(*callbacks)

    return ans


async def _execute_search_over_text(  # type: ignore
    texts: list[str],
    search_query: str,
    search_result_callback: SearchResultStreamingCallback | None = None,
):
    """
    TODO(mengk): this is a hack for bridgewater, remove it later.
    """
    ids = [str(i) for i in range(len(texts))]

    llm_callback = (
        _get_llm_streaming_callback(search_query, ids, search_result_callback)
        if search_result_callback is not None
        else None
    )

    prompts = [SEARCH_PROMPT.format(search_query=search_query, item=item) for item in texts]
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
        PROVIDER_PREFERENCES.execute_search,
        max_new_tokens=4096,
        timeout=180.0,
        use_cache=True,
        completion_callback=llm_callback,
    )

    ans: list[list[str] | None] = []
    for output in outputs:
        ans.append(_parse_llm_output(output))

    return ans
