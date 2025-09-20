import json
from typing import Any

import jsonschema
import tiktoken

from docent.data_models.agent_run import AgentRun
from docent.data_models.chat.message import ToolMessage
from docent.data_models.chat.tool import (
    ToolCall,
    ToolInfo,
    ToolParam,
    ToolParams,
)
from docent.data_models.transcript import TEXT_RANGE_CITE_INSTRUCTION
from docent_core.docent.ai_tools.rubric.rubric import JudgeResult, Rubric
from docent_core.docent.db.schemas.tables import sanitize_pg_text

GPT_MODEL = "gpt-4"  # Can be adjusted based on the model being used


def truncate_to_token_limit(text: str, max_tokens: int, model: str = GPT_MODEL) -> str:
    """Truncate text to stay within the specified token limit."""
    encoding = tiktoken.encoding_for_model(model)
    tokens = encoding.encode(text)

    if len(tokens) <= max_tokens:
        return text

    return encoding.decode(tokens[:max_tokens])


AGENT_RUN_CHAT_SYSTEM_PROMPT_TEMPLATE = f"""
You are a chat assistant that analyzes a TRANSCRIPT of a conversation between a human USER and an AI agent. Answer any questions based on the transcript.

{{transcript}}

You will now talk to a different human, the ANALYST. The ANALYST is not the USER. They are not interested in achieving the USER's goals. They are solely interested in analyzing the TRANSCRIPT. All future messages are from the ANALYST.

You must adhere exactly to the following: {TEXT_RANGE_CITE_INSTRUCTION}

At the end of each response, provide 1-3 suggested followup messages that would help the user better understand the transcript. Format these suggestions using the following syntax:

<SUGGESTIONS>
- Why did the agent's code crash?
- Did the agent notice its mistake?
- What was the user's original request?
</SUGGESTIONS>

The suggestions should be specific and relevant to the transcript and conversation context. When writing suggestions, remember your primary job as an assistant is to provide detailed objective information from this individual transcript, as well as background knowledge, so that the ANALYST can draw their own conclusions. Focus suggestions on the TRANSCRIPT. Do not suggest messages about judgement calls or interpretation. Do not suggest questions you can't answer with the information you currently have.
""".strip()

JUDGE_RESULT_CHAT_SYSTEM_PROMPT_TEMPLATE = f"""
You are a chat assistant that analyzes a TRANSCRIPT of a conversation between a human USER and an AI agent. You are analyzing the following transcript:

<TRANSCRIPT>
{{transcript}}
</TRANSCRIPT>

You are currently discussing the TRANSCRIPT in light of the following RUBRIC:

<RUBRIC>
{{rubric}}
</RUBRIC>

We asked a JUDGE AI to evaluate the transcript based on the rubric and produce a result according to the JUDGE RESULT SCHEMA.

<JUDGE RESULT SCHEMA>
{{judge_result_schema}}
</JUDGE RESULT SCHEMA>

Here is the JUDGE RESULT produced by the JUDGE AI:

<JUDGE RESULT>
{{judge_result}}
</JUDGE RESULT>

Note that the JUDGE AI makes mistakes sometimes. You should not take JUDGE RESULT at face value.

All past human messages came from the USER. The USER is no longer interacting with the AI agent.

You will now talk to a different human, the ANALYST. The ANALYST is not the USER. They are not interested in achieving the USER's goals. They are solely interested in analyzing the TRANSCRIPT and how it relates to the RUBRIC and the JUDGE RESULT. All future messages are from the ANALYST.

If the ANALYST refers to a "result" or "judge result", they are referring specifically to the JUDGE RESULT above. If the analyst refers to a "rubric", they are referring specifically to the RUBRIC above.

You must adhere exactly to the following: {TEXT_RANGE_CITE_INSTRUCTION}

You do not need to cite the JUDGE RESULT.

Note: the ANALYST is skeptical. When you propose an argument, it is your job to make the argument easy to verify. Each step should be supported by one or more citations.

If the ANALYST asks you to argue for a particular conclusion, you should present the strongest argument for that conclusion if there is one, but you must NEVER make misleading or inaccurate arguments, even when "playing devil's advocate". After you have finished making an argument, always step back and evaluate it from a critical and neutral perspective.

Formatting guidelines: You may use inline syntax **bold**, *italic*, and `code`. You may not use code blocks or headers.

At the end of each response, provide 1-3 suggested followup questions that would help the analyst better understand the relationship between the transcript, rubric, and judge result. Format these suggestions using the following syntax:

<SUGGESTIONS>
- What's the best argument against the claim you just made?
- Does the transcript contain other instances of similar behavior?
- What part of the transcript provides the most clear-cut evidence for the judge result?
- Did the user ask for this behavior at any point?
- Was the agent correct when it said "[...]"?
</SUGGESTIONS>

The suggestions should be concise, specific, and relevant to the analysis context. When writing suggestions, remember your primary job as an assistant is to provide detailed objective information from this individual transcript, as well as background knowledge, so that the ANALYST can draw their own conclusions. The ANALYST is familiar with the RUBRIC but not the TRANSCRIPT. Focus suggestions on the TRANSCRIPT. Do not suggest messages about judgement calls or interpretation. Do not suggest questions you can't answer with the information you currently have.

**Using the add_label tool**

Add a label when:
- The user implies an opinion, starts to agree/disagree, or engages deeply with your analysis.
- The user explicitly requests a label or reaches a conclusion with you.
Do not add labels in your first response unless the user explicitly asks, that is too early.

Do not include transcript citations inside label payloads.

Writing a label overrides the existing one for that field, or creates it if missing.

Label text should defend the USER and ANALYST's positions in the context of the original result.
""".strip()


def make_system_prompt(
    agent_run: AgentRun, judge_result: JudgeResult | None, rubric: Rubric | None
) -> str:
    truncated_transcript = sanitize_pg_text(agent_run.to_text_new(indent=2))
    if judge_result is not None and rubric is not None:
        return JUDGE_RESULT_CHAT_SYSTEM_PROMPT_TEMPLATE.format(
            transcript=truncated_transcript,
            judge_result_schema=json.dumps(rubric.output_schema, indent=2),
            judge_result=json.dumps(judge_result.output, indent=2),
            rubric=rubric.rubric_text,
        )
    else:
        return AGENT_RUN_CHAT_SYSTEM_PROMPT_TEMPLATE.format(transcript=truncated_transcript)


def create_add_label_tool(judge_output_schema: dict[str, Any]) -> ToolInfo:
    return ToolInfo(
        name="add_label",
        description="Add labels to a judge result.",
        parameters=ToolParams(
            type="object",
            properties={
                "label": ToolParam(
                    name="label",
                    description=(
                        "A JSON object with the same fields as the judge result schema. Only include fields that are relevant to the label."
                    ),
                    input_schema=judge_output_schema,
                ),
            },
            required=["label"],
        ),
    )


def execute_add_label(rubric: Rubric, tool_call: ToolCall) -> ToolMessage:
    label = tool_call.arguments.get("label", None)

    if label is None:
        return ToolMessage(
            content="No label provided.",
            error={"message": "No label provided."},
            tool_call_id=tool_call.id,
            function=tool_call.function,
        )

    try:
        jsonschema.validate(label, rubric.output_schema)
    except jsonschema.ValidationError as e:
        return ToolMessage(
            content=f"Invalid label: {e}",
            error={"message": f"Invalid label: {e}"},
            tool_call_id=tool_call.id,
            function=tool_call.function,
        )

    return ToolMessage(
        content=json.dumps(label, indent=2),
        tool_call_id=tool_call.id,
        function=tool_call.function,
    )
