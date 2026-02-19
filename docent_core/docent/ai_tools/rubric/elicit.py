from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel, Field

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


class SubRubricProposal(BaseModel):
    """A proposed sub-rubric extracted from the main rubric."""

    name: str  # Short descriptive name
    description: str  # What this sub-rubric measures
    key_indicators: list[str]  # Specific behaviors/patterns it captures


class DecompositionProposal(BaseModel):
    """A proposed decomposition of the current rubric into sub-rubrics."""

    summary: str  # Overview of why decomposition might help
    proposed_sub_rubrics: list[SubRubricProposal]
    recommendation: str  # Advice on whether to decompose
    confidence: str  # HIGH/MEDIUM/LOW


class ElicitedQuestionOption(BaseModel):
    title: str | None = None
    title_citations: list[InlineCitation] = Field(default_factory=list[InlineCitation])
    description: str | None = None
    description_citations: list[InlineCitation] = Field(default_factory=list[InlineCitation])


class ElicitedQuestion(BaseModel):
    agent_run_id: str | None = None
    quote_title: str | None = None
    framed_question: str | None = None
    framed_question_citations: list[InlineCitation] = Field(default_factory=list[InlineCitation])
    question_context: str | None = None
    question_context_citations: list[InlineCitation] = Field(default_factory=list[InlineCitation])
    example_options: list[ElicitedQuestionOption] = Field(
        default_factory=list[ElicitedQuestionOption]
    )
    error: str | None = None
    # Novelty rating assessed during extraction (HIGH/MEDIUM/LOW)
    novelty_rating: str | None = None
    novelty_rationale: str | None = None
    # Relevance rating assessed during extraction (HIGH/MEDIUM/LOW)
    relevance_rating: str | None = None
    relevance_rationale: str | None = None


class BottleneckExtractionInput(BaseModel):
    """Input for bottleneck extraction (decoupled from CLI-specific types)."""

    question_index: int
    agent_run_id: str | None
    original_question: str
    user_answer: str


class RubricChangeBottleneck(BaseModel):
    """Intermediate representation of extracted change info from a user answer."""

    question_index: int
    agent_run_id: str | None
    original_question: str
    user_answer: str
    change_type: str  # "add_criterion", "clarify_criterion", "add_exception", etc.
    affected_section: str | None
    key_insight: str
    proposed_change: str
    example_from_run: str | None
    confidence: str  # "high", "medium", "low"


class BottleneckExtractionResult(BaseModel):
    """Result of extracting a bottleneck from a single user answer."""

    question_index: int
    bottleneck: RubricChangeBottleneck | None
    error: str | None


class AggregatedRubricResult(BaseModel):
    """Result of aggregating bottlenecks into a final rubric update."""

    updated_rubric: Rubric
    change_summary: str
    bottlenecks_used: list[RubricChangeBottleneck]
    extracted_principles: list[str] | None = None
    error: str | None = None


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
    """Estimated p_j and p_u distributions plus disagreement score for one run."""

    agent_run_id: str
    judge_distribution: OutputDistribution | None = None
    user_distribution: OutputDistribution | None = None
    cross_entropy: float | None = None
    error: str | None = None


class LabelingRequestResult(BaseModel):
    """Best-effort wrapper for labeling request generation."""

    agent_run_id: str
    request: LabelingRequest | None = None
    error: str | None = None


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


def _build_selected_label_payload(labeled_run: "LabeledRun") -> dict[str, Any]:
    user_distribution: dict[str, Any] | None = None
    labeling_request: dict[str, Any] | None = None
    if labeled_run.labeling_request is not None:
        labeling_request = labeled_run.labeling_request.model_dump(mode="json")
    if labeled_run.metadata is not None:
        user_distribution_raw = labeled_run.metadata.get("user_distribution")
        if isinstance(user_distribution_raw, dict):
            user_distribution_dict = cast(dict[str, Any], user_distribution_raw)
            user_distribution = {
                "outcomes": user_distribution_dict.get("outcomes"),
                "reasoning": user_distribution_dict.get("reasoning"),
            }
    return {
        "label_value": labeled_run.label_value,
        "explanation": labeled_run.explanation,
        "labeling_request": labeling_request,
        "metadata": {"user_distribution": user_distribution},
    }


def _format_selected_label_entry(labeled_run: "LabeledRun") -> str:
    payload = _build_selected_label_payload(labeled_run)
    return json.dumps(payload, indent=2, sort_keys=True)


def _format_label_evidence_block(labeled_run: "LabeledRun") -> str:
    label_payload_json = _format_selected_label_entry(labeled_run)
    return (
        "User label evidence fields:\n"
        "- label_value: the user's selected rubric output for this run.\n"
        "- explanation: the user's own rationale for the chosen label, when provided.\n"
        "- labeling_request: the structured labeling request shown when collecting this label.\n"
        "- metadata.user_distribution: the model-estimated p_u distribution shown during labeling, "
        "including only outcomes and reasoning.\n"
        "User label evidence (selected JSON fields):\n"
        f"{label_payload_json}"
    )


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
    label_section = "\n".join(label_lines) if label_lines else "No labels."
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
    label_section = "\n\n".join(label_blocks) if label_blocks else "No label summaries."
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


# === Feedback Question Extraction ===


def create_direct_question_prompt(
    agent_run_text: str,
    rubric_description: str,
    user_model_text: str,
    citation_instructions: str,
    max_questions: int = 3,
) -> str:
    """
    Create prompt for directly extracting questions from an agent run.

    This combines uncertainty identification and question framing into a single step,
    bypassing the aggregation process.

    Args:
        agent_run_text: Text representation of the agent run (with citation markers)
        rubric_description: Description of the rubric to evaluate against
        user_model_text: Current inferred user model text from prior QA/labels
        citation_instructions: Instructions for citing passages from the agent run
        max_questions: Maximum number of questions to extract per run (default: 3)

    Returns:
        Prompt string for the LLM
    """
    return f"""You are helping to refine a rubric for evaluating AI agent behavior by identifying cases where evaluators might disagree and framing them as clear questions.

{citation_instructions}

RUBRIC DESCRIPTION:
{rubric_description}

CURRENT USER MODEL (z):
{user_model_text}

The rubric and user model are not the same thing:
- The rubric is the explicit evaluation policy we are optimizing for.
- The user model is an inferred summary of the user's preferences and judgment tendencies from prior QA/label data.

AGENT RUN TO ANALYZE:
{agent_run_text}

Your task: Identify decision-relevant ambiguities in how THIS run should be judged under the rubric, and frame each as a context + question pair.

QUALITY THRESHOLD - Only include a case if:
- Two reasonable, experienced evaluators could plausibly reach different scores
- The ambiguity is actually triggered by something specific in THIS run (not hypothetical)
- Resolving it would meaningfully change how this run should be judged
- The question is directly about behavior that the rubric is trying to measure in this run

DO NOT include:
- Generic ambiguities that apply to any rubric (e.g., "what counts as 'good'?")
- Definitional nitpicks that wouldn't change practical judgment
- Hypothetical edge cases not actually present in this run
- Cases where the "right" interpretation is obvious from context
- Questions that are orthogonal to rubric-measured behavior in this run

For each case (limit to {max_questions} most important, and it's completely fine to return fewer), provide:
1. A brief title capturing the essence of what this question is about
2. A standalone context summarizing the relevant situation
3. A succinct question asking for the user's judgment
4. Example answer options
5. A novelty rating and rationale (novelty relative to the CURRENT USER MODEL)
6. A relevance rating and rationale (relevance to rubric-measured behavior in this run)

**FORMATTING GUIDANCE**:
- **Title**: A general description of the core ambiguity that could apply to other agent runs. No citations in titles.
- **Context**: Write a self-contained "case study" that someone can read and understand WITHOUT having seen the full agent run. Include specific details about what the agent did, the circumstances, and the outcome. Use citations [T0B5] to reference specific passages.
- **Question**: A SHORT, direct question asking for judgment. Assume the reader just read the context—don't repeat information. Examples:
  - "Should this count as a successful completion?"
  - "Is this response appropriately concise?"
  - "Does this meet the rubric's standard for error handling?"
- **Question relevance**: The question must be answerable by inspecting behavior in this run and must map to a rubric-measured dimension. Do not ask broad preference questions unrelated to this run's judged behavior.

Use bracket notation like [T0B5] or [T0B5:<RANGE>exact text<RANGE>] to cite specific passages. Citations can appear in context and question.

**NOVELTY RATING CRITERIA (relative to CURRENT USER MODEL, not rubric)**:
- **HIGH**: Targets a blind spot or unresolved judgment pattern that is not covered in the current user model
- **MEDIUM**: Partially overlaps with current user-model patterns but adds meaningful new clarification
- **LOW**: Mostly already covered or settled by the current user model

**RELEVANCE RATING CRITERIA (relative to rubric-measured behavior in THIS run)**:
- **HIGH**: Directly tied to behavior the rubric is meant to score in this run; answer would plausibly affect labeling
- **MEDIUM**: Somewhat related to rubric-measured behavior but less central to likely scoring decisions
- **LOW**: Weak or indirect connection to rubric-measured behavior in this run

Output your response as a JSON object:
{{
    "questions": [
        {{
            "title": "A general description of the core ambiguity",
            "context": "A standalone summary of the situation. Include what the agent was asked to do, what it actually did, and the outcome. Use citations. This should be readable as a complete 'case study' without needing the full agent run.",
            "question": "A short question asking for the user's judgment (one sentence).",
            "example_options": [
                {{
                    "title": "Option title",
                    "description": "What this option means"
                }}
            ],
            "novelty_rating": "HIGH|MEDIUM|LOW",
            "novelty_rationale": "Brief explanation of why this rating was assigned",
            "relevance_rating": "HIGH|MEDIUM|LOW",
            "relevance_rationale": "Brief explanation of why this rating was assigned"
        }}
    ]
}}

Focus on quality over quantity. Return an empty list if the rubric is sufficiently clear for judging this run.

**IMPORTANT**: Do NOT invent ambiguities or grasp for marginal edge cases. If the rubric clearly covers this run, return an empty list. Only surface genuine ambiguities where reasonable evaluators would actually disagree—not hypothetical disagreements that are unlikely in practice.
"""


async def extract_questions_from_agent_runs(
    agent_runs: list[AgentRun],
    rubric_description: str,
    user_model_text: str,
    llm_svc: BaseLLMService,
    max_questions_per_run: int = 3,
) -> list[ElicitedQuestion]:
    """
    Extract questions directly from individual agent runs, bypassing aggregation.

    This function combines uncertainty identification and question framing into a single
    step for each agent run. It's an alternative to the 3-step process (identify ->
    aggregate -> frame) that preserves more detail from individual runs.

    Args:
        agent_runs: List of agent runs to analyze
        rubric_description: Description of the rubric to evaluate against
        user_model_text: Current inferred user model text from prior QA/labels
        llm_svc: LLM service for making API calls
        max_questions_per_run: Maximum questions to extract per run (default: 3)

    Returns:
        Flat list of ElicitedQuestion objects from all runs
    """
    logger.info(
        f"Starting direct question extraction for {len(agent_runs)} agent runs "
        f"(max {max_questions_per_run} questions per run)"
    )

    inputs: list[list[dict[str, str]]] = []
    run_metadata: list[dict[str, Any]] = []

    for agent_run in agent_runs:
        context = LLMContext(items=[agent_run])
        citation_instructions = context.get_system_message(
            interactive=False, include_citations=True
        )

        agent_run_text = context.to_str()
        agent_run_text, num_toks, orig_num_toks = truncate_to_token_limit(
            agent_run_text, max_tokens=AGENT_RUN_TOK_LIMIT
        )

        if num_toks < orig_num_toks:
            logger.warning(
                f"Truncated agent run {agent_run.id} for direct extraction: {num_toks} < {orig_num_toks}"
            )

        prompt = create_direct_question_prompt(
            agent_run_text=agent_run_text,
            rubric_description=rubric_description,
            user_model_text=user_model_text,
            citation_instructions=citation_instructions,
            max_questions=max_questions_per_run,
        )

        inputs.append([{"role": "user", "content": prompt}])
        run_metadata.append(
            {
                "agent_run_id": agent_run.id,
                "agent_run": agent_run,
                "was_truncated": num_toks < orig_num_toks,
            }
        )

    logger.info(f"Prepared {len(inputs)} prompts, sending to LLM for direct extraction")
    outputs = await llm_svc.get_completions(
        inputs=inputs,
        model_options=[DEFAULT_MODEL_OPTION],
        max_new_tokens=16384,
        temperature=1.0,
        timeout=180.0,
    )

    results: list[ElicitedQuestion] = []

    for output, metadata in zip(outputs, run_metadata):
        agent_run_id = metadata["agent_run_id"]
        agent_run = metadata["agent_run"]

        if output.did_error:
            error_msg = "; ".join(str(e) for e in output.errors)
            results.append(
                ElicitedQuestion(
                    agent_run_id=agent_run_id,
                    error=f"LLM error: {error_msg}",
                )
            )
            continue

        llm_response = output.completions[0].text
        parsed = parse_llm_json_response(
            llm_response or "", keys=("questions", "question", "ambiguity")
        )

        if not parsed or "questions" not in parsed:
            results.append(
                ElicitedQuestion(
                    agent_run_id=agent_run_id,
                    error="Failed to parse JSON response",
                )
            )
            continue

        questions = parsed["questions"]
        if not questions:
            # No ambiguities found for this run - this is fine
            logger.debug(f"No ambiguities found for agent run {agent_run_id}")
            continue

        # Process each question from this run
        context = LLMContext(items=[agent_run])

        for q in questions:
            if not isinstance(q, dict):
                continue

            q_dict = cast(dict[str, Any], q)

            # Extract title (plain string, no citations)
            raw_title = q_dict.get("title", "")
            quote_title = raw_title if isinstance(raw_title, str) else None

            # Resolve citations in question
            raw_question = q_dict.get("question", "")
            question_text = raw_question if isinstance(raw_question, str) else ""
            framed_question, framed_question_citations = resolve_citations_with_context(
                question_text, context, validate_text_ranges=True
            )

            # Resolve citations in context
            raw_context = q_dict.get("context", "")
            context_text = raw_context if isinstance(raw_context, str) else ""
            question_context, question_context_citations = resolve_citations_with_context(
                context_text, context, validate_text_ranges=True
            )

            # Process example options
            example_options: list[ElicitedQuestionOption] = []
            raw_options: list[Any] = q_dict.get("example_options", []) or []
            for option in raw_options:
                if not isinstance(option, dict):
                    continue
                option_dict = cast(dict[str, Any], option)
                raw_opt_title: Any = option_dict.get("title")
                raw_description: Any = option_dict.get("description")
                opt_title_text = raw_opt_title if isinstance(raw_opt_title, str) else ""
                description_text = raw_description if isinstance(raw_description, str) else ""

                title_cleaned, title_citations = resolve_citations_with_context(
                    opt_title_text, context, validate_text_ranges=True
                )
                description_cleaned, description_citations = resolve_citations_with_context(
                    description_text, context, validate_text_ranges=True
                )

                example_options.append(
                    ElicitedQuestionOption(
                        title=title_cleaned,
                        title_citations=title_citations,
                        description=description_cleaned,
                        description_citations=description_citations,
                    )
                )

            # Extract novelty rating and rationale
            raw_novelty_rating = q_dict.get("novelty_rating")
            novelty_rating = raw_novelty_rating if isinstance(raw_novelty_rating, str) else None
            raw_novelty_rationale = q_dict.get("novelty_rationale")
            novelty_rationale = (
                raw_novelty_rationale if isinstance(raw_novelty_rationale, str) else None
            )
            raw_relevance_rating = q_dict.get("relevance_rating")
            relevance_rating = (
                raw_relevance_rating if isinstance(raw_relevance_rating, str) else None
            )
            raw_relevance_rationale = q_dict.get("relevance_rationale")
            relevance_rationale = (
                raw_relevance_rationale if isinstance(raw_relevance_rationale, str) else None
            )

            results.append(
                ElicitedQuestion(
                    agent_run_id=agent_run_id,
                    quote_title=quote_title,
                    framed_question=framed_question,
                    framed_question_citations=framed_question_citations,
                    question_context=question_context,
                    question_context_citations=question_context_citations,
                    example_options=example_options,
                    novelty_rating=novelty_rating,
                    novelty_rationale=novelty_rationale,
                    relevance_rating=relevance_rating,
                    relevance_rationale=relevance_rationale,
                )
            )

    successful = sum(1 for r in results if r.error is None)
    logger.info(
        f"Direct extraction complete: {successful} questions extracted "
        f"from {len(agent_runs)} runs ({len(results) - successful} errors)"
    )
    return results


# === Question Ranking and Selection ===


def _rating_to_score(rating: str | None) -> int:
    if rating is None:
        return 0
    return {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(rating.strip().upper(), 0)


def _question_relevance_score(question: ElicitedQuestion) -> int:
    return _rating_to_score(question.relevance_rating)


def _question_novelty_score(question: ElicitedQuestion) -> int:
    return _rating_to_score(question.novelty_rating)


def _question_weighted_score(question: ElicitedQuestion) -> int:
    # After Pareto filtering, use relevance-forward weighting for deterministic tie-breaks.
    return 6 * _question_relevance_score(question) + 4 * _question_novelty_score(question)


def _dominates(lhs: ElicitedQuestion, rhs: ElicitedQuestion) -> bool:
    lhs_rel = _question_relevance_score(lhs)
    lhs_nov = _question_novelty_score(lhs)
    rhs_rel = _question_relevance_score(rhs)
    rhs_nov = _question_novelty_score(rhs)
    return (lhs_rel >= rhs_rel and lhs_nov >= rhs_nov) and (lhs_rel > rhs_rel or lhs_nov > rhs_nov)


def _pareto_frontier_ranks(questions: list[ElicitedQuestion]) -> dict[int, int]:
    frontier_ranks: dict[int, int] = {}
    remaining_indices: list[int] = [idx for idx in range(len(questions))]
    frontier_rank = 0

    while remaining_indices:
        frontier_indices: list[int] = []
        for idx in remaining_indices:
            is_dominated = False
            for other_idx in remaining_indices:
                if idx == other_idx:
                    continue
                if _dominates(questions[other_idx], questions[idx]):
                    is_dominated = True
                    break
            if not is_dominated:
                frontier_indices.append(idx)

        for idx in frontier_indices:
            frontier_ranks[idx] = frontier_rank
        frontier_index_set = set(frontier_indices)
        remaining_indices = [idx for idx in remaining_indices if idx not in frontier_index_set]
        frontier_rank += 1

    return frontier_ranks


def sort_questions_by_relevance_novelty_pareto(
    questions: list[ElicitedQuestion],
    max_questions: int | None = None,
) -> list[ElicitedQuestion]:
    """
    Sort questions by Pareto frontier over relevance+novelty, then weighted tie-break.

    Primary ordering:
    1) Pareto frontier rank on (relevance, novelty), where earlier frontiers are better.

    Tie-break ordering within a frontier:
    2) Weighted score = 0.6 * relevance + 0.4 * novelty (higher is better)
    3) Relevance score (higher is better)
    4) Novelty score (higher is better)
    5) Agent run id (lexicographic ascending)
    6) Original input index (ascending) for full determinism

    Args:
        questions: List of ElicitedQuestion objects to sort
        max_questions: Optional limit - if provided, truncate to this many questions

    Returns:
        Sorted (and optionally truncated) list of ElicitedQuestion objects
    """
    frontier_ranks = _pareto_frontier_ranks(questions)
    sorted_pairs = sorted(
        enumerate(questions),
        key=lambda idx_and_q: (
            frontier_ranks.get(idx_and_q[0], 0),
            -_question_weighted_score(idx_and_q[1]),
            -_question_relevance_score(idx_and_q[1]),
            -_question_novelty_score(idx_and_q[1]),
            idx_and_q[1].agent_run_id or "",
            idx_and_q[0],
        ),
    )
    sorted_questions = [question for _, question in sorted_pairs]

    if max_questions is not None:
        return sorted_questions[:max_questions]
    return sorted_questions


def sort_questions_by_novelty(
    questions: list[ElicitedQuestion],
    max_questions: int | None = None,
) -> list[ElicitedQuestion]:
    """
    Backward-compatible wrapper for question pre-sorting.

    Deprecated semantic note:
    This now uses Pareto ranking over relevance+novelty to better prioritize
    rubric-relevant user-model blind spots before deduplication.
    """
    return sort_questions_by_relevance_novelty_pareto(
        questions=questions,
        max_questions=max_questions,
    )


def create_question_deduplication_prompt(
    questions: list[ElicitedQuestion],
    rubric_description: str,
    user_model_text: str,
    max_questions: int,
    max_context_length: int = 500,
) -> str:
    """
    Create prompt for deduplicating and selecting the most diverse/interesting questions.

    Args:
        questions: List of ElicitedQuestion objects to deduplicate
        rubric_description: The rubric text for judging relevance of candidate questions
        user_model_text: Current inferred user model text from prior QA/labels
        max_questions: Maximum number of questions to select (hard limit, not a target)
        max_context_length: Maximum characters of context to include per question

    Returns:
        Prompt string for the LLM
    """
    question_entries: list[str] = []
    has_pre_assessed_novelty = False
    has_pre_assessed_relevance = False

    for i, q in enumerate(questions):
        if q.error:
            continue

        q_id = f"Q{i:03d}"
        framed_question = q.framed_question or "N/A"
        context = q.question_context or ""
        if len(context) > max_context_length:
            context = context[:max_context_length] + "..."

        entry = f"""
--- {q_id} ---
Agent Run ID: {q.agent_run_id}
Context: {context}
Question: {framed_question}"""

        # Include pre-assessed novelty/relevance ratings if available
        if q.novelty_rating:
            has_pre_assessed_novelty = True
            entry += f"\nPre-assessed Novelty: {q.novelty_rating}"
            if q.novelty_rationale:
                entry += f"\nNovelty Rationale: {q.novelty_rationale}"
        if q.relevance_rating:
            has_pre_assessed_relevance = True
            entry += f"\nPre-assessed Relevance: {q.relevance_rating}"
            if q.relevance_rationale:
                entry += f"\nRelevance Rationale: {q.relevance_rationale}"

        entry += "\n"
        question_entries.append(entry)

    questions_str = "\n".join(question_entries)

    # Add note about pre-assessed ratings if any questions have them
    pre_assessed_notes: list[str] = []
    if has_pre_assessed_novelty:
        pre_assessed_notes.append(
            "**Note on Pre-assessed Novelty**: Questions have pre-assessed novelty ratings "
            "(HIGH/MEDIUM/LOW) from the extraction step. These indicate how much each question "
            "addresses a blind spot in the current user model."
        )
    if has_pre_assessed_relevance:
        pre_assessed_notes.append(
            "**Note on Pre-assessed Relevance**: Questions have pre-assessed relevance ratings "
            "(HIGH/MEDIUM/LOW) from the extraction step. These indicate how directly each "
            "question targets rubric-measured behavior in the run."
        )
    pre_assessed_note = "\n".join(pre_assessed_notes)

    return f"""You are selecting questions to ask a user to clarify their rubric for evaluating AI agents.

CURRENT RUBRIC:
{rubric_description}

CURRENT USER MODEL (z):
{user_model_text}

The rubric and user model are not the same thing:
- The rubric is the explicit evaluation policy we are optimizing for.
- The user model summarizes observed judgment tendencies and preferences inferred from prior QA/label data.
- Use the user model to avoid asking questions that are already well-settled, and to prioritize unresolved judgment patterns.

Below are {len(question_entries)} candidate questions extracted from agent run analysis.
{pre_assessed_note}
CANDIDATE QUESTIONS:
{questions_str}

## Your Task

Select a set of questions that is **MECE** (Mutually Exclusive, Collectively Exhaustive):

### 1. Mutually Exclusive (Deduplication)

**No two selected questions should address the same underlying ambiguity.**

- If multiple questions ask about the same issue (even if framed differently), select only the single best representative
- Questions are duplicates if resolving one would effectively resolve the other
- Err on the side of fewer, distinct questions over more overlapping ones

### 2. Collectively Exhaustive (Coverage)

**Don't omit high-value questions that address distinct unresolved judgment needs.**

- Ensure the selected set covers the range of distinct ambiguities identified
- Prefer breadth (covering different aspects of the rubric behavior) over depth (multiple questions about one aspect)
- HIGH novelty questions (user-model blind spots) and HIGH relevance questions (rubric-aligned behavior) should generally be included unless they duplicate another selected question

### 3. Prioritization

When choosing between non-duplicate questions:

1. **Pareto priority on relevance + novelty**: Prefer questions on the Pareto frontier of:
   - Relevance to rubric-measured behavior in this run (HIGH > MEDIUM > LOW)
   - Novelty relative to the current user model (HIGH > MEDIUM > LOW)
2. **Tie-break after Pareto**: If too many frontier questions remain, prioritize by weighted score:
   - 60% relevance + 40% novelty
3. **Low-relevance handling**: LOW relevance questions are allowed but should be strongly deprioritized unless needed for coverage
4. **Impact**: Prefer questions where different answers would meaningfully change how runs are scored
5. **Dependency-aware sequencing**: If one question is a prerequisite for another, place the prerequisite first in the final selected list
6. **General-before-specific ordering**: Place broad clarification questions before object-level/specific follow-up questions that depend on them

### 4. Ordering Rules

- Treat the order of selected questions as the recommended ask order
- If Question B depends on the answer to Question A, Question A should come first
- Do not keep duplicates just to preserve an order chain; MECE deduplication still takes priority

## Constraints

**Maximum questions: {max_questions}**

This is a hard ceiling, not a target. Return fewer questions if:
- There aren't {max_questions} distinct ambiguities
- Lower-priority questions would be duplicative or low-impact
- The rubric is already clear on most points

It is completely acceptable—even expected—to return significantly fewer than {max_questions} questions.

## Output Format

Output as JSON:
{{
    "selected_questions": [
        {{
            "question_id": "Q003",
            "selection_rationale": "Brief explanation of why this was selected and what distinct ambiguity it addresses"
        }}
    ]
}}

Return `selected_questions` in the recommended ask order (dependency-aware: prerequisite/general clarifications first, then dependent/object-level questions).
"""


async def deduplicate_and_select_questions(
    questions: list[ElicitedQuestion],
    llm_svc: BaseLLMService,
    rubric_description: str,
    user_model_text: str,
    max_questions: int,
) -> tuple[list[ElicitedQuestion], dict[str, Any]]:
    """
    Deduplicate and select the most diverse/interesting questions from a list.

    This function takes all extracted questions and uses an LLM to select the most
    valuable questions based on relevance, user-model novelty, impact,
    concreteness, diversity, and coverage criteria.

    Args:
        questions: List of ElicitedQuestion objects to deduplicate
        llm_svc: LLM service for making API calls
        rubric_description: The rubric text to evaluate question relevance against
        user_model_text: Current inferred user model text from prior QA/labels
        max_questions: Maximum number of questions to select.
            This is a hard upper limit, not a target - the LLM may return fewer
            based on quality (prioritizing Pareto-strong relevance/novelty questions).

    Returns:
        Tuple of:
        - Filtered list of ElicitedQuestion objects (selected questions)
        - Metadata dict with keys:
            - selected_ids: list of question IDs that were selected
            - rationales: dict mapping question_id to selection_rationale
            - error: error message if any, None otherwise

    Edge cases handled:
    - Empty input → returns empty list with appropriate metadata
    - All questions have errors → returns empty list
    - Fewer valid questions than max_questions → returns all valid questions (no LLM call)
    - LLM error → fallback to first max_questions valid questions
    - JSON parse failure → fallback to first max_questions valid questions
    """
    logger.info(
        f"Starting question deduplication: {len(questions)} input questions, "
        f"max_questions={max_questions}"
    )

    # Initialize metadata
    metadata: dict[str, Any] = {
        "selected_ids": [],
        "rationales": {},
        "error": None,
    }

    # Edge case: empty input
    if not questions:
        logger.info("No questions to deduplicate")
        return [], metadata

    # Filter out questions with errors
    valid_questions = [q for q in questions if q.error is None]
    logger.info(f"Valid questions (no errors): {len(valid_questions)}/{len(questions)}")

    # Edge case: all questions have errors
    if not valid_questions:
        logger.info("All questions have errors, returning empty list")
        metadata["error"] = "All input questions had errors"
        return [], metadata

    # Edge case: fewer valid questions than max_questions - return all valid questions
    if len(valid_questions) <= max_questions:
        logger.info(
            f"Only {len(valid_questions)} valid questions, returning all (no deduplication needed)"
        )
        # Build metadata for this case
        for i, q in enumerate(questions):
            if q.error is None:
                q_id = f"Q{i:03d}"
                metadata["selected_ids"].append(q_id)
                metadata["rationales"][q_id] = "Selected (fewer candidates than max_questions)"
        return valid_questions, metadata

    # Create prompt and call LLM
    prompt = create_question_deduplication_prompt(
        questions,
        rubric_description=rubric_description,
        user_model_text=user_model_text,
        max_questions=max_questions,
    )

    outputs = await llm_svc.get_completions(
        inputs=[[{"role": "user", "content": prompt}]],
        model_options=[DEFAULT_MODEL_OPTION],
        max_new_tokens=8192,
        temperature=1.0,
        timeout=180.0,
    )

    output = outputs[0]

    # Handle LLM error - fallback to first max_questions valid questions
    if output.did_error:
        error_msg = "; ".join(str(e) for e in output.errors)
        logger.warning(
            f"LLM error during deduplication, falling back to first {max_questions}: {error_msg}"
        )
        metadata["error"] = f"LLM error (fallback used): {error_msg}"

        # Fallback: return first max_questions valid questions
        fallback_questions = valid_questions[:max_questions]
        for i, q in enumerate(questions):
            if q.error is None and q in fallback_questions:
                q_id = f"Q{i:03d}"
                metadata["selected_ids"].append(q_id)
                metadata["rationales"][q_id] = "Fallback selection (LLM error)"

        return fallback_questions, metadata

    # Parse LLM response
    llm_response = output.completions[0].text
    parsed = parse_llm_json_response(llm_response or "", keys=("selected_questions",))

    # Handle JSON parse failure - fallback to first max_questions valid questions
    if not parsed or "selected_questions" not in parsed:
        logger.warning(
            f"Failed to parse deduplication response, falling back to first {max_questions}"
        )
        metadata["error"] = "JSON parse error (fallback used)"

        # Fallback: return first max_questions valid questions
        fallback_questions = valid_questions[:max_questions]
        for i, q in enumerate(questions):
            if q.error is None and q in fallback_questions:
                q_id = f"Q{i:03d}"
                metadata["selected_ids"].append(q_id)
                metadata["rationales"][q_id] = "Fallback selection (JSON parse error)"

        return fallback_questions, metadata

    # Process successful response
    selected_questions_data = parsed["selected_questions"]

    # Build index mapping from Q### IDs to question indices
    selected_indices: list[int] = []
    for item in selected_questions_data:
        q_id = item.get("question_id", "")
        if q_id.startswith("Q") and q_id[1:].isdigit():
            idx = int(q_id[1:])
            if 0 <= idx < len(questions) and questions[idx].error is None:
                selected_indices.append(idx)
                metadata["selected_ids"].append(q_id)
                metadata["rationales"][q_id] = item.get("selection_rationale", "")

    # Build the result list preserving order from LLM
    selected_questions = [questions[idx] for idx in selected_indices]

    logger.info(
        f"Deduplication complete: selected {len(selected_questions)} questions from {len(valid_questions)} valid candidates"
    )

    return selected_questions, metadata


# === User Model Update ===


def create_user_model_update_prompt(
    user_data: "UserData",
    current_model_text: str,
) -> str:
    """Create prompt for updating the user model based on collected feedback."""
    # Format new QA pairs in rich block format
    qa_entries: list[str] = []
    for i, qa in enumerate(user_data.qa_pairs, 1):
        entry = (
            f"--- New feedback {i} (run: {qa.agent_run_id or 'unknown'}) ---\n"
            f"Situation: {_truncate_for_prompt(qa.question_context or 'N/A', 1200)}\n"
            f"Question asked: {_truncate_for_prompt(qa.question, 600)}\n"
            f"User's answer: {_truncate_for_prompt(qa.answer, 600)}\n"
            f"Custom response: {'Yes' if qa.is_custom_response else 'No'}"
        )
        qa_entries.append(entry)

    qa_section = "\n\n".join(qa_entries) if qa_entries else "No new feedback."

    return f"""You are updating a user model that is structured as a **curated collection of richly annotated examples**. The model is used downstream by an LLM that reasons by analogy from these examples.

INITIAL RUBRIC:
{user_data.initial_rubric}

CURRENT USER MODEL (example-based):
{current_model_text}

NEW FEEDBACK TO INCORPORATE:
{qa_section}

Your task: Update the user model by **accumulating examples**. Follow these rules:

1. **Preserve all existing examples** from the current user model. Do NOT remove, summarize, or abstract away existing examples unless consolidating per rule 5.
2. **Start the updated model with this section**:

### User Intent Snapshot
- [2-4 concise bullets summarizing what the user generally looks for]

Keep this section brief and grounded in the examples. Capture stable preferences and important conditional tendencies (e.g., "values X especially when Y is present").

3. **Add new feedback as new annotated examples** using this format:

### Example N: [short descriptive title]
**Situation:** [Rich description of the context — what the agent did, what the task was, what happened. Preserve concrete details from the feedback above.]
**Question:** [The question that was asked]
**User's judgment:** [The user's full answer]
**What this reveals:** [1-2 concrete sentences about what this specific case tells us. Stay grounded in this example.]

4. **Number new examples** continuing from the highest existing example number.
5. **If new feedback contradicts an existing example**, keep BOTH examples and add a note in "What this reveals" for each, e.g. "Note: this appears to conflict with Example 3 — the user may weigh X differently when Y is present."
6. **If the model exceeds ~25 examples**, consolidate the least informative ones (those that are near-duplicates or add little new signal). Prefer keeping examples that show edge cases, contradictions, or strong preferences.
7. **Update the "Connecting patterns" section** at the end — keep it brief (2-4 bullets citing example numbers). This section should be ~20% of the output at most. Use this section to connect specific examples; do not use it to replace the top-level intent snapshot.

CRITICAL: The annotated examples ARE the core of the user model. Do NOT replace them with abstract principles or summaries. The downstream LLM needs rich, concrete cases to reason from by analogy.

Output your response in this format:
<user_model>
[Your updated example-based user model in markdown]
</user_model>
"""


async def update_user_model(
    user_data: "UserData",
    current_model_text: str,
    llm_svc: BaseLLMService,
) -> str:
    """
    Update the user model based on collected feedback.

    Args:
        user_data: The UserData containing initial rubric and QA pairs
        current_model_text: The current user model text
        llm_svc: LLM service for API calls

    Returns:
        Updated user model text (markdown string)
    """
    # Skip if no new QA pairs
    if not user_data.qa_pairs:
        return current_model_text

    prompt = create_user_model_update_prompt(user_data, current_model_text)

    outputs = await llm_svc.get_completions(
        inputs=[[{"role": "user", "content": prompt}]],
        model_options=[DEFAULT_MODEL_OPTION],
        max_new_tokens=16384,
        timeout=120.0,
    )

    output = outputs[0]

    if output.did_error:
        logger.warning(f"Failed to update user model: {output.errors}")
        return current_model_text

    llm_response = output.completions[0].text or ""

    # Parse user_model tag
    match = re.search(r"<user_model>(.*?)</user_model>", llm_response, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Fallback: return the whole response if no tags
    return llm_response.strip() or current_model_text


# === Label Distribution Estimation and Scoring ===


def create_judge_distribution_prompt(
    agent_run_text: str,
    rubric_text: str,
    output_schema: dict[str, Any],
    citation_instructions: str,
    point_estimate: bool = True,
) -> str:
    """Create prompt for p_j(y | x, r)."""
    point_estimate_instruction = (
        "Use a point estimate: return exactly one outcome with probability 1.0."
        if point_estimate
        else "Return a probability distribution over plausible outcomes."
    )

    schema_text = json.dumps(output_schema, indent=2)
    return f"""You are an LLM judge estimating p_j(y | x, r).

{citation_instructions}

Rubric:
{rubric_text}

Output schema:
{schema_text}

Agent run:
{agent_run_text}

Task:
1. Predict rubric-compliant output(s) for this run.
2. Provide probabilities and one concise holistic rationale for the distribution.
3. {point_estimate_instruction}

Return JSON:
{{
  "reasoning": "<brief rationale with optional citations>",
  "outcomes": [
    {{
      "output": <json object compliant with schema>,
      "probability": <float>
    }}
  ]
}}
"""


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

    overall_reasoning_text = parsed.get("reasoning")
    if not isinstance(overall_reasoning_text, str):
        overall_reasoning_text = parsed.get("explanation")
    overall_reasoning = overall_reasoning_text if isinstance(overall_reasoning_text, str) else None

    raw_outcomes: list[Any] | None = None
    if isinstance(parsed.get("outcomes"), list):
        raw_outcomes = cast(list[Any], parsed["outcomes"])
    elif isinstance(parsed.get("distribution"), list):
        raw_outcomes = cast(list[Any], parsed["distribution"])
    elif isinstance(parsed.get("output"), dict):
        raw_outcomes = [parsed]

    if raw_outcomes is None:
        return None

    extracted_outputs: list[dict[str, Any]] = []
    extracted_probs: list[float | None] = []
    outcome_reasoning: list[str] = []

    for raw in raw_outcomes:
        if not isinstance(raw, dict):
            continue
        raw_dict = cast(dict[str, Any], raw)
        raw_output = raw_dict.get("output")
        if not isinstance(raw_output, dict):
            continue

        if overall_reasoning is None:
            outcome_reasoning_text = raw_dict.get("reasoning")
            if not isinstance(outcome_reasoning_text, str):
                outcome_reasoning_text = raw_dict.get("explanation")
            if isinstance(outcome_reasoning_text, str) and outcome_reasoning_text.strip():
                outcome_reasoning.append(outcome_reasoning_text.strip())

        extracted_outputs.append(cast(dict[str, Any], raw_output))
        extracted_probs.append(_coerce_probability(raw_dict.get("probability")))

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
        concrete_probs = [cast(float, prob) for prob in extracted_probs]
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


async def estimate_label_distributions_for_agent_runs(
    agent_runs: list[AgentRun],
    rubric: Rubric,
    user_model_text: str,
    llm_svc: BaseLLMService,
    judge_point_estimate: bool = True,
    cross_entropy_epsilon: float = 1e-2,
) -> list[RunDistributionEstimate]:
    """
    Estimate p_j and p_u for each run and score disagreement by H[p_u, p_j].

    Both p_j and p_u are computed in parallel using batched LLM calls.
    """
    if not agent_runs:
        return []
    agreement_keys = _get_entropy_agreement_keys(rubric.output_schema)

    judge_inputs: list[list[dict[str, str]]] = []
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

        judge_prompt = create_judge_distribution_prompt(
            agent_run_text=agent_run_text,
            rubric_text=rubric.rubric_text,
            output_schema=rubric.output_schema,
            citation_instructions=citation_instructions,
            point_estimate=judge_point_estimate,
        )

        judge_inputs.append([{"role": "user", "content": judge_prompt}])
        run_metadata.append((agent_run.id, context))

    judge_task = llm_svc.get_completions(
        inputs=judge_inputs,
        model_options=[DEFAULT_MODEL_OPTION],
        max_new_tokens=8192,
        temperature=1.0,
        timeout=180.0,
    )
    user_task = estimate_user_distributions_for_agent_runs(
        agent_runs=agent_runs,
        rubric=rubric,
        user_model_text=user_model_text,
        llm_svc=llm_svc,
    )

    judge_outputs, user_estimates = await asyncio.gather(judge_task, user_task)
    results: list[RunDistributionEstimate] = []

    for (agent_run_id, context), judge_output, user_estimate in zip(
        run_metadata, judge_outputs, user_estimates
    ):
        if judge_output.did_error:
            error_msg = "; ".join(str(e) for e in judge_output.errors)
            results.append(
                RunDistributionEstimate(
                    agent_run_id=agent_run_id,
                    error=f"Judge distribution error: {error_msg}",
                )
            )
            continue
        if user_estimate.error is not None or user_estimate.user_distribution is None:
            results.append(
                RunDistributionEstimate(
                    agent_run_id=agent_run_id,
                    error=user_estimate.error or "Failed to parse user distribution response",
                )
            )
            continue

        judge_text = judge_output.completions[0].text or ""
        judge_distribution = parse_output_distribution_response(
            judge_text, context=context, point_estimate=judge_point_estimate
        )
        user_distribution = user_estimate.user_distribution

        if judge_distribution is None:
            results.append(
                RunDistributionEstimate(
                    agent_run_id=agent_run_id,
                    error="Failed to parse judge distribution response",
                )
            )
            continue

        cross_entropy = compute_cross_entropy(
            user_distribution,
            judge_distribution,
            epsilon=cross_entropy_epsilon,
            agreement_keys=agreement_keys,
        )
        results.append(
            RunDistributionEstimate(
                agent_run_id=agent_run_id,
                judge_distribution=judge_distribution,
                user_distribution=user_distribution,
                cross_entropy=cross_entropy,
                error=None,
            )
        )

    valid_estimates = [
        estimate
        for estimate in results
        if estimate.error is None
        and estimate.cross_entropy is not None
        and estimate.judge_distribution is not None
        and estimate.user_distribution is not None
    ]
    logger.info(
        "Finished sampled run distribution estimates: %d total, %d valid.",
        len(results),
        len(valid_estimates),
    )

    return results


def _project_output_for_entropy(output: dict[str, Any], agreement_keys: set[str]) -> dict[str, Any]:
    """Keep only entropy-scoring fields (enum/boolean agreement keys)."""
    return {key: output[key] for key in agreement_keys if key in output}


def _normalize_output_distribution_for_entropy(
    distribution: OutputDistribution,
    agreement_keys: set[str],
) -> OutputDistribution:
    """Normalize probabilities after projecting outcomes to entropy-scoring fields."""
    projected_outcomes = [
        DistributionOutcome(
            output=_project_output_for_entropy(outcome.output, agreement_keys),
            probability=outcome.probability,
        )
        for outcome in distribution.outcomes
    ]
    return normalize_output_distribution(
        OutputDistribution(
            outcomes=projected_outcomes,
            point_estimate=distribution.point_estimate,
            reasoning=distribution.reasoning,
            reasoning_citations=list(distribution.reasoning_citations),
        )
    )


def get_enum_boolean_fields_from_schema(
    output_schema: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Extract top-level enum/boolean fields with option metadata from a JSON schema."""
    properties_raw = output_schema.get("properties")
    if not isinstance(properties_raw, dict):
        return {}
    properties = cast(dict[object, object], properties_raw)

    fields: dict[str, dict[str, Any]] = {}
    for key_obj, field_schema_obj in properties.items():
        if not isinstance(key_obj, str) or not isinstance(field_schema_obj, dict):
            continue

        key = key_obj
        field_schema = cast(dict[str, Any], field_schema_obj)
        field_type = field_schema.get("type")

        if isinstance(field_type, str) and field_type == "boolean":
            fields[key] = {"type": "boolean", "options": [True, False]}
            continue

        enum_values = field_schema.get("enum")
        if isinstance(enum_values, list):
            fields[key] = {"type": "enum", "options": enum_values}

    return fields


def _get_entropy_agreement_keys(output_schema: dict[str, Any]) -> list[str]:
    """Top-level schema keys used for entropy scoring (enum or boolean fields)."""
    return list(get_enum_boolean_fields_from_schema(output_schema).keys())


def compute_cross_entropy(
    p_true: OutputDistribution,
    p_pred: OutputDistribution,
    epsilon: float = 1e-2,
    agreement_keys: list[str] | None = None,
) -> float:
    """
    Compute cross-entropy H[p_true, p_pred] with epsilon smoothing.

    Inputs are normalized internally. Missing support in p_pred receives epsilon mass.
    """
    scoring_keys: set[str] | None = set(agreement_keys) if agreement_keys is not None else None
    if scoring_keys is not None:
        if not scoring_keys:
            return 0.0
        p_norm = _normalize_output_distribution_for_entropy(p_true, scoring_keys)
        q_norm = _normalize_output_distribution_for_entropy(p_pred, scoring_keys)
    else:
        p_norm = normalize_output_distribution(p_true)
        q_norm = normalize_output_distribution(p_pred)

    if not p_norm.outcomes or not q_norm.outcomes:
        return float("inf")

    p_map = {_stable_json_dict(item.output): item.probability for item in p_norm.outcomes}
    q_map = {_stable_json_dict(item.output): item.probability for item in q_norm.outcomes}
    support = set(p_map.keys()) | set(q_map.keys())
    if not support:
        return 0.0 if scoring_keys is not None else float("inf")

    q_smoothed: dict[str, float] = {}
    for key in support:
        q_smoothed[key] = q_map.get(key, 0.0) + epsilon

    q_total = sum(q_smoothed.values())
    if q_total <= 0:
        return float("inf")

    cross_entropy = 0.0
    for key, p_prob in p_map.items():
        if p_prob <= 0:
            continue
        q_prob = q_smoothed.get(key, epsilon) / q_total
        cross_entropy += -p_prob * math.log(max(q_prob, epsilon))

    return cross_entropy


def sort_runs_by_cross_entropy(
    estimates: list[RunDistributionEstimate],
) -> list[RunDistributionEstimate]:
    """Sort descending by H[p_u, p_j], placing errored entries last."""
    valid_estimates = [e for e in estimates if e.error is None and e.cross_entropy is not None]
    invalid_estimates = [e for e in estimates if e.error is not None or e.cross_entropy is None]

    sorted_valid = sorted(valid_estimates, key=lambda e: cast(float, e.cross_entropy), reverse=True)
    return sorted_valid + invalid_estimates


# === Labeling Request Generation ===


def _distribution_summary_for_prompt(
    distribution: OutputDistribution,
    max_outcomes: int = 5,
) -> str:
    normalized = normalize_output_distribution(distribution)
    payload_outcomes: list[dict[str, Any]] = []
    for outcome in normalized.outcomes[:max_outcomes]:
        payload_outcomes.append(
            {
                "output": outcome.output,
                "probability": round(outcome.probability, 6),
            }
        )
    payload: dict[str, Any] = {
        "reasoning": _truncate_for_prompt(normalized.reasoning or "", 220),
        "outcomes": payload_outcomes,
    }
    return json.dumps(payload, indent=2)


def create_labeling_request_prompt(
    agent_run_text: str,
    citation_instructions: str,
    user_model_text: str,
    user_distribution: OutputDistribution,
    priority_score: float | None = None,
    priority_metric_name: str = "H[p_u]",
) -> str:
    """Create prompt for constructing a user-facing labeling request with citations."""
    user_summary = _distribution_summary_for_prompt(user_distribution)
    priority_score_text = f"{priority_score:.6f}" if priority_score is not None else "N/A"

    return f"""You are preparing a human labeling request for an AI agent run.

{citation_instructions}

Background:
We are running an active learning loop to elicit a user's rubric for evaluating agent runs.
- z is the current user model: a summary of the user's known preferences and evaluation criteria.
- p_u(y | x, z, r) is the anticipated user distribution, predicted from z.
- The run is prioritized when p_u indicates high uncertainty, because labeling this case is likely to improve the user model.

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
- priority_rationale: brief user-model-grounded explanation of why this run is high-priority to label, with citations.
- review_focus: a checklist of specific things to inspect; this field can be more detailed than review_context and priority_rationale, and each item must include a citation.

Requirements for priority_rationale (the most important field):
- Quote or paraphrase the specific part of user model z that drives uncertainty.
- State what p_u predicts the user would say, grounded in z.
- Explicitly surface the central uncertainty crux from p_u (for example, two plausible outcomes and why both are plausible).
- If p_u includes a reasoning explanation, use it to explain why this run is high priority to adjudicate.
- Keep it concise and focused on the uncertainty.
- Include citations to relevant run evidence.
- Do not restate the full run chronology here.

Return JSON:
{{
  "title": "<short title>",
  "review_context": "<succinct context and key events with citations>",
  "priority_rationale": "<user-model-grounded explanation of the disagreement, with citations>",
  "review_focus": [
    "<specific thing to inspect with citation>",
    "<another thing to inspect with citation>"
  ]
}}
"""


async def generate_labeling_requests(
    agent_runs: list[AgentRun],
    estimates: list[RunDistributionEstimate],
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
            user_model_text=user_model_text,
            user_distribution=cast(OutputDistribution, estimate.user_distribution),
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
        raw_focus = parsed.get("review_focus")
        if isinstance(raw_focus, list):
            for focus_item in cast(list[Any], raw_focus):
                if not isinstance(focus_item, str):
                    continue
                focus_text, focus_citations = resolve_citations_with_context(
                    focus_item, context, validate_text_ranges=True
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


def create_decomposition_analysis_prompt(
    user_data: "UserData",
    current_model_text: str,
    previous_proposal: DecompositionProposal | None = None,
    user_feedback: str | None = None,
) -> str:
    """Create prompt for analyzing potential rubric decomposition into sub-rubrics."""
    # Format QA pairs with context
    qa_entries: list[str] = []
    for i, qa in enumerate(user_data.qa_pairs, 1):
        entry = f"""
--- Feedback {i} ---
Agent Run ID: {qa.agent_run_id}
Question Context: {qa.question_context or "N/A"}
Question: {qa.question}
User's Answer: {qa.answer}
Custom Response: {"Yes" if qa.is_custom_response else "No"}
"""
        qa_entries.append(entry)

    qa_section = "\n".join(qa_entries) if qa_entries else "No feedback collected yet."
    n_qa_pairs = len(user_data.qa_pairs)

    prompt = f"""You are analyzing whether a rubric for evaluating AI agents should be split into multiple sub-rubrics.

INITIAL RUBRIC:
{user_data.initial_rubric}

CURRENT USER MODEL (after {n_qa_pairs} rounds of feedback):
{current_model_text}

COLLECTED FEEDBACK ({n_qa_pairs} QA pairs):
{qa_section}

## Your Task

Analyze whether the user's feedback reveals DISTINCT evaluation dimensions that would be better served by separate rubrics.

Look for evidence of:
1. **Conflated Concepts**: Does the user's feedback address fundamentally different concerns that happen to be lumped together?
2. **Tension in Priorities**: Do some answers suggest competing values that are hard to balance in a single rubric?
3. **Distinct Measurement Axes**: Are there behaviors that should be evaluated independently rather than as part of one score?

## Important Guidelines

- **Ground every observation in specific QA pairs**: Reference actual feedback, not hypotheticals
- **Always provide suggestions**: You MUST propose at least one sub-rubric decomposition, even if you believe the current rubric is already well-structured
- **Focus on practical utility**: Would separate rubrics actually help measurement?
- **Use confidence to indicate benefit**: Use HIGH confidence when decomposition would clearly improve measurement, MEDIUM when it would provide modest benefits, and LOW when the rubric is already fairly coherent but decomposition could still offer minor improvements

## Output Format

Output your response as a JSON object:
{{
    "summary": "1-2 sentence overview of your analysis and whether decomposition would help",
    "proposed_sub_rubrics": [
        {{
            "name": "Short descriptive name for this sub-rubric",
            "description": "What this sub-rubric would measure",
            "key_indicators": [
                "Specific behavior or pattern this sub-rubric would capture",
                "Another indicator"
            ]
        }}
    ],
    "recommendation": "Clear advice on whether to decompose this rubric, and why",
    "confidence": "HIGH|MEDIUM|LOW"
}}

You MUST always propose at least one sub-rubric. If the current rubric is coherent, propose the most reasonable decomposition anyway and explain in the recommendation that while the rubric is fairly well-structured, this decomposition could offer specific benefits.
"""

    # Add feedback section if previous proposal and user feedback are provided
    if previous_proposal and user_feedback:
        feedback_section = f"""

## Previous Proposal

You previously proposed the following decomposition:
{previous_proposal.model_dump_json(indent=2)}

## User Feedback

The user provided the following feedback on your proposal:
{user_feedback}

Please revise your decomposition based on this feedback. The user may be:
- Asking for different sub-rubric boundaries
- Requesting more/fewer sub-rubrics
- Pointing out that certain aspects were missed
- Clarifying their priorities
"""
        return prompt + feedback_section

    return prompt


async def analyze_rubric_decomposition(
    user_data: "UserData",
    current_model_text: str,
    llm_svc: BaseLLMService,
    previous_proposal: DecompositionProposal | None = None,
    user_feedback: str | None = None,
) -> DecompositionProposal | None:
    """
    Analyze whether the current rubric should be decomposed into sub-rubrics.

    This function examines the collected QA pairs and current user model to identify
    whether the user's feedback reveals distinct evaluation dimensions that would be
    better served by separate rubrics.

    Args:
        user_data: The UserData containing initial rubric and QA pairs
        current_model_text: The current user model text
        llm_svc: LLM service for API calls
        previous_proposal: Optional previous decomposition proposal for refinement
        user_feedback: Optional user feedback on the previous proposal

    Returns:
        DecompositionProposal if analysis succeeds, None on error
    """
    # Skip if no QA pairs
    if not user_data.qa_pairs:
        logger.info("Skipping decomposition analysis: no QA pairs collected")
        return None

    prompt = create_decomposition_analysis_prompt(
        user_data,
        current_model_text,
        previous_proposal=previous_proposal,
        user_feedback=user_feedback,
    )

    outputs = await llm_svc.get_completions(
        inputs=[[{"role": "user", "content": prompt}]],
        model_options=[DEFAULT_MODEL_OPTION],
        max_new_tokens=16384,
        timeout=120.0,
    )

    output = outputs[0]

    if output.did_error:
        logger.warning(f"Failed to analyze rubric decomposition: {output.errors}")
        return None

    llm_response = output.completions[0].text or ""

    # Parse JSON response
    parsed = parse_llm_json_response(llm_response, keys=("summary", "proposed_sub_rubrics"))

    if not parsed:
        logger.warning("Failed to parse decomposition analysis JSON response")
        return None

    try:
        # Parse sub-rubrics
        sub_rubrics: list[SubRubricProposal] = []
        raw_sub_rubrics: list[Any] = parsed.get("proposed_sub_rubrics", [])
        for sr in raw_sub_rubrics:
            if isinstance(sr, dict):
                sr_dict = cast(dict[str, Any], sr)
                sub_rubrics.append(
                    SubRubricProposal(
                        name=str(sr_dict.get("name", "")),
                        description=str(sr_dict.get("description", "")),
                        key_indicators=list(sr_dict.get("key_indicators", [])),
                    )
                )

        return DecompositionProposal(
            summary=parsed.get("summary", ""),
            proposed_sub_rubrics=sub_rubrics,
            recommendation=parsed.get("recommendation", ""),
            confidence=parsed.get("confidence", "LOW"),
        )
    except Exception as e:
        logger.warning(f"Failed to create DecompositionProposal: {e}")
        return None
