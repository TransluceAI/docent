from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, Field, ValidationError

from docent._llm_util.llm_svc import BaseLLMService
from docent._llm_util.providers.preference_types import ModelOption
from docent._log_util.logger import get_logger
from docent.data_models._tiktoken_util import get_token_count, truncate_to_token_limit
from docent.data_models.agent_run import AgentRun
from docent.data_models.citation import InlineCitation
from docent.judges.types import Rubric
from docent.sdk.llm_context import LLMContext, resolve_citations_with_context
from docent_core.docent.ai_tools.rubric.user_model import (
    LabelingRequest,
    LabelingRequestFocusItem,
)

if TYPE_CHECKING:
    from docent_core.docent.ai_tools.rubric.user_model import LabeledRun, QAPair, UserData

logger = get_logger(__name__)

# AGENT_RUN_TOK_LIMIT = 175_000
# DEFAULT_MODEL_OPTION = ModelOption(
#     provider="openrouter",
#     model_name="minimax/minimax-m2.5",
#     reasoning_effort=None,
# )
AGENT_RUN_TOK_LIMIT = 300_000
DEFAULT_MODEL_OPTION = ModelOption(
    provider="openrouter",
    model_name="openai/gpt-5.2",
    reasoning_effort=None,
)
# DEFAULT_MODEL_OPTION = ModelOption(
#     provider="openai",
#     model_name="gpt-5.2-2025-12-11",
#     reasoning_effort=None,
# )
# DEFAULT_MODEL_OPTION = ModelOption(
#     provider="anthropic",
#     model_name="claude-opus-4-5-20251101",
#     reasoning_effort=None,
# )
# DEFAULT_MODEL_OPTION = ModelOption(
#     provider="google",
#     model_name="gemini-3-flash-preview",
#     reasoning_effort=None,
# )
DEFAULT_USER_REASONING_FALLBACK = (
    "No explicit reasoning provided. This probability is inferred from the user model and "
    "available user QA/label history."
)
USER_DATA_PROMPT_TOKEN_LIMIT = 12_000
USER_DATA_SUMMARY_AGENT_RUN_TOK_LIMIT = 20_000
USER_DATA_SUMMARY_MAX_NEW_TOKENS = 1_200


class DistributionOutcome(BaseModel):
    """Single outcome and probability mass for a predictive distribution."""

    output: dict[str, Any]
    probability: float


class OutputDistribution(BaseModel):
    """Probability distribution over rubric-compliant outputs."""

    outcomes: list[DistributionOutcome] = Field(default_factory=list[DistributionOutcome])
    point_estimate: bool = False
    reasoning: str | None = None
    reasoning_citations: list[InlineCitation] = Field(default_factory=list[InlineCitation])


class RunDistributionEstimate(BaseModel):
    """Estimated user distribution for one run."""

    agent_run_id: str
    user_distribution: OutputDistribution | None = None
    error: str | None = None


class LabelingRequestResult(BaseModel):
    """Best-effort wrapper for labeling request generation."""

    agent_run_id: str
    request: LabelingRequest | None = None
    error: str | None = None


class SchemaSelectableField(BaseModel):
    """Top-level rubric output field that can be selected during interactive labeling."""

    kind: Literal["boolean", "enum"]
    options: list[Any] = Field(default_factory=list[Any])


class LabelMetadataUserDistribution(BaseModel):
    """Subset of p_u persisted in label metadata for prompt construction."""

    outcomes: list[DistributionOutcome] | None = None
    reasoning: str | None = None


class SelectedLabelMetadata(BaseModel):
    """Metadata fields included when summarizing existing labels."""

    user_distribution: LabelMetadataUserDistribution | None = None


class SelectedLabelPayload(BaseModel):
    """Structured label evidence block used in user-model prompt summaries."""

    label_value: dict[str, Any]
    explanation: str | None = None
    metadata: SelectedLabelMetadata = Field(default_factory=SelectedLabelMetadata)


class _RawDistributionOutcome(BaseModel):
    output: dict[str, Any]
    probability: object | None = None
    reasoning: str | None = None
    explanation: str | None = None


class _RawDistributionResponse(BaseModel):
    reasoning: str | None = None
    explanation: str | None = None
    outcomes: list[_RawDistributionOutcome] | None = None
    distribution: list[_RawDistributionOutcome] | None = None
    output: dict[str, Any] | None = None
    probability: object | None = None


# === User Model Inference ===


@dataclass
class _UserDataSummaryTask:
    item_type: str  # "qa" or "label"
    item_index: int
    agent_run_id: str


def _create_qa_item_summary_prompt(
    qa_pair: "QAPair",
    agent_run_text: str,
) -> str:
    qa_payload = {
        "question_context": qa_pair.question_context,
        "question": qa_pair.question,
        "answer": qa_pair.answer,
        "is_custom_response": qa_pair.is_custom_response,
        "timestamp": qa_pair.timestamp.isoformat(),
    }
    qa_payload_json = json.dumps(qa_payload, indent=2, sort_keys=True)
    return f"""You are summarizing one piece of human feedback for user-model inference.

AGENT RUN CONTEXT:
{agent_run_text}

QA ENTRY:
{qa_payload_json}

Write a concrete, rich summary (4-7 sentences) that captures:
- the relevant run context (what happened and why this case matters),
- how the user answered the question,
- what the answer suggests about this user's rubric reasoning in this case.

Stay grounded in specific details from this run and this QA entry. Do not write abstract principles.

Return only:
<summary>
[your summary]
</summary>
"""


def _create_label_item_summary_prompt(
    labeled_run: "LabeledRun",
    agent_run_text: str,
) -> str:
    label_entry = _format_label_evidence_block(labeled_run)
    return f"""You are summarizing one human labeling action for user-model inference.

AGENT RUN CONTEXT:
{agent_run_text}

LABEL ENTRY:
{label_entry}

Write a concrete, rich summary (4-7 sentences) that captures:
- the relevant run context (what happened and what behavior was evaluated),
- how the user labeled the run (including label values and explanation/metadata if provided),
- what this labeling behavior suggests about this user's rubric reasoning in this case.

Stay grounded in specific details from this run and this label entry. Do not write abstract principles.

Return only:
<summary>
[your summary]
</summary>
"""


def _extract_summary_text(raw_response: str) -> str:
    match = re.search(r"<summary>(.*?)</summary>", raw_response, re.DOTALL)
    if match:
        return match.group(1).strip()
    return raw_response.strip()


def _coerce_string_keyed_dict(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    parsed: dict[str, Any] = {}
    for key, item in cast(dict[object, object], value).items():
        if not isinstance(key, str):
            return None
        parsed[key] = item
    return parsed


def _extract_metadata_user_distribution(
    metadata: dict[str, Any] | None,
) -> LabelMetadataUserDistribution | None:
    if metadata is None:
        return None

    raw_user_distribution = _coerce_string_keyed_dict(metadata.get("user_distribution"))
    if raw_user_distribution is None:
        return None

    raw_outcomes = raw_user_distribution.get("outcomes")
    raw_reasoning = raw_user_distribution.get("reasoning")
    payload: dict[str, Any] = {}
    if isinstance(raw_outcomes, list):
        payload["outcomes"] = raw_outcomes
    if isinstance(raw_reasoning, str):
        payload["reasoning"] = raw_reasoning
    if not payload:
        return None

    try:
        return LabelMetadataUserDistribution.model_validate(payload)
    except ValidationError:
        logger.warning("Failed to parse label metadata user_distribution payload.")
        return None


def _build_selected_label_payload(labeled_run: "LabeledRun") -> SelectedLabelPayload:
    user_distribution = _extract_metadata_user_distribution(labeled_run.metadata)
    return SelectedLabelPayload(
        label_value=labeled_run.label_value,
        explanation=labeled_run.explanation,
        metadata=SelectedLabelMetadata(user_distribution=user_distribution),
    )


def _format_selected_label_entry(labeled_run: "LabeledRun") -> str:
    payload = _build_selected_label_payload(labeled_run)
    return json.dumps(payload.model_dump(mode="json"), indent=2, sort_keys=True)


def _get_user_label_evidence_fields_description() -> str:
    return (
        "User label evidence fields:\n"
        "- label_value: the user's selected rubric output for this run.\n"
        "- explanation: the user's own rationale for the chosen label, when provided.\n"
        "- metadata.user_distribution: the model-estimated p_u distribution shown during labeling, "
        "including only outcomes and reasoning."
    )


def _format_label_evidence_block(labeled_run: "LabeledRun") -> str:
    label_payload_json = _format_selected_label_entry(labeled_run)
    return f"User label evidence (selected JSON fields):\n{label_payload_json}"


def _format_user_data_qa_block(idx: int, user_data: "UserData") -> str:
    qa = user_data.qa_pairs[idx]
    return (
        f"--- Example {idx + 1} (run: {qa.agent_run_id or 'unknown'}) ---\n"
        f"Situation: {qa.question_context or 'N/A'}\n"
        f"Question asked: {qa.question}\n"
        f"User's answer: {qa.answer}\n"
        f"Custom response: {'Yes' if qa.is_custom_response else 'No'}"
    )


def _format_user_data_label_line(idx: int, user_data: "UserData") -> str:
    label = user_data.labels[idx]
    return (
        f"--- Label {idx + 1} (run: {label.agent_run_id}) ---\n"
        f"{_format_label_evidence_block(label)}"
    )


def _build_user_data_summary_text(
    qa_blocks: list[str],
    label_lines: list[str],
    total_qa_pairs: int,
    total_labels: int,
) -> str:
    qa_section = "\n\n".join(qa_blocks) if qa_blocks else "No QA pairs."
    if label_lines:
        label_section = f"{_get_user_label_evidence_fields_description()}\n\n" + "\n".join(
            label_lines
        )
    else:
        label_section = "No labels."
    return (
        f"QA Pairs ({len(qa_blocks)}/{total_qa_pairs} shown):\n{qa_section}\n\n"
        f"Labels ({len(label_lines)}/{total_labels} shown):\n{label_section}"
    )


def summarize_user_data_for_prompt(
    user_data: "UserData",
    max_tokens: int = USER_DATA_PROMPT_TOKEN_LIMIT,
    log_truncation_warning: bool = True,
) -> str:
    if max_tokens <= 0:
        raise ValueError("max_tokens must be > 0")

    total_qa_pairs = len(user_data.qa_pairs)
    total_labels = len(user_data.labels)

    qa_blocks: list[str] = []
    label_lines: list[str] = []

    omitted_qa_pairs = 0
    for qa_idx in range(total_qa_pairs):
        candidate_block = _format_user_data_qa_block(qa_idx, user_data)
        candidate_summary = _build_user_data_summary_text(
            qa_blocks=qa_blocks + [candidate_block],
            label_lines=label_lines,
            total_qa_pairs=total_qa_pairs,
            total_labels=total_labels,
        )
        if get_token_count(candidate_summary) <= max_tokens:
            qa_blocks.append(candidate_block)
            continue

        omitted_qa_pairs = total_qa_pairs - len(qa_blocks)
        break

    omitted_labels = 0
    for label_idx in range(total_labels):
        candidate_line = _format_user_data_label_line(label_idx, user_data)
        candidate_summary = _build_user_data_summary_text(
            qa_blocks=qa_blocks,
            label_lines=label_lines + [candidate_line],
            total_qa_pairs=total_qa_pairs,
            total_labels=total_labels,
        )
        if get_token_count(candidate_summary) <= max_tokens:
            label_lines.append(candidate_line)
            continue

        omitted_labels = total_labels - len(label_lines)
        break

    summary = _build_user_data_summary_text(
        qa_blocks=qa_blocks,
        label_lines=label_lines,
        total_qa_pairs=total_qa_pairs,
        total_labels=total_labels,
    )
    used_tokens = get_token_count(summary)
    logger.info(
        (
            "Built user-data summary for prompt: %d/%d tokens, "
            "%d/%d QA pairs included, %d/%d labels included"
        ),
        used_tokens,
        max_tokens,
        len(qa_blocks),
        total_qa_pairs,
        len(label_lines),
        total_labels,
    )

    if log_truncation_warning and (omitted_qa_pairs > 0 or omitted_labels > 0):
        logger.warning(
            (
                "User-data summary hit token limit (%d/%d). "
                "Omitted %d QA pair(s) and %d label(s) from prompt context."
            ),
            used_tokens,
            max_tokens,
            omitted_qa_pairs,
            omitted_labels,
        )

    return summary


def _build_generated_user_data_summary_text(
    qa_blocks: list[str],
    label_blocks: list[str],
    total_qa_pairs: int,
    total_labels: int,
) -> str:
    qa_section = "\n\n".join(qa_blocks) if qa_blocks else "No QA summaries."
    if label_blocks:
        label_section = f"{_get_user_label_evidence_fields_description()}\n\n" + "\n\n".join(
            label_blocks
        )
    else:
        label_section = "No label summaries."
    return (
        f"QA Summaries ({len(qa_blocks)}/{total_qa_pairs} shown):\n{qa_section}\n\n"
        f"Label Summaries ({len(label_blocks)}/{total_labels} shown):\n{label_section}"
    )


def _fit_generated_user_data_summary_to_token_limit(
    qa_blocks: list[str],
    label_blocks: list[str],
    total_qa_pairs: int,
    total_labels: int,
    max_tokens: int,
) -> tuple[str, int, int]:
    included_qa: list[str] = []
    included_labels: list[str] = []

    for qa_block in qa_blocks:
        candidate = _build_generated_user_data_summary_text(
            qa_blocks=included_qa + [qa_block],
            label_blocks=included_labels,
            total_qa_pairs=total_qa_pairs,
            total_labels=total_labels,
        )
        if get_token_count(candidate) <= max_tokens:
            included_qa.append(qa_block)
            continue
        break

    for label_block in label_blocks:
        candidate = _build_generated_user_data_summary_text(
            qa_blocks=included_qa,
            label_blocks=included_labels + [label_block],
            total_qa_pairs=total_qa_pairs,
            total_labels=total_labels,
        )
        if get_token_count(candidate) <= max_tokens:
            included_labels.append(label_block)
            continue
        break

    summary = _build_generated_user_data_summary_text(
        qa_blocks=included_qa,
        label_blocks=included_labels,
        total_qa_pairs=total_qa_pairs,
        total_labels=total_labels,
    )
    omitted_qa_pairs = total_qa_pairs - len(included_qa)
    omitted_labels = total_labels - len(included_labels)
    return summary, omitted_qa_pairs, omitted_labels


async def summarize_user_data_for_prompt_with_agent_runs(
    user_data: "UserData",
    agent_runs_by_id: dict[str, AgentRun],
    llm_svc: BaseLLMService,
    max_tokens: int = USER_DATA_PROMPT_TOKEN_LIMIT,
    log_truncation_warning: bool = True,
) -> str:
    if max_tokens <= 0:
        raise ValueError("max_tokens must be > 0")

    total_qa_pairs = len(user_data.qa_pairs)
    total_labels = len(user_data.labels)

    inputs: list[list[dict[str, str]]] = []
    summary_tasks: list[_UserDataSummaryTask] = []

    for qa_idx, qa_pair in enumerate(user_data.qa_pairs):
        agent_run = agent_runs_by_id.get(qa_pair.agent_run_id)
        if agent_run is None:
            logger.error(
                "Skipping QA pair %d for user-data summary; missing agent run %s",
                qa_idx + 1,
                qa_pair.agent_run_id,
            )
            continue

        agent_run_text = LLMContext(items=[agent_run]).to_str()
        agent_run_text, _, _ = truncate_to_token_limit(
            agent_run_text, max_tokens=USER_DATA_SUMMARY_AGENT_RUN_TOK_LIMIT
        )
        prompt = _create_qa_item_summary_prompt(
            qa_pair=qa_pair,
            agent_run_text=agent_run_text,
        )
        inputs.append([{"role": "user", "content": prompt}])
        summary_tasks.append(
            _UserDataSummaryTask(
                item_type="qa",
                item_index=qa_idx,
                agent_run_id=qa_pair.agent_run_id,
            )
        )

    for label_idx, labeled_run in enumerate(user_data.labels):
        agent_run = agent_runs_by_id.get(labeled_run.agent_run_id)
        if agent_run is None:
            logger.error(
                "Skipping label %d for user-data summary; missing agent run %s",
                label_idx + 1,
                labeled_run.agent_run_id,
            )
            continue

        agent_run_text = LLMContext(items=[agent_run]).to_str()
        agent_run_text, _, _ = truncate_to_token_limit(
            agent_run_text, max_tokens=USER_DATA_SUMMARY_AGENT_RUN_TOK_LIMIT
        )
        prompt = _create_label_item_summary_prompt(
            labeled_run=labeled_run,
            agent_run_text=agent_run_text,
        )
        inputs.append([{"role": "user", "content": prompt}])
        summary_tasks.append(
            _UserDataSummaryTask(
                item_type="label",
                item_index=label_idx,
                agent_run_id=labeled_run.agent_run_id,
            )
        )

    qa_blocks: list[str] = []
    label_blocks: list[str] = []

    if inputs:
        outputs = await llm_svc.get_completions(
            inputs=inputs,
            model_options=[DEFAULT_MODEL_OPTION],
            max_new_tokens=USER_DATA_SUMMARY_MAX_NEW_TOKENS,
            temperature=0.2,
            timeout=120.0,
        )

        for summary_task, output in zip(summary_tasks, outputs):
            if output.did_error:
                logger.error(
                    "Failed to summarize user-data %s %d for run %s: %s",
                    summary_task.item_type,
                    summary_task.item_index + 1,
                    summary_task.agent_run_id,
                    output.errors,
                )
                continue

            response_text = output.completions[0].text if output.completions else ""
            summary_text = _extract_summary_text(response_text or "")
            if not summary_text:
                logger.error(
                    "Failed to summarize user-data %s %d for run %s: empty summary",
                    summary_task.item_type,
                    summary_task.item_index + 1,
                    summary_task.agent_run_id,
                )
                continue

            if summary_task.item_type == "qa":
                qa_blocks.append(
                    (
                        f"--- QA Summary {summary_task.item_index + 1} "
                        f"(run: {summary_task.agent_run_id}) ---\n{summary_text}"
                    )
                )
            else:
                label_evidence_entry = _format_label_evidence_block(
                    user_data.labels[summary_task.item_index]
                )
                label_blocks.append(
                    (
                        f"--- Label Summary {summary_task.item_index + 1} "
                        f"(run: {summary_task.agent_run_id}) ---\n"
                        f"{label_evidence_entry}\n\n"
                        f"Generated contextual summary:\n{summary_text}"
                    )
                )

    summary, omitted_qa_pairs, omitted_labels = _fit_generated_user_data_summary_to_token_limit(
        qa_blocks=qa_blocks,
        label_blocks=label_blocks,
        total_qa_pairs=total_qa_pairs,
        total_labels=total_labels,
        max_tokens=max_tokens,
    )
    used_tokens = get_token_count(summary)

    logger.info(
        (
            "Built agent-run user-data summary for prompt: %d/%d tokens, "
            "%d/%d QA summaries included, %d/%d label summaries included"
        ),
        used_tokens,
        max_tokens,
        total_qa_pairs - omitted_qa_pairs,
        total_qa_pairs,
        total_labels - omitted_labels,
        total_labels,
    )

    if log_truncation_warning and (omitted_qa_pairs > 0 or omitted_labels > 0):
        logger.warning(
            (
                "Agent-run user-data summary hit token or availability limits (%d/%d). "
                "Omitted %d QA pair(s) and %d label(s) from prompt context."
            ),
            used_tokens,
            max_tokens,
            omitted_qa_pairs,
            omitted_labels,
        )

    return summary


def _create_user_model_inference_prompt(
    initial_rubric: str,
    user_data_summary: str,
) -> str:
    return f"""You are building a user model for rubric-based labeling. The model should be a **curated collection of richly annotated examples** that a downstream LLM can reason from by analogy — NOT a set of abstract principles.

INITIAL RUBRIC:
{initial_rubric}

OBSERVED USER DATA:
{user_data_summary}

Your task: Transform the observed data into a set of annotated examples that capture how this user thinks.

OUTPUT FORMAT — use this structure exactly:

Start with a concise orientation section:

### High-level user orientation
[2-4 sentences on what the user seems to optimize for overall, what they are trying to avoid, and any major tradeoff they repeatedly make.]

Then, for each meaningful piece of feedback, produce an entry:

### Example N: [short descriptive title]
**Situation:** [Rich description of the context — what the agent did, what the task was, what happened. Preserve concrete details.]
**Question:** [The question that was asked]
**User's judgment:** [The user's full answer]
**What this reveals:** [1-2 concrete sentences about what this specific case tells us about the user's preferences. Stay grounded in this example — do NOT generalize into abstract principles.]

After all examples, include ONE brief section:

### Connecting patterns
- [2-4 bullets, each citing specific example numbers, e.g. "Examples 3 and 7 both show the user cares about X when Y happens"]

CRITICAL RULES:
- The "High-level user orientation" must be at the top and stay succinct (2-4 sentences).
- The annotated examples should comprise ~80% of the output. Do NOT abstract them away into principles.
- Preserve rich situational detail — the downstream LLM needs enough context to reason by analogy to new cases.
- If two examples seem contradictory, keep BOTH and note the tension in "What this reveals."
- The "Connecting patterns" section should be SHORT (2-4 bullets). It exists to help orient a reader, not to replace the examples.
- Treat any "User label evidence (selected JSON fields)" block as source-of-truth evidence. Do not contradict or overwrite user-provided wording; when referencing user-stated explanation text, quote it exactly.

Return your response in this format:
<user_model>
[Your example-based user model in markdown]
</user_model>
"""


def build_user_model_inference_prompt(
    user_data: "UserData",
    max_tokens: int = USER_DATA_PROMPT_TOKEN_LIMIT,
    log_truncation_warning: bool = True,
) -> tuple[str, str]:
    """Render user-data summary and inference prompt in one place."""
    user_data_summary = summarize_user_data_for_prompt(
        user_data=user_data,
        max_tokens=max_tokens,
        log_truncation_warning=log_truncation_warning,
    )
    prompt = _create_user_model_inference_prompt(
        initial_rubric=user_data.initial_rubric,
        user_data_summary=user_data_summary,
    )
    return user_data_summary, prompt


async def build_user_model_inference_prompt_with_agent_runs(
    user_data: "UserData",
    agent_runs_by_id: dict[str, AgentRun],
    llm_svc: BaseLLMService,
    max_tokens: int = USER_DATA_PROMPT_TOKEN_LIMIT,
    log_truncation_warning: bool = True,
) -> tuple[str, str]:
    """Render user-data summary and inference prompt using AgentRun-grounded summaries."""
    user_data_summary = await summarize_user_data_for_prompt_with_agent_runs(
        user_data=user_data,
        agent_runs_by_id=agent_runs_by_id,
        llm_svc=llm_svc,
        max_tokens=max_tokens,
        log_truncation_warning=log_truncation_warning,
    )
    prompt = _create_user_model_inference_prompt(
        initial_rubric=user_data.initial_rubric,
        user_data_summary=user_data_summary,
    )
    return user_data_summary, prompt


def create_user_model_inference_prompt(user_data: "UserData") -> str:
    """Create prompt for inferring textual user model z from U=(QA, labels, initial rubric)."""
    _, prompt = build_user_model_inference_prompt(
        user_data=user_data,
        max_tokens=USER_DATA_PROMPT_TOKEN_LIMIT,
        log_truncation_warning=True,
    )
    return prompt


async def infer_user_model_from_user_data(
    user_data: "UserData",
    llm_svc: BaseLLMService,
    user_data_summary: str | None = None,
) -> str:
    """Infer textual user model z from U. Falls back to initial rubric on failure."""
    if not user_data.qa_pairs and not user_data.labels:
        return user_data.initial_rubric

    if user_data_summary is None:
        _, prompt = build_user_model_inference_prompt(
            user_data=user_data,
            max_tokens=USER_DATA_PROMPT_TOKEN_LIMIT,
            log_truncation_warning=True,
        )
    else:
        prompt = _create_user_model_inference_prompt(
            initial_rubric=user_data.initial_rubric,
            user_data_summary=user_data_summary,
        )

    outputs = await llm_svc.get_completions(
        inputs=[[{"role": "user", "content": prompt}]],
        model_options=[DEFAULT_MODEL_OPTION],
        max_new_tokens=8192,
        timeout=120.0,
    )
    output = outputs[0]

    if output.did_error:
        logger.warning(f"Failed to infer user model from user data: {output.errors}")
        return user_data.initial_rubric

    response_text = output.completions[0].text or ""
    match = re.search(r"<user_model>(.*?)</user_model>", response_text, re.DOTALL)
    if match:
        return match.group(1).strip()

    stripped = response_text.strip()
    return stripped or user_data.initial_rubric


def create_user_distribution_prompt(
    agent_run_text: str,
    rubric_text: str,
    output_schema: dict[str, Any],
    user_model_text: str,
    citation_instructions: str,
) -> str:
    """Create prompt for p_u(y | x, z, r)."""
    schema_text = json.dumps(output_schema, indent=2)

    return f"""You are estimating p_u(y | x, z, r), where y follows the rubric output schema.

{citation_instructions}

Rubric:
{rubric_text}

Output schema:
{schema_text}

User model z:
{user_model_text}

Agent run:
{agent_run_text}

Task:
Given the user model, what would you anticipate the user says?
Estimate the distribution using this reasoning procedure:
1. Follow the rubric and identify the key cruxes that would change the output/outcome.
2. For each crux, inspect user model z for specific evidence that resolves or partially resolves it.
3. Holistically synthesize all cruxes and evidence to produce the final probability distribution.

Guidance:
- Anchor your reasoning to rubric-relevant cruxes only.
- For each crux, look for both supporting and conflicting signals in z.
- Explicitly note unresolved, sparse, or conflicting evidence and how it affects uncertainty.
- Situations explicitly covered in user model are generally less uncertain (with exceptions).
- Situations not explicitly covered are generally uncertain, unless the interpretation is obvious.
- Connect the final distribution to specific user-model signals.
- If support in z is sparse or conflicting, explicitly state uncertainty and why.
- Probabilities should sum to 1.

Return JSON:
{{
  "reasoning": "<holistic rationale explaining key cruxes, how z resolves them, and why the final distribution looks this way>",
  "outcomes": [
    {{
      "output": <json object compliant with schema>,
      "probability": <float>
    }}
  ]
}}
"""


def parse_output_distribution_response(
    llm_response: str,
    context: LLMContext | None,
    point_estimate: bool,
    require_reasoning: bool = False,
    missing_reasoning_fallback: str = DEFAULT_USER_REASONING_FALLBACK,
) -> OutputDistribution | None:
    """Parse distribution JSON from LLM response, resolve citations, normalize probabilities."""
    parsed = parse_llm_json_response(llm_response, keys=("outcomes", "distribution", "output"))
    if parsed is None:
        return None

    try:
        parsed_distribution = _RawDistributionResponse.model_validate(parsed)
    except ValidationError:
        return None

    overall_reasoning = parsed_distribution.reasoning or parsed_distribution.explanation

    raw_outcomes = parsed_distribution.outcomes or parsed_distribution.distribution
    if raw_outcomes is None and parsed_distribution.output is not None:
        raw_outcomes = [
            _RawDistributionOutcome(
                output=parsed_distribution.output,
                probability=parsed_distribution.probability,
                reasoning=parsed_distribution.reasoning,
                explanation=parsed_distribution.explanation,
            )
        ]

    if raw_outcomes is None:
        return None

    extracted_outputs: list[dict[str, Any]] = []
    extracted_probs: list[float | None] = []
    outcome_reasoning: list[str] = []

    for raw_outcome in raw_outcomes:
        if overall_reasoning is None:
            outcome_reasoning_text = raw_outcome.reasoning or raw_outcome.explanation
            if isinstance(outcome_reasoning_text, str) and outcome_reasoning_text.strip():
                outcome_reasoning.append(outcome_reasoning_text.strip())

        extracted_outputs.append(raw_outcome.output)
        extracted_probs.append(_coerce_probability(raw_outcome.probability))

    if not extracted_outputs:
        return None

    if overall_reasoning is None and outcome_reasoning:
        overall_reasoning = outcome_reasoning[0]

    overall_reasoning_citations: list[InlineCitation] = []
    if overall_reasoning and context is not None:
        overall_reasoning, overall_reasoning_citations = resolve_citations_with_context(
            overall_reasoning, context, validate_text_ranges=True
        )

    if require_reasoning and (not overall_reasoning or not overall_reasoning.strip()):
        overall_reasoning = missing_reasoning_fallback

    assign_uniform = any(prob is None for prob in extracted_probs)
    probabilities: list[float] = []
    if assign_uniform:
        uniform = 1.0 / len(extracted_outputs)
        probabilities = [uniform] * len(extracted_outputs)
    else:
        concrete_probs = [prob for prob in extracted_probs if prob is not None]
        total = sum(concrete_probs)
        if total <= 0:
            uniform = 1.0 / len(extracted_outputs)
            probabilities = [uniform] * len(extracted_outputs)
        else:
            probabilities = [prob / total for prob in concrete_probs]

    outcomes = [
        DistributionOutcome(
            output=output,
            probability=prob,
        )
        for output, prob in zip(
            extracted_outputs,
            probabilities,
        )
    ]

    distribution = OutputDistribution(
        outcomes=outcomes,
        point_estimate=point_estimate,
        reasoning=overall_reasoning,
        reasoning_citations=overall_reasoning_citations,
    )
    return normalize_output_distribution(distribution)


async def estimate_user_distributions_for_agent_runs(
    agent_runs: list[AgentRun],
    rubric: Rubric,
    user_model_text: str,
    llm_svc: BaseLLMService,
) -> list[RunDistributionEstimate]:
    """Estimate p_u for each run using only the inferred user model."""
    if not agent_runs:
        return []

    user_inputs: list[list[dict[str, str]]] = []
    run_metadata: list[tuple[str, LLMContext]] = []

    for agent_run in agent_runs:
        context = LLMContext(items=[agent_run])
        citation_instructions = context.get_system_message(
            interactive=False, include_citations=True
        )
        agent_run_text = context.to_str()
        agent_run_text, _, _ = truncate_to_token_limit(
            agent_run_text, max_tokens=AGENT_RUN_TOK_LIMIT
        )

        user_prompt = create_user_distribution_prompt(
            agent_run_text=agent_run_text,
            rubric_text=rubric.rubric_text,
            output_schema=rubric.output_schema,
            user_model_text=user_model_text,
            citation_instructions=citation_instructions,
        )

        user_inputs.append([{"role": "user", "content": user_prompt}])
        run_metadata.append((agent_run.id, context))

    user_outputs = await llm_svc.get_completions(
        inputs=user_inputs,
        model_options=[DEFAULT_MODEL_OPTION],
        max_new_tokens=8192,
        temperature=1.0,
        timeout=180.0,
    )

    results: list[RunDistributionEstimate] = []
    for (agent_run_id, context), user_output in zip(run_metadata, user_outputs):
        if user_output.did_error:
            error_msg = "; ".join(str(e) for e in user_output.errors)
            results.append(
                RunDistributionEstimate(
                    agent_run_id=agent_run_id,
                    error=f"User distribution error: {error_msg}",
                )
            )
            continue

        user_text = user_output.completions[0].text or ""
        user_distribution = parse_output_distribution_response(
            user_text,
            context=context,
            point_estimate=False,
            require_reasoning=True,
            missing_reasoning_fallback=DEFAULT_USER_REASONING_FALLBACK,
        )

        if user_distribution is None:
            results.append(
                RunDistributionEstimate(
                    agent_run_id=agent_run_id,
                    error="Failed to parse user distribution response",
                )
            )
            continue

        results.append(
            RunDistributionEstimate(
                agent_run_id=agent_run_id,
                user_distribution=user_distribution,
                error=None,
            )
        )

    valid_estimates = [
        estimate
        for estimate in results
        if estimate.error is None and estimate.user_distribution is not None
    ]
    logger.info(
        "Finished sampled user distribution estimates: %d total, %d valid.",
        len(results),
        len(valid_estimates),
    )
    return results


def get_enum_boolean_fields_from_schema(
    output_schema: dict[str, Any],
) -> dict[str, SchemaSelectableField]:
    """Extract top-level enum/boolean fields with option metadata from a JSON schema."""
    properties = _coerce_string_keyed_dict(output_schema.get("properties"))
    if properties is None:
        return {}

    fields: dict[str, SchemaSelectableField] = {}
    for key_obj, field_schema_obj in properties.items():
        field_schema = _coerce_string_keyed_dict(field_schema_obj)
        if field_schema is None:
            continue

        field_type = field_schema.get("type")

        if isinstance(field_type, str) and field_type == "boolean":
            fields[key_obj] = SchemaSelectableField(kind="boolean", options=[True, False])
            continue

        enum_values = field_schema.get("enum")
        if isinstance(enum_values, list):
            enum_options: list[Any] = []
            for enum_value in cast(list[object], enum_values):
                enum_options.append(enum_value)
            fields[key_obj] = SchemaSelectableField(kind="enum", options=enum_options)

    return fields


# === Labeling Request Generation ===


def _distribution_summary_for_prompt(
    distribution: OutputDistribution,
    max_outcomes: int = 5,
) -> str:
    return format_user_distribution_for_display(
        distribution=distribution,
        max_outcomes=max_outcomes,
        max_reasoning_chars=220,
    )


def format_user_distribution_for_display(
    distribution: OutputDistribution,
    max_outcomes: int = 5,
    max_reasoning_chars: int | None = None,
) -> str:
    """Render normalized p_u outcomes and reasoning as pretty JSON for display."""
    normalized = normalize_output_distribution(distribution)
    payload_outcomes: list[dict[str, Any]] = []
    for outcome in normalized.outcomes[:max_outcomes]:
        payload_outcomes.append(
            {
                "output": outcome.output,
                "probability": round(outcome.probability, 6),
            }
        )

    reasoning_text = normalized.reasoning or ""
    if max_reasoning_chars is not None:
        reasoning_text = _truncate_for_prompt(reasoning_text, max_reasoning_chars)

    payload: dict[str, Any] = {"reasoning": reasoning_text, "outcomes": payload_outcomes}
    return json.dumps(payload, indent=2)


def _inline_citation_identity_key(citation: InlineCitation) -> str:
    return json.dumps(
        citation.target.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )


def _format_inline_citation_target(citation: InlineCitation, max_snippet_chars: int) -> str:
    target = citation.target.item
    item_type = getattr(target, "item_type", "unknown")
    details: list[str] = []

    transcript_id = getattr(target, "transcript_id", None)
    if transcript_id is not None:
        details.append(str(transcript_id))

    block_idx = getattr(target, "block_idx", None)
    if block_idx is not None:
        details.append(f"B{block_idx}")

    content_idx = getattr(target, "content_idx", None)
    if content_idx is not None:
        details.append(f"C{content_idx}")

    metadata_key = getattr(target, "metadata_key", None)
    if metadata_key is not None:
        details.append(f"M.{metadata_key}")

    result_set_id = getattr(target, "result_set_id", None)
    if result_set_id is not None:
        details.append(f"set:{result_set_id}")

    result_id = getattr(target, "result_id", None)
    if result_id is not None:
        details.append(f"result:{result_id}")

    if not details:
        agent_run_id = getattr(target, "agent_run_id", None)
        if agent_run_id is not None:
            details.append(str(agent_run_id))

    target_text = item_type if not details else f"{item_type}:{':'.join(details)}"

    text_range = citation.target.text_range
    snippet = text_range.start_pattern if text_range is not None else None
    if snippet is None:
        return target_text

    snippet_text = " ".join(snippet.split())
    if len(snippet_text) > max_snippet_chars:
        snippet_text = snippet_text[:max_snippet_chars] + "..."
    if not snippet_text:
        return target_text
    return f'{target_text} | "{snippet_text}"'


def render_text_with_citation_footnotes(
    text: str,
    citations: Sequence[InlineCitation],
    max_snippet_chars: int = 120,
) -> tuple[str, list[str]]:
    """Replace inline citation spans with numeric references and section footnotes."""
    if not citations:
        return text, []

    sorted_citations = sorted(citations, key=lambda cite: (cite.start_idx, cite.end_idx))
    rendered_parts: list[str] = []
    identity_to_number: dict[str, int] = {}
    footnotes_by_number: dict[int, str] = {}

    cursor = 0
    text_len = len(text)
    next_number = 1
    for citation in sorted_citations:
        start_idx = citation.start_idx
        end_idx = citation.end_idx
        if start_idx < 0 or end_idx > text_len or start_idx >= end_idx:
            continue
        if start_idx < cursor:
            # Ignore conflicting/overlapping spans and keep deterministic output.
            continue

        rendered_parts.append(text[cursor:start_idx])

        citation_key = _inline_citation_identity_key(citation)
        citation_number = identity_to_number.get(citation_key)
        if citation_number is None:
            citation_number = next_number
            identity_to_number[citation_key] = citation_number
            footnotes_by_number[citation_number] = _format_inline_citation_target(
                citation=citation,
                max_snippet_chars=max_snippet_chars,
            )
            next_number += 1

        rendered_parts.append(f"[{citation_number}]")
        cursor = end_idx

    rendered_parts.append(text[cursor:])
    rendered_text = "".join(rendered_parts)
    footnotes = [f"[{idx}] {footnotes_by_number[idx]}" for idx in range(1, next_number)]
    return rendered_text, footnotes


def create_labeling_request_prompt(
    agent_run_text: str,
    citation_instructions: str,
    rubric_text: str,
    rubric_output_schema: dict[str, Any],
    user_model_text: str,
    user_distribution: OutputDistribution,
    priority_score: float | None = None,
    priority_metric_name: str = "H[p_u]",
) -> str:
    """Create prompt for constructing a user-facing labeling request with citations."""
    user_summary = _distribution_summary_for_prompt(user_distribution)
    rubric_schema_text = json.dumps(rubric_output_schema, indent=2, sort_keys=True)
    priority_score_text = f"{priority_score:.6f}" if priority_score is not None else "N/A"

    return f"""You are preparing a human labeling request for an AI agent run.

{citation_instructions}

Background:
We are running an active learning loop to elicit a user's rubric for evaluating agent runs.
- z is the current user model: a summary of the user's known preferences and evaluation criteria.
- p_u(y | x, z, r) is the anticipated user distribution, predicted from z.
- The run is prioritized when p_u indicates high uncertainty, because labeling this case is likely to improve the user model.

Original rubric r (source of truth for what should be evaluated):
{rubric_text}

Rubric output schema (allowed label fields):
{rubric_schema_text}

User model z:
{user_model_text}

Anticipated user distribution p_u(y | x, z, r):
{user_summary}

Run priority score {priority_metric_name}:
{priority_score_text}

Agent run:
{agent_run_text}

Task:
Craft a labeling request that helps the user quickly adjudicate this run.

Other fields:
- title: concise and scannable.
- review_context: brief context and key events with citations.
- priority_rationale: brief p_u-centered explanation of why this run is high-priority to label, with citations.
- review_focus: a checklist of specific rubric-related things to inspect; this field can be more detailed than review_context and priority_rationale, and each item must include a citation.

Scope requirement:
- Stay anchored to rubric r and its output schema.
- Ask only for judgments that map directly to rubric criteria/fields.
- Do not introduce new evaluation dimensions or preferences outside rubric r.

Requirements for priority_rationale (the most important field):
- Basically recap the p_u reasoning

Return JSON:
{{
  "title": "<short title>",
  "review_context": "<succinct context and key events with citations>",
  "priority_rationale": "<p_u-centered uncertainty explanation, grounded in rubric and evidence, with citations>",
  "review_focus": [
    "<specific rubric-related thing to inspect with citation>",
    "<another rubric-related thing to inspect with citation>"
  ]
}}
"""


async def generate_labeling_requests(
    agent_runs: list[AgentRun],
    estimates: list[RunDistributionEstimate],
    rubric: Rubric,
    user_model_text: str,
    llm_svc: BaseLLMService,
    max_requests: int | None = None,
    priority_scores_by_run_id: dict[str, float] | None = None,
    priority_metric_name: str = "H[p_u]",
) -> list[LabelingRequestResult]:
    """Generate user-facing labeling requests for high-priority runs."""
    if not agent_runs or not estimates:
        return []

    runs_by_id = {run.id: run for run in agent_runs}
    viable_estimates = [
        estimate
        for estimate in estimates
        if estimate.error is None and estimate.user_distribution is not None
    ]
    if priority_scores_by_run_id is None:
        ranked_estimates = viable_estimates
    else:
        ranked_estimates = sorted(
            viable_estimates,
            key=lambda estimate: priority_scores_by_run_id.get(
                estimate.agent_run_id, float("-inf")
            ),
            reverse=True,
        )

    if max_requests is not None:
        ranked_estimates = ranked_estimates[:max_requests]

    prompts: list[list[dict[str, str]]] = []
    contexts: list[LLMContext] = []
    estimate_ids: list[str] = []
    for estimate in ranked_estimates:
        run = runs_by_id.get(estimate.agent_run_id)
        if run is None:
            continue
        user_distribution = estimate.user_distribution
        if user_distribution is None:
            continue
        context = LLMContext(items=[run])
        citation_instructions = context.get_system_message(
            interactive=False, include_citations=True
        )
        run_text = context.to_str()
        run_text, _, _ = truncate_to_token_limit(run_text, max_tokens=AGENT_RUN_TOK_LIMIT)

        priority_score = (
            priority_scores_by_run_id.get(estimate.agent_run_id)
            if priority_scores_by_run_id is not None
            else None
        )
        prompt = create_labeling_request_prompt(
            agent_run_text=run_text,
            citation_instructions=citation_instructions,
            rubric_text=rubric.rubric_text,
            rubric_output_schema=rubric.output_schema,
            user_model_text=user_model_text,
            user_distribution=user_distribution,
            priority_score=priority_score,
            priority_metric_name=priority_metric_name,
        )
        prompts.append([{"role": "user", "content": prompt}])
        contexts.append(context)
        estimate_ids.append(estimate.agent_run_id)

    if not prompts:
        return []

    outputs = await llm_svc.get_completions(
        inputs=prompts,
        model_options=[DEFAULT_MODEL_OPTION],
        max_new_tokens=8192,
        temperature=1.0,
        timeout=180.0,
    )

    results: list[LabelingRequestResult] = []
    for agent_run_id, context, output in zip(estimate_ids, contexts, outputs):
        if output.did_error:
            error_msg = "; ".join(str(e) for e in output.errors)
            results.append(
                LabelingRequestResult(
                    agent_run_id=agent_run_id,
                    request=None,
                    error=f"LLM error while generating request: {error_msg}",
                )
            )
            continue

        response_text = output.completions[0].text or ""
        parsed = parse_llm_json_response(
            response_text,
            keys=("title", "priority_rationale", "review_context"),
        )
        if parsed is None:
            results.append(
                LabelingRequestResult(
                    agent_run_id=agent_run_id,
                    request=None,
                    error="Failed to parse labeling request JSON",
                )
            )
            continue

        raw_title = parsed.get("title")
        raw_priority_rationale = parsed.get("priority_rationale")
        raw_review_context = parsed.get("review_context")

        title = raw_title if isinstance(raw_title, str) else "Label this run"
        priority_rationale_text = (
            raw_priority_rationale if isinstance(raw_priority_rationale, str) else ""
        )
        review_context_text = raw_review_context if isinstance(raw_review_context, str) else ""

        priority_rationale, priority_rationale_citations = resolve_citations_with_context(
            priority_rationale_text, context, validate_text_ranges=True
        )
        review_context, review_context_citations = resolve_citations_with_context(
            review_context_text, context, validate_text_ranges=True
        )

        review_focus_items: list[LabelingRequestFocusItem] = []
        raw_focus_raw = parsed.get("review_focus")
        raw_focus: list[object] = []
        if isinstance(raw_focus_raw, list):
            for focus_item in cast(list[object], raw_focus_raw):
                raw_focus.append(focus_item)

        for focus_item_raw in raw_focus:
            if not isinstance(focus_item_raw, str):
                continue
            focus_text, focus_citations = resolve_citations_with_context(
                focus_item_raw, context, validate_text_ranges=True
            )
            review_focus_items.append(
                LabelingRequestFocusItem(text=focus_text, citations=focus_citations)
            )

        request = LabelingRequest(
            agent_run_id=agent_run_id,
            title=title,
            priority_rationale=priority_rationale,
            priority_rationale_citations=priority_rationale_citations,
            review_context=review_context,
            review_context_citations=review_context_citations,
            review_focus=review_focus_items,
        )
        results.append(
            LabelingRequestResult(agent_run_id=agent_run_id, request=request, error=None)
        )

    return results


# === Misc ===


def parse_llm_json_response(response: str, keys: Sequence[str]) -> dict[str, Any] | None:
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```json\s*(\{.*?\})\s*```", response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    for key in keys:
        escaped_key = re.escape(key)
        match = re.search(rf'\{{.*"{escaped_key}".*\}}', response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                continue

    return None


def _stable_json_dict(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _truncate_for_prompt(text: str, max_chars: int = 600) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def _coerce_probability(value: Any) -> float | None:
    prob: float | None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        prob = float(value)
    elif isinstance(value, str):
        try:
            prob = float(value.strip())
        except ValueError:
            return None
    else:
        return None

    if not math.isfinite(prob) or prob < 0:
        return None
    return prob


def normalize_output_distribution(distribution: OutputDistribution) -> OutputDistribution:
    """Normalize probabilities and merge duplicate outcomes by canonical JSON output."""
    if not distribution.outcomes:
        return OutputDistribution(
            point_estimate=distribution.point_estimate,
            reasoning=distribution.reasoning,
            reasoning_citations=list(distribution.reasoning_citations),
        )

    merged: dict[str, DistributionOutcome] = {}
    for outcome in distribution.outcomes:
        key = _stable_json_dict(outcome.output)
        existing = merged.get(key)
        if existing is None:
            merged[key] = DistributionOutcome(
                output=outcome.output,
                probability=max(0.0, outcome.probability),
            )
            continue

        existing.probability += max(0.0, outcome.probability)

    merged_outcomes = list(merged.values())
    if not merged_outcomes:
        return OutputDistribution(
            point_estimate=distribution.point_estimate,
            reasoning=distribution.reasoning,
            reasoning_citations=list(distribution.reasoning_citations),
        )

    total_probability = sum(item.probability for item in merged_outcomes)
    if total_probability <= 0:
        uniform_prob = 1.0 / len(merged_outcomes)
        for item in merged_outcomes:
            item.probability = uniform_prob
    else:
        for item in merged_outcomes:
            item.probability = item.probability / total_probability

    merged_outcomes.sort(key=lambda item: item.probability, reverse=True)

    if distribution.point_estimate:
        best = merged_outcomes[0]
        best.probability = 1.0
        return OutputDistribution(
            outcomes=[best],
            point_estimate=True,
            reasoning=distribution.reasoning,
            reasoning_citations=list(distribution.reasoning_citations),
        )

    return OutputDistribution(
        outcomes=merged_outcomes,
        point_estimate=False,
        reasoning=distribution.reasoning,
        reasoning_citations=list(distribution.reasoning_citations),
    )
