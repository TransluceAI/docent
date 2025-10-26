# Labeling Agent Runs

Labels let you annotate agent runs with structured data. Use labels to measure judge performance or keep track of interesting agent runs.

## Creating a Label Set

Label sets are collections of labels with the same [schema](https://json-schema.org/). You will need to create a label set in order to upload labels to Docent.

<!-- ### Via Python SDK -->

```python
import os
from docent import Docent

client = Docent(
    api_key=os.getenv("DOCENT_API_KEY"),
)

# Define your label schema using JSON Schema
label_schema = {
  "type": "object",
  "properties": {
    "label": {
      "enum": [
        "match",
        "no match"
      ],
      "type": "string"
    },
    "explanation": {
      "type": "string",
      # Custom field for citations in the UI
      "citations": true
    }
  }
}

# Create the label set
label_set_id = client.create_label_set(
    collection_id="your-collection-id",
    name="Auditor Labels",
    label_schema=label_schema,
    description="Labels from human auditors."
)

print(f"Created label set: {label_set_id}")
```

<!-- ### Via UI

Navigate to your collection and click the "Label Sets" button.

_[IMAGE: Screenshot of label sets button]_

Click "Create New" and fill in the form:

_[IMAGE: Screenshot of label set creation dialog]_

Use the visual schema editor or write JSON directly. -->

## Adding Labels to Agent Runs

<!-- ### Via Python SDK -->

Once you've created a label set, you can upload labels into Docent.

```python
from docent.data_models.judge import Label

# Create a label for a specific agent run
label = Label(
    label_set_id=label_set_id,
    agent_run_id="your-agent-run-id",
    label_value={
        "label": "match",
        "explanation": "The agent..."
    }
)

client.add_label(collection_id="your-collection-id", label=label)
```

For bulk uploads:

```python
labels = [
    Label(
        label_set_id=label_set_id,
        agent_run_id="run-1",
        label_value={...}
    ),
    Label(
        label_set_id=label_set_id,
        agent_run_id="run-2",
        label_value={...}
    ),
]

client.add_labels(collection_id="your-collection-id", labels=labels)
```

<!-- ### Via UI

Navigate to an agent run and click the "Labels" tab.

_[IMAGE: Screenshot of agent run page with labels tab highlighted]_

Click "Add Label" and select a label set:

_[IMAGE: Screenshot of label set selection dialog]_

Fill in the form fields defined by your schema:

_[IMAGE: Screenshot of label editing form]_ -->
