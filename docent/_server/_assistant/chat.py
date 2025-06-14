import tiktoken

from docent.data_models.agent_run import AgentRun
from docent.data_models.transcript import SINGLE_RUN_CITE_INSTRUCTION

MAX_TOKENS = 50_000
GPT_MODEL = "gpt-4"  # Can be adjusted based on the model being used


def truncate_to_token_limit(text: str, max_tokens: int, model: str = GPT_MODEL) -> str:
    """Truncate text to stay within the specified token limit."""
    encoding = tiktoken.encoding_for_model(model)
    tokens = encoding.encode(text)

    if len(tokens) <= max_tokens:
        return text

    return encoding.decode(tokens[:max_tokens])


SINGLE_TEMPLATE = f"""
You are a chat assistant that analyzes a transcript of a conversation between a human and an AI agent. Answer any questions based on the transcript.

{{transcript}}

You must adhere exactly to the following: {SINGLE_RUN_CITE_INSTRUCTION}
""".strip()


def make_single_tasst_system_prompt(agent_run: AgentRun) -> str:
    truncated_transcript = truncate_to_token_limit(agent_run.text, MAX_TOKENS)
    return SINGLE_TEMPLATE.format(transcript=truncated_transcript)
