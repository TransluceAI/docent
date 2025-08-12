# LLM providers and calls

Docent uses a unified interface to call and aggregate results from different LLM providers.

### Provider registry

Each LLM provider is specified through a [`ProviderConfig`][docent_core._llm_util.providers.registry.ProviderConfig] object, which requires three functions:

- `async_client_getter`: Returns an async client for the provider
- `single_output_getter`: Gets a single completion from the provider, compatible with the [`AsyncSingleOutputGetter`][docent_core._llm_util.providers.registry.SingleOutputGetter] protocol
- `single_streaming_output_getter`: Gets a streaming completion from the provider, compatible with the [`AsyncSingleStreamingOutputGetter`][docent_core._llm_util.providers.registry.SingleStreamingOutputGetter] protocol

We currently support `anthropic`, `openai`, and `azure_openai`.

#### Adding a new provider

1. Create a new module in `docent_core/_llm_util/providers/` (e.g., `my_provider.py`)
2. Implement the functions required by `ProviderConfig`
3. Add the provider to the [`PROVIDERS`][docent_core._llm_util.providers.registry.PROVIDERS] dictionary in `registry.py`

### Selecting models for Docent functions

Docent uses a preference system to determine which LLM models to use for different functions. [`ProviderPreferences`][docent_core._llm_util.providers.preferences.ProviderPreferences] manages the mapping between Docent functions and their ordered preference of [`ModelOption`][docent_core._llm_util.providers.preferences.ModelOption] objects:

```python
@cached_property
def function_name(self) -> list[ModelOption]:
    """Get model options for the function_name function.

    Returns:
        List of configured model options for this function.
    """
    return [
        ModelOption(
            provider="anthropic",
            model_name="claude-sonnet-4-20250514",
            reasoning_effort="medium"  # only for reasoning models
        ),
        ModelOption(
            provider="openai",
            model_name="o1",
            reasoning_effort="medium"
        ),
    ]
```

Any function that calls an LLM API must have a corresponding function in `ProviderPreferences` that returns its `ModelOption` preferences. `LLMManager` will try to use the first `ModelOption`, then fall back to following ones upon failure.

#### Usage

To customize which models are used for a specific function:

1. Locate `docent_core/_llm_util/providers/preferences.py`
2. Find or modify the cached property for the function you want to customize
3. Specify the [`ModelOption`][docent_core._llm_util.providers.preferences.ModelOption] objects in the returned list



::: docent_core._llm_util.providers.registry
::: docent_core._llm_util.providers.preferences
