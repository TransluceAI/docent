from typing import Iterator, List, Tuple

from scipy import stats

from docent._log_util import get_logger

logger = get_logger(__name__)


def print_stats_with_intervals(name: str, mean: float, std: float, confidence_levels: list[float]):
    """Print statistics with confidence intervals at multiple confidence levels.

    Args:
        name: Name of the statistic
        mean: Mean value
        std: Standard deviation
        confidence_levels: List of confidence levels (e.g., [0.90, 0.95, 0.99])
    """
    intervals_str = ", ".join(
        [
            f"{int(level*100)}% interval: [{mean - stats.norm.ppf((1+level)/2) * std:.4f}, {mean + stats.norm.ppf((1+level)/2) * std:.4f}]"  # type: ignore
            for level in confidence_levels
        ]
    )
    print(f"{name} mean: {mean:.4f}, std: {std:.4f}, {intervals_str}")


def _bounded_compositions(total: int, parts: int, bound: int) -> Iterator[Tuple[int, ...]]:
    """
    Yield all tuples (x1,...,x_parts) of nonnegative ints summing to `total`
    with each xk <= bound.
    """

    # Recursive backtracking with pruning by remaining capacity.
    def rec(k: int, remaining: int, prefix: List[int]) -> Iterator[Tuple[int, ...]]:
        if k == parts:
            if remaining == 0:
                yield tuple(prefix)
            return
        # Max we can put here is min(bound, remaining - min_needed_for_rest)
        # The min needed for the rest is 0; also cannot exceed remaining.
        max_here = min(bound, remaining)
        # Optional pruning: ensure the rest can absorb what's left (always true since min=0)
        for x in range(max_here + 1):
            prefix.append(x)
            yield from rec(k + 1, remaining - x, prefix)
            prefix.pop()

    yield from rec(0, total, [])


def plurality_vectors(m: int, K: int, i: int) -> Iterator[Tuple[int, ...]]:
    """
    Generate all count vectors n = (n1,...,nm) of nonnegative integers with
    sum(n) = K and STRICT plurality at index i:
       n[i] > n[j] for all j != i.

    Yields vectors in no particular order.
    """
    if not (0 <= i < m):
        raise ValueError("i must be in [0, m).")
    if m < 2 or K < 1:
        return  # nothing to yield in degenerate cases

    for ni in range(1, K + 1):  # at least 1 vote for the winner
        rest_total = K - ni
        cap = ni - 1  # strict plurality: others must be <= ni-1
        # If cap < 0 but rest_total > 0, impossible
        if cap < 0 and rest_total > 0:
            continue
        # Build the other m-1 counts under the cap
        for others in _bounded_compositions(rest_total, m - 1, cap):
            # Stitch back in ni at position i
            vec = list(others[:i]) + [ni] + list(others[i:])
            yield tuple(vec)


def p_mode(n: int, p_v: list[float], idx: int) -> float:
    """Probability that the modal sample of sampling Multinom(n, p_v) is the idxth one."""
    count_vecs = plurality_vectors(len(p_v), n, idx)
    return sum(stats.multinomial.pmf(vec, n, p_v) for vec in count_vecs)  # type: ignore


# async def analyze_majority_judge(
#     rubric: Rubric,
#     agent_runs: list[AgentRun],
#     matched_labels: dict[str, dict[str, Any]],  # agent_run_id -> gold label obj
#     results_path: Path,
#     samples_per_agent_run: int = 10,
#     maj_k: int = 5,  # Does not affect data collection
#     max_llm_concurrency: int = 100,
# ):
#     # if rubric.n_rollouts_per_input != 1:
#     #     raise ValueError("You should use n_rollouts_per_input=1")

#     if not results_path.exists():
#         logger.info(f"Evaluating rubrics and saving results to {results_path}")

#         max_conc_per_rubric = min(
#             max_llm_concurrency, len(agent_runs) * rubric.n_rollouts_per_input
#         )
#         max_parallel_rubrics = max(1, max_llm_concurrency // max_conc_per_rubric)
#         logger.info(
#             f"Evaluating {samples_per_agent_run} samples per agent run, {max_conc_per_rubric} concurrent LLM calls per rubric, {max_parallel_rubrics} parallel rubrics"
#         )

#         await evaluate_multiple_rubrics(
#             rubrics=[rubric] * samples_per_agent_run,
#             agent_runs=agent_runs,
#             llm_svc=SimpleLLMService(),
#             output_path=results_path,
#             max_concurrent_llm_calls_per_rubric=max_conc_per_rubric,
#             max_parallel_rubrics=max_parallel_rubrics,
#         )
#     else:
#         logger.info(f"Found existing results at {results_path}, loading them")

#     rows = load_rubric_results_from_file(results_path)

#     # Parse results into a flat dataframe
#     parsed_results: list[dict[str, Any]] = []
#     for row in rows:
#         config_key = row.rubric.model_dump_json(
#             exclude={
#                 "rubric_text",
#                 "id",
#                 "version",
#                 "system_prompt_template",
#                 "citation_instructions",
#                 "output_schema",
#             }
#         )
#         for result in row.judge_results:
#             if result is None:
#                 print("found null")
#                 continue
#                 # raise ValueError("result is None")

#             gold_label = matched_labels[result.agent_run_id]["label"]
#             judge_label = result.output["label"]
#             md = result.result_metadata or {}

#             parsed_results.append(
#                 {
#                     "config_key": config_key,
#                     "agent_run_id": result.agent_run_id,
#                     "gold_label": gold_label,
#                     "judge_label": judge_label,
#                     "final_results": md.get("final_results"),
#                     "is_correct": gold_label == judge_label,
#                 }
#             )

#     df = pd.DataFrame(parsed_results)
#     potential_labels = ["cheating", "future leakage", "not suspicious"]

#     def _get_pred_dist(x: pd.Series):
#         x = x.tolist()
#         counts = [x.count(l) for l in potential_labels]
#         assert np.sum(counts) == len(x)
#         return {l: counts[i] / len(x) for i, l in enumerate(potential_labels)}

#     n_ars = len(df.groupby("agent_run_id").count())
#     p_correct = (
#         df.groupby("agent_run_id")
#         .agg(
#             {
#                 "gold_label": lambda x: x.iloc[0],
#                 "judge_label": _get_pred_dist,
#                 "is_correct": np.mean,
#             }
#         )
#         .rename(columns={"judge_label": "pred_dist", "is_correct": "p_correct_naive"})
#     )
#     p_correct["p_correct_naive_var"] = p_correct["p_correct_naive"].apply(lambda x: x * (1 - x))

#     p_correct["p_correct_majority"] = p_correct.apply(
#         lambda row: p_mode(
#             maj_k,
#             [row["pred_dist"][l] for l in potential_labels],
#             potential_labels.index(row["gold_label"]),
#         ),
#         axis=1,
#     )
#     p_correct["p_correct_majority_var"] = p_correct["p_correct_majority"].apply(
#         lambda x: x * (1 - x)
#     )
#     p_correct.sort_values(by="p_correct_majority_var", ascending=False, inplace=True)

#     overall_naive_mean = p_correct["p_correct_naive"].mean()
#     overall_naive_std = np.sqrt(p_correct["p_correct_naive_var"].sum() / n_ars**2)
#     overall_majority_mean = p_correct["p_correct_majority"].mean()
#     overall_majority_std = np.sqrt(p_correct["p_correct_majority_var"].sum() / n_ars**2)

#     confidence_levels = [0.5, 0.95]
#     print_stats_with_intervals(
#         "Overall naive", overall_naive_mean, overall_naive_std, confidence_levels
#     )
#     print_stats_with_intervals(
#         f"Overall majority (k={maj_k})",
#         overall_majority_mean,
#         overall_majority_std,
#         confidence_levels,
#     )
#     return p_correct
