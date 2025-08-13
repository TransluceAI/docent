# from docent.data_models.transcript import SINGLE_RUN_CITE_INSTRUCTION
import re
from typing import Any

from docent.data_models.chat.message import ChatMessage, UserMessage
from docent.data_models.chat.tool import (
    ToolCall,
    ToolInfo,
    ToolParam,
    ToolParams,
)
from docent_core._ai_tools.rubric.rubric import ResultType, Rubric
from docent_core.docent.db.schemas.rubric import JudgeResult, SQLARubricCentroid

DEV_MESSAGE_TEMPLATE = """
<rubric_state>
{rubric_state}
</rubric_state>
<search_hits>
{search_hits}
</search_hits>
<centroids>
{centroids}
</centroids>
<user_message>
{user_message}
</user_message>
""".strip()

INITIAL_MESSAGE = "The rubric version has incremented and this is the start of a new conversation."


def _clean_message_state(message: ChatMessage, key: str, replacement: str):
    """Replace rubric state content in previous messages with 'Outdated transcript.'"""
    rubric_state_pattern = rf"<{key}>.*?</{key}>"
    replacement = f"<{key}>\n{replacement}\n</{key}>"

    if hasattr(message, "content") and isinstance(message.content, str):
        message.content = re.sub(
            rubric_state_pattern, replacement, message.content, flags=re.DOTALL
        )


def _format_search_hits(judgements: list[JudgeResult]) -> str:
    template = "<search_result_[R{idx}]>\n{result}\n</search_result_[R{idx}]>"
    search_results = [judgement.value for judgement in judgements if judgement.value is not None]
    return "\n".join(
        template.format(idx=idx + 1, result=result) for idx, result in enumerate(search_results)
    )


def _get_assignment_strings(
    assignments: dict[str, list[str]], search_hits: list[JudgeResult]
) -> dict[str, str]:
    formatted_assignments: dict[str, str] = {}

    result_ids_to_idx = {
        result.id: idx + 1 for idx, result in enumerate(search_hits) if result.value is not None
    }

    for centroid_id, result_ids in assignments.items():
        formatted_assignments[centroid_id] = "\n".join(
            f"[R{result_ids_to_idx[result_id] + 1}]" for result_id in result_ids
        )

    return formatted_assignments


# def _format_centroids(centroids: list[SQLARubricCentroid]) -> str:
#     direct_centroids = [
#         centroid.centroid
#         for centroid in centroids
#         if centroid.result_type == ResultType.DIRECT_RESULT
#     ]
#     near_miss_centroids = [
#         centroid.centroid for centroid in centroids if centroid.result_type == ResultType.NEAR_MISS
#     ]

#     direct_centroids.sort()
#     near_miss_centroids.sort()

#     template = "<centroid_{idx}>\n{centroid}\n</centroid_{idx}>"

#     return "\n".join(
#         template.format(idx=idx + 1, centroid=centroid)
#         for idx, centroid in enumerate(direct_centroids + near_miss_centroids)
#     )


def _format_centroids_with_assignments(
    centroids: list[SQLARubricCentroid], assignment_strings: dict[str, str]
) -> str:
    direct_centroids = [
        (centroid.centroid, centroid.id)
        for centroid in centroids
        if centroid.result_type == ResultType.DIRECT_RESULT
    ]
    near_miss_centroids = [
        (centroid.centroid, centroid.id)
        for centroid in centroids
        if centroid.result_type == ResultType.NEAR_MISS
    ]

    direct_centroids.sort(key=lambda x: x[0])
    near_miss_centroids.sort(key=lambda x: x[0])

    template = "<centroid_{idx}>\n{centroid}\n<assignments>\n{assignments}\n</assignments>\n</centroid_{idx}>"

    string = ""
    for idx, (centroid, centroid_id) in enumerate(direct_centroids + near_miss_centroids):
        result_assignments = assignment_strings.get(centroid_id, "")
        string += template.format(idx=idx + 1, centroid=centroid, assignments=result_assignments)

    return string


def format_conversation_for_client(
    messages: list[ChatMessage], serialize: bool = True
) -> list[ChatMessage | dict[str, Any]]:
    """Format the conversation for the client."""
    formatted_messages: list[ChatMessage | dict[str, Any]] = []
    for message in messages:
        # Create a copy of the message to avoid modifying the original
        message_copy = message.model_copy(deep=True)

        if message_copy.role == "user" and not isinstance(message_copy.content, list):
            user_message_pattern = r"<user_message>(.*?)</user_message>"
            match = re.search(user_message_pattern, message_copy.content, re.DOTALL)
            if match:
                message_copy.content = match.group(1).strip()

        if message_copy.role == "user" and message_copy.content == INITIAL_MESSAGE:
            continue

        if serialize:
            formatted_messages.append(message_copy.model_dump())
        else:
            formatted_messages.append(message_copy)

    return formatted_messages


def format_conversation(
    prompt: str,
    messages: list[ChatMessage],
    rubric: Rubric,
    centroids: list[SQLARubricCentroid],
    judgements: list[JudgeResult],
    assignments: dict[str, list[str]],
) -> list[ChatMessage]:
    """
    Include the most recent rubric and search results in the conversation.

    Clear the rubric state and search results from previous messages.
    """

    fresh_results = True
    last_user_message = None
    for message in messages[::-1]:
        if message.role == "user":
            last_user_message = message
            break

    if (
        last_user_message is not None
        and hasattr(last_user_message, "content")
        and isinstance(last_user_message.content, str)
    ):
        contents = last_user_message.content
        if f"<rubric_state>\n(v{rubric.version})" in contents:
            fresh_results = False

    for message in messages:
        if fresh_results:
            _clean_message_state(message, "search_hits", "Outdated search hits.")
            _clean_message_state(message, "centroids", "Outdated centroids.")

    formatted_judgements = ""
    formatted_centroids = ""
    if fresh_results:
        formatted_judgements = _format_search_hits(judgements)
        assignment_strings = _get_assignment_strings(assignments, judgements)
        formatted_centroids = _format_centroids_with_assignments(centroids, assignment_strings)

    user_message = UserMessage(
        content=DEV_MESSAGE_TEMPLATE.format(
            search_hits=formatted_judgements,
            rubric_state=rubric.text,
            centroids=formatted_centroids,
            user_message=prompt,
        ),
        role="user",
    )

    return messages + [user_message]


# Define the search tool
def create_search_tool() -> ToolInfo:
    return ToolInfo(
        name="search",
        description="Search for agent runs",
        parameters=ToolParams(
            type="object",
            properties={},
            required=[],
        ),
    )


def create_add_rubric_rule_tool() -> ToolInfo:
    return ToolInfo(
        name="addRubricRule",
        description="Add one or more new rules to a Rubric object.",
        parameters=ToolParams(
            type="object",
            properties={
                "field": ToolParam(
                    name="field",
                    description="The field to edit: 'inclusion_rules' or 'exclusion_rules'",
                    input_schema={
                        "type": "string",
                        "enum": [
                            "inclusion_rules",
                            "exclusion_rules",
                        ],
                    },
                ),
                "new_rules": ToolParam(
                    name="new_rules",
                    description="The new rules to add (can be a single rule or multiple rules)",
                    input_schema={
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                ),
            },
            required=["field", "new_rules"],
        ),
    )


def create_update_description_tool() -> ToolInfo:
    return ToolInfo(
        name="updateDescription",
        description="Update the high level description of a Rubric object.",
        parameters=ToolParams(
            type="object",
            properties={
                "updated_description": ToolParam(
                    name="updated_description",
                    description="The updated description for the Rubric object.",
                    input_schema={"type": "string"},
                ),
            },
            required=["updated_description"],
        ),
    )


# Define the updateRubric tool
def create_update_rule_tool() -> ToolInfo:
    return ToolInfo(
        name="updateRubric",
        description="Update one or more existing rules in a Rubric object.",
        parameters=ToolParams(
            type="object",
            properties={
                "updates": ToolParam(
                    name="updates",
                    description="List of updates to apply to the rubric rules.",
                    input_schema={
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {
                                    "type": "string",
                                    "enum": [
                                        "inclusion_rules",
                                        "exclusion_rules",
                                    ],
                                    "description": "The field to update: 'inclusion_rules' or 'exclusion_rules'.",
                                },
                                "index": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "description": "The index of the rule to update.",
                                },
                                "updated_rule": {
                                    "type": "string",
                                    "description": "The updated rule.",
                                },
                            },
                            "required": ["field", "index", "updated_rule"],
                        },
                        "minItems": 1,
                    },
                ),
            },
            required=["updates"],
        ),
    )


def execute_update_description(rubric: Rubric, tool_call: ToolCall) -> str:
    """Execute the update description tool."""
    try:
        updated_description = tool_call.arguments.get("updated_description", "")
        rubric.high_level_description = updated_description
        return f"Updated rubric description to: {updated_description}"
    except Exception as e:
        return f"Error updating description: {str(e)}"


def execute_add_rubric_rule(rubric: Rubric, tool_call: ToolCall) -> str:
    """Execute the add rubric rule tool."""
    try:
        field = tool_call.arguments.get("field", "")
        new_rules: list[str] = tool_call.arguments.get("new_rules", [])

        if field == "inclusion_rules":
            rubric.inclusion_rules.extend(new_rules)
            return f"Added {len(new_rules)} inclusion rule(s): {', '.join(new_rules)}"
        elif field == "exclusion_rules":
            rubric.exclusion_rules.extend(new_rules)
            return f"Added {len(new_rules)} exclusion rule(s): {', '.join(new_rules)}"
        else:
            return f"Invalid field: {field}. Must be 'inclusion_rules' or 'exclusion_rules'"

    except Exception as e:
        return f"Error adding rules: {str(e)}"


def execute_update_rule(rubric: Rubric, tool_call: ToolCall) -> str:
    """Execute the update rule tool."""
    try:
        updates: list[dict[str, str | int]] = tool_call.arguments.get("updates", [])
        results: list[str] = []

        for update in updates:
            field: str = update.get("field", "")  # type: ignore
            index: int = update.get("index", 0)  # type: ignore
            updated_rule: str = update.get("updated_rule", "")  # type: ignore

            if field == "inclusion_rules":
                if 0 <= index < len(rubric.inclusion_rules):
                    old_rule: str = rubric.inclusion_rules[index]  # type: ignore
                    rubric.inclusion_rules[index] = updated_rule
                    results.append(
                        f"Updated inclusion rule at index {index} from '{old_rule}' to '{updated_rule}'"
                    )
                else:
                    results.append(
                        f"Invalid index {index} for inclusion rules (have {len(rubric.inclusion_rules)} rules)"
                    )
            elif field == "exclusion_rules":
                if 0 <= index < len(rubric.exclusion_rules):
                    old_rule: str = rubric.exclusion_rules[index]  # type: ignore
                    rubric.exclusion_rules[index] = updated_rule
                    results.append(
                        f"Updated exclusion rule at index {index} from '{old_rule}' to '{updated_rule}'"
                    )
                else:
                    results.append(
                        f"Invalid index {index} for exclusion rules (have {len(rubric.exclusion_rules)} rules)"
                    )
            else:
                results.append(
                    f"Invalid field: {field}. Must be 'inclusion_rules' or 'exclusion_rules'"
                )

        return "\n".join(results)

    except Exception as e:
        return f"Error updating rules: {str(e)}"


# Create tool instances
search_tool_info = create_search_tool()
update_description_tool_info = create_update_description_tool()
update_rule_tool_info = create_update_rule_tool()
add_rubric_rule_tool_info = create_add_rubric_rule_tool()

TOOL_DESCRIPTIONS = "\n".join(
    str(tool.model_dump())
    for tool in [
        # search_tool_info,
        update_description_tool_info,
        update_rule_tool_info,
        add_rubric_rule_tool_info,
    ]
)


REFINEMENT_TOOLS = [
    update_description_tool_info,
    update_rule_tool_info,
    add_rubric_rule_tool_info,
]

JUDGEMENT_CITE_INSTRUCTION = "Cite the search results in brackets when relevant, like [R<idx>]. Use multiple tags to cite multiple blocks, like [R<idx>][R<idx>]."

# formerly part of sys prompt. we are no longer giving the agent the search tool
SEARCH_TOOL_CLAUSE = f"""
<search_and_clustering>
You may call the search tool to find agent run transcripts that match the rubric.

*Never* call the search tool without confirming with the user first. You should ask to use the search tool in the following situations:
- After asking clarifying questions.
- After you have applied an edit to the rubric provided a user suggestion.

You may also call the search tool when the user directs you to do so.

{JUDGEMENT_CITE_INSTRUCTION}
</search_and_clustering>
""".strip()


SYSTEM_PROMPT = f"""
Your task is to help build and refine a rubric for something a user wants to find in an agent run.

<clarification_questions>
At the start of the conversation, you will be provided with the user's initial search query and, optionally, a list of results from a sample of agent runs + clusters of those results.

You must ask clarifying questions until you understand the user's query. Ask one clarifying question per message. Only ask 3 clarifying questions *max*. Do not number your questions.

If the user asks to skip the clarifying questions, you may do so.

In the process of asking questions, you should start to build and refine the rubric.
</clarification_questions>

<rubric_refinement>
The user may provide feedback on the rubric. You may call the edit_rubric tool to apply the feedback.

To add a new rule to the rubric, you may call the add_rubric_rule tool.
</rubric_refinement>

<centroids>
The user may ask about certain centroids. They will reference them using @1, @2, etc. which correspond to the order of centroids in the <centroids> tag.
</centroids>

# Tools

You may call one or more functions to assist with the user query.

You are provided with function signatures:
<tools>
{TOOL_DESCRIPTIONS}
</tools>

You will now be given the user's initial query and results + clusters.

Your initial response should always be to clarify the existing clusters: reply with exactly "Hello! I'm here to help you refine your search rubric. To start out, I've clustered the results and near misses for you. Do you see any clusters of search hits that don't belong, or clusters of near misses that should be included in the rubric?" and nothing else.

When the rubric version changes (eg. from (v0) to (v1)), you will receive a fresh set of results + clusters; you should treat this as the start of a new sub-conversation and also reply with the exact same message as above in that case.

In subsequent messages, your response should obey the following pattern:
- Take the feedback from the user's most recent message into account and revise the rubric with the edit_rubric tool.
- Rubric rules should always follow this exact format: "Cases where <some predicate occurs>", eg. "Cases where the agent did X".
- If the query / rubric still feels ambiguous to you, ask a clarifying question, eg. "Should the rubric include / exclude cases of X?".
- It's usually more helpful to ask clarifying questions about the rubric as a whole, rather than questions about whatever the user's most recent feedback was.
- If the rubric no longer feels ambiguous, you should instead ask for general feedback, eg. "Are there any other changes you would like to make to the rubric?"
- While the user may use tags like @1, @2 to reference clusters, you must NOT use these tags when adding rules to the rubric.
""".strip()
