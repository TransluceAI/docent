---
title: "Quickstart"
description: "Get started with Docent"
---

# Quickstart

This guide helps you ingest agent runs into Docent.

Before starting, navigate to [docent.transluce.org](https://docent.transluce.org) and sign up for an account.

## Ingesting transcripts

Docent provides three main ways to ingest transcripts:

1. **Tracing**: Automatically capture LLM interactions in real-time using Docent's tracing SDK
2. **Drag-and-drop Inspect `.eval` files**: Upload existing logs through the web UI
3. **SDK Ingestion**: Programmatically ingest transcripts using the Python SDK

### Option 1: Tracing (Recommended)

Docent's tracing system automatically captures LLM interactions and organizes them into agent runs.

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

### Option 2: Upload Inspect Evaluations

You can upload Inspect AI evaluation files directly through the Docent web interface:

1. Create a collection on the Docent website
2. Click "Add Data"
3. Select "Upload Inspect Log"
4. Upload your Inspect evaluation file

### Option 3: SDK Ingestion

For programmatic ingestion or custom data formats, use the Python SDK:

```bash
pip install docent-python
```

First go to the API keys page, create a key, and instantiate a client object:

```python
import os
from docent import Docent

client = Docent(
    api_key=os.getenv("DOCENT_API_KEY"),
)
```

Create a collection:

```python
collection_id = client.create_collection(
    name="sample collection",
    description="example that comes with the Docent repo",
)
```

Then ingest your agent runs:

```python
client.add_agent_runs(collection_id, agent_runs)
```

If you navigate to the frontend URL printed by `client.create_collection(...)`, you should see the run available for viewing.
