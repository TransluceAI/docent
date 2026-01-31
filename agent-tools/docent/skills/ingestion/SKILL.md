---
name: ingestion
description: Structured workflow for ingesting agent run data into Docent. Use when the user wants to upload evaluation logs or agent transcripts to Docent. Triggers on phrases like "ingest into Docent", "upload to Docent", "import runs to Docent", or when working with agent evaluation data that needs to be loaded into Docent for analysis.
---

# **Docent Ingestion Skill**

This skill provides a structured workflow for converting transcripts and evaluation logs into the correct format for ingestion to Docent, an agent analysis tool.

## **Overview of Docent**

Docent is a trace analysis tool that helps researchers analyze and debug agents. Researchers upload a “collection” of traces (“agent runs”) into Docent, where the tool enables them to:

* Engage in structured data analysis such as grouping and joining to understand trends and create charts
* Quickly view traces of interest and capture human annotations of traces through labeling and comments
* Run a semantic search over transcripts by running a user-provided query of each transcript in their collection, and the cluster the results to understand high-level patterns
* Draft, refine, and iterate with the user on detailed rubrics to capture fuzzy behaviors like sycophancy, cheating, verbosity, etc.

Docent accelerates researchers by helping them form hypotheses and directing them to read the most relevant transcripts. Researchers use Docent to qualitatively explain and understand shifts in quantitative metrics. Common use cases for Docent include:

* Comparing between two checkpoints to understand a regression or to understand a quantitative tradeoff in their benchmark results
* Understanding an unexpected result. For instance, investigating why a checkpoint that receives high reward from a preference model (e.g. for code quality) appears to perform poorly with real users (e.g. PRs frequently rejected for low quality)
* Surfacing previously unknown failure modes. For instance, noticing that the timeout constraint is not explicit in an evaluation, causing thinking models to perform poorly compared to their non-thinking counterparts

## **When to Offer This Workflow**

**Trigger conditions**:
The user mentions phrases like "ingest transcripts into Docent", "upload to Docent", "import runs to Docent,” “move data into Docent,” “upload traces to Docent”

### **Initial offer:**

Offer the user a structured workflow for ingesting their transcripts into Docent. Briefly explain the four stages:

1. **Context gathering**: User provides relevant context on their data, including the path to the data, how it was produced, and what kinds of analysis they would like to do
2. **Planning**: Understand how the user’s data is organized, plan an ingestion strategy, and recommend a suggested organization in Docent to the user. Surface the plan for user approval.
   1. Examine the overall data hierarchy by mapping the directory and file structure to understand if there are recurring patterns.
   2. For individual transcripts, identify all unique formats and create a template for ingesting each one. Map out a schema of each unique transcript format and map each field to the most appropriate class in Docent.
   3. Propose an organization structure in Docent (broken down into collections, agent runs, transcript groups, and transcripts) that fits the user’s analysis needs.
3. **Ingestion:** Given the suggested organization, plan how, write, and test a script that uploads all data from the user-provided directory to Docent.
4. **Testing**: After uploading to a collection in Docent, use the Docent SDK to pull down the collection data and verify that the metadata, transcript formats, and overall organization match expectations.

Explain that you will ingest all the data provided in a directory of the user’s choosing. Explain the ask for context on the user’s analysis: while explaining is optional, it helps structure the data in Docent. Ask if they want to try this workflow or proceed freeform.

If the user declines, work freeform. If the user accepts, proceed to Stage 1\.

## **Stage 1: Context Gathering**

### **Environment Setup**

Before running any Python commands, check for and activate a virtual environment:

```shell
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi
```

### **Gathering Information**

Collect the information needed to plan and execute the ingestion. Let the user know they can answer in shorthand or dump context—whichever works best for them. Aim to collect answers to the following:

- **API Key:** What is your Docent API key? (You can find or create one at: [https://docent.transluce.org/settings/api-keys](https://docent.transluce.org/settings/api-keys))
- **Data Path:** What is the path to the files or directory you want to ingest?
- **Collection Name:** What would you like to name this collection in Docent?
- **Data Context:** What kind of data is this? (e.g., benchmark evaluation, agent task runs, multi-agent debate, red-teaming attempts) How was this data produced? What does each file represent? (e.g., one task per file, one episode per file, multiple attempts per task)
- **Analysis Goals:** What kinds of analysis do you want to do in Docent? (e.g., compare two model checkpoints, find failure modes, understand a metric regression)

Store these values for use in subsequent stages. Create `ingestion-plan.md` in the working directory to log all decisions and findings throughout the workflow. Here is an example structure:

```
# Docent Ingestion Plan

## Configuration
- Data path: [from user]
- Collection name: [from user]

## File Analysis
[to be filled in Stage 2a]

## Schema
[to be filled in Stage 2b]

## Data Structure Proposal
[to be filled in Stage 2c]

## Field Mapping
[to be filled in Stage 2c]

## Omitted Data
[MUST document any data not ingested and why]

## Execution Log
[to be filled in Stage 3]

## Verification
[to be filled in Stage 4 - compare expected vs actual counts]
```

---

## **Stage 2: Planning**

### **Stage 2a: Understanding File Structure**

Build understanding of the data organization to understand holistically how the user is storing their data and why they chose to organize it that way. Consider how this reflects on how they want their data stored in Docent. You can quickly get a sense of the data by using the appropriate strategies below.

#### Build Structural Tree

You can generate a folder-only tree with the following script, to see the overall directory structure. You may want to strategically list individual files in a few folders to understand them as well.

```py
import os
from pathlib import Path
from collections import Counter

def build_folder_tree(path: str, max_depth: int = 5) -> dict:
    """Build a tree of folder structure, detecting patterns."""
    path = Path(path)

    def _recurse(p: Path, depth: int) -> dict:
        if depth > max_depth or not p.is_dir():
            return None

        children = {}
        file_extensions = Counter()

        for item in sorted(p.iterdir()):
            if item.is_dir():
                children[item.name] = _recurse(item, depth + 1)
            else:
                file_extensions[item.suffix.lower() or "no_ext"] += 1

        return {
            "children": children,
            "file_counts": dict(file_extensions),
            "total_files": sum(file_extensions.values()),
        }

    return _recurse(path, 0)
```

Understanding what individual files are in a few folders may also be useful. List files in key directories to understand the naming conventions and file types present.

#### Detect Naming Patterns

Examine folder and file names to understand the organizational logic. Sample a few names at different levels of the hierarchy and reason about what they might represent.

Common patterns to look for (as suggestions, not strict rules):

- **Dates:** ISO format (2024-01-15), compact (20240115), or human-readable (jan\_15)
- **Model identifiers:** Model names, versions, or checkpoints
- **Sequential numbering:** run\_001, sample\_42, task\_5, episode\_100
- **Experiment tags:** baseline, ablation, v2, control, treatment
- **Subdirectory conventions:** trajs/, logs/, results/, metadata/, configs/

Rather than pattern-matching, describe what you observe and hypothesize about the user's organizational intent. For example:

- "Folders appear to be organized by date, then by model name"
- "Each subfolder contains a `trajs/` directory with JSON files and a `config.yaml`"
- "File names include what looks like a task ID followed by an attempt number"

Ask the user to confirm your interpretation if uncertain.

#### Identify Repeatable Templates

Find the structural unit that repeats across the directory (e.g., each experiment folder has the same subdirectory structure):

```py
def find_repeatable_template(tree: dict) -> dict:
    """Find the pattern that repeats across the directory structure."""

    def get_structure_signature(node: dict) -> tuple:
        if node is None:
            return ()
        children = node.get("children", {})
        child_names = tuple(sorted(children.keys()))
        file_exts = tuple(sorted(node.get("file_counts", {}).keys()))
        return (child_names, file_exts)

    signatures = {}
    def collect_signatures(node: dict, path: str = ""):
        if node is None:
            return
        sig = get_structure_signature(node)
        if sig not in signatures:
            signatures[sig] = []
        signatures[sig].append(path)
        for name, child in node.get("children", {}).items():
            collect_signatures(child, f"{path}/{name}")

    collect_signatures(tree)

    repeated = [(sig, paths) for sig, paths in signatures.items()
                if len(paths) > 1 and sig[0]]

    if repeated:
        repeated.sort(key=lambda x: len(x[1]), reverse=True)
        return {
            "template_structure": repeated[0][0],
            "instance_count": len(repeated[0][1]),
            "example_paths": repeated[0][1][:3],
        }
    return {"template_structure": None, "note": "No repeating pattern found"}
```

#### Detect Inspect AI Files

Check for Inspect AI `.eval` files, which have a dedicated loader:

```py
def detect_inspect_files(path: Path) -> list[str]:
    """Detect Inspect .eval files that can use the built-in loader."""
    return [str(f) for f in path.rglob("*.eval")]
```

If Inspect `.eval` files are detected, use the built-in loader (see Stage 3).

#### Decision Point

Based on the structural analysis, determine next steps:

| Structure Pattern | Action |
| :---- | :---- |
| Clear repeating template with trajs/logs subdirs | Proceed to schema inference on representative samples |
| Flat directory with consistent file types | Sample files directly for schema |
| Mixed/unclear structure | Ask user for clarification |
| Inspect .eval files present | Use built-in Inspect loader |
| No recognizable data files | Ask user to confirm path |

Log the structural analysis to `ingestion-plan.md`.

---

### **Stage 2b: Schema Inference**

Sample files strategically based on the template structure identified in Stage 2a.

#### Strategic Sampling

```py
def sample_files_strategically(path: Path, template_info: dict) -> list[Path]:
    """Sample files from representative locations within the template structure."""
    samples = []

    if template_info.get("example_paths"):
        for instance_path in template_info["example_paths"][:2]:
            instance = path / instance_path.lstrip("/")
            for subdir in ["trajs", "trajectories", "logs", "results", ""]:
                candidate = instance / subdir if subdir else instance
                if candidate.exists():
                    json_files = list(candidate.glob("*.json"))[:1]
                    jsonl_files = list(candidate.glob("*.jsonl"))[:1]
                    samples.extend(json_files + jsonl_files)
                    if samples:
                        break

    if not samples:
        samples = list(path.rglob("*.json"))[:3] + list(path.rglob("*.jsonl"))[:2]

    return samples[:5]
```

#### Infer Schema

```py
def infer_json_schema(data: dict | list, max_depth: int = 5) -> dict:
    """Recursively infer schema from JSON data."""
    if max_depth == 0:
        return {"type": "any", "note": "truncated"}

    if isinstance(data, dict):
        return {
            "type": "object",
            "fields": {
                k: infer_json_schema(v, max_depth - 1)
                for k, v in data.items()
            }
        }
    elif isinstance(data, list):
        if not data:
            return {"type": "array", "items": "unknown"}
        item_schemas = [infer_json_schema(item, max_depth - 1) for item in data[:3]]
        return {"type": "array", "items": item_schemas[0], "sample_count": len(data)}
    else:
        return {"type": type(data).__name__, "example": repr(data)[:100]}
```

#### Classify Fields

Identify fields that indicate transcript content, scores, and metadata:

```py
TRANSCRIPT_INDICATORS = ["messages", "conversation", "transcript", "dialogue", "turns", "traj", "trajectory"]
SCORE_INDICATORS = ["score", "reward", "accuracy", "correct", "success", "metric", "result"]
ID_INDICATORS = ["id", "task_id", "sample_id", "episode", "run_id", "uuid"]

def classify_fields(schema: dict) -> dict:
    """Classify fields by their likely purpose."""
    classified = {"transcript": [], "scores": [], "identifiers": [], "metadata": []}

    def check_field(name: str, field_schema: dict, path: str = ""):
        full_path = f"{path}.{name}" if path else name
        name_lower = name.lower()

        if any(ind in name_lower for ind in TRANSCRIPT_INDICATORS):
            classified["transcript"].append(full_path)
        elif any(ind in name_lower for ind in SCORE_INDICATORS):
            classified["scores"].append(full_path)
        elif any(ind in name_lower for ind in ID_INDICATORS):
            classified["identifiers"].append(full_path)
        else:
            classified["metadata"].append(full_path)

        if field_schema.get("type") == "object":
            for sub_name, sub_schema in field_schema.get("fields", {}).items():
                check_field(sub_name, sub_schema, full_path)

    for name, field_schema in schema.get("fields", {}).items():
        check_field(name, field_schema)

    return classified
```

Log schema and field classification to `ingestion-plan.md`.

---

### **Stage 2c: Docent Organization Proposal**

Propose how to organize the data in Docent based on the user's analysis goals and data structure.

#### Docent Hierarchy Best Practices

**Critical:** Most Docent analysis features (rubrics, search, clustering) operate at the **AgentRun level**. Structure data accordingly:

| Level | Purpose | When to Use |
| :---- | :---- | :---- |
| **Collection** | One experiment, benchmark run, or dataset | Usually one per ingestion; multiple if fundamentally different experiments |
| **AgentRun** | Primary analysis unit | One per complete unit you want to analyze, compare, or score. Rubrics run here. Search returns these. |
| **TranscriptGroup** | Logical groupings within an AgentRun | Multiple attempts (pass@k), phases of a task |
| **Transcript** | One agent's conversation history | One per agent in multi-agent setups; otherwise usually one per AgentRun |

**Default:** If unsure, make each independent task/episode/sample its own AgentRun with a single Transcript.

**Tree/branching data:** Ingest each branch as its own Transcript in its own AgentRun. Use metadata fields to identify how branches relate to each other (e.g., `parent_branch_id`, `branch_depth`, `root_task_id`).

#### Data Pattern to Docent Mapping

| Data Pattern | Collection | AgentRun | TranscriptGroup | Transcript |
| :---- | :---- | :---- | :---- | :---- |
| Simple evals | experiment | sample\_id, scores | — | messages |
| Pass@k | experiment | task\_id, best\_score | attempt\_k | messages per attempt |
| Tree/branching | experiment | one per branch, with metadata linking branches | — | messages for that branch |
| Multi-agent | experiment | episode\_id, joint\_scores | — | one per agent |

#### Field Mapping

Map each source field to a Docent location:

| Source Field | Target Location | Target Field | Notes |
| :---- | :---- | :---- | :---- |
| messages | Transcript.messages | — | Convert via parse\_chat\_message |
| reward | AgentRun.metadata | scores.reward |  |
| task\_id | AgentRun.metadata | task\_id |  |

#### Document Omitted Data

**CRITICAL:** If ANY data will not be ingested, document it clearly:

| Field/File | Reason for Omission | Impact |
| :---- | :---- | :---- |
| `debug_logs/` | Contains only debug output, not agent transcripts | None |
| `raw_api_responses` | Redundant with parsed messages | Low |

**Never silently skip data.**

#### Present Plan for Review

Present the ingestion plan to the user:

1. Directory structure discovered
2. Data type detected
3. Proposed Docent hierarchy
4. Key field mappings
5. Omitted data (if any)

Wait for confirmation before proceeding to Stage 3\.

---

## **Stage 3: Ingestion**

### **Environment Setup**

Activate virtual environment if present:

```shell
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi
```

### **Handle Inspect AI Files**

If Inspect `.eval` files were detected, use the built-in loader:

```py
from inspect_ai.log import read_eval_log
from docent.loaders.load_inspect import load_inspect_log

eval_log = read_eval_log("path/to/file.eval")
agent_runs = load_inspect_log(eval_log)
print(f"Loaded {len(agent_runs)} runs from Inspect log")
```

Skip to "Upload to Docent" below.

### **Custom Data Loading**

For non-Inspect data, build the ingestion script incrementally.

#### Load Data

```py
import os
import json
from pathlib import Path
from docent import Docent
from docent.data_models import AgentRun, Transcript, TranscriptGroup
from docent.data_models.chat import parse_chat_message, ToolCall

def load_data(path: str) -> list[dict]:
    """Load data based on structure identified in Stage 2a."""
    path = Path(path)
    records = []
    # Implementation based on detected template structure
    return records

raw_data = load_data(data_path)
print(f"Loaded {len(raw_data)} records")
```

#### Conversion Function

```py
def convert_to_agent_run(record: dict) -> AgentRun:
    """Convert a single record to AgentRun."""
    raw_messages = record.get("messages") or record.get("traj") or []
    messages = [parse_chat_message(m) for m in raw_messages]

    # Handle tool calls if present
    for i, msg in enumerate(raw_messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            messages[i].tool_calls = [
                ToolCall(
                    id=tc.get("id", f"call_{i}"),
                    function=tc.get("function", {}).get("name", tc.get("name", "")),
                    arguments=tc.get("function", {}).get("arguments", tc.get("arguments", {})),
                    type="function"
                )
                for tc in msg["tool_calls"]
            ]

    transcript = Transcript(
        messages=messages,
        metadata={...}  # transcript-level metadata from mapping
    )

    return AgentRun(
        transcripts=[transcript],
        metadata={
            "scores": {...},  # from mapping
            # other metadata from mapping
        }
    )
```

#### Validation Loop

Test conversion on a sample before full ingestion:

```py
errors = []
for i, record in enumerate(raw_data[:10]):
    try:
        agent_run = convert_to_agent_run(record)
        _ = agent_run.text  # Validate by rendering
        print(f"✓ Record {i} converted successfully")
    except Exception as e:
        errors.append((i, str(e)))
        print(f"✗ Record {i} failed: {e}")

if errors:
    print(f"\n{len(errors)} validation errors in first 10 records")
```

#### Full Conversion

```py
agent_runs = []
conversion_errors = []

for i, record in enumerate(raw_data):
    try:
        agent_runs.append(convert_to_agent_run(record))
    except Exception as e:
        conversion_errors.append({"index": i, "error": str(e)})

print(f"Converted {len(agent_runs)}/{len(raw_data)} records")
if conversion_errors:
    print(f"Errors ({len(conversion_errors)}): {conversion_errors[:5]}...")
```

### **Upload to Docent**

```py
client = Docent(api_key=DOCENT_API_KEY)

collection_id = client.create_collection(
    name=collection_name,
    description="",
)
print(f"Created collection: {collection_id}")

client.add_agent_runs(collection_id, agent_runs)
print(f"Uploaded {len(agent_runs)} runs")

print(f"View at: https://docent.transluce.org/collection/{collection_id}")
```

---

## **Stage 4: Testing & Verification**

Verify that the upload succeeded and counts match expectations.

### **Count Verification**

```py
expected_runs = len(agent_runs)
failed_conversions = len(conversion_errors)
total_source_records = len(raw_data)

print(f"\n{'='*50}")
print("VERIFICATION REPORT")
print(f"{'='*50}")
print(f"Source records found:     {total_source_records}")
print(f"Successfully converted:   {expected_runs}")
print(f"Failed to convert:        {failed_conversions}")

# Verify upload via Docent SDK
try:
    collection_info = client.get_collection(collection_id)
    uploaded_count = collection_info.get("agent_run_count", "unknown")
    print(f"Uploaded to Docent:       {uploaded_count}")

    if uploaded_count != expected_runs:
        print(f"⚠️  WARNING: Count mismatch! Expected {expected_runs}, got {uploaded_count}")
    else:
        print(f"✓ Counts match!")
except Exception as e:
    print(f"Could not verify upload count via API: {e}")
    print(f"Please verify manually at: https://docent.transluce.org/collection/{collection_id}")
```

### **Log Verification Results**

Update `ingestion-plan.md`:

```
## Verification

### Counts
- Source records: [total_source_records]
- Converted successfully: [expected_runs]
- Conversion failures: [failed_conversions]
- Uploaded to Docent: [uploaded_count]
- **Status:** [MATCH / MISMATCH]

### Errors (if any)
[List conversion errors with record index and error message]

### Collection URL
https://docent.transluce.org/collection/[collection_id]
```

---

## **Reference**

See `references/docent-data-models.md` for complete Docent data model documentation.

For additional guidance on Docent data models and API usage, consult the official documentation: [https://docs.transluce.org/llms.txt](https://docs.transluce.org/llms.txt)

## **Common Patterns**

### **Inspect AI Logs**

When `.eval` files detected, use the built-in loader:

```py
from inspect_ai.log import read_eval_log
from docent.loaders.load_inspect import load_inspect_log

eval_log = read_eval_log("path/to/file.eval")
agent_runs = load_inspect_log(eval_log)
```

### **Parsing Chat Messages**

Use `parse_chat_message` to convert dictionaries to proper message objects:

```py
from docent.data_models.chat import parse_chat_message

# From dict - automatically determines message type from "role"
msg = parse_chat_message({
    "role": "user",
    "content": "What's 2+2?"
})

msg = parse_chat_message({
    "role": "assistant",
    "content": "The answer is 4."
})

msg = parse_chat_message({
    "role": "system",
    "content": "You are a helpful assistant."
})

# Direct construction is also available
from docent.data_models.chat import UserMessage, AssistantMessage, SystemMessage
msg = UserMessage(content="Hello")
msg = AssistantMessage(content="Hi!", model="gpt-4")
```

### **Simple Dict to AgentRun**

A common pattern for converting flat records:

```py
from docent.data_models import AgentRun, Transcript
from docent.data_models.chat import parse_chat_message

def convert_simple(record: dict) -> AgentRun:
    messages = [parse_chat_message(m) for m in record["messages"]]
    return AgentRun(
        transcripts=[Transcript(messages=messages)],
        metadata={
            "scores": {"reward": record.get("reward", 0)},
            **{k: v for k, v in record.items() if k != "messages"}
        }
    )
```

### **Tool Calls**

Handle assistant messages with tool calls and their responses:

```py
from docent.data_models.chat import AssistantMessage, ToolMessage, ToolCall

# Assistant making a tool call
assistant_msg = AssistantMessage(
    content="Let me search for that.",
    tool_calls=[
        ToolCall(
            id="call_123",
            function="web_search",
            arguments={"query": "weather today"},
            type="function"
        )
    ]
)

# Tool response
tool_msg = ToolMessage(
    content="Sunny, 72°F",
    tool_call_id="call_123",
    function="web_search"
)

# Helper to parse tool calls from raw data
def parse_tool_calls(raw_calls: list) -> list[ToolCall]:
    return [
        ToolCall(
            id=tc["id"],
            function=tc["function"]["name"],
            arguments=tc["function"].get("arguments", {}),
            type="function"
        )
        for tc in raw_calls
    ]
```

### **Pass@k Evaluation**

Use `TranscriptGroup` for attempts:

```py
from uuid import uuid4
from docent.data_models import AgentRun, Transcript, TranscriptGroup

def convert_pass_at_k(task_data: dict) -> AgentRun:
    agent_run_id = str(uuid4())
    groups = []
    transcripts = []

    for k, attempt in enumerate(task_data["attempts"]):
        group = TranscriptGroup(
            name=f"Attempt {k+1}",
            agent_run_id=agent_run_id,
            metadata={"k": k}
        )
        groups.append(group)

        transcript = Transcript(
            messages=[parse_chat_message(m) for m in attempt["messages"]],
            transcript_group_id=group.id,
            metadata={"attempt": k}
        )
        transcripts.append(transcript)

    return AgentRun(
        id=agent_run_id,
        transcripts=transcripts,
        transcript_groups=groups,
        metadata={"task_id": task_data["task_id"]}
    )
```

### **Tree/Branching**

Ingest each branch as its own `Transcript` in its own `AgentRun`. Use metadata to link branches:

```py
AgentRun(
    transcripts=[transcript],
    metadata={
        "root_task_id": "task_123",
        "branch_id": "branch_a_1",
        "parent_branch_id": "branch_a",
        "branch_depth": 2,
    }
)
```

### **Multi-Agent**

One `Transcript` per agent in the same `AgentRun`:

```py
AgentRun(
    transcripts=[
        Transcript(messages=agent_1_messages, metadata={"agent_id": "agent_1"}),
        Transcript(messages=agent_2_messages, metadata={"agent_id": "agent_2"}),
    ],
    metadata={
        "episode_id": "episode_42",
        "scores": {"joint_reward": 0.85}
    }
)
```

### **Validation**

Always validate by rendering before upload:

```py
try:
    _ = agent_run.text  # Triggers validation
    print("Valid")
except Exception as e:
    print(f"Invalid: {e}")
```
