import pytest

from docent.judges.types import (
    DEFAULT_JUDGE_MODEL,
    DEFAULT_JUDGE_OUTPUT_SCHEMA,
    Rubric,
)
from docent_core.docent.db.schemas.rubric import SQLARubric


@pytest.mark.unit
def test_to_pydantic_maps_legacy_system_prompt_template_to_prompt_templates():
    sql_rubric = SQLARubric(
        id="rubric-123",
        version=1,
        collection_id="collection-456",
        rubric_text="Test rubric",
        output_schema=DEFAULT_JUDGE_OUTPUT_SCHEMA,
        judge_model=DEFAULT_JUDGE_MODEL.model_dump(),
        system_prompt_template=(
            "{rubric} {agent_run} {output_schema} <response></response> {citation_instructions}"
        ),
        prompt_templates=None,
    )

    rubric = sql_rubric.to_pydantic()

    assert isinstance(rubric, Rubric)
    assert rubric.prompt_templates[0].role == "user"
    assert "{citation_instructions}" not in rubric.prompt_templates[0].content
