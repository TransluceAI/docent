import json
import re

from jsonschema.exceptions import SchemaError, ValidationError

from docent._llm_util.llm_svc import BaseLLMService
from docent._llm_util.providers.preference_types import ModelOption
from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRunView
from docent.data_models.chat.message import ChatMessage, ToolMessage, UserMessage
from docent.data_models.chat.tool import (
    ToolCall,
    ToolInfo,
    ToolParam,
    ToolParams,
)
from docent.judges import Rubric
from docent_core.docent.ai_tools.rubric.rewrite import rewrite_rubric

logger = get_logger(__name__)

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
- I'll first propose an initial rubric, get your high-level feedback, and ask questions to clarify specific ambiguities.
- At any time, you can ask me to update the rubric based on feedback.
- Whenever I update the rubric, it will be re-run, and you can see the results in the left.
""".strip()

DIRECT_SEARCH_WELCOME_MESSAGE = """
Hi! Let's build a concrete rubric that captures the behavior you're looking for.
- Feel free to examine and label results from your query. In the meantime, I'll ask you some questions to clarify specific ambiguities.
- At any time, you can ask me to update the rubric based on feedback.
- Whenever I update the rubric, it will be re-run, and you can see the results in the left.
""".strip()

##################
# System prompts #
##################
# Again, two: one for guided search, and another for direct

GUIDED_SEARCH_PROCEDURE = """
Start by calling the rewrite_rubric tool to propose an initial rubric and output schema. Provide the instruction "initial operationalization; potentially rewrite schema if necessary" to the tool. After the initial rubric is produced, ask the user for general feedback and lampshade that you will move on to some more concrete questions next, but do not ask any specific questions yet. If they provide any feedback, incorporate it by calling rewrite_rubric again, but with an instruction describing the feedback, which should exclusively be derived from the user's feedback. Do NOT continue to the next step before the user responds. Next, ask the user a series of specific questions to clarify ambiguities in the natural language predicates and decision points.
""".strip()

DIRECT_SEARCH_PROCEDURE = """
The user has started with a simple rubric. Start by asking the user a series of specific questions to clarify ambiguities in the natural language predicates and decision points.
""".strip()

SYS_PROMPT_TEMPLATE = """
<High-level overview>
    You are guiding a user through a rubric refinement process, where they start with a vague idea of a behavior they're looking for in a dataset of AI agent run transcripts. You must help the user write out a concrete specification of what they are looking for - i.e., create and refine a rubric. The initial rubric will be provided as `rubric` in XML.
</High-level overview>

<How to engage with the user>
    {starting_procedure}

    Continue asking questions until the important principal components of uncertainty have been resolved. Once you feel like you have a pretty good idea of how would rewrite the rubric, do so using the rewrite_rubric tool while keeping the key components of a rubric in mind. Make sure that the rubric is sufficiently detailed and could be properly evaluated by another system.

    Guidelines for questions:
        - Make sure your questions are simple, self-contained, and only address one issue at a time.
        - Do not assume that the user has read any of the transcripts; contextualize questions with sufficient detail.
        - Ask questions one by one as if you are having a conversation with a user. Do NOT put them all in the same message.
        - The user may have follow-up questions about specific details. Do your best to answer, and make your answers self-contained and comprehensive.
</How to engage with the user>

<Rules for using rewrite_rubric>
    - You should invoke this tool when the user asks you to rewrite the rubric or change the schema. You can also invoke it yourself in accordance with the "how to engage with the user" section.
    - When you call this tool, provide instructions for how to perform the rewrite, based on what you have learned from engaging with the user. You may also pass an empty string to start.
    - The rewrite_rubric tool returns an output containing the new rubric and output schema. This is for your information, so you know how the rewrite was performed.
    - After calling rewrite_rubric, do NOT regurgitate the content of the rubric. The user can see it on their UI.
</Rules for using rewrite_rubric>
""".strip()

DIRECT_SEARCH_SYS_PROMPT = _remove_leading_whitespaces(
    SYS_PROMPT_TEMPLATE.format(starting_procedure=DIRECT_SEARCH_PROCEDURE)
)
GUIDED_SEARCH_SYS_PROMPT = _remove_leading_whitespaces(
    SYS_PROMPT_TEMPLATE.format(starting_procedure=GUIDED_SEARCH_PROCEDURE)
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


def create_rewrite_rubric_tool() -> ToolInfo:
    return ToolInfo(
        name="rewrite_rubric",
        description="Rewrite the rubric and output schema given some instructions.",
        parameters=ToolParams(
            type="object",
            properties={
                "instructions": ToolParam(
                    name="instructions",
                    description="Instructions for rewriting the rubric",
                    input_schema={"type": "string"},
                ),
            },
        ),
    )


async def execute_rewrite_rubric(
    old_rubric: Rubric,
    tool_call: ToolCall,
    llm_svc: BaseLLMService,
    model_options: list[ModelOption],
    sampled_agent_run_views: list[AgentRunView] | None = None,
    annotated_agent_run_views: list[AgentRunView] | None = None,
) -> tuple[Rubric | None, ToolMessage]:
    # This function may raise errors for a number of reasons
    try:
        rubric = await rewrite_rubric(
            old_rubric,
            instructions=tool_call.arguments.get("instructions", ""),
            selection_indices=None,
            model_options=model_options,
            sampled_agent_run_views=sampled_agent_run_views,
            annotated_agent_run_views=annotated_agent_run_views,
            llm_svc=llm_svc,
        )

        return rubric, ToolMessage(
            content=f"""
The rubric has been rewritten.
<rubric_version>{rubric.version}</rubric_version>
<rubric_text>{rubric.rubric_text}</rubric_text>
<rubric_output_schema>{rubric.output_schema}</rubric_output_schema>
            """.strip(),
            tool_call_id=tool_call.id,
            function=tool_call.function,
            error=None,
        )
    except json.JSONDecodeError as e:
        error_msg = f"Failed to parse output schema as JSON: {e}"
        logger.error(error_msg, exc_info=True)
        return None, ToolMessage(
            content=error_msg,
            error={"detail": error_msg},
            tool_call_id=tool_call.id,
            function=tool_call.function,
        )
    except ValidationError as e:
        error_msg = f"Output schema validation failed: {e.message}"
        logger.error(error_msg, exc_info=True)
        return None, ToolMessage(
            content=error_msg,
            error={"detail": error_msg},
            tool_call_id=tool_call.id,
            function=tool_call.function,
        )
    except SchemaError as e:
        error_msg = f"Invalid JSON Schema: {e.message}"
        logger.error(error_msg, exc_info=True)
        return None, ToolMessage(
            content=error_msg,
            error={"detail": error_msg},
            tool_call_id=tool_call.id,
            function=tool_call.function,
        )
    except Exception as e:
        logger.error(f"Unknown error rewriting rubric: {e}", exc_info=True)
        return None, ToolMessage(
            content="An unknown error occurred while rewriting the rubric.",
            error={"detail": "Unknown error"},
            tool_call_id=tool_call.id,
            function=tool_call.function,
        )


################################
# User-message context helpers #
################################


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


##########################
# Rubric update template #
##########################

RUBRIC_UPDATE_TEMPLATE = """
The user updated the rubric from v{previous_version} to v{new_version}.
<rubric>
{rubric}
</rubric>
<output_schema>
{output_schema}
</output_schema>
""".strip()
