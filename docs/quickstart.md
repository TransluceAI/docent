# Quickstart

This guide helps you ingest agent runs into Docent.
<!-- Feel free to explore some sample agent runs in the dashboard. -->

Before starting, navigate to [docent.transluce.org](https://docent.transluce.org){target=_blank} and sign up for an account.

### Ingesting transcripts


Docent provides three main ways to ingest transcripts:

1. Tracing: Automatically capture LLM interactions in real-time using Docent's tracing SDK
2. Drag-and-drop Inspect `.eval` files: Upload existing logs through the web UI
3. SDK Ingestion: Programmatically ingest transcripts using the Python SDK

#### Option 1: Tracing (Recommended)

Docent's tracing system automatically captures LLM interactions, organizes them into agent runs.

Tracing allows you to:

- Automatically instrument LLM provider calls (OpenAI, Anthropic)
- Organize code into logical agent runs with metadata and scores
- Track chat conversations and tool calls
- Attach metadata to your runs and transcripts
- Resume agent runs across different parts of your codebase

```python
from docent.trace import initialize_tracing

# Basic initialization
initialize_tracing("my-collection-name")

# Your existing LLM code will now be automatically traced
response = client.chat.completions.create(
    model="gpt-5",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

For detailed tracing documentation, see [Tracing Introduction](tracing/introduction.md).

#### Option 2: Upload Inspect Evaluations

You can upload Inspect AI evaluation files directly through the Docent web interface:

1. Create a collection on the Docent website
2. Click "Add Data"
3. Select "Upload Inspect Log"
4. Upload your Inspect evaluation file

This is the quickest way to get started if you already have Inspect evaluation logs.

#### Option 3: SDK Ingestion

For programmatic ingestion or custom data formats, use the Python SDK:
```bash
pip install docent-python
```

First go to the [API keys page](https://docent.transluce.org/settings/api-keys){target=_blank}, create a key, and instantiate a client object with that key:

```python
import os
from docent import Docent

client = Docent(
    api_key=os.getenv("DOCENT_API_KEY"),  # is default and can be omitted

    # Uncomment and adjust these if you're self-hosting
    # server_url="http://localhost:8889",
    # web_url="http://localhost:3001",
)
```

Let's create a fresh collection of agent runs:

```python
collection_id = client.create_collection(
    name="sample collection",
    description="example that comes with the Docent repo",
)
```

Now we're ready to ingest some logs! There are three end-to-end examples below; pick whichever you're most interested in.

=== "Simple example"

    <!-- !!! note
        To directly run the code in this section, see [`examples/ingest_simple.ipynb`](https://github.com/TransluceAI/docent/blob/main/examples/ingest_simple.ipynb). -->

    Say we have three simple agent runs.

    ```python
    transcript_1 = [
        {
            "role": "user",
            "content": "What's the weather like in New York today?"
        },
        {
            "role": "assistant",
            "content": "The weather in New York today is mostly sunny with a high of 75°F (24°C)."
        }
    ]
    metadata_1 = {"model": "gpt-3.5-turbo", "agent_scaffold": "foo", "hallucinated": True}
    transcript_2 = [
        {
            "role": "user",
            "content": "What's the weather like in San Francisco today?"
        },
        {
            "role": "assistant",
            "content": "The weather in San Francisco today is mostly cloudy with a high of 65°F (18°C)."
        }
    ]
    metadata_2 = {"model": "gpt-3.5-turbo", "agent_scaffold": "foo", "hallucinated": True}
    transcript_3 = [
        {
            "role": "user",
            "content": "What's the weather like in Paris today?"
        },
        {
            "role": "assistant",
            "content": "I'm sorry, I don't know because I don't have access to weather tools."
        }
    ]
    metadata_3 = {"model": "gpt-3.5-turbo", "agent_scaffold": "bar", "hallucinated": False}

    transcripts = [transcript_1, transcript_2, transcript_3]
    metadata = [metadata_1, metadata_2, metadata_3]
    ```

    We need to convert each input into an [`AgentRun`](concepts/data_models/agent_run.md) object, which holds [`Transcript`][docent.data_models.transcript.Transcript] objects where each message needs to be a [`ChatMessage`](concepts/data_models/chat_messages.md). We could construct the messages manually, but it's easier to use the [`parse_chat_message`][docent.data_models.chat.message.parse_chat_message] function, since the raw dicts already conform to the expected schema.

    ```python
    from docent.data_models.chat import parse_chat_message
    from docent.data_models import Transcript

    parsed_transcripts = [
        Transcript(messages=[parse_chat_message(msg) for msg in transcript])
        for transcript in transcripts
    ]
    ```

    Now we can create the [`AgentRun`](concepts/data_models/agent_run.md) objects.

    ```python
    from docent.data_models import AgentRun

    agent_runs = [
        AgentRun(
            transcripts=[t],
            metadata={
                "model": m["model"],
                "agent_scaffold": m["agent_scaffold"],
                "scores": {"hallucinated": m["hallucinated"]},
            }
        )
        for t, m in zip(parsed_transcripts, metadata)
    ]
    ```

=== "$\tau$-Bench"

    <!-- !!! note
        To directly run the code in this section, see [`examples/ingest_tau_bench.ipynb`](https://github.com/TransluceAI/docent/blob/main/examples/ingest_tau_bench.ipynb). -->

    For a more complex case that involves tool calls, Docent ships with a sample $\tau$-bench log file, generated by running Sonnet 3.5 (new) on *one* task from the $\tau$-bench-airline dataset.

    To inspect the log, we can load it as a dictionary.

    ```python
    from docent.samples import get_tau_bench_airline_fpath
    import json
    with open(get_tau_bench_airline_fpath(), "r") as f:
        tb_log = json.load(f)
    print(tb_log)
    ```

    Next, we write a function that parses the dict into an [`AgentRun`](concepts/data_models/agent_run.md) object, complete with metadata. Most of the effort is in converting the raw tool calls into the expected format.

    ```python
    from docent.data_models import AgentRun, Transcript
    from docent.data_models.chat import ChatMessage, ToolCall, parse_chat_message

    def load_tau_bench_log(data: dict[str, Any]) -> AgentRun:
        traj, info, reward, task_id = data["traj"], data["info"], data["reward"], data["task_id"]

        messages: list[ChatMessage] = []
        for msg in traj:
            # Extract raw message data
            role = msg.get("role")
            content = msg.get("content", "")
            raw_tool_calls = msg.get("tool_calls")
            tool_call_id = msg.get("tool_call_id")

            # Create a message data dictionary
            message_data = {
                "role": role,
                "content": content,
            }

            # For tool messages, include the tool name
            if role == "tool":
                message_data["name"] = msg.get("name")
                message_data["tool_call_id"] = tool_call_id

            # For assistant messages, include tool calls if present
            if role == "assistant" and raw_tool_calls:
                # Convert tool calls to the expected format
                parsed_tool_calls: list[ToolCall] = []
                for tc in raw_tool_calls:
                    tool_call = ToolCall(
                        id=tc.get("id"),
                        function=tc.get("function", {}).get("name"),
                        arguments=tc.get("function", {}).get("arguments", {}),
                        type="function",
                        parse_error=None,
                    )
                    parsed_tool_calls.append(tool_call)

                message_data["tool_calls"] = parsed_tool_calls

            # Parse the message into the appropriate type
            chat_message = parse_chat_message(message_data)
            messages.append(chat_message)

        # Extract metadata from the sample
        task_id = info["task"]["user_id"]
        scores = {"reward": round(reward, 3)}

        # Build metadata
        metadata = {
            "benchmark_id": task_id,
            "task_id": task_id,
            "model": "sonnet-35-new",
            "scores": scores,
            "additional_metadata": info,
            "scoring_metadata": info["reward_info"],
        }

        # Create the transcript and wrap in AgentRun
        transcript = Transcript(
            messages=messages,
            metadata=metadata,
        )
        agent_run = AgentRun(
            transcripts=[transcript],
            metadata=metadata,
        )

        return agent_run
    ```

    Let's just load the single run in, and print its string representation.

    ```python
    agent_runs = [load_tau_bench_log(tb_log)]
    print(agent_runs[0].text)
    ```

=== "Inspect AI logs"

    <!-- !!! note
        To directly run the code in this section, see [`examples/ingest_inspect.ipynb`](https://github.com/TransluceAI/docent/blob/main/examples/ingest_inspect.ipynb). -->

    You can upload Inspect files directly into Docent! After making a collection on the website, just click "Add Data" and then "Upload Inspect Log".

    Alternatively, you can also add Inspect logs via the SDK; keep reading for an example of how to do this.

    Our [`ChatMessage`](concepts/data_models/chat_messages.md) schema is compatible with Inspect AI's format (as of `inspect-ai==0.3.93`), which means you can directly use the [`parse_chat_message`][docent.data_models.chat.message.parse_chat_message] function to parse Inspect messages.

    Docent ships with a sample Inspect log file, generated by running GPT-4o on a subset of the Intercode CTF benchmark.

    First install [Inspect](https://inspect.aisi.org.uk/){target=_blank}:

    === "uv"
        ```bash
        uv add inspect-ai
        ```

    === "pip"
        ```bash
        pip install inspect-ai
        ```

    Inspect provides a library function to read the log; we can convert it to a dictionary for easier viewing.

    ```python
    from docent.samples import get_inspect_fpath
    from inspect_ai.log import read_eval_log
    from pydantic_core import to_jsonable_python

    ctf_log = read_eval_log(get_inspect_fpath())
    ctf_log_dict = to_jsonable_python(ctf_log)
    ```

    Now we can write a function that takes the Inspect log and converts it into an [`AgentRun`](concepts/data_models/agent_run.md) object.

    ```python
    from inspect_ai.log import EvalLog
    from docent.data_models import AgentRun, Transcript
    from docent.data_models.chat import parse_chat_message

    def load_inspect_log(log: EvalLog) -> list[AgentRun]:
        if log.samples is None:
            return []

        agent_runs: list[AgentRun] = []

        for s in log.samples:
            # Extract sample_id from the sample ID
            sample_id = s.id
            epoch_id = s.epoch

            # Gather scores
            scores: dict[str, int | float | bool] = {}

            # Evaluate correctness (for this CTF benchmark)
            if s.scores and "includes" in s.scores:
                scores["correct"] = s.scores["includes"].value == "C"

            # Set metadata
            metadata = {
                "task_id": log.eval.task,
                "sample_id": str(sample_id),
                "epoch_id": epoch_id,
                "model": log.eval.model,
                "scores": scores,
                "additional_metadata": s.metadata,
                "scoring_metadata": s.scores,
            }

            # Create transcript
            agent_runs.append(
                AgentRun(
                    transcripts=[
                        Transcript(
                            messages=[parse_chat_message(m.model_dump()) for m in s.messages]
                        )
                    ],
                    metadata=metadata,
                )
            )

        return agent_runs
    ```

    Let's check on our loaded run:

    ```python
    agent_runs = load_inspect_log(ctf_log)
    print(agent_runs[0].text)
    ```


We can finally ingest the agent run and watch the UI update:

```python
client.add_agent_runs(collection_id, agent_runs)
```

If you navigate to the frontend URL printed by `client.create_collection(...)`, you should see the run available for viewing.

### Tips and tricks

#### Including sufficient context

Docent can only catch issues that are evident from the context it has about your evaluation. For example:

- If you're looking to catch issues with solution labels, you should provide the exact label in the metadata, not just the agent's score.
- For software engineering tasks, if you want to know *why* agents failed, you should include information about what tests were run and their traceback/execution logs.
