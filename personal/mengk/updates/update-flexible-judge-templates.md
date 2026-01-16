Quick update on the flexible judge templates work we discussed:

What's new:

* You can now define custom multi-message prompt templates for judges (system/user/assistant messages)
* Built-in template variables: `{agent_run}`, `{rubric}`, `{output_schema}`, `{citation_instructions}`
* Sampling parameters (`temperature`, `max_new_tokens`) are now configurable per-judge
* Two output parsing modes:
  * `xml_key` (default) - extracts response from XML tags like `<response>...</response>`
  * `constrained_decoding` - parses the entire output as JSON (for APIs with structured output support)

Your existing judge pattern with `system_prompt`, `user_prompt`, and `response_format` can now be represented in Docent:

```python
Rubric(
    prompt_templates=[
        PromptTemplateMessage(role="system", content=judge_config.system_prompt),
        PromptTemplateMessage(role="user", content="""
            Rubric: {rubric}
            Trajectory: {agent_run}
        """),
    ],
    output_schema=judge_config.response_type.model_json_schema(),
    output_parsing_mode=OutputParsingMode.CONSTRAINED_DECODING,
    temperature=0.0,
)
```

To run it on an agent run:

```python
from docent._llm_util.llm_svc import BaseLLMService
from docent.judges.impl import SingleRolloutJudge

judge = SingleRolloutJudge(rubric, BaseLLMService())
result = await judge(agent_run)  # Returns JudgeResult with output matching your schema
```

Not changing yet:

* Still requires the `AgentRun` abstraction (needed for citations and result linking)
* No private/self-hosted model support yet (but OpenRouter covers most use cases)

Let me know if you have questions or want to walk through the integration!
