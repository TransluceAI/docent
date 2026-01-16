# autoflake: skip_file
# pyright: ignore
"""
Test script demonstrating a Rubric with default settings.
Uses minimal customization - only rubric_text is required.
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
# 1. CREATE RUBRIC WITH DEFAULT SETTINGS
# =============================================================================

from docent.judges.types import Rubric

# Only rubric_text is required - everything else uses defaults
rubric = Rubric(
    rubric_text="The agent should successfully complete the user's request in a helpful and accurate manner."
)

print("Rubric created with defaults!")
print(f"  - judge_model: {rubric.judge_model}")
print(f"  - judge_variant: {rubric.judge_variant}")
print(f"  - n_rollouts_per_input: {rubric.n_rollouts_per_input}")
print(f"  - output_parsing_mode: {rubric.output_parsing_mode}")
print(f"  - response_xml_key: {rubric.response_xml_key}")
print(f"  - prompt_templates: {len(rubric.prompt_templates)} message(s)")

#%%
# Print default output schema
import json

print("\nDefault output_schema:")
print(json.dumps(rubric.output_schema, indent=2))

#%%
# Print default prompt template
print("\nDefault prompt_template:")
for i, tmpl in enumerate(rubric.prompt_templates):
    print(f"  [{i}] role: {tmpl.role}")
    print("-" * 60)
    print(tmpl.content)

#%%
# =============================================================================
# 2. CREATE DUMMY AGENT RUNS
# =============================================================================

from docent.data_models import AgentRun, Transcript
from docent.data_models.chat import AssistantMessage, UserMessage

# Simple successful interaction
agent_run_1 = AgentRun(
    transcripts=[
        Transcript(
            messages=[
                UserMessage(content="What is 2 + 2?"),
                AssistantMessage(content="2 + 2 equals 4."),
            ]
        )
    ]
)

# Slightly longer interaction
agent_run_2 = AgentRun(
    transcripts=[
        Transcript(
            messages=[
                UserMessage(content="Can you help me sort a list in Python?"),
                AssistantMessage(
                    content="Sure! You can use the `sorted()` function or the `.sort()` method.\n\n"
                    "```python\n"
                    "my_list = [3, 1, 4, 1, 5]\n"
                    "sorted_list = sorted(my_list)  # Returns new list\n"
                    "my_list.sort()  # Sorts in place\n"
                    "```"
                ),
            ]
        )
    ]
)

print(f"Created {2} agent runs")

#%%
# =============================================================================
# 3. MATERIALIZE MESSAGES (inspect what gets sent to the LLM)
# =============================================================================

print("=" * 60)
print("MATERIALIZED MESSAGES FOR AGENT RUN 1")
print("=" * 60)

messages = rubric.materialize_messages(agent_run_1)
for i, msg in enumerate(messages):
    print(f"\n--- Message {i} [{msg.role.upper()}] ---")
    print(msg.content)

#%%
# =============================================================================
# 4. RUN THE JUDGE
# =============================================================================

from docent._llm_util.llm_svc import BaseLLMService
from docent.judges.impl import MajorityVotingJudge

llm_svc = BaseLLMService()
judge = MajorityVotingJudge(cfg=rubric, llm_svc=llm_svc)

print("Judge initialized!")

#%%
# Run on agent_run_1
result_1 = await judge(agent_run_1, temperature=0.0)
print("\n" + "=" * 60)
print("RESULT FOR AGENT RUN 1")
print("=" * 60)
print(result_1.model_dump_json(indent=2))

#%%
# Run on agent_run_2
result_2 = await judge(agent_run_2, temperature=0.0)
print("\n" + "=" * 60)
print("RESULT FOR AGENT RUN 2")
print("=" * 60)
print(result_2.model_dump_json(indent=2))

# %%
