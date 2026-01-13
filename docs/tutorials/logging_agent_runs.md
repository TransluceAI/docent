# Logging Agent Runs

For non-blocking uploads of `AgentRun` objects, create an `AgentRunWriter` object with `docent.init()`. It will automatically create a new collection to write to, or you can pass an existing `collection_id`.

```python
import os
import docent

writer = docent.init(
    collection_name="elicitation-run",
    collection_id="optional-existing-collection-id",
    api_key=os.getenv("DOCENT_API_KEY"),  # is default and can be omitted
    # Uncomment and adjust these if you're self-hosting
    # server_url="http://localhost:8889",
    # web_url="http://localhost:3001",
)
```

Then pass a list of `AgentRun` objects to `writer.log_agent_runs()`.

```python
agent_runs: list[AgentRun] = ...
writer.log_agent_runs(agent_runs)
```

By default, the background queue has a max size of 20,000 runs. `log_agent_runs` will block the calling thread when the queue is full, but you can pass `queue_maxsize <= 0` to make the queue size infinite.

To override defaults, manually create an `AgentRunWriter` instance:
```python
from docent.agent_run_writer import AgentRunWriter

writer = AgentRunWriter(
    ...
    # Maximum async workers processing runs from the queue
    num_workers: int = 2,
    # Maximum number of runs in the queue
    queue_maxsize: int = 20_000
    # How often (in seconds) to flush accumulated batches
    flush_interval: float = 1.0
    # Maximum number of agent runs per request to backend
    batch_size: int = 1_000
    # Timeout (in seconds) to wait for shutdown
    shutdown_timeout: int = 60
)
```

Finally, call `.finish()`
```python
writer.finish(force=False)
```

The `AgentRunWriter` thread will persist up to `shutdown_timeout` seconds to finish uploading queued runs, after which it will cancel pending requests and close the thread. Call `.finish(force=True)` to close the thread immediately.
