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
# Imports
from docent._llm_util.llm_svc import BaseLLMService
from docent._llm_util.providers.preference_types import ModelOption
from docent.data_models.agent_run import AgentRun
from docent.data_models.chat import AssistantMessage, UserMessage
from docent.data_models.transcript import Transcript
from docent.judges import OutputParsingMode, Rubric
from docent.judges.impl import build_judge

#%%
# Create sample agent runs with transcripts

agent_run_1 = AgentRun(
    name="Math Problem",
    transcripts=[
        Transcript(
            name="Main conversation",
            messages=[
                UserMessage(role="user", content="What is 2 + 2?"),
                AssistantMessage(content="2 + 2 equals 4."),
            ],
        )
    ],
    metadata={"expected_answer": "4"},
)

agent_run_2 = AgentRun(
    name="Capital Question",
    transcripts=[
        Transcript(
            name="Main conversation",
            messages=[
                UserMessage(content="What is the capital of France?"),
                AssistantMessage(content="The capital of France is Paris."),
            ],
        )
    ],
    metadata={"expected_answer": "Paris"},
)

agent_run_3 = AgentRun(
    name="Wrong Answer",
    transcripts=[
        Transcript(
            name="Main conversation",
            messages=[
                UserMessage(content="What is 5 * 5?"),
                AssistantMessage(content="5 * 5 equals 20."),
            ],
        )
    ],
    metadata={"expected_answer": "25"},
)

print(f"Created {len([agent_run_1, agent_run_2, agent_run_3])} agent runs")

#%%
# Define rubric text for evaluation
RUBRIC_TEXT = """
Evaluate whether the assistant's response correctly answers the user's question.

The agent run metadata contains an "expected_answer" field. Compare the assistant's
response to this expected answer.

If the assistant's response contains the correct answer, label it as "match".
If the response is incorrect or does not contain the expected answer, label it as "no match".
"""

# Define output schema for constrained decoding
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": ["match", "no match"]},
        "explanation": {"type": "string"},
    },
    "required": ["label", "explanation"],
    "additionalProperties": False,
}

#%%
# Create rubric with OpenRouter model (using constraint decoding)
openrouter_rubric = Rubric(
    rubric_text=RUBRIC_TEXT,
    output_schema=OUTPUT_SCHEMA,
    output_parsing_mode=OutputParsingMode.CONSTRAINED_DECODING,
    judge_model=ModelOption(provider="openrouter", model_name="openai/gpt-4o-mini"),
    n_rollouts_per_input=1,
)

print(f"OpenRouter rubric created with model: {openrouter_rubric.judge_model}")
print(f"Output parsing mode: {openrouter_rubric.output_parsing_mode}")

#%%
# Create rubric with OpenAI model (using constraint decoding)
openai_rubric = Rubric(
    rubric_text=RUBRIC_TEXT,
    output_schema=OUTPUT_SCHEMA,
    output_parsing_mode=OutputParsingMode.CONSTRAINED_DECODING,
    judge_model=ModelOption(provider="openai", model_name="gpt-4o-mini"),
    n_rollouts_per_input=1,
)

print(f"OpenAI rubric created with model: {openai_rubric.judge_model}")
print(f"Output parsing mode: {openai_rubric.output_parsing_mode}")

#%%
# Create rubric with Minimax M2 model (using constraint decoding via OpenRouter)
minimax_m2_rubric = Rubric(
    rubric_text=RUBRIC_TEXT,
    output_schema=OUTPUT_SCHEMA,
    output_parsing_mode=OutputParsingMode.CONSTRAINED_DECODING,
    judge_model=ModelOption(provider="openrouter", model_name="minimax/minimax-m2"),
    n_rollouts_per_input=1,
)

print(f"Minimax M2 rubric created with model: {minimax_m2_rubric.judge_model}")
print(f"Output parsing mode: {minimax_m2_rubric.output_parsing_mode}")

#%%
# Create rubric with Minimax M2.1 model (using constraint decoding via OpenRouter)
minimax_m2_1_rubric = Rubric(
    rubric_text=RUBRIC_TEXT,
    output_schema=OUTPUT_SCHEMA,
    output_parsing_mode=OutputParsingMode.CONSTRAINED_DECODING,
    judge_model=ModelOption(provider="openrouter", model_name="minimax/minimax-m2.1"),
    n_rollouts_per_input=1,
)

print(f"Minimax M2.1 rubric created with model: {minimax_m2_1_rubric.judge_model}")
print(f"Output parsing mode: {minimax_m2_1_rubric.output_parsing_mode}")

#%%
# Create LLM service and build judges
llm_svc = BaseLLMService()

openrouter_judge = build_judge(openrouter_rubric, llm_svc)
openai_judge = build_judge(openai_rubric, llm_svc)
minimax_m2_judge = build_judge(minimax_m2_rubric, llm_svc)
minimax_m2_1_judge = build_judge(minimax_m2_1_rubric, llm_svc)

print(f"OpenRouter judge type: {type(openrouter_judge).__name__}")
print(f"OpenAI judge type: {type(openai_judge).__name__}")
print(f"Minimax M2 judge type: {type(minimax_m2_judge).__name__}")
print(f"Minimax M2.1 judge type: {type(minimax_m2_1_judge).__name__}")

#%%
# Test OpenRouter judge with constraint decoding
print("=" * 60)
print("Testing OpenRouter Judge with Constraint Decoding")
print("=" * 60)

for agent_run in [agent_run_1, agent_run_2, agent_run_3]:
    print(f"\n--- Testing: {agent_run.name} ---")
    result = await openrouter_judge(agent_run, temperature=0.0)
    print(f"Result type: {result.result_type}")
    print(f"Output: {result.output}")
    print(f"Expected: {agent_run.metadata.get('expected_answer')}")

#%%
# Test OpenAI judge with constraint decoding
print("=" * 60)
print("Testing OpenAI Judge with Constraint Decoding")
print("=" * 60)

for agent_run in [agent_run_1, agent_run_2, agent_run_3]:
    print(f"\n--- Testing: {agent_run.name} ---")
    result = await openai_judge(agent_run, temperature=0.0)
    print(f"Result type: {result.result_type}")
    print(f"Output: {result.output}")
    print(f"Expected: {agent_run.metadata.get('expected_answer')}")

#%%
# Test Minimax M2 judge with constraint decoding
print("=" * 60)
print("Testing Minimax M2 Judge with Constraint Decoding")
print("=" * 60)

for agent_run in [agent_run_1, agent_run_2, agent_run_3]:
    print(f"\n--- Testing: {agent_run.name} ---")
    result = await minimax_m2_judge(agent_run, temperature=0.0)
    print(f"Result type: {result.result_type}")
    print(f"Output: {result.output}")
    print(f"Expected: {agent_run.metadata.get('expected_answer')}")

#%%
# Test Minimax M2.1 judge with constraint decoding
print("=" * 60)
print("Testing Minimax M2.1 Judge with Constraint Decoding")
print("=" * 60)

for agent_run in [agent_run_1, agent_run_2, agent_run_3]:
    print(f"\n--- Testing: {agent_run.name} ---")
    result = await minimax_m2_1_judge(agent_run, temperature=0.0)
    print(f"Result type: {result.result_type}")
    print(f"Output: {result.output}")
    print(f"Expected: {agent_run.metadata.get('expected_answer')}")

#%%
# ============================================================
# PART 2: XML_KEY Parsing Mode (with custom "output" tag)
# ============================================================

# Define rubric text for XML_KEY mode - must mention the <output> tag
RUBRIC_TEXT_XML = """
Evaluate whether the assistant's response correctly answers the user's question.

The agent run metadata contains an "expected_answer" field. Compare the assistant's
response to this expected answer.

If the assistant's response contains the correct answer, label it as "match".
If the response is incorrect or does not contain the expected answer, label it as "no match".
"""

#%%
# Create rubric with OpenRouter model (using XML_KEY mode with custom tag)
openrouter_xml_rubric = Rubric(
    rubric_text=RUBRIC_TEXT_XML,
    output_schema=OUTPUT_SCHEMA,
    output_parsing_mode=OutputParsingMode.XML_KEY,
    response_xml_key="response",  # Custom tag instead of default "response"
    judge_model=ModelOption(provider="openrouter", model_name="openai/gpt-4o-mini"),
    n_rollouts_per_input=1,
)

print(f"OpenRouter XML rubric created with model: {openrouter_xml_rubric.judge_model}")
print(f"Output parsing mode: {openrouter_xml_rubric.output_parsing_mode}")
print(f"XML key: {openrouter_xml_rubric.response_xml_key}")

#%%
# Create rubric with OpenAI model (using XML_KEY mode with custom tag)
openai_xml_rubric = Rubric(
    rubric_text=RUBRIC_TEXT_XML,
    output_schema=OUTPUT_SCHEMA,
    output_parsing_mode=OutputParsingMode.XML_KEY,
    response_xml_key="response",  # Custom tag instead of default "response"
    judge_model=ModelOption(provider="openai", model_name="gpt-4o-mini"),
    n_rollouts_per_input=1,
)

print(f"OpenAI XML rubric created with model: {openai_xml_rubric.judge_model}")
print(f"Output parsing mode: {openai_xml_rubric.output_parsing_mode}")
print(f"XML key: {openai_xml_rubric.response_xml_key}")

#%%
# Build XML_KEY judges
openrouter_xml_judge = build_judge(openrouter_xml_rubric, llm_svc)
openai_xml_judge = build_judge(openai_xml_rubric, llm_svc)

print(f"OpenRouter XML judge type: {type(openrouter_xml_judge).__name__}")
print(f"OpenAI XML judge type: {type(openai_xml_judge).__name__}")

#%%
# Test OpenRouter judge with XML_KEY mode
print("=" * 60)
print("Testing OpenRouter Judge with XML_KEY Mode (tag: <output>)")
print("=" * 60)

for agent_run in [agent_run_1, agent_run_2, agent_run_3]:
    print(f"\n--- Testing: {agent_run.name} ---")
    result = await openrouter_xml_judge(agent_run, temperature=0.0)
    print(f"Result type: {result.result_type}")
    print(f"Output: {result.output}")
    print(f"Expected: {agent_run.metadata.get('expected_answer')}")

#%%
# Test OpenAI judge with XML_KEY mode
print("=" * 60)
print("Testing OpenAI Judge with XML_KEY Mode (tag: <output>)")
print("=" * 60)

for agent_run in [agent_run_1, agent_run_2, agent_run_3]:
    print(f"\n--- Testing: {agent_run.name} ---")
    result = await openai_xml_judge(agent_run, temperature=0.0)
    print(f"Result type: {result.result_type}")
    print(f"Output: {result.output}")
    print(f"Expected: {agent_run.metadata.get('expected_answer')}")

#%%
# Summary
print("\n" + "=" * 60)
print("All Tests Complete!")
print("=" * 60)
print(
    """
CONSTRAINED_DECODING mode:
- Uses JSON schema to force valid JSON output from the LLM
- No XML tags needed; entire output is the JSON response

XML_KEY mode (with custom "output" tag):
- LLM outputs free-form text with JSON wrapped in <output>...</output> tags
- Parser extracts and validates the JSON from within the tags

Expected results for all judges:
1. result_type=ResultType.DIRECT_RESULT
2. output dict with 'label' and 'explanation' keys
3. agent_run_1 and agent_run_2 should have label='match'
4. agent_run_3 should have label='no match' (5*5 is 25, not 20)
"""
)

# %%
