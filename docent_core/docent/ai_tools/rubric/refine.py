import json
import re
from typing import Any, Protocol

from docent.data_models.agent_run import AgentRun
from docent.data_models.chat.message import ChatMessage, SystemMessage, ToolMessage, UserMessage
from docent.data_models.chat.tool import (
    ToolCall,
    ToolInfo,
    ToolParam,
    ToolParams,
)
from docent_core._llm_util.data_models.llm_output import LLMOutput
from docent_core._llm_util.prod_llms import MessagesInput, get_llm_completions_async
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES
from docent_core.docent.ai_tools.rubric.rubric import (
    JudgeResult,
    JudgeRunLabel,
    Rubric,
    validate_schema,
)

# TODO(mengk): if a user asks a statistical question, reframe it into a rubric question and then tell them to use the plotting functions to accomplish their goal.
# TODO(mengk): ask for context on what the various transcripts are if it's not clear.


def _remove_leading_whitespaces(text: str) -> str:
    lines_with_endings = text.splitlines(keepends=True)
    stripped_lines = (line.lstrip() for line in lines_with_endings)
    return "".join(stripped_lines)


####################
# Welcome messages #
####################
# There are two: one for guided search, and another for direct

GUIDED_SEARCH_WELCOME_MESSAGE = """
Hi! Let's build a concrete rubric that captures the behavior you're looking for.
- First, I'll look through your dataset and find illuminating examples that could be a match.
- Then, I'll propose an initial rubric, get your high-level feedback, and ask questions to clarify specific ambiguities.
- Whenever I update the rubric, it will be re-run, and you can see the results in the left.
""".strip()

DIRECT_SEARCH_WELCOME_MESSAGE = """
Hi! Let's build a concrete rubric that captures the behavior you're looking for.
- Feel free to examine and label results from your query.
- In the meantime, I'll ask you some questions to clarify specific ambiguities.
- At any time, you can ask me to update the rubric based on feedback.
""".strip()

##################
# System prompts #
##################
# Again, two: one for guided search, and another for direct

GUIDED_SEARCH_PROCEDURE = """
<Procedure for engaging with the user>
    We have generated summaries of a subset of agent runs from the dataset to provide context about the types of behaviors and interactions present. These summaries give you insight into the content and patterns within the agent run transcripts. This will be provided as `summaries` in XML. If the summaries are empty, acknowledge that you don't have specific context about the dataset, but that you'll try to operationalize the rubric anyway.

    Start by proposing an initial rubric and output schema that follows the guidelines above, using the set_rubric_and_schema tool. Use your best judgement and consult the summaries for inspiration about the types of behaviors present in the dataset. After you produce the initial rubric, ask the user for general feedback and lampshade that you will move on to some more concrete questions next, but do not ask any specific questions yet. If they provide any feedback, incorporate it by calling set_rubric_and_schema again. Do NOT continue to the next step before the user responds.

    If the user cancels the summarization, that means they'd like to refine starting from a simple rubric. Do NOT call set_rubric_and_schema. Instead, acknowledge that you'll start with a simple rubric and refine from there.

    Next, ask the user a series of specific questions to clarify ambiguities in the natural language predicates and decision points.
    - Make sure your questions are simple, self-contained, and only address one issue at a time.
    - Do not assume that the user has read any of the transcripts; contextualize questions with sufficient detail.
    - Ask questions one by one as if you are having a conversation with a user. Do NOT put them all in the same message.
    - The user may have follow-up questions about specific details. Do your best to answer, and make your answers self-contained and comprehensive.

    Continue asking questions until the important principal components of uncertainty have been resolved. Once you feel like you have a pretty good idea of how would rewrite the rubric, do so using the set rubric tool while keeping the key components of a rubric in mind. Make sure that the rubric is sufficiently detailed and could be properly evaluated by another system.

    If the user asks you to update the rubric, you should use the get_labels tool before calling set_rubric_and_schema. The tool will return labels, which are the user's annotations on a handlful of judge results. You should refine the rubric based on the feedback from the labels.
</Procedure for engaging with the user>
""".strip()

DIRECT_SEARCH_PROCEDURE = """
<Procedure for engaging with the user>
    The user has started with a simple rubric.

    Start by asking the user a series of specific questions to clarify ambiguities in the natural language predicates and decision points.
    - Make sure your questions are simple, self-contained, and only address one issue at a time.
    - Do not assume that the user has read any of the transcripts; contextualize questions with sufficient detail.
    - Ask questions one by one as if you are having a conversation with a user. Do NOT put them all in the same message.
    - The user may have follow-up questions about specific details. Do your best to answer, and make your answers self-contained and comprehensive.

    Continue asking questions until the important principal components of uncertainty have been resolved. Once you feel like you have a pretty good idea of how would rewrite the rubric, do so using the set rubric tool while keeping the key components of a rubric in mind. Make sure that the rubric is sufficiently detailed and could be properly evaluated by another system.

    If the user asks you to update the rubric, you should use the get_labels tool before calling set_rubric_and_schema. The tool will return labels, which are the user's annotations on a handlful of judge results. You should refine the rubric based on the feedback from the labels.
</Procedure for engaging with the user>
""".strip()

SYS_PROMPT_TEMPLATE = """
<High-level overview>
    You are guiding a user through a rubric refinement process, where they start with a vague idea of a behavior they're looking for in a dataset of AI agent run transcripts. You must help the user write out a concrete specification of what they are looking for - i.e., create and refine a rubric. The initial rubric will be provided as `rubric` in XML.
</High-level overview>

<Rubric guidelines>
    A rubric must contain exactly these components:
    - One paragraph with an insightful high-level framing that makes the ensuing specification highly simple and parsimonious. Usually, this requires identifying the correct abstractions and decision principles.
    - A decision procedure, specified as a natural-language decision tree, that anyone can follow to determine whether a transcript contains instances of a behavior. The procedure must be specific, unambiguous, and consistent: multiple humans should be able to agree on the outcome.
    - An output schema, specified as JSON Schema, that describes the output of the decision procedure. The output schema should strive to capture additional, important dimensions of the rubric and decision procedure. If outputs are too simple, certain decisions get flattened into oversimplified judgments that lose critical information about the decision procedure.

    Guidelines for creating and revising rubrics:
    - It's extremely important that the decision procedure is concise, simple, and clear - 惜墨如金. Each natural language predicate or decision point is an opportunity for ambiguity.
    - Create new versions (including the initial) of rubrics using the set_rubric_and_schema tool.
    - The initial version of a rubric should be especially short and sweet. You should work with the user over the course of the conversation to specify additional complexity. If you start with a long rubric, the user will be too overwhelmed to provide useful feedback.
    - Unless otherwise stated, revisions to the rubric should be as minimal and targeted as possible. Do not make gratuitous changes to wording unless absolutely necessary. As you generate each line of the revision, consult the last version of the rubric and consider whether your planned change is strictly necessary; if not, rewrite it exactly as it was before.
    - Users are permitted to update rubrics; when this happens, you will receive a user message with the new content and version of the rubric. No action is required on your part other than acknowledging what the user did and continuing where you left off.
</Rubric guidelines>

{procedure}

<Formatting instructions>
    - Format your answers and rubrics in Markdown.
    - To create a new line, use two newlines (\\n\\n).
    - Unordered lists (-), ordered lists (1.), bold (*), italics (_), code ticks (` or ```), and quotes (>) are supported.
    - You may nest ordered and unordered lists, but make sure to use the correct indentation.
    - Headings are strictly forbidden. Do not use them. Instead of headers, use bold text.
    - The first couple words of each list item must be bolded so that the list is skimmable.
    - If you provide examples, don't provide them as inline parentheses. Instead, provide them as a list item.
    - Do not put the output schema in the rubric text.
</Formatting instructions>

<Output schema guidelines>
    - The schema must follow the JSON Schema standard.
    - The schema must NOT use nested objects or arrays.
    - The schema must NOT use any custom string formats such as dates or addresses.
    - There is a custom optional key "citations" (bool type) which may be added to string properties. If the judge model outputs a citation at this field, it will be parsed for the user.
    - By default, the schema should remain as is. Only edit it if the user asks you to.
</Output schema guidelines>
""".strip()

DIRECT_SEARCH_SYS_PROMPT = _remove_leading_whitespaces(
    SYS_PROMPT_TEMPLATE.format(procedure=DIRECT_SEARCH_PROCEDURE)
)
GUIDED_SEARCH_SYS_PROMPT = _remove_leading_whitespaces(
    SYS_PROMPT_TEMPLATE.format(procedure=GUIDED_SEARCH_PROCEDURE)
)

FIRST_USER_MESSAGE_TEMPLATE = """
<rubric>
{rubric}
</rubric>
<output_schema>
{output_schema}
</output_schema>
""".strip()

#########
# Tools #
#########


def create_set_rubric_and_schema_tool() -> ToolInfo:
    return ToolInfo(
        name="set_rubric_and_schema",
        description="Set the markdown text content and output schema of a rubric",
        parameters=ToolParams(
            type="object",
            properties={
                "text": ToolParam(
                    name="text",
                    description="The markdown text content of the rubric",
                    input_schema={"type": "string"},
                ),
                "output_schema": ToolParam(
                    name="output_schema",
                    description="The output schema object of the rubric",
                    input_schema={"type": "object"},
                ),
            },
        ),
    )


LABEL_TEMPLATE = """
<agent_run_id>{agent_run_id}</agent_run_id>
<result>{result}</result>
<label>{label}</label>
""".strip()


def execute_set_rubric(rubric: Rubric, tool_call: ToolCall) -> ToolMessage:
    rubric.rubric_text = tool_call.arguments.get("text", rubric.rubric_text)
    output_schema: dict[str, Any] | None = tool_call.arguments.get("output_schema")

    # Output schema was not edited
    if output_schema is None:
        rubric.version += 1
        return ToolMessage(
            content=str(rubric.version),
            tool_call_id=tool_call.id,
            function=tool_call.function,
            error=None,
        )

    # Output schema was edited: validate, set, and increment
    is_valid_schema, err = validate_schema(output_schema)
    if not is_valid_schema:
        return ToolMessage(
            content=f"Invalid output schema: {err}",
            error={"detail": err},
            tool_call_id=tool_call.id,
            function=tool_call.function,
        )
    else:
        rubric.output_schema = output_schema
        rubric.version += 1
        return ToolMessage(
            content=str(rubric.version),
            tool_call_id=tool_call.id,
            function=tool_call.function,
            error=None,
        )


################################
# User-message context helpers #
################################


USER_MESSAGE_TEMPLATE = """
<labeled_results>
{labeled_results}
</labeled_results>
<user_message>
{user_message}
</user_message>
""".strip()


def clear_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Clear labeled results from past user messages by replacing the
    context of old messages with the new user message.
    """

    def _extract_user_message(content: str) -> str:
        match = re.search(r"<user_message>(.*?)</user_message>", content, re.DOTALL)
        return match.group(1).strip() if match else content

    # Reformat old messages to just contain the messages
    for message in messages:
        if isinstance(message, UserMessage) and isinstance(message.content, str):
            current_state = _extract_user_message(message.content)
            message.content = current_state

    return messages


def update_user_message_with_labels(
    messages: list[ChatMessage], labels_and_results: list[tuple[JudgeRunLabel, JudgeResult]]
) -> None:
    """Add labels and corresponding results to the most recent user message.
    Clear labels from past user messages.
    """

    clear_messages(messages)

    tool_message = ""
    for label, result in labels_and_results:
        result_text = json.dumps(result.output, indent=2)
        label_text = json.dumps(label.label, indent=2)
        agent_run_id = label.agent_run_id
        formatted_label = LABEL_TEMPLATE.format(
            agent_run_id=agent_run_id, result=result_text, label=label_text
        )
        tool_message += formatted_label + "\n\n"

    last_message = messages[-1].content
    messages[-1].content = USER_MESSAGE_TEMPLATE.format(
        labeled_results=tool_message, user_message=last_message
    )


############################
# First-step summarization #
############################


SUMMARIZE_AGENT_RUNS_SYS_PROMPT = """
You are helping with a rubric refinement process where a user is trying to identify specific behaviors in AI agent run transcripts. Your job is to summarize agent run transcripts to provide context for another agent that will help the user create and refine a rubric.

The user has a vague idea of a behavior they're looking for in the dataset, and they want to create a concrete specification (rubric) to identify instances of this behavior. Your summaries will help the refinement agent understand what types of interactions and behaviors are present in the dataset.

When summarizing each agent run transcript:
- Focus on the key behaviors, interactions, and patterns that occurred
- Highlight any notable decision-making processes, tool usage, or communication patterns
- Include relevant context about what the agent was trying to accomplish
- Note any interesting successes, failures, or edge cases
- Keep your summary concise but informative -- 10 sentences max

The user's query about the behavior they're looking for will be provided as context. Consider this query when deciding what aspects of the transcript to emphasize in your summary.

<user_query>
{user_query}
</user_query>
""".strip()


class SummaryStreamingCallback(Protocol):
    """Supports batched streaming for cases where many search results are pre-computed.
    This avoids invoking the callback separately for each datapoint.
    """

    async def __call__(
        self,
        batch_index: int,
        summary: str,
    ) -> None: ...


def _get_llm_callback(callback: SummaryStreamingCallback):

    async def _llm_callback(batch_index: int, llm_output: LLMOutput):
        summary = llm_output.first_text or ""
        await callback(batch_index, summary)

    return _llm_callback


RUN_SUMMARY_TEMPLATE = """
<run {agent_run_id}>
{summary}
</run {agent_run_id}>
""".strip()


async def summarize_agent_runs(
    rubric_text: str, agent_runs: list[AgentRun], completion_callback: SummaryStreamingCallback
) -> list[LLMOutput]:
    messages_batch: list[MessagesInput] = []
    for ar in agent_runs:
        messages = [
            SystemMessage(content=SUMMARIZE_AGENT_RUNS_SYS_PROMPT.format(user_query=rubric_text)),
            UserMessage(content=ar.text),
        ]
        messages_batch.append(messages)

    return await get_llm_completions_async(
        messages_batch,
        model_options=PROVIDER_PREFERENCES.handle_refinement_message,
        max_new_tokens=8192,
        timeout=180.0,
        use_cache=True,
        completion_callback=_get_llm_callback(completion_callback),
    )


##########################
# Rubric update template #
##########################

RUBRIC_UPDATE_TEMPLATE = """
<user_message>
The user updated the rubric from v{previous_version} to v{new_version}.
</user_message>
<rubric>
{rubric}
</rubric>
<output_schema>
{output_schema}
</output_schema>
""".strip()
