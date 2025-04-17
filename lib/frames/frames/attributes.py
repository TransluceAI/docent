import re
from typing import Protocol

from frames.transcript import SINGLE_BLOCK_CITE_INSTRUCTION
from frames.types import Datapoint
from llm_util.prod_llms import get_llm_completions_async
from llm_util.types import LLMApiKeys, LLMOutput

ATTRIBUTE_EXTRACTION_PROMPT = f"""
Your task is to check for instances of a search query in some text:
<text>
{{item}}
</text>
<query>
{{attribute}}
</query>

First think carefully about whether the text contains any instances of the query.

If not, return "N/A" only.

If so, for each instance of the attribute, describe how the text pertains to it. Be concise but detailed and specific. I should be able to maximally mentally reconstruct the item from your description. You should return all instances of the attribute in the following exact format:
<instance>
description
</instance>
...
<instance>
description
</instance>

{SINGLE_BLOCK_CITE_INSTRUCTION}
""".strip()


class AttributeStreamingCallback(Protocol):
    async def __call__(
        self,
        datapoint_id: str,
        attribute_id: str,
        attributes: list[str] | None,
    ) -> None: ...


def _get_llm_streaming_callback(
    attribute_id: str,
    datapoint_ids: list[str],
    attribute_streaming_callback: AttributeStreamingCallback,
):
    async def _streaming_callback(batch_index: int, llm_output: LLMOutput):
        attributes = _parse_llm_output(llm_output)
        await attribute_streaming_callback(datapoint_ids[batch_index], attribute_id, attributes)

    return _streaming_callback


def _parse_llm_output(output: LLMOutput) -> list[str] | None:
    if output.first_text is None:
        return None
    elif output.first_text.strip().upper() == "N/A":
        return []
    else:
        # Pattern matches text between <instance> and </instance> tags
        pattern = r"<instance>\n?(.*?)\n?</instance>"
        matches = re.finditer(pattern, output.first_text, re.DOTALL)
        return [str(match.group(1).strip()) for match in matches]


async def extract_attributes(
    datapoints: list[Datapoint],
    attribute: str,
    attribute_callback: AttributeStreamingCallback | None = None,
    llm_api_keys: LLMApiKeys | None = None,
):
    """
    Processes items sequentially and calls streaming_callback with the
    current cumulative results using the batch_index.
    """
    ids = [dp.id for dp in datapoints]
    texts = [dp.text for dp in datapoints]

    llm_callback = (
        _get_llm_streaming_callback(attribute, ids, attribute_callback)
        if attribute_callback is not None
        else None
    )

    prompts = [ATTRIBUTE_EXTRACTION_PROMPT.format(attribute=attribute, item=item) for item in texts]
    outputs = await get_llm_completions_async(
        [
            [
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
            for prompt in prompts
        ],
        model_category="reasoning_smart",
        reasoning_effort="medium",
        max_new_tokens=4096,
        timeout=180.0,
        default_provider="anthropic",
        use_cache=True,
        completion_callback=llm_callback,
        llm_api_keys=llm_api_keys,
    )

    ans: list[list[str] | None] = []
    for output in outputs:
        ans.append(_parse_llm_output(output))

    return ans
