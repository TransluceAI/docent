# from typing import Protocol
# from uuid import uuid4

# import anyio
# import numpy as np

# from docent._llm_util.providers.preference_types import ModelOption
# from docent.data_models.agent_run import AgentRun
# from docent.data_models.chat import UserMessage
# from docent.data_models.judge import JudgeRunLabel
# from docent.judges import JudgeResult
# from docent_core.docent.db.schemas.rubric import Rubric

# ####################
# # RUBRIC CONSTANTS #
# ####################

# INCLUDE_RUBRIC = """
# Here is a rubric.
# <Rubric>
# {rubric}
# </Rubric>
# """.strip()

# INCLUDE_LABELS = """
# Here is a set of labels for the rubric. Each label is associated with an agent run. The label contains feedback on the output of a judge evaluating the agent run against the rubric.
# {labels}
# """.strip()


# RUBRIC_GUIDELINES = """
# Please propose a new version of the rubric that incorporates the user feedback.

# <Rubric guidelines>
# A rubric must contain exactly these components:
#   - One paragraph with an insightful high-level framing that makes the ensuing specification highly simple and parsimonious. Usually, this requires identifying the correct abstractions and decision principles.
#   - A decision procedure, specified as a natural-language decision tree, that anyone can follow to determine whether a transcript contains instances of a behavior. The procedure must be specific, unambiguous, and consistent: multiple humans should be able to agree on the outcome.

# Guidelines for creating and revising rubrics:
#   - It's extremely important that the decision procedure is concise, simple, and clear - 惜墨如金. Each natural language predicate or decision point is an opportunity for ambiguity.
#   - Unless otherwise stated, revisions to the rubric should be as minimal and targeted as possible. Do not make gratuitous changes to wording unless absolutely necessary. As you generate each line of the revision, consult the last version of the rubric and consider whether your planned change is strictly necessary.
#   - The rubric should not just list the user's labels as feedback.
#   - If you provide examples, don't provide them as inline parentheses. Instead, provide them as a list item. Use examples sparingly--only include an example if it is a specific edge case that cannot be captured by a thoughtful description.
#   - Do not include anything about the output format of the rubric.
# </Rubric guidelines>

# <Formatting instructions>
#   - Format your answers and rubrics in Markdown.
#   - To create a new line, use two newlines (\\n\\n).
#   - Unordered lists (-), ordered lists (1.), bold (*), italics (_), code ticks (` or ```), and quotes (>) are supported.
#   - You may nest ordered and unordered lists, but make sure to use the correct indentation.
#   - Headings are strictly forbidden. Instead of headers, use bold text.
# </Formatting instructions>

# <Response format>
# Please return the updated version of the rubric text. Do not output anything else.
# </Response format>
# """.strip()


# async def propose_rubrics(
#     rubric: Rubric,
#     labels: list[JudgeRunLabel],
#     judgements: list[JudgeResult],
#     num_proposals: int,
#     proposer_model: ModelOption,
#     clarification: str | None = None,
# ) -> list[Rubric]:
#     """
#     Assumes the order of labels corresponds to the order of results.

#     Args:
#         clarification (str | None): Optional clarifying information for the proposer.
#         include_label_text (bool): Whether to provide the proposer with human written annotations on the labels.
#     """

#     prompt = make_prompt(rubric.rubric_text, labels, judgements, clarification)

#     # TODO(cadentj): I wonder if I should use a System + User prompt instead
#     llm_outputs = await get_llm_completions_async(
#         [[UserMessage(content=prompt)]] * num_proposals,
#         [proposer_model],
#         max_new_tokens=8192,
#         timeout=180.0,
#         use_cache=False,
#         temperature=1.0,
#     )

#     rubric_texts = [llm_output.completions[0].text for llm_output in llm_outputs]

#     if len(rubric_texts) != num_proposals:
#         raise ValueError(f"Expected {num_proposals} rubric texts, got {len(rubric_texts)}")

#     rubrics = [
#         rubric.model_copy(update={"rubric_text": rubric_text, "id": str(uuid4())})
#         for rubric_text in rubric_texts
#     ]

#     return rubrics


# class EvaluateRubricsCallback(Protocol):
#     async def __call__(
#         self,
#         rubric_idx: int,
#         search_rollout_idx: int,
#         judge_results: list[JudgeResult] | None,
#     ):
#         """
#         Args:
#             rubric_idx: The index of the rubric in the list of rubrics.
#             search_rollout_idx: The index of the search rollout in the list of search rollouts.
#             judge_results: A list of judge results.
#         """


# async def evaluate_rubrics(
#     runs: list[AgentRun],
#     rubrics: list[Rubric],
#     num_search_rollouts: int,
#     judge_model: ModelOption,
#     callback: EvaluateRubricsCallback | None = None,
# ) -> np.ndarray:
#     # Update the judge model for given rubrics
#     rubrics = [rubric.model_copy(update={"judge_model": judge_model}) for rubric in rubrics]

#     def _make_callback(rubric_idx: int, search_rollout_idx: int):
#         if callback is None:
#             return None

#         async def _callback(batch_index: int, judge_results: list[JudgeResult] | None):
#             if judge_results is None:
#                 return

#             await callback(rubric_idx, search_rollout_idx, judge_results)  # type: ignore

#         return _callback

#     # Shape (N, M, L) where N is the number of rubrics,
#     # M is the number of search rollouts, and L is the number of judge results
#     # Store as numpy array with object dtype containing JSON strings
#     results = np.empty((len(rubrics), num_search_rollouts, len(runs)), dtype=object)

#     async def _evaluate_and_store(rubric_idx: int, search_rollout_idx: int, rubric: Rubric):
#         judge_results = await evaluate_rubric(
#             runs,
#             rubric,
#             callback=_make_callback(rubric_idx, search_rollout_idx),
#             max_concurrent_llm_calls=5,
#         )

#         for i, jr in enumerate(judge_results):
#             value = jr.output if jr is not None else None
#             results[rubric_idx, search_rollout_idx, i] = value

#     async with anyio.create_task_group() as tg:
#         for rubric_idx, rubric in enumerate(rubrics):
#             for search_rollout_idx in range(num_search_rollouts):
#                 tg.start_soon(
#                     _evaluate_and_store,
#                     rubric_idx,
#                     search_rollout_idx,
#                     rubric,
#                 )

#     return results
