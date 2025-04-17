# LLM Module

This module provides a unified interface for interacting with various Language Model (LLM) providers. The main entry point is the asynchronous function `get_llm_completions_async`, which supports functionalities such as caching and custom tool integration.

## Overview

- **Unified API:** Call `get_llm_completions_async` with your list of messages and required parameters. The function handles provider-specific details and provides a consistent interface.

- **Provider Agnostic:** To add a provider, create a new file that implements a single asynchronous request using the `SingleOutputGetter` protocol. Providers like OpenAI and Anthropic are implemented as separate files in this directory.

- **Consistent Types:** All message formats, tool definitions, and output structures adhere to the types specified in [types.py](./types.py).

## Usage

Call the asynchronous function `get_llm_completions_async`, which accepts:

- A list of message lists, where each message is either a dict or a `ChatMessage`.
- Model parameters (e.g., `model_category`, `max_new_tokens`, `temperature`, etc.).
- Optional tool integrations via the `tools` parameter and a `tool_choice` option (e.g., "auto").

### Example

#### Basic Usage

```python
import random
from llm_apis.prod_llms import get_llm_completions_async

async def example_basic_usage():
    messages = [
        [{"role": "user", "content": f"Hello, how are you? (seed {random.random()})"}]
    ]
    result = await get_llm_completions_async(
        messages,
        model_category="fast",
        max_concurrency=100,
        use_cache=True,
    )
    print(result)
```

#### Custom Tool Integration

```python
import random
from llm_apis.prod_llms import get_llm_completions_async
from llm_apis.types import ToolDef, tools_info


def add_fn(a: int, b: int) -> int:
    return a + b

add_tool = ToolDef(
    tool=add_fn,
    name="add",
    description="Add two numbers together",
    parameters={
        "a": "The first number to add",
        "b": "The second number to add",
    },
)

async def example_tool_integration():
    messages = [
        [{"role": "user", "content": f"what is 2+2? (seed {random.random()})"}]
    ]
    result = await get_llm_completions_async(
        messages,
        model_category="smart",
        default_provider="anthropic",
        max_concurrency=100,
        use_cache=True,
        tools=[tools_info(add_tool)],
        tool_choice="auto",
    )
    print(result)
```

#### Streaming Support

The module supports streaming responses from LLM providers, allowing you to process partial completions as they arrive. To use streaming, provide a `streaming_callback` function:

```python
from llm_apis.types import LLMOutput, AsyncStreamingCallback

async def handle_stream(batch_index: int, llm_output: LLMOutput):
    # Process each chunk of the response as it arrives
    # batch_index indicates which message batch this chunk belongs to
    if llm_output.first and llm_output.first.text:
        print(f"Batch {batch_index}: {partial_output.first.text}", end="", flush=True)

async def example_streaming():
    # Multiple message batches can be processed concurrently
    messages = [
        [{"role": "user", "content": "Write a story about space"}],
        [{"role": "user", "content": "Write a story about the ocean"}]
    ]
    result = await get_llm_completions_async(
        messages,
        model_category="smart",
        streaming_callback=handle_stream,  # Must implement AsyncStreamingCallback protocol
    )
    print("\nAll responses received!")
```

## Extending the Module

To add a new LLM provider:

1. Create a new Python file in this directory (e.g., `my_provider.py`).
2. Implement the provider's API call as an asynchronous function conforming to the `SingleOutputGetter` protocol.
3. Add the provider to the `providers` dictionary in `prod_llms.py`:

```python
self.providers = {
    # ... existing providers ...
    "my_provider": {
        "keys": [ENV.MY_PROVIDER_API_KEY],
        "current_key_index": 0,
        "async_client": my_provider.get_my_provider_client_async(),
        "single_output_getter": get_my_provider_chat_completion_async,
        "models": {
            "smart": "my-provider-smart-model",
            "fast": "my-provider-fast-model",
        },
    },
}
```

4. The new provider becomes available via the `default_provider` parameter in `get_llm_completions_async`.
