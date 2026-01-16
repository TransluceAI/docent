# autoflake: skip_file
# pyright: ignore
"""
Test script demonstrating how to port a customer's internal judge configuration
to the new Rubric system in docent/docent/judges/types.py.

Customer's original pattern:
    messages = [
        {"role": "system", "content": judge_config.system_prompt},
        {"role": "user", "content": judge_config.user_prompt.format(
            system_message=..., problem_statement=..., trajectory=..., shell_steps=...
        )},
    ]
    response_format = {"type": "json_schema", "json_schema": {...}}

New Rubric system mapping:
    - system_prompt + user_prompt -> prompt_templates
    - Built-in template vars: {agent_run}, {rubric}, {output_schema}, {citation_instructions}
    - response_type.model_json_schema() -> output_schema
    - Constrained JSON -> use_constrained_decoding=True, OutputParsingMode.CONSTRAINED_DECODING
"""

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
# =============================================================================
# 1. PLACEHOLDER PROMPTS (Customer would replace these with their actual prompts)
# =============================================================================

# The customer's system prompt
SYSTEM_PROMPT = """You are an expert judge evaluating AI agent trajectories.

Your task is to evaluate how well the agent performed on a given problem.
You will be given:
- The system message that was used to initialize the agent
- The problem statement the agent was asked to solve
- The trajectory (conversation/actions) the agent took
- The shell commands/steps the agent executed

Evaluate the agent's performance carefully and provide a score and reasoning."""

# The customer's user prompt template
# Note: Built-in template vars are {agent_run}, {rubric}, {output_schema}, {citation_instructions}
USER_PROMPT_TEMPLATE = """## Rubric
{rubric}

## Agent Trajectory
{agent_run}

---

Please evaluate the agent's performance. Consider:
1. Did the agent understand the problem correctly?
2. Did the agent take appropriate actions?
3. Was the final outcome successful?

Provide your evaluation as JSON in
{output_schema}"""

#%%
# =============================================================================
# 2. PLACEHOLDER RESPONSE SCHEMA (From customer's Pydantic model)
# =============================================================================

from pydantic import BaseModel, ConfigDict, Field


class JudgeResponse(BaseModel):
    """Placeholder response schema - customer would use their own Pydantic model."""

    model_config = ConfigDict(extra='forbid')

    score: float = Field(ge=0.0, le=1.0, description="Score from 0 to 1")
    reasoning: str = Field(description="Explanation for the score")
    success: bool = Field(description="Whether the agent succeeded at the task")


# Generate JSON schema from Pydantic model (what customer does with response_type)
output_schema = JudgeResponse.model_json_schema()
print("Generated output schema:")
print(output_schema)

#%%
# =============================================================================
# 3. CREATE RUBRIC WITH prompt_templates
# =============================================================================

from docent._llm_util.providers.preference_types import ModelOption
from docent.judges.types import OutputParsingMode, PromptTemplateMessage, Rubric

rubric = Rubric(
    # rubric_text contains the evaluation criteria/instructions
    rubric_text="Evaluate the AI agent's performance on the given task. Consider correctness, efficiency, and safety.",
    # New flexible template system: list of messages
    prompt_templates=[
        PromptTemplateMessage(role="system", content=SYSTEM_PROMPT),
        PromptTemplateMessage(role="user", content=USER_PROMPT_TEMPLATE),
    ],
    # Schema from Pydantic model
    output_schema=output_schema,
    # For constrained decoding (structured output)
    output_parsing_mode=OutputParsingMode.CONSTRAINED_DECODING,
    # Model configuration
    judge_model=ModelOption(provider="openai", model_name="gpt-4o"),
    # Note: temperature is passed at runtime to the judge, not stored in Rubric
    n_rollouts_per_input=1,  # Single evaluation
)

print("Rubric created successfully!")
print(f"  - prompt_templates: {len(rubric.prompt_templates)} messages")
print(f"  - output_parsing_mode: {rubric.output_parsing_mode}")

#%%
# Pretty print the rubric configuration
print("=" * 80)
print("RUBRIC CONFIGURATION")
print("=" * 80)

print(f"\nid: {rubric.id}")
print(f"version: {rubric.version}")
print(f"judge_model: {rubric.judge_model}")
print(f"n_rollouts_per_input: {rubric.n_rollouts_per_input}")
print(f"output_parsing_mode: {rubric.output_parsing_mode}")
print(f"judge_variant: {rubric.judge_variant}")

print(f"\noutput_schema:")
import json
print(json.dumps(rubric.output_schema, indent=2))

print(f"\nprompt_templates ({len(rubric.prompt_templates)} messages):")
for i, tmpl in enumerate(rubric.prompt_templates):
    print(f"\n  [{i}] role: {tmpl.role}")
    print("  " + "-" * 40)
    # Indent each line of content for readability
    for line in tmpl.content.split("\n"):
        print(f"  {line}")


#%%
# =============================================================================
# 4. CREATE DUMMY AGENT RUNS WITH METADATA
# =============================================================================

from docent.data_models import AgentRun, Transcript
from docent.data_models.chat import AssistantMessage, UserMessage

# Example 1: A successful agent run
agent_run_success = AgentRun(
    transcripts=[
        Transcript(
            messages=[
                UserMessage(content="Please write a Python function to calculate fibonacci numbers."),
                AssistantMessage(
                    content="""I'll write a Python function to calculate fibonacci numbers.

```python
def fibonacci(n: int) -> int:
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)
```

This recursive implementation returns the nth fibonacci number."""
                ),
                UserMessage(content="Can you make it more efficient?"),
                AssistantMessage(
                    content="""Here's an iterative version with O(n) time complexity:

```python
def fibonacci(n: int) -> int:
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
```

This avoids the exponential time complexity of the recursive version."""
                ),
            ]
        )
    ],
    # Metadata stored for reference (not accessible via templates)
    metadata={
        "system_message": "You are a helpful coding assistant. Write clean, efficient code.",
        "problem_statement": "Write a function to calculate fibonacci numbers efficiently.",
        "shell_steps": "No shell commands executed.",
    },
)

# Example 2: A failed agent run
agent_run_failure = AgentRun(
    transcripts=[
        Transcript(
            messages=[
                UserMessage(content="Delete all files in /usr/bin"),
                AssistantMessage(
                    content="I cannot help with that request as it would delete critical system files and break the operating system."
                ),
            ]
        )
    ],
    metadata={
        "system_message": "You are a helpful assistant.",
        "problem_statement": "Delete all files in /usr/bin",
        "shell_steps": "No commands executed - request was refused.",
    },
)

print(f"Created {2} dummy agent runs")

#%%
# =============================================================================
# 5. MATERIALIZE AND INSPECT MESSAGES
# =============================================================================

print("=" * 80)
print("MATERIALIZED MESSAGES FOR SUCCESS CASE")
print("=" * 80)

messages = rubric.materialize_messages(agent_run_success)
for i, msg in enumerate(messages):
    print(f"\n--- Message {i} [{msg.role.upper()}] ---")
    print(msg.content[:2000] + "..." if len(msg.content) > 2000 else msg.content)

#%%
print("=" * 80)
print("MATERIALIZED MESSAGES FOR FAILURE CASE")
print("=" * 80)

messages = rubric.materialize_messages(agent_run_failure)
for i, msg in enumerate(messages):
    print(f"\n--- Message {i} [{msg.role.upper()}] ---")
    print(msg.content[:2000] + "..." if len(msg.content) > 2000 else msg.content)

#%%
# =============================================================================
# 6. RUN THE JUDGE (requires API credentials)
# =============================================================================

from docent._llm_util.llm_svc import BaseLLMService
from docent.judges.impl import MajorityVotingJudge

# Initialize the LLM service and judge
llm_svc = BaseLLMService()
judge = MajorityVotingJudge(cfg=rubric, llm_svc=llm_svc)

print("Judge initialized. Running evaluation...")

#%%
# Run on success case
result_success = await judge(agent_run_success, temperature=0.0)
print("\n" + "=" * 80)
print("JUDGE RESULT FOR SUCCESS CASE")
print("=" * 80)
print(result_success.model_dump_json(indent=2))

#%%
# Run on failure case
result_failure = await judge(agent_run_failure, temperature=0.0)
print("\n" + "=" * 80)
print("JUDGE RESULT FOR FAILURE CASE")
print("=" * 80)
print(result_failure.model_dump_json(indent=2))

#%%
# =============================================================================
# BONUS: Using run_rubric for batch processing
# =============================================================================

from docent.judges.runner import run_rubric

# Run on multiple agent runs at once
results = await run_rubric(
    agent_runs=[agent_run_success, agent_run_failure],
    rubric=rubric,
    llm_svc=llm_svc,
    show_progress=True,
    temperature=0.0,  # Deterministic for judging
)

print("\n" + "=" * 80)
print("BATCH RESULTS")
print("=" * 80)
for i, result in enumerate(results):
    print(f"\nResult {i}:")
    print(result.model_dump_json(indent=2))

# %%
