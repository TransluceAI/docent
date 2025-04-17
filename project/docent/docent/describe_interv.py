from frames.transcript import format_chat_message
from llm_util.prod_llms import get_llm_completions_async
from llm_util.types import ChatMessage, LLMApiKeys


async def describe_insertion_intervention(
    new_message: ChatMessage,
    previous_messages: list[ChatMessage],
    api_keys: LLMApiKeys | None = None,
):
    prompt = f"""
A user has inserted a new message into an AI agent trace. Please summarize the user's intervention into a phrase of few words.

Messages loading up to intervention:
{"\n".join([format_chat_message(None, None, m) for m in previous_messages])}

Intervention:
{format_chat_message(None, None, new_message)}

Return the description on the first line, and nothing else.
    """.strip()

    output = await get_llm_completions_async(
        messages_list=[
            [{"role": "user", "content": prompt}],
        ],
        model_category="smart",
        llm_api_keys=api_keys,
    )
    return output[0].first_text


async def describe_replacement_intervention(
    old_message: ChatMessage,
    new_message: ChatMessage,
    previous_messages: list[ChatMessage],
    api_keys: LLMApiKeys | None = None,
):
    prompt = f"""
A user has replaced an existing message in an AI agent trace. Please summarize the user's intervention into a phrase of few words.

Messages loading up to intervention:
{"\n".join([format_chat_message(None, None, m) for m in previous_messages])}

Old message:
{format_chat_message(None, None, old_message)}

New message:
{format_chat_message(None, None, new_message)}

Return the description on the first line, and nothing else.
    """.strip()

    output = await get_llm_completions_async(
        messages_list=[
            [{"role": "user", "content": prompt}],
        ],
        model_category="smart",
        llm_api_keys=api_keys,
    )
    return output[0].first_text
