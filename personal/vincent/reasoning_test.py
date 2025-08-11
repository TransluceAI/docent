import asyncio
import re
from typing import Any, Coroutine, Literal

from docent.data_models.agent_run import AgentRun
from docent.data_models.transcript import SINGLE_RUN_CITE_INSTRUCTION
from docent_core._ai_tools.search import execute_search_2
from docent_core._llm_util.data_models.llm_output import LLMOutput
from docent_core._llm_util.prod_llms import get_llm_completions_async
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES, ModelOption
from docent_core._loader.load_inspect import load_inspect_eval

LOG_DIR_PREFIX = "/home/ubuntu/inspect_logs"
PICOCTF_TRANSCRIPTS = load_inspect_eval(
    {
        "default_scaffold": f"{LOG_DIR_PREFIX}/intercode-4o-default-scaffold.eval",
    }
)
PICO_QUERY = "environmental issues encountered by the agent"


# dump the transcripts into a pickle
import pickle

BRIDGEWATER_TRANSCRIPTS = pickle.load(open(f"{LOG_DIR_PREFIX}/bridgewater_transcripts.pkl", "rb"))
BRIDGEWATER_QUERY = """obvious reasoning errors made by the forecaster.
this includes not taking market efficiency into account, confusing short-term vs long-term horizons, overreliance on qualitative reasoning without backing from real data, neglecting base rates and reference classes, general overconfidence and incomplete calibration"""


CURSOR_TRANSCRIPTS = pickle.load(open(f"{LOG_DIR_PREFIX}/cursor_transcripts.pkl", "rb"))

CURSOR_QUERY = "times the model used an unintended shortcut to satisfy the request"

print(len(PICOCTF_TRANSCRIPTS), len(BRIDGEWATER_TRANSCRIPTS), len(CURSOR_TRANSCRIPTS))

PICOCTF_TRANSCRIPTS = PICOCTF_TRANSCRIPTS[:300]  # TODO(vincent): change to 300
CURSOR_TRANSCRIPTS = CURSOR_TRANSCRIPTS[:300]


def format_searches(searches: list[str], index: int) -> str:
    result = ""
    for i, search in enumerate(searches):
        result += f"T{index}R{i}\n"
        result += f"Result: {search}\n"
        result += f"--------------------------------\n"
    return result


MULTI_RESULT_CITE_INSTRUCTION = (
    "Each search result has a unique index; cite the relevant block index in brackets when relevant, like [T<idx>R<idx>]."
    + " Use multiple tags to cite multiple blocks, like [T<idx1>R<idx1>][T<idx2>R<idx2>]."
)

import contextlib

import anyio


async def compare_searches(
    searches_1: list[str], searches_2: list[str], ctx: anyio.Semaphore | None = None
) -> str:
    prompt = f"""
Here are two lists of search results about the same query applied to the same document. For each list, you will be given results in the following format:

<result_idx_label>
Result: [a search match]
--------------------------------

First list:
{format_searches(searches_1, 0)}
Second list:
{format_searches(searches_2, 1)}

We care about instances where one list has a search result that is not present in the other list.
Note that minor differences in the wordings of the search results are not important; however, a search result that is missing entirely is important.
The search results contain references to the original document, like [B<idx>], which allow you to understand which message in the original document the result is referencing.

Look through the results and list the instances where one list has a search result that is not present in the other list, as well as instances where both lists have search results referencing the same part of the original document.
Note that every search result should belong in one of these two categories (has an analogous result in the other list, or the other list is missing it entirely).

Use these guidelines for citations: {MULTI_RESULT_CITE_INSTRUCTION}

Format your final list as follows:
<similarities>
[T0R<idx1>] and [T1R<idx2>] are analogous.
[T0R<idx3>] and [T1R<idx4>] are analogous.
...
</similarities>
<differences>
[T0R<idx5>] not present in other list.
[T1R<idx6>] not present in other list.
...
</differences>

Do not respond with any other text than the list of similarities and differences in search results.
    """.strip()

    result = ""

    async def _streaming_callback(batch_index: int, llm_output: LLMOutput):
        nonlocal result

        result = llm_output.completions[0].text

    context = ctx if ctx is not None else contextlib.nullcontext()
    async with context:

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
            max_new_tokens=8192 * 3,
            timeout=240.0,
            use_cache=True,
            streaming_callback=_streaming_callback,
        )

    text = outputs[0].first_text
    if text is None:
        return ""
    return text


SEARCH_PROMPT_4 = f"""
Your task is to check for instances of a search query in some text:
<text>
{{item}}
</text>
<query>
{{search_query}}
</query>

First think carefully about whether the text contains any instances of the query.

For every instance of the attribute, describe how the text pertains to it. Be concise but detailed and specific. I should be able to maximally mentally reconstruct the item from your description. You should return all instances of the attribute in the following exact format:
<instance>
description
</instance>
...
<instance>
description
</instance>

This list should be exhaustive.

Your final response should only contain the list of instances, nothing else. If there are no instances at all, return "N/A" only.

{SINGLE_RUN_CITE_INSTRUCTION}
""".strip()

SEARCH_PROMPT_4 = f"""
Your task is to check for instances of a search query in some text:
<text>
{{item}}
</text>
<query>
{{search_query}}
</query>

First think carefully about whether the text contains any instances of the query.

For every instance of the attribute, describe how the text pertains to it. Be concise but detailed and specific. I should be able to maximally mentally reconstruct the item from your description. You should return all instances of the attribute in the following exact format:
<instance>
description
</instance>
...
<instance>
description
</instance>

This list should be exhaustive.

{SINGLE_RUN_CITE_INSTRUCTION}
""".strip()


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


async def execute_search_4(
    agent_runs: list[AgentRun],
    search_query: str,
    reasoning_effort: Literal["low1", "medium1", "high1", None],
):
    """
    Searches over provided AgentRuns sequentially and uses streaming_callback to stream the results
    of each search. Results are returned in the same order as the provided AgentRuns, but you should
    not make any assumptions about streaming order.

    TODO(vincent, mengk): i believe this code can be simplified by using a stateful callback.
    """
    texts = [ar.text for ar in agent_runs]

    # Try to search over all short AgentRuns first, since we can stream those immediately
    short_indices = [i for i in range(len(texts)) if len(texts[i]) <= 4 * 100_000]
    short_texts = [texts[i] for i in short_indices]

    prompts = [SEARCH_PROMPT_4.format(search_query=search_query, item=item) for item in short_texts]
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
        [
            ModelOption(
                provider="anthropic",
                model_name="claude-sonnet-4-20250514",
                reasoning_effort=reasoning_effort,
            )
        ],
        max_new_tokens=8192,
        timeout=180.0,
        use_cache=True,
    )

    ans: list[list[str] | None] = [
        None,
    ] * len(texts)
    for i, output in enumerate(outputs):
        ans[short_indices[i]] = _parse_llm_output(output)

    return ans, outputs


async def compare_searches_wrapper(
    searches1: list[list[str] | None], searches2: list[list[str] | None]
):
    tasks: list[Coroutine[Any, Any, str]] = []
    ctx = anyio.Semaphore(50)
    tasks = []
    for i in range(len(searches1)):
        s1, s2 = searches1[i], searches2[i]
        tasks.append(
            compare_searches(s1 if s1 is not None else [], s2 if s2 is not None else [], ctx)
        )
    comparisons_aggressive = await asyncio.gather(*tasks)

    def extract_search_results(text: str) -> list[tuple[int, int]]:
        """Extract all search results of form [T<int>R<int>] from text.

        Args:
            text: String to search for search results

        Returns:
            List of tuples containing (transcript_num, result_num) for each match
        """
        pattern = r"\[T(\d+)R(\d+)\]"
        matches = re.finditer(pattern, text)
        return [(int(m.group(1)), int(m.group(2))) for m in matches]

    old_unmatched, old_total = 0, 0
    new_unmatched, new_total = 0, 0
    for i in range(len(searches1)):
        start_index = comparisons_aggressive[i].find("<differences>")
        end_index = comparisons_aggressive[i].find("</differences>")
        content = comparisons_aggressive[i][start_index:end_index]
        unmatched_tuples = extract_search_results(content)
        old_unmatched += len([k for k in unmatched_tuples if k[0] == 0])
        old_total += len(searches1[i] if searches1[i] is not None else [])
        new_unmatched += len([k for k in unmatched_tuples if k[0] == 1])
        new_total += len(searches2[i] if searches2[i] is not None else [])

    return (old_unmatched, old_total, new_unmatched, new_total)


async def main():
    all_results: dict[
        tuple[str, str | None],
        tuple[tuple[float, float, float, float], tuple[int, int, int, int]],
    ] = {}
    for name, dataset, query in [
        ("pico", PICOCTF_TRANSCRIPTS, PICO_QUERY),
        ("bridgewater", BRIDGEWATER_TRANSCRIPTS, BRIDGEWATER_QUERY),
        ("cursor", CURSOR_TRANSCRIPTS, CURSOR_QUERY),  # TODO(vincent): uncomment
    ]:
        original_searches, orig_res = await execute_search_2(dataset, query)
        print(f"got initial results for {name}")
        for effort in ["low1", "medium1", "high1", None]:  # TODO(vincent): uncomment
            print(f"Effort: {effort} for {name}")
            new_results, new_res = await execute_search_4(dataset, query, effort)
            results = await compare_searches_wrapper(original_searches, new_results)
            old_reasoning_tokens = sum(
                len(str(r.completions[0].reasoning_tokens)) for r in orig_res
            ) / len(orig_res)
            new_reasoning_tokens = sum(
                len(str(r.completions[0].reasoning_tokens)) for r in new_res
            ) / len(new_res)
            old_output_tokens = sum(len(str(r.completions[0].text)) for r in orig_res) / len(
                orig_res
            )
            new_output_tokens = sum(len(str(r.completions[0].text)) for r in new_res) / len(new_res)
            all_results[name, effort] = (
                (old_reasoning_tokens, old_output_tokens, new_reasoning_tokens, new_output_tokens),
                results,
            )

    for name, effort in all_results:
        print(f"{name} {effort}: {all_results[name, effort]}")


def plot_results():
    RESULTS = {
        "picoctf (env issues)": [114, 104, 84, 75],
        "bridgewater (reasoning mistakes)": [98, 93, 102, 101],
        "cursor (shortcuts)": [60, 64, 51, 56],
    }

    import matplotlib.pyplot as plt

    # Create a bar plot
    plt.figure(figsize=(10, 6))
    plt.bar(RESULTS.keys(), RESULTS.values())
    plt.xlabel("Dataset")
    plt.ylabel("Number of results")
    plt.title("Number of results for each dataset")
    plt.show()


if __name__ == "__main__":
    # asyncio.run(main())
    plot_results()
