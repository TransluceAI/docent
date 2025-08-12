# Docent Tracing

Docent provides a comprehensive tracing system that automatically captures LLM interactions, organizes them into "agent runs", and enables detailed analysis of your AI applications.

## Overview

The Docent tracing system allows you to:

- Automatically instrument LLM provider calls (OpenAI, Anthropic, Bedrock)
- Organize code into logical agent runs with metadata and scores
- Track chat conversations and tool calls
- Analyze performance and quality metrics
- Resume agent runs across different parts of your codebase

## Getting Started

### 1. Installation

Docent tracing is included with the main Docent SDK package:

```bash
pip install docent-python
```

### 2. API Key Setup

You'll need a Docent API key to send traces to the Docent backend. You can get one by:

1. Signing up or logging in at [Docent](https://docent.transluce.org)
2. On your dashboard, click on your account icon in the top right
3. Select "API Keys"
4. Generate an API key

Set your API key as an environment variable:

```bash
export DOCENT_API_KEY="your-api-key-here"
```

Or pass it directly to the initialization function.

### 3. Initialize Tracing

The primary entry point for setting up Docent tracing is `initialize_tracing()`:

```python
from docent.trace import initialize_tracing

# Basic initialization
initialize_tracing("my-application")

# With custom configuration
initialize_tracing(
    collection_name="my-application",
    endpoint="https://docent.transluce.org/rest/telemetry",  # Optional, uses default if not provided
    api_key="your-api-key",  # Optional, uses env var if not provided
)
```

**Parameters:**

- `collection_name`: Name for your application/collection
- `endpoint`: Optional OTLP endpoint URL (defaults to Docent's hosted service)
- `api_key`: Optional API key (uses `DOCENT_API_KEY` environment variable if not provided)
- `enable_console_export`: Whether to also export traces to console for debugging (default: False)


## Three Levels of Organization

Docent organizes your traces into three hierarchical levels:

### 1. Collection
A **collection** is the top-level organization unit. It represents a set of agent runs that you want to analyze together.

### 2. Agent Run
An **agent run** typically represents a single execution of your entire system. It could include:

- Multiple LLM calls
- Tool calls and responses
- Associated metadata and scores
- One or more chat sessions (transcripts)

### 3. Transcript
A **transcript** is essentially a chat session - a sequence of messages with an LLM. Transcripts are automatically created by detecting consistent chat messages from whithin LLM calls that are tagged to the same agent run.

## Creating Agent Runs

### Using the Decorator

The simplest way to create an agent run is using the `@agent_run` decorator:

```python
from docent.trace import agent_run

@agent_run
def analyze_document(document_text: str):
    # This entire function will be wrapped in an agent run
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": f"Analyze this document: {document_text}"}]
    )
    return response.choices[0].message.content
```

### Using Context Managers

For more control, use the context manager approach:

```python
from docent.trace import agent_run_context

def process_user_query(query: str):
    with agent_run_context():
        # Your agent code here
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": query}]
        )
        return response.choices[0].message.content
```

### Async Support

Both decorators and context managers work with async code:

```python
from docent.trace import agent_run_context

async def async_agent_function():
    async with agent_run_context():
        # Async agent code here
        response = await client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": "Hello"}]
        )
        return response.choices[0].message.content
```

## Attaching Scores to Agent Runs

You can attach scores to agent runs to track performance metrics and quality indicators. It will automatically be associated with the agent run that is currently in context.

```python
from docent.trace import agent_run_score

def evaluate_response(response: str, expected: str):
    # Calculate some score
    accuracy = calculate_accuracy(response, expected)

    # Attach the score to the current agent run
    agent_run_score("accuracy", accuracy)

    # You can attach multiple scores
    agent_run_score("response_length", len(response))
    agent_run_score("processing_time", 1.23)
    agent_run_score("user_satisfaction", 4.5)

    return accuracy

@agent_run
def run_system()
  # ...

  evaluate_response(response, expected)

```

## Attaching Metadata to Agent Runs

You can attach metadata to agent runs to provide context and enable filtering:

```python
from docent import agent_run_context, agent_run_metadata

# Using context manager with metadata
with agent_run_context(
    metadata={
        "user_id": "user_123",
        "session_id": "session_456",
        "temperature": 0.7
    }
):
    # Your agent code here
    pass

# Using decorator with metadata
@agent_run(metadata={"task_type": "document_analysis", "priority": "high"})
def analyze_document_with_metadata(document_text: str):
    # Function code here
    pass

# Adding metadata during execution
def process_with_dynamic_metadata():
    with agent_run_context() as (agent_run_id, transcript_id):
        # Do some work
        result = process_data()

        # Add metadata based on results
        agent_run_metadata({
            "processing": {
                "input_size": len(input_data),
                "output_size": len(result),
                "success": True
            }
        })

        return result
```

## Automatic Transcript Creation

Docent automatically creates transcripts by detecting consistent chat completions. When you make LLM calls within an agent run, they're automatically grouped into logical conversation threads.

## Advanced Agent Run Usage

### Resuming Agent Runs

You can resume agent runs across different parts of your codebase by passing the `agent_run_id`. This is useful for connecting related work that happens in different modules or at different times.

#### Using Context Managers

With context managers, you can explicitly pass and resume agent runs:

```python
from docent import agent_run_context

def run_agent(state):
    with agent_run_context() as (agent_run_id, _):
        # Agent logic here
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": user_input}]
        )

        # save the agent_run_id
        state.metadata["agent_run_id"] = agent_run_id

        return response.choices[0].message.content

def evaluate_agent(state):
    # Resume the same agent run by passing the agent_run_id
    with agent_run_context(agent_run_id=state.metadata.agent_run_id):
        # This continues the same agent run
        accuracy = calculate_accuracy(response, expected_answer)
        agent_run_score("evaluation_accuracy", accuracy)

        # Add evaluation metadata
        agent_run_metadata({
            "evaluation": {
                "method": "human_review",
                "reviewer": "expert_1",
                "timestamp": "2024-01-15T10:30:00Z"
            }
        })

        return accuracy


```

#### Using Decorators

With decorators, you can access the agent run ID from the function's attributes:

```python
from docent import agent_run

@agent_run
def run_agent(user_input: str):
    # Agent logic here
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": user_input}]
    )

    # The agent run ID is available as an attribute
    agent_run_id = run_agent.docent.agent_run_id

    # Pass to evaluation function
    evaluate_agent_response(agent_run_id, response.choices[0].message.content)

    return response.choices[0].message.content
```
