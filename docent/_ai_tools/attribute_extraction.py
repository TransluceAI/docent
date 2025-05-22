import re
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from docent._llm_util.data_models.llm_output import LLMOutput
from docent._llm_util.prod_llms import get_llm_completions_async
from docent._llm_util.providers.preferences import PROVIDER_PREFERENCES
from docent.data_models.agent_run import AgentRun
from docent.data_models.citation import Citation, parse_citations_single_transcript
from docent.data_models.transcript import SINGLE_BLOCK_CITE_INSTRUCTION

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


class Attribute(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_run_id: str
    attribute: str
    attribute_idx: int | None = None
    value: str | None = None


class AttributeWithCitations(Attribute):
    citations: list[Citation] | None

    @classmethod
    def from_attribute(cls, attribute: Attribute) -> "AttributeWithCitations":
        return cls(
            **attribute.model_dump(),
            citations=(
                parse_citations_single_transcript(attribute.value)
                if attribute.value is not None
                else None
            ),
        )


class AttributeStreamingCallback(Protocol):
    """Supports batched streaming for cases where many attributes are pre-computed.
    This avoids invoking the callback separately for each datapoint.
    """

    async def __call__(
        self,
        attributes: list[Attribute],
    ) -> None: ...


def _get_llm_streaming_callback(
    attribute: str,
    datapoint_ids: list[str],
    attribute_streaming_callback: AttributeStreamingCallback,
):
    async def _streaming_callback(batch_index: int, llm_output: LLMOutput):
        attributes = _parse_llm_output(llm_output)

        # Return nothing if the LLM call failed (hence None)
        if attributes is None:
            await attribute_streaming_callback(list[Attribute]())
        else:
            await attribute_streaming_callback(
                [
                    Attribute(
                        agent_run_id=datapoint_ids[batch_index],
                        attribute=attribute,
                        attribute_idx=i,
                        value=value,
                    )
                    # If there were no matches, return a single None attribute
                    # Otherwise, return all attributes
                    for i, value in enumerate(attributes if len(attributes) > 0 else [None])
                ]
            )

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
    agent_runs: list[AgentRun],
    attribute: str,
    attribute_callback: AttributeStreamingCallback | None = None,
):
    """
    Processes items sequentially and calls streaming_callback with the
    current cumulative results using the batch_index.
    """
    ids = [ar.id for ar in agent_runs]
    texts = [ar.text for ar in agent_runs]

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
        PROVIDER_PREFERENCES.extract_attributes,
        max_new_tokens=4096,
        timeout=180.0,
        use_cache=True,
        completion_callback=llm_callback,
    )

    ans: list[list[str] | None] = []
    for output in outputs:
        ans.append(_parse_llm_output(output))

    return ans
