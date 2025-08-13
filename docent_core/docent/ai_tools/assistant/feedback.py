from docent_core._llm_util.prod_llms import get_llm_completions_async
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES
from docent_core.docent.ai_tools.clustering.cluster_assigner import assign_with_backend


async def evaluate_new_queries(
    new_queries: list[str], good_results: list[str], bad_results: list[str]
) -> str:
    items = (good_results + bad_results) * len(new_queries)
    num_results = len(good_results) + len(bad_results)
    clusters: list[str] = []
    for n in new_queries:
        clusters.extend(
            [
                n,
            ]
            * num_results
        )
    results = await assign_with_backend(
        backend="sonnet-4-thinking",
        items=items,
        clusters=clusters,
    )
    scores: list[list[bool]] = []
    max_score = 0.0
    max_score_index = -1
    for i, n in enumerate(new_queries):
        score: list[bool] = []
        relevant_results = results[num_results * i : num_results * (i + 1)]
        for j, r in enumerate(relevant_results):
            if r is None:
                continue
            if r[0] and j < len(good_results):
                score.append(True)
            elif (not r[0]) and j >= len(good_results):
                score.append(True)
            else:
                score.append(False)
        scores.append(score)
        if sum(score) > max_score:
            max_score = sum(score)
            max_score_index = i
    print(scores)
    return new_queries[max_score_index]


QUERY_IMPROVEMENT_PROMPT = """
You are helping conduct semantic search for instances of a search query in some text. The search query is not returning great results, so your job is to help make it more precise.

Here is the current search query:
<query>
{query}
</query>

Here are some examples of results that match the current search query, which we would ideally like to NOT match the improved query:
<bad_results>
{bad_results}
</bad_results>

Here are some examples of results that match the current search query, which we would ideally like to CONTINUE matching the improved query:
<good_results>
{good_results}
</good_results>

Finally, here are examples of results that are not showing up under the current search query, but which we would like to surface with the improved query:
<missing_results>
{missing_results}
</missing_results>

Think carefully about how to improve the search query to better match the results we want. Then, return the improved query. Keep it as concise as possible while remaining specific.

We suggest following this format for your response:

Improved query: <original_query/>, such as <new_criteria_for_matches/> but not including <bad_criteria_for_matches/>
""".strip()


async def generate_new_queries(
    query: str,
    bad_results: list[str],
    good_results: list[str],
    missing_results: str = "",
) -> str:
    """
    Processes items sequentially and calls streaming_callback with the
    current cumulative results using the batch_index.
    """

    prompts = [
        QUERY_IMPROVEMENT_PROMPT.format(
            query=query,
            bad_results=bad_results,
            good_results=good_results,
            missing_results=missing_results,
        )
        for _ in range(10)
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
        PROVIDER_PREFERENCES.generate_new_queries,
        max_new_tokens=4096,
        timeout=180.0,
        use_cache=False,
    )

    print(outputs)

    ans: list[str] = []
    for output in outputs:
        completion = output.completions[0].text
        if completion is not None:
            index = completion.find("Improved query: ")
            if index != -1:
                ans.append(completion[index + len("Improved query: ") :].strip())
            else:
                ans.append(completion.strip())

    best_query = await evaluate_new_queries(ans, good_results + [missing_results], bad_results)

    print(best_query)

    return best_query
