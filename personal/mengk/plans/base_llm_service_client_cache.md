# Goal
- Reuse provider clients inside `docent/_llm_util/llm_svc.BaseLLMService` so repeated completion calls avoid recreating SDK clients for the same provider/api-key tuple.

# Background
- `BaseLLMService.get_completions` currently calls `PROVIDERS[provider]["async_client_getter"]` on every invocation, which can incur connection warm-up, socket allocation, and rate-limit penalty for heavy usage.
- Providers accept an optional override key; different overrides must not reuse the same client, but default keypaths should share a single instance per provider.
- Clients from OpenAI, Anthropic, Google, etc. are async-friendly and expose `.aclose()` (or `.close()`) for cleanup; we should retain the ability to shut them down when the service is disposed.

# Implementation Plan
- **Survey client lifecycle requirements**
  - Confirm each provider module exposes async client classes that can be safely reused concurrently.
  - Note any provider-specific close/cleanup method so we can call it when tearing down the service.
- **Extend `BaseLLMService` state**
  - Add a private cache like `self._client_cache: dict[tuple[str, str | None], Any]` plus a lightweight async lock (`anyio.Lock`) to guard multi-task access.
  - Optionally store metadata about whether a client provides `aclose` vs `close` to simplify teardown.
- **Introduce a `_get_cached_client` helper**
  - Accept `provider` and `override_key`, build the cache key, and return an existing client when present.
  - On cache miss, create the client via the provider registry, store it, and return it.
  - Ensure the helper runs under the lock to prevent duplicate instantiation during concurrent calls.
- **Wire cache usage into `get_completions`**
  - Replace the direct `async_client_getter` invocation with a call to `_get_cached_client`.
  - Keep other flow (model rotation, semaphore usage, caching results) untouched.
- **Add optional shutdown hook**
  - Provide `async def aclose(self)` (and maybe sync `close`) that iterates cached clients and calls `aclose`/`close` when available, then clears the cache.
  - Update callers (if any) that manage service lifecycles to invoke the cleanup hook; otherwise document it.
- **Cover with tests**
  - Add a unit test that calls `get_completions` twice with the same provider and asserts the provider `async_client_getter` mock is invoked only once.
  - Add a concurrency-focused test (using `anyio`) to ensure parallel invocations still share the cached client.
- **Documentation/notes**
  - Update developer docs or inline comments explaining the cache key rules and the need to call `aclose` when disposing the service.
