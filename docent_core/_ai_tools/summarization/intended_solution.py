# import re
# from typing import Literal, Protocol, TypedDict

# from docent_core._llm_util.data_models.llm_output import LLMOutput
# from docent_core._llm_util.prod_llms import get_llm_completions_async
# from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES
# from docent.data_models.citation import Citation, parse_citations_single_run
# from docent.data_models.transcript import SINGLE_RUN_CITE_INSTRUCTION, Transcript


# class SummarizeIntendedSolutionStreamingCallback(Protocol):
#     async def __call__(self, summary: str, parts: list[str]) -> None: ...


# def _get_intended_solution_llm_callback(
#     streaming_callback: SummarizeIntendedSolutionStreamingCallback | None,
# ):
#     if streaming_callback is None:
#         return None

#     async def callback(batch_index: int, llm_output: LLMOutput):
#         summary, parts = _parse_solution_summary(llm_output.first_text or "N/A")
#         await streaming_callback(summary, parts)

#     return callback


# async def summarize_intended_solution(
#     transcript: Transcript,
#     streaming_callback: SummarizeIntendedSolutionStreamingCallback | None = None,
# ):
#     prompt = f"""
# Transcript:
# {transcript.to_str()}

# If there is no provided solution in the metadata, return "N/A".

# Otherwise, summarize the intended solution into a summary of the high-level idea, a list of steps or concepts (called parts) which include specific details that someone could follow to implement the solution. Tailor your response to a user with: {USER_BACKGROUND}.

# Return your response in the following format:
# <summary>
# ...
# </summary>
# <part>
# ...
# </part>
# <part>
# ...
# </part>
# ...
# """.strip()

#     llm_callback = _get_intended_solution_llm_callback(streaming_callback)

#     output = await get_llm_completions_async(
#         [
#             [
#                 {
#                     "role": "user",
#                     "content": prompt,
#                 },
#             ]
#         ],
#         PROVIDER_PREFERENCES.summarize_intended_solution,
#         max_new_tokens=8192,
#         timeout=180.0,
#         streaming_callback=llm_callback,
#         use_cache=True,
#     )

#     return _parse_solution_summary(output[0].first_text or "N/A")


# def _parse_solution_summary(text: str):
#     # Default values in case parsing fails
#     summary = ""
#     parts: list[str] = []

#     # Extract summary
#     summary_match = re.search(r"<summary>\s*([\s\S]+?)\s*</summary>", text, re.IGNORECASE)
#     if summary_match:
#         summary = str(summary_match.group(1)).strip()

#     # Extract parts
#     part_matches = re.finditer(r"<part>\s*([\s\S]+?)\s*</part>", text, re.IGNORECASE)
#     parts = [match.group(1).strip() for match in part_matches]

#     return summary, parts
