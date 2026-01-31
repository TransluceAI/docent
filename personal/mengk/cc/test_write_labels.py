#%%
# IPython autoreload setup
try:
    from IPython import get_ipython
    ipython = get_ipython()
    if ipython is not None:
        ipython.run_line_magic("load_ext", "autoreload")
        ipython.run_line_magic("autoreload", "2")
except Exception:
    pass  # Not in IPython environment

#%%
# Setup client and constants
from docent.sdk import Docent
from docent.data_models.judge import Label

client = Docent(server_url="http://localhost:8903")
COLLECTION_ID = "da2d9ea5-9bf3-4347-9401-8bdae71de2d9"

#%%
# Create label set with various field types: number, bool, enum, string
label_schema = {
    "type": "object",
    "required": ["score", "is_valid", "category", "notes"],
    "properties": {
        "score": {
            "type": "number",
            "minimum": 0,
            "maximum": 10,
            "description": "Numeric score from 0 to 10",
        },
        "is_valid": {
            "type": "boolean",
            "description": "Whether the response is valid",
        },
        "category": {
            "type": "string",
            "enum": ["excellent", "good", "fair", "poor"],
            "description": "Quality category",
        },
        "notes": {
            "type": "string",
            "description": "Free-form notes about the evaluation",
        },
    },
}

label_set_id = client.create_label_set(
    collection_id=COLLECTION_ID,
    name="Multi-Type Label Set",
    label_schema=label_schema,
    description="A label set with number, boolean, enum, and string fields",
)
print(f"Created label set: {label_set_id}")

#%%
# Get some agent run IDs from the collection to label
agent_run_ids = client.list_agent_run_ids(COLLECTION_ID)
print(f"Found {len(agent_run_ids)} agent runs in collection")

# Use up to 5 agent runs for testing
agent_run_ids_to_label = agent_run_ids[:5]
print(f"Will label {len(agent_run_ids_to_label)} agent runs")

#%%
# Create some arbitrary labels with dummy values for each field type
import random

categories = ["excellent", "good", "fair", "poor"]
notes_templates = [
    "This response demonstrates clear understanding of the task.",
    "The output needs some improvement in clarity.",
    "Good effort but missing key details.",
    "Excellent work with comprehensive coverage.",
    "Fair attempt, requires additional context.",
]

labels: list[Label] = []
for agent_run_id in agent_run_ids_to_label:
    score = round(random.uniform(0, 10), 2)  # Random float between 0-10
    is_valid = random.choice([True, False])  # Random boolean
    category = random.choice(categories)  # Random enum value
    notes = random.choice(notes_templates)  # Random string

    label = Label(
        label_set_id=label_set_id,
        agent_run_id=agent_run_id,
        label_value={
            "score": score,
            "is_valid": is_valid,
            "category": category,
            "notes": notes,
        },
    )
    labels.append(label)

print(f"Created {len(labels)} labels")
for label in labels:
    print(f"  - Agent run {label.agent_run_id}:")
    print(f"      score: {label.label_value['score']}")
    print(f"      is_valid: {label.label_value['is_valid']}")
    print(f"      category: {label.label_value['category']}")
    print(f"      notes: {label.label_value['notes'][:50]}...")

#%%
# Write labels to the label set
result = client.add_labels(COLLECTION_ID, labels)
print(f"Added labels: {result}")

#%%
# Verify labels were written by fetching them back
fetched_labels = client.get_labels(COLLECTION_ID, label_set_id)
print(f"Fetched {len(fetched_labels)} labels from label set")
for fetched in fetched_labels:
    print(f"  - {fetched}")

# %%
