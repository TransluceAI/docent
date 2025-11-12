# %%

import IPython

IPython.get_ipython().run_line_magic("load_ext", "autoreload")
IPython.get_ipython().run_line_magic("autoreload", "2")

# %%

from docent._llm_util.llm_svc import BaseLLMService
from docent._llm_util.providers.preference_types import ModelOption

llm_svc = BaseLLMService()

# %%

await llm_svc.get_completions(
    inputs=[
        [
            {"role": "user", "content": "Hello, what's 1 + 1?"},
        ]
    ],
    model_options=[ModelOption(provider="openai", model_name="gpt-4o-mini")],
)

# %%

from docent.trace import (
    agent_run_context,
    initialize_tracing,
    transcript_group,
    transcript_group_context,
    transcript_group_metadata,
)

DOCENT_API_KEY = "dk_OAsemTbrmXIonGIk_76PQIMTadPq3iA80txM9j1ZNYXk410MZsMZMnOvUQs2ZGM"
DOCENT_ENDPOINT = "https://api.docent-bridgewater.transluce.org/rest/telemetry"
DOCENT_COLLECTION_ID = "d12f04f8-507e-4799-a9e0-fa819d8b3545"
initialize_tracing(
    api_key=DOCENT_API_KEY, endpoint=DOCENT_ENDPOINT, collection_id=DOCENT_COLLECTION_ID
)
# set_disabled(True)

# %%

import random

from tqdm.auto import tqdm

# from contextlib import nullcontext


async def inner():
    i = random.randint(0, 100)
    with transcript_group_context(name=f"inner_{i}"):
        # with nullcontext():
        transcript_group_metadata(metadata={"foo": "bar"})
        output = await llm_svc.get_completions(
            inputs=[
                [
                    {"role": "user", "content": f"Hello, what's {i} + {i}?"},
                ]
            ],
            model_options=[ModelOption(provider="openai", model_name="gpt-4o-mini")],
            use_cache=False,
        )
        print(output)
        transcript_group_metadata(metadata={"bar": "baz"})


@transcript_group()
async def outer():
    for _ in tqdm(range(3)):
        await inner()

    for _ in tqdm(range(3)):
        await inner()


async def run_my_agent():
    with agent_run_context(metadata={"user": "John", "yoo": "bruh"}):
        await outer()


await run_my_agent()
# %%
