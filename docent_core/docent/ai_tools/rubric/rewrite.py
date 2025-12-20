import json
import re
from typing import Any

from docent._llm_util.llm_svc import BaseLLMService
from docent._llm_util.providers.preference_types import ModelOption
from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRunView
from docent.judges import Rubric

logger = get_logger(__name__)

RUBRIC_GUIDELINES = """
The following rules govern how you should write rubrics and their schemas:

<Rubric guidelines>
    A rubric must contain exactly these components:
    - One paragraph with an insightful high-level framing that makes the ensuing specification highly simple and parsimonious. Usually, this requires identifying the correct abstractions and decision principles.
    - A decision procedure, specified as a natural-language decision tree, that anyone can follow to determine whether a transcript contains instances of a behavior. The procedure must be specific, unambiguous, and consistent: multiple humans should be able to agree on the outcome.
    - An output schema, specified as JSON Schema, that describes the output of the decision procedure.

    Guidelines for creating and revising rubrics:
    - The level of specificity and detail in the decision procedure should be commensurate with the amount of information available to you. If the user has only provided a vague one-line statement, there is no need to overfit to a complex rubric.
    - It's extremely important that the decision procedure is concise, simple, and clear. Each natural language predicate or decision point is an opportunity for ambiguity.
    - Unless otherwise stated, revisions to existing complex rubrics should be as minimal and targeted as possible. Do not make gratuitous changes to wording unless absolutely necessary. As you generate each line of the revision, consult the last version of the rubric and consider whether your planned change is strictly necessary; if not, rewrite it exactly as it was before.
</Rubric guidelines>

<Formatting instructions>
    - Format your answers and rubrics in Markdown.
    - To create a new line, use two newlines (\\n\\n).
    - Unordered lists (-), ordered lists (1.), and code ticks (` or ```) are permitted. All other forms of markup including bold, italics, and headings are strictly forbidden.
    - You may nest lists, but make sure to use the correct indentation.
    - Do not put the output schema in the rubric text.
</Formatting instructions>

<Output schema guidelines>
    - The schema must follow the JSON Schema standard.
    - The schema must NOT use nested objects or arrays.
    - The schema must NOT use any custom string formats such as dates or addresses.
    - There is a custom optional key "citations" (bool type) which may be added to string properties. If the judge model outputs a citation at this field, it will be parsed for the user.
</Output schema guidelines>
""".strip()

SELECTION_TAG = "SELECTED"
SELECTION_PROMPT = f"""
<User-provided selection>
    Notice that the user has selected a piece of text in the <{SELECTION_TAG}>...</{SELECTION_TAG}> tag. You are only permitted to rewrite content within the selection. Do NOT change any other text when rewriting the rubric.
</User-provided selection>
""".strip()

REWRITE_PROMPT = """
You are engaging in a rubric refinement process, where a user comes in with a vague idea of a behavior they are looking for in a dataset of AI agent run transcripts. Your job is to help the user write out a concrete specification of what they are looking for.

Here is the current rubric and schema:

<rubric_text>
{rubric}
</rubric_text>
<rubric_output_schema>
{rubric_output_schema}
</rubric_output_schema>

Follow these instructions for how to rewrite the rubric:

<Rewriting instructions>
{instructions}
</Rewriting instructions>

{rubric_guidelines}

Return the rewritten rubric and/or schema using the following XML tags. You may omit a tag entirely if you do not wish to modify that component (e.g., if the user's instructions only pertain to the rubric text, you may omit <rubric_output_schema>).

<rubric_text>
[Rubric text in Markdown]
</rubric_text>
<rubric_output_schema>
[Output schema in JSONSchema]
</rubric_output_schema>
""".strip()


ANNOTATED_ARV_PROMPT = """
A user has come in with a vague idea of a behavior they are looking for in a dataset of AI agent run transcripts. We are trying to concretize what they are judging for. They have provided this initial rubric and schema:

<rubric_text>
{rubric}
</rubric_text>
<rubric_output_schema>
{rubric_output_schema}
</rubric_output_schema>

They have also provided comments on a specific agent run, which may reveal important information about what they want to judge for, *how* they think about judging it, etc.

<Annotated agent run view>
{annotated_agent_run_view}
</Annotated agent run view>

Your job is to extract details about what the user wants to measure or how they believe it should be judged, based on their comments, and detail them in an executive summary. Include rich, concrete details that will help the downstream system understand the full context. Make sure the summary is as concise as possible while conveying the key information.

Return your answer in the following format:
<details>
...
</details>

It is critical that you only include information pertinent to the provided annotated agent run. You may abstain from answering if it does not seem like any of the user's annotations have any relevance to the topic being judged; you can do so by not printing the <details>...</details> tags and instead briefly explaining why you are abstaining.
""".strip()

ANNOTATED_ARV_CTX_PROMPT = """
<User annotations on agent runs>
The user has left comments on agent runs detailing how they think about what they're trying to judge. We've used another system to extract the key details from these annotated agent runs. Incorporate this information while rewriting the rubric, but do not overfit to irrelevant details.
{user_annotations_on_agent_runs}
</User annotations on agent runs>
""".strip()

ARV_PROMPT = """
A user has come in with a vague idea of a behavior they are looking for in a dataset of AI agent run transcripts. We are trying to concretize what they are judging for. They have provided this initial rubric and schema:

<rubric_text>
{rubric}
</rubric_text>
<rubric_output_schema>
{rubric_output_schema}
</rubric_output_schema>

Here is a randomly-sampled agent run, which may reveal important information about how to judge for what they want.

<Agent run view>
{agent_run_view}
</Agent run view>

Your job is to extract information that could be useful for judging for what the user wants, and detail them in an executive summary. Include rich, concrete details that will help the downstream system understand the full context. Make sure the summary is as concise as possible while conveying the key information.

Return your answer in the following format:
<details>
...
</details>
""".strip()

ARV_CTX_PROMPT = """
<Details from agent runs>
Here are some details extracted from randomly-sampled agent runs that may be useful for understanding the context. Incorporate this information while rewriting the rubric, but do not overfit to irrelevant details.
{details}
</Details from agent runs>
""".strip()


async def extract_details_from_annotated_arvs(
    rubric: Rubric,
    annotated_agent_run_views: list[AgentRunView],
    model_options: list[ModelOption],
    llm_svc: BaseLLMService,
) -> list[str]:
    """
    Extract details from annotated agent run views using an LLM.

    Args:
        rubric: The rubric to use for context.
        annotated_agent_run_views: List of annotated agent run views to process.
        model_options: The model options to use for completions.
        llm_svc: The LLM service to use for completions.

    Returns:
        A list of extracted details from the annotated agent runs.
    """
    prompts = [
        ANNOTATED_ARV_PROMPT.format(
            rubric=rubric.rubric_text,
            rubric_output_schema=rubric.output_schema,
            annotated_agent_run_view=arv.to_text(),
        )
        for arv in annotated_agent_run_views
    ]
    logger.info(f"Processing {len(prompts)} agent runs with human annotations")
    outputs = await llm_svc.get_completions(
        inputs=[[{"role": "user", "content": prompt}] for prompt in prompts],
        model_options=model_options,
        max_new_tokens=16384,
    )
    details: list[str] = []
    for output in outputs:
        if output.first_text:
            match = re.search(r"<details>(.*?)</details>", output.first_text, re.DOTALL)
            if match:
                details.append(match.group(1).strip())
    return details


async def extract_details_from_agent_run_views(
    rubric: Rubric,
    agent_run_views: list[AgentRunView],
    model_options: list[ModelOption],
    llm_svc: BaseLLMService,
) -> list[str]:
    """
    Extract details from agent run views using an LLM.

    Args:
        rubric: The rubric to use for context.
        agent_run_views: List of agent run views to process.
        model_options: The model options to use for completions.
        llm_svc: The LLM service to use for completions.

    Returns:
        A list of extracted details from the agent runs.
    """
    prompts = [
        ARV_PROMPT.format(
            rubric=rubric.rubric_text,
            rubric_output_schema=rubric.output_schema,
            agent_run_view=arv.to_text(),
        )
        for arv in agent_run_views
    ]
    logger.info(f"Processing {len(prompts)} agent runs for detail extraction")
    outputs = await llm_svc.get_completions(
        inputs=[[{"role": "user", "content": prompt}] for prompt in prompts],
        model_options=model_options,
        max_new_tokens=16384,
    )
    details: list[str] = []
    for output in outputs:
        if output.first_text:
            match = re.search(r"<details>(.*?)</details>", output.first_text, re.DOTALL)
            if match:
                details.append(match.group(1).strip())
    return details


async def rewrite_rubric(
    rubric: Rubric,
    instructions: str,
    model_options: list[ModelOption],
    selection_indices: tuple[int, int] | None = None,
    sampled_agent_run_views: list[AgentRunView] | None = None,
    annotated_agent_run_views: list[AgentRunView] | None = None,
    llm_svc: BaseLLMService = BaseLLMService(),
) -> Rubric:
    """
    Note that this also increments the rubric version.

    Raises:
        ValueError: If selection indices are invalid (negative, start > end, or end exceeds rubric length).
        json.JSONDecodeError: If the LLM output cannot be parsed as valid JSON.
        jsonschema.ValidationError: If the output schema is invalid.
        jsonschema.SchemaError: If the output schema is not a valid JSON Schema.
        Some LLM errors, probably
    """

    rubric_text_formatted = rubric.rubric_text
    rubric_guidelines = RUBRIC_GUIDELINES

    # Convert the annotated agent runs into instructions for the rewriter to follow.
    if annotated_agent_run_views:
        details = await extract_details_from_annotated_arvs(
            rubric=rubric,
            annotated_agent_run_views=annotated_agent_run_views,
            model_options=model_options,
            llm_svc=llm_svc,
        )

        instructions += "\n\n" + ANNOTATED_ARV_CTX_PROMPT.format(
            user_annotations_on_agent_runs="\n".join(
                [f"Detail on agent run {i+1}:\n{detail}" for i, detail in enumerate(details)]
            )
        )

    # Convert the sampled agent runs into instructions for the rewriter to follow.
    if sampled_agent_run_views:
        details = await extract_details_from_agent_run_views(
            rubric=rubric,
            agent_run_views=sampled_agent_run_views,
            model_options=model_options,
            llm_svc=llm_svc,
        )
        instructions += "\n\n" + ARV_CTX_PROMPT.format(details="\n".join(details))

    # Format rubric text with selection tags
    if selection_indices is not None:
        start, end = selection_indices
        if start < 0 or end < 0:
            raise ValueError(f"Selection indices must be non-negative, got ({start}, {end})")
        if start > end:
            raise ValueError(f"Start index must be <= end index, got ({start}, {end})")
        if end > len(rubric_text_formatted):
            raise ValueError(
                f"End index {end} exceeds rubric text length {len(rubric_text_formatted)}"
            )
        rubric_text_formatted = (
            rubric_text_formatted[:start]
            + f"<{SELECTION_TAG}>"
            + rubric_text_formatted[start:end]
            + f"</{SELECTION_TAG}>"
            + rubric_text_formatted[end:]
        )

        rubric_guidelines += f"\n\n{SELECTION_PROMPT}"

    rewrite_prompt = REWRITE_PROMPT.format(
        rubric=rubric_text_formatted,
        rubric_output_schema=rubric.output_schema,
        instructions=instructions,
        rubric_guidelines=rubric_guidelines,
    )
    outputs = await llm_svc.get_completions(
        inputs=[[{"role": "user", "content": rewrite_prompt}]],
        model_options=model_options,
        max_new_tokens=16384,
    )
    output = outputs[0]
    output_text = output.first_text or ""

    updates: dict[str, Any] = {"version": rubric.version + 1}
    # Parse rubric text
    rubric_match = re.search(r"<rubric_text>(.*?)</rubric_text>", output_text, re.DOTALL)
    if rubric_match:
        updates["rubric_text"] = rubric_match.group(1).strip()

    # Parse output schema
    schema_match = re.search(
        r"<rubric_output_schema>(.*?)</rubric_output_schema>", output_text, re.DOTALL
    )
    if schema_match:
        schema_text = schema_match.group(1).strip()
        updates["output_schema"] = json.loads(schema_text)

    return rubric.model_copy(update=updates)
