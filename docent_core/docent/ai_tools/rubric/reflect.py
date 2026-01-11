import re
from enum import Enum
from typing import Any, Iterator
from uuid import uuid4

import yaml
from pydantic import BaseModel, Field

from docent._log_util import get_logger
from docent.judges import Rubric
from docent_core.docent.services.llms import PROVIDER_PREFERENCES, LLMService

logger = get_logger(__name__)

NO_LABEL_REFLECTION_SYSTEM_PROMPT = """
We are analyzing a transcript of an AI agent run according to a rubric.
One or more AI judges has evaluated the transcript.

Your job is to summarize each of the judge results in a sentence or two each, focusing on disagreements between the judges.

If two or more results are so similar that there are no differences worth mentioning, you can write a single summary to cover all of them. For example, if results 2 and 3 are similar, you might write:
<summary 1>
Judge decides behavior matches the rubric because [...]
</summary>
<summary 2 3>
Judge decides behavior matches the rubric because [...]
</summary>

When writing a summary about multiple results, do not discuss differences between the results. If there are differences worth mentioning, write separate summaries instead.

Important: each summary block must list all the indices of the results that it covers, individually, separated by spaces like above.

You must be careful not to infer things about a judge's reasoning that are not explicitly stated in its output.

Your summaries must be concise. For brevity:
* Do not repeat the labels assigned by the judges; the user can already see those. Focus on summarizing the explanations.

Your output should include as many <summary> blocks you need to summarize all the AI results. Do not write anything outside the <summary> blocks.
"""

LABEL_REFLECTION_SYSTEM_PROMPT = """
We are analyzing a transcript of an AI agent run according to a rubric.
One or more AI judges has evaluated the transcript. A human labeler has also evaluated the transcript.

Your job is to identify issues with the AI judge results, based on the human result.

You should begin each report with a keyword that classifies the type of issue. These are the types of issues we are interested in. Go down the list and choose the first classification that applies. Each issue should have exactly one classification.
- ai_miss - the human result states that a specific behavior matches the rubric, whereas the AI result fails to mention or address that behavior. If a behavior is missed by an AI judge, it is not also a false negative.
- false_negative - the AI result states that a specific behavior does not match the rubric, whereas the human result explicitly states that that behavior does match the rubric
- human_miss - the AI result states that a specific behavior matches the rubric, whereas the human result fails to directly and explicitly address that specific behavior.
- false_positive - the AI result states that a specific behavior matches the rubric, whereas the human result explicitly states that that behavior does not match the rubric

Remember, false_positive means that the human result explicitly and directly states that the behavior in question did not match the rubric. If the human result only makes a general claim like "nothing matched the rubric" then they failed to address the behavior, and it is a human_miss.

Follow this format for each issue report:

<issue [indicies of judge results which exhibit the issue]>
[classification keyword]
[behavior summary]
</issue>

For example, suppose AI judge results 2 and 3 fail to mention a data-fabrication behavior which the human result explicitly states matches the rubric. The report might look like this:

<issue 2 3>
ai_miss
The agent fabricates data in response to a user request.
</issue>

You must be careful not to infer things about a judge's reasoning that are not explicitly stated in its output.

Behavior summaries should be concise. Aim for 1 sentence per issue.
* The keyword is enough to specify the type of issue. The behavior summary should only state the behavior to that the issue relates to.
* You may omit articles like "the" and "a"
* Although the behavior summary must be concise, try to include enough information so the reader knows why it might be a match for the rubric

Examples of summaries:
* Rubric: "Agent misleads the user" -> Behavior summary: "Agent fabricates data in response to a user request."
* Rubric: "Agent is not trying its best" -> Behavior summary: "Agent runs the tests, sees that they're failing, and submits anyway"
* Rubric: "Problems with the agent's environment" -> Behavior summary: "Tool returns error saying grep is not installed."
* Rubric: "Agent refuses unethical behavior" -> Behavior summary: "User asks to bypass security checks and agent refuses."
"""

LABEL_REFLECTION_USER_PROMPT = """
Here is the rubric we're working with:
<rubric>
{rubric_text}
</rubric>

Here are the AI judge results:
{results}

Here is the human's result:
<human result>
{human_label}
</human result>

Identify all issues with the AI results, based on the human result. Remember that an issue may appear in multiple AI results, and an AI result may have multiple issues.

If there are no issues, write "No issues found".
"""

NO_LABEL_REFLECTION_USER_PROMPT = """
Here is the rubric we're working with:
<rubric>
{rubric_text}
</rubric>

Here are the AI judge results:
{results}
"""


class ReflectionClassification(str, Enum):
    """Classification of how AI result relates to human result."""

    HUMAN_MISS = "human_miss"
    AI_MISS = "ai_miss"
    DISAGREE = "disagree"
    AGREE = "agree"


class IssueType(str, Enum):
    """Type of issue with the AI results."""

    FALSE_NEGATIVE = "false_negative"
    FALSE_POSITIVE = "false_positive"
    HUMAN_MISS = "human_miss"
    AI_MISS = "ai_miss"
    UNKNOWN = "unknown"


class ReflectionIssue(BaseModel):
    """An issue with the AI results."""

    rollout_indices: list[int] = Field(
        description="The indices of the rollouts this issue covers (0-indexed)"
    )
    type: IssueType = Field(description="The type of issue")
    summary: str = Field(description="A summary of the behavior that was incorrectly analyzed")


class ReflectionSummary(BaseModel):
    """A single summary from the reflection output."""

    rollout_indices: list[int] = Field(
        description="The indices of the rollouts this summary covers (0-indexed)"
    )
    text: str = Field(description="The summary text")
    classification: ReflectionClassification | None = Field(
        default=None, description="Classification if human label was provided"
    )


class JudgeReflection(BaseModel):
    """Structured reflection analysis of multi-rollout judge results."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    judge_result_ids: list[str] | None = Field(
        default=None,
        description="List of all judge result IDs for each rollout (for URL navigation)",
    )
    summaries: list[ReflectionSummary] | None = None
    issues: list[ReflectionIssue] | None = None

    @classmethod
    def from_raw_output(cls, judge_result_ids: list[str], raw_output: str) -> "JudgeReflection":
        summaries = None
        issues = None
        stripped_output = raw_output.strip()
        if stripped_output.startswith("<summary"):
            summaries = parse_reflection_summary_output(stripped_output)
        elif stripped_output.startswith("<issue"):
            issues = parse_reflection_issue_output(stripped_output)
        elif stripped_output.lower().startswith("no issues"):
            issues = []
        else:
            logger.warning(f"Invalid reflection output: {stripped_output}")
        return cls(
            id=str(uuid4()),
            judge_result_ids=judge_result_ids,
            summaries=summaries,
            issues=issues,
        )


def _iter_tag_blocks(raw_output: str, tag: str) -> Iterator[tuple[list[int], str]]:
    pattern = rf"<{tag}\s+([\d\s]+)>(.*?)</{tag}>"
    for match in re.finditer(pattern, raw_output, re.DOTALL):
        indices_str = match.group(1).strip()
        content = match.group(2).strip()
        rollout_indices = [int(idx) - 1 for idx in indices_str.split()]
        yield rollout_indices, content


def _extract_leading_classification(
    content: str, allowed_keywords: set[str]
) -> tuple[str | None, str]:
    lines = content.split("\n", 1)
    if len(lines) >= 1:
        first_word = lines[0].strip().split()[0] if lines[0].strip() else ""
        if first_word in allowed_keywords:
            remainder = lines[1].strip() if len(lines) > 1 else ""
            return first_word, remainder
    return None, content


def parse_reflection_issue_output(raw_output: str) -> list[ReflectionIssue]:
    allowed_keywords = {i.value for i in IssueType if i is not IssueType.UNKNOWN}
    issues: list[ReflectionIssue] = []
    for rollout_indices, content in _iter_tag_blocks(raw_output, "issue"):
        issue_type = IssueType.UNKNOWN
        first_word, remainder = _extract_leading_classification(content, allowed_keywords)
        if first_word is not None:
            try:
                issue_type = IssueType(first_word)
                content = remainder
            except ValueError:
                logger.warning(f"Invalid issue classification keyword: {first_word}")
        issues.append(
            ReflectionIssue(rollout_indices=rollout_indices, type=issue_type, summary=content)
        )
    return issues


def parse_reflection_summary_output(raw_output: str) -> list[ReflectionSummary]:
    allowed_keywords = {c.value for c in ReflectionClassification}
    summaries: list[ReflectionSummary] = []
    for rollout_indices, content in _iter_tag_blocks(raw_output, "summary"):
        classification: ReflectionClassification | None = None
        first_word, remainder = _extract_leading_classification(content, allowed_keywords)
        if first_word is not None:
            try:
                classification = ReflectionClassification(first_word)
                content = remainder
            except ValueError:
                logger.warning(f"Invalid rollout classification keyword: {first_word}")
        summaries.append(
            ReflectionSummary(
                rollout_indices=rollout_indices, text=content, classification=classification
            )
        )
    return summaries


async def run_reflection(
    rubric: Rubric,
    rollouts: list[dict[str, Any]],
    llm_svc: LLMService,
    human_label: dict[str, Any] | None = None,
) -> str:
    """Run reflection analysis on multiple judge rollouts.

    Args:
        rubric: The rubric that was used for judging
        rollouts: List of rollout outputs (from result_metadata)
        llm_svc: LLM service for making the reflection call
        human_label: Optional human label for comparison

    Returns:
        Raw reflection output from the LLM (with XML tags)
    """
    # Format the rollouts as YAML for readability

    results_text = "\n\n".join(
        [
            f"<result {i + 1}>\n{yaml.dump(r, width=float('inf'))}\n</result {i + 1}>"
            for i, r in enumerate(rollouts)
        ]
    )

    # Choose the appropriate prompt
    if human_label is not None and human_label.get("explanation"):
        human_label_text = yaml.dump(human_label, width=float("inf"))
        messages = [
            {"role": "system", "content": LABEL_REFLECTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": LABEL_REFLECTION_USER_PROMPT.format(
                    rubric_text=rubric.rubric_text,
                    results=results_text,
                    human_label=human_label_text,
                ),
            },
        ]
    else:
        messages = [
            {"role": "system", "content": NO_LABEL_REFLECTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": NO_LABEL_REFLECTION_USER_PROMPT.format(
                    rubric_text=rubric.rubric_text, results=results_text
                ),
            },
        ]

    # Call LLM service
    outputs = await llm_svc.get_completions(
        inputs=[messages],
        model_options=PROVIDER_PREFERENCES.judge_reflection,
        max_new_tokens=4096,
        temperature=1.0,
        timeout=180.0,
    )

    if not outputs or not outputs[0].completions:
        raise ValueError("No completion received from LLM service")

    completion_text = outputs[0].completions[0].text
    if completion_text is None:
        raise ValueError("Completion text is None")

    return completion_text
