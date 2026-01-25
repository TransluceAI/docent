#!/usr/bin/env python3
"""
Rubric Elicitation Script (Interactive Mode)

This script samples agent runs from a collection and uses an LLM to identify
ambiguities in rubric interpretation that would affect judging outcomes, then
collects user answers interactively to refine the rubric.

Pipeline:
1. Initialize clients and instantiate Rubric object
2. Sample N agent runs from a collection (default: 50)
3. Extract questions directly from each agent run (identifying ambiguities)
4. Deduplicate and select top K most diverse/important questions (default: 10)
5. Collect user answers interactively via CLI
6. Extract bottlenecks from user answers
7. Aggregate bottlenecks into refined rubric

Usage:
    python elicit_ambiguities.py <collection_id> <rubric_description> [options]

Options:
    --num-samples <int>       Number of agent runs to sample (default: 50)
    --top-k <int>             Number of top questions to select (default: 10)
    --resume <path>           Resume from checkpoint file (requires --resume-step)
    --resume-step <I.S>       Iteration.step to resume from (e.g., "2.3" = iteration 2, step 3)

Checkpointing:
    The script automatically saves checkpoints after each step to allow resumption.
    Checkpoint files are created in the current working directory with the format:
    checkpoint_{collection_id[:8]}_{timestamp}_gitignore.json

    To resume from a checkpoint:
    python elicit_ambiguities.py <collection_id> <rubric> --resume checkpoint.json --resume-step 1.3

    Step numbers (per iteration):
    1. Extract Questions - extract questions from agent runs using current rubric (extracted_questions)
    2. Deduplicate - deduplicate and select top K questions (selected_questions, dedup_metadata)
    3. Collect Answers - collect user answers interactively via CLI (user_answers)
    4. Extract Insights - extract bottlenecks/insights from answers (bottleneck_results)
    5. Aggregate - aggregate insights into rubric update (aggregated_result)

    Resume behavior:
    - --resume-step is REQUIRED when using --resume.
    - Resuming at iteration I, step S validates that steps 1 through S-1 have completed.
    - If resuming at an earlier iteration than the latest in the checkpoint, later
      iterations are truncated/deleted to avoid stale history.
    - At least 10 valid agent runs must be retrievable from the checkpoint.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from rich.console import Console
from rich.panel import Panel

from docent import Docent
from docent._llm_util.llm_svc import BaseLLMService
from docent.data_models.agent_run import AgentRun
from docent.judges.types import Rubric
from docent_core._env_util import ENV
from docent_core.docent.ai_tools.rubric.elicit import (
    AggregatedRubricResult,
    BottleneckExtractionInput,
    BottleneckExtractionResult,
    ElicitedQuestion,
    aggregate_bottlenecks_into_rubric,
    deduplicate_and_select_questions,
    extract_all_bottlenecks,
    extract_questions_from_agent_runs,
)

# Rich console for interactive display
console = Console()


# =============================================================================
# DATA STRUCTURES FOR INTERACTIVE MODE
# =============================================================================


class UserAnswerWithContext(BaseModel):
    """Represents a user's answer to an elicited question."""

    question_index: int
    question: ElicitedQuestion
    answer_text: str  # Either selected option text or custom response
    is_custom_response: bool
    timestamp: datetime


class IterationState(BaseModel):
    """State for a single iteration of the elicitation loop."""

    iteration: int
    rubric_text: str  # Rubric used for this iteration
    rubric_version: int
    current_step: int = 0  # 0 = not started, 1-5 = completed through that step
    extracted_questions: list[ElicitedQuestion] | None = None
    selected_questions: list[ElicitedQuestion] | None = None
    dedup_metadata: dict[str, Any] | None = None
    user_answers: list[UserAnswerWithContext] | None = None
    bottleneck_results: list[BottleneckExtractionResult] | None = None
    aggregated_result: AggregatedRubricResult | None = None

    def is_complete(self) -> bool:
        """Check if this iteration completed all 5 steps."""
        return self.aggregated_result is not None


class PipelineCheckpoint(BaseModel):
    """Checkpoint containing all intermediate pipeline state."""

    # Metadata
    created_at: datetime
    last_updated: datetime
    completed_step: int = 0  # Legacy field, kept for backwards compatibility

    # Run parameters (for validation on resume)
    collection_id: str
    rubric_description: str
    num_samples: int
    max_questions: int
    max_iterations: int = 10

    # Agent run IDs (not full objects - re-fetch on resume)
    agent_run_ids: list[str] | None = None

    # Iteration tracking
    current_iteration: int = 0
    current_step: int = (
        0  # 0 = not started, 1-5 = in progress at that step within current_iteration
    )
    iteration_history: list[IterationState] = []
    final_rubric_text: str | None = None  # Set when converged
    final_rubric_version: int | None = None
    convergence_reason: str | None = None  # "no_questions", "user_skipped", "max_iterations"


# =============================================================================
# CHECKPOINT UTILITIES
# =============================================================================


def save_checkpoint(path: Path, checkpoint: PipelineCheckpoint) -> None:
    """Save checkpoint to JSON file."""
    with open(path, "w") as f:
        json.dump(checkpoint.model_dump(), f, indent=2, default=str)
    print(f"✓ Checkpoint saved to {path}")


def load_checkpoint(path: Path) -> PipelineCheckpoint:
    """Load checkpoint from JSON file. Raises ValidationError on schema mismatch."""
    with open(path) as f:
        data = json.load(f)
    return PipelineCheckpoint.model_validate(data)


def create_checkpoint_path(collection_id: str) -> Path:
    """Generate a unique checkpoint filename in the current working directory."""
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    return Path(f"checkpoint_{collection_id[:8]}_{timestamp}_gitignore.json")


def parse_resume_step(resume_step_str: str) -> tuple[int, int]:
    """
    Parse a resume step string in the format "I.S" (iteration.step).

    Args:
        resume_step_str: String like "2.3" meaning iteration 2, step 3

    Returns:
        Tuple of (iteration, step)

    Raises:
        ValueError: If format is invalid or values are out of range
    """
    try:
        parts = resume_step_str.split(".")
        if len(parts) != 2:
            raise ValueError(f"Invalid format '{resume_step_str}'. Expected 'I.S' (e.g., '2.3')")

        iteration = int(parts[0])
        step = int(parts[1])

        if iteration < 1:
            raise ValueError(f"Iteration must be >= 1, got {iteration}")
        if step < 1 or step > 5:
            raise ValueError(f"Step must be 1-5, got {step}")

        return (iteration, step)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Invalid resume step format '{resume_step_str}': {e}") from e


def validate_resume_state(
    checkpoint: PipelineCheckpoint,
    target_iteration: int,
    target_step: int,
) -> IterationState | None:
    """
    Validate that we can resume at the specified iteration and step.

    For resuming at iteration I, step S:
    - If I > len(iteration_history) + 1: Error (can't skip iterations)
    - If I == len(iteration_history) + 1: Starting a new iteration, S must be 1
    - If I <= len(iteration_history): Resuming within existing iteration
      - Steps 1 through S-1 must have results

    Args:
        checkpoint: The loaded checkpoint
        target_iteration: Iteration to resume at (1-indexed)
        target_step: Step to resume at (1-5)

    Returns:
        IterationState for the target iteration if resuming mid-iteration,
        or None if starting a fresh iteration

    Raises:
        ValueError: If resume state is invalid
    """
    num_iterations = len(checkpoint.iteration_history)

    # Case 1: Trying to skip iterations
    if target_iteration > num_iterations + 1:
        raise ValueError(
            f"Cannot resume at iteration {target_iteration}. "
            f"Checkpoint only has {num_iterations} iteration(s). "
            f"Maximum resumable iteration is {num_iterations + 1}."
        )

    # Case 2: Starting a brand new iteration
    if target_iteration == num_iterations + 1:
        if target_step != 1:
            raise ValueError(
                f"Cannot resume at iteration {target_iteration} step {target_step}. "
                f"Iteration {target_iteration} hasn't started yet; must start at step 1."
            )
        return None  # No existing state to load

    # Case 3: Resuming within an existing iteration (target_iteration <= num_iterations)
    iter_state = checkpoint.iteration_history[target_iteration - 1]

    # Validate that prior steps have results
    step_fields = [
        (1, "extracted_questions"),
        (2, "selected_questions"),
        (3, "user_answers"),
        (4, "bottleneck_results"),
        (5, "aggregated_result"),
    ]

    for step_num, field_name in step_fields:
        if step_num >= target_step:
            break  # Don't need results for this step or later
        field_value = getattr(iter_state, field_name)
        if field_value is None:
            raise ValueError(
                f"Cannot resume at iteration {target_iteration} step {target_step}. "
                f"Step {step_num} ({field_name}) has no results."
            )

    return iter_state


def get_resume_state(
    checkpoint: PipelineCheckpoint,
    resume_step_str: str,
) -> tuple[int, int, IterationState | None]:
    """
    Determine where to resume based on checkpoint and resume-step.

    Args:
        checkpoint: The loaded checkpoint
        resume_step_str: "I.S" format string (required)

    Returns:
        Tuple of (target_iteration, target_step, existing_iter_state_or_none)

    Raises:
        ValueError: If resume-step is invalid
    """
    target_iteration, target_step = parse_resume_step(resume_step_str)
    iter_state = validate_resume_state(checkpoint, target_iteration, target_step)
    return (target_iteration, target_step, iter_state)


def sample_agent_runs(dc: Docent, collection_id: str, num_samples: int = 50) -> list[AgentRun]:
    """
    Sample agent runs from a collection.

    Args:
        dc: Docent client
        collection_id: Collection to sample from
        num_samples: Number of runs to sample

    Returns:
        List of AgentRun objects

    Raises:
        ValueError: If collection doesn't have enough runs
        RuntimeError: If agent run retrieval fails
    """
    print(f"Fetching agent run IDs from collection {collection_id}...")
    agent_run_ids = dc.list_agent_run_ids(collection_id)

    if len(agent_run_ids) < 10:
        raise ValueError(
            f"Collection has only {len(agent_run_ids)} agent runs. "
            f"Need at least 10 for meaningful analysis."
        )

    # Sample first N runs (or all if fewer than N)
    sampled_ids = agent_run_ids[:num_samples]
    print(f"Sampling {len(sampled_ids)} agent runs...")

    agent_runs: list[AgentRun] = []
    for agent_run_id in sampled_ids:
        agent_run = dc.get_agent_run(collection_id, agent_run_id)
        if agent_run is not None:
            agent_runs.append(agent_run)
        else:
            print(f"Warning: Could not fetch agent run {agent_run_id}")

    if len(agent_runs) < 10:
        raise ValueError(
            f"Only retrieved {len(agent_runs)} valid agent runs. "
            f"Need at least 10 for meaningful analysis."
        )

    print(f"Successfully retrieved {len(agent_runs)} agent runs")
    return agent_runs


def display_direct_extraction_results(questions: list[ElicitedQuestion]):
    """
    Display questions from direct extraction, organized by agent run.

    Args:
        questions: List of ElicitedQuestion objects from extract_questions_from_agent_runs
    """
    print("\n" + "=" * 80)
    print("DIRECTLY EXTRACTED QUESTIONS (BY AGENT RUN)")
    print("=" * 80 + "\n")

    if not questions:
        print("No questions were extracted.")
        return

    # Group questions by agent run
    questions_by_run: dict[str, list[ElicitedQuestion]] = {}
    errors: list[ElicitedQuestion] = []

    for q in questions:
        if q.error:
            errors.append(q)
        else:
            run_id = q.agent_run_id or "unknown"
            if run_id not in questions_by_run:
                questions_by_run[run_id] = []
            questions_by_run[run_id].append(q)

    # Summary stats
    total_questions = sum(len(qs) for qs in questions_by_run.values())
    runs_with_questions = len(questions_by_run)
    print(f"Total questions extracted: {total_questions}")
    print(f"Agent runs with questions: {runs_with_questions}")
    if errors:
        print(f"Errors: {len(errors)}")
    print()

    # Display questions grouped by run
    run_num = 0
    for run_id, run_questions in questions_by_run.items():
        run_num += 1
        print("═" * 80)
        print(f"AGENT RUN {run_num}: {run_id}")
        print(f"Questions from this run: {len(run_questions)}")
        print("═" * 80 + "\n")

        for i, q in enumerate(run_questions, 1):
            print("─" * 80)
            print(f"Question {i}/{len(run_questions)}")
            print("─" * 80 + "\n")

            # Show title first
            if q.quote_title:
                print(f"Title: {q.quote_title}\n")

            # Show context
            if q.question_context:
                print(f"Context: {q.question_context}\n")

            # Show question
            print(f"Question: {q.framed_question}\n")

            # Show ambiguity explanation
            if q.ambiguity_explanation:
                print(f"Why Ambiguous: {q.ambiguity_explanation}\n")

            # Show citation counts
            if q.question_context_citations:
                print(f"Citations: {len(q.question_context_citations)} citation(s) in context")
            if q.framed_question_citations:
                print(f"           {len(q.framed_question_citations)} citation(s) in question")
            if q.framed_question_citations or q.question_context_citations:
                print()

            # Show example options
            if q.example_options:
                print("Suggested options:")
                for j, option in enumerate(q.example_options, 1):
                    print(f"  {j}. {option.title}")
                    if option.description:
                        print(f"     {option.description}")
                print()

        print()  # Extra space between runs

    # Display errors
    if errors:
        print("─" * 80)
        print(f"Errors ({len(errors)}):")
        print("─" * 80 + "\n")
        for err in errors:
            print(f"  - Agent run {err.agent_run_id}: {err.error}")

    # Final summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total questions: {total_questions}")
    print(f"Runs with questions: {runs_with_questions}")
    print(f"Errors: {len(errors)}")
    print()


def display_deduplicated_questions(
    selected_questions: list[ElicitedQuestion],
    dedup_metadata: dict[str, Any],
):
    """
    Display the deduplicated/selected questions with selection rationales.

    Args:
        selected_questions: List of selected ElicitedQuestion objects
        dedup_metadata: Metadata from deduplicate_and_select_questions containing
            selected_ids, rationales, excluded_similar, summary, and error
    """
    print("\n" + "=" * 80)
    print("DEDUPLICATED/SELECTED QUESTIONS")
    print("=" * 80 + "\n")

    # Show any errors or notes
    if dedup_metadata.get("error"):
        print(f"Note: {dedup_metadata['error']}\n")

    # Show summary
    if dedup_metadata.get("summary"):
        print(f"Selection Summary: {dedup_metadata['summary']}\n")

    if not selected_questions:
        print("No questions were selected.")
        return

    print(f"Selected {len(selected_questions)} question(s):\n")

    selected_ids = dedup_metadata.get("selected_ids", [])

    for i, q in enumerate(selected_questions, 1):
        print("─" * 80)
        print(f"SELECTED QUESTION {i}/{len(selected_questions)}")
        print("─" * 80 + "\n")

        # Get the question ID for this question (aligned by index)
        q_id = selected_ids[i - 1] if i - 1 < len(selected_ids) else None

        # Show title first
        if q.quote_title:
            print(f"Title: {q.quote_title}\n")

        # Show context
        if q.question_context:
            print(f"Context: {q.question_context}\n")

        # Show question
        print(f"Question: {q.framed_question}\n")

        # Show ambiguity explanation
        if q.ambiguity_explanation:
            print(f"Why Ambiguous: {q.ambiguity_explanation}\n")

        # Show agent run
        print(f"From Agent Run: {q.agent_run_id}")

        # Show selection rationale if available
        if q_id and q_id in dedup_metadata.get("rationales", {}):
            rationale = dedup_metadata["rationales"][q_id]
            print(f"Selection Rationale: {rationale}")

        # Show excluded similar questions if available
        if q_id and q_id in dedup_metadata.get("excluded_similar", {}):
            excluded = dedup_metadata["excluded_similar"][q_id]
            if excluded:
                print(f"Similar Questions Excluded: {', '.join(excluded)}")

        # Show example options
        if q.example_options:
            print("\nSuggested options:")
            for j, option in enumerate(q.example_options, 1):
                print(f"  {j}. {option.title}")
                if option.description:
                    print(f"     {option.description}")

        print()

    # Summary statistics
    print("=" * 80)
    print("DEDUPLICATION SUMMARY")
    print("=" * 80)
    print(f"Questions selected: {len(selected_questions)}")
    print(f"Question IDs: {', '.join(dedup_metadata.get('selected_ids', []))}")
    if dedup_metadata.get("summary"):
        print(f"Coverage: {dedup_metadata['summary']}")
    print()


# =============================================================================
# INTERACTIVE MODE FUNCTIONS
# =============================================================================


def collect_interactive_answers(
    questions: list[ElicitedQuestion],
    dedup_metadata: dict[str, Any] | None = None,
) -> list[UserAnswerWithContext]:
    """
    Collect user answers via CLI using beaupy for selection.

    For each question:
    1. Display the question and context using rich.console
    2. Build options list from question.example_options (title + description)
    3. Add "[Write my own response]" and "[Skip]" options
    4. Use beaupy.select() for selection
    5. If custom selected, use rich.prompt.Prompt.ask() for text input
    6. Return list of UserAnswerWithContext

    Args:
        questions: List of ElicitedQuestion objects to present to user
        dedup_metadata: Optional metadata from deduplication containing
            novelty_ratings and rationales

    Returns:
        List of UserAnswerWithContext for non-skipped questions
    """
    import beaupy
    from rich.prompt import Prompt

    console.print("\n" + "=" * 80)
    console.print("[bold cyan]INTERACTIVE ANSWER COLLECTION[/bold cyan]")
    console.print("=" * 80 + "\n")

    console.print(f"You will be asked {len(questions)} question(s) to help clarify the rubric.\n")
    console.print("For each question:")
    console.print("  • Select one of the suggested options, OR")
    console.print("  • Write your own response, OR")
    console.print("  • Skip the question\n")

    results: list[UserAnswerWithContext] = []

    for idx, question in enumerate(questions):
        # Display question header
        console.print("─" * 80)
        console.print(f"[bold]Question {idx + 1}/{len(questions)}[/bold]")
        console.print("─" * 80 + "\n")

        # Show title first
        if question.quote_title:
            console.print(
                Panel(question.quote_title, title="[bold cyan]Title[/bold cyan]", expand=False)
            )

        # Show context
        if question.question_context:
            console.print(
                Panel(
                    question.question_context, title="[bold blue]Context[/bold blue]", expand=False
                )
            )

        # Show the question
        console.print(
            Panel(
                question.framed_question or "No question text",
                title="[bold green]Question[/bold green]",
                expand=False,
            )
        )

        console.print()

        # Show metadata if available
        if dedup_metadata:
            selected_ids = dedup_metadata.get("selected_ids", [])
            q_id = selected_ids[idx] if idx < len(selected_ids) else None
            if q_id:
                novelty = dedup_metadata.get("novelty_ratings", {}).get(q_id, "")
                rationale = dedup_metadata.get("rationales", {}).get(q_id, "")
                if novelty or rationale:
                    if novelty:
                        console.print(f"[dim]Novelty: {novelty}[/dim]")
                    if rationale:
                        console.print(f"[dim]Selection Rationale: {rationale}[/dim]")
                    console.print()

        # Build options list
        options: list[str] = []
        option_values: list[tuple[str, bool]] = []  # (answer_text, is_custom)

        for opt in question.example_options:
            title = opt.title or "Untitled option"
            description = opt.description or ""
            if description:
                display_text = f"{title}: {description}"
            else:
                display_text = title
            options.append(display_text)
            # Use full description as the answer text for better context
            option_values.append((display_text, False))

        # Add special options
        custom_option = "[Write my own response]"
        skip_option = "[Skip this question]"
        options.append(custom_option)
        options.append(skip_option)

        # Use beaupy for selection
        console.print("[bold]Select an answer:[/bold]\n")
        # beaupy's type hints are incorrect - it accepts list[str] but annotates as List[Tuple[int, ...] | str]
        selected = beaupy.select(options, cursor="→ ", cursor_style="cyan")  # pyright: ignore[reportArgumentType]

        if selected is None or selected == skip_option:
            console.print("[dim]Skipped[/dim]\n")
            continue

        if selected == custom_option:
            # Prompt for custom text input
            custom_answer = Prompt.ask("\n[bold]Enter your response[/bold]")
            if not custom_answer or not custom_answer.strip():
                console.print("[dim]Empty response, skipping[/dim]\n")
                continue
            answer_text = custom_answer.strip()
            is_custom = True
        else:
            # Find the selected option
            selected_str = str(selected)
            selected_idx = options.index(selected_str)
            answer_text, is_custom = option_values[selected_idx]

        # Create and store the result
        user_answer = UserAnswerWithContext(
            question_index=idx,
            question=question,
            answer_text=answer_text,
            is_custom_response=is_custom,
            timestamp=datetime.now(timezone.utc),
        )
        results.append(user_answer)

        console.print(f"\n[green]✓ Recorded answer[/green]: {answer_text[:100]}...")
        console.print()

    console.print("=" * 80)
    console.print(f"[bold]Collected {len(results)} answer(s)[/bold]")
    console.print("=" * 80 + "\n")

    return results


# =============================================================================
# ITERATION STATS AND DISPLAY HELPERS
# =============================================================================


def print_iteration_header(iteration: int, rubric_version: int, max_iterations: int) -> None:
    """Print a header for the start of an iteration."""
    console.print()
    console.print("=" * 80)
    console.print(
        f"[bold cyan]ITERATION {iteration}/{max_iterations}[/bold cyan] "
        f"[dim](Rubric v{rubric_version})[/dim]"
    )
    console.print("=" * 80)
    console.print()


def print_iteration_stats(
    iteration: int,
    num_extracted: int,
    num_selected: int = 0,
    num_answered: int = 0,
) -> None:
    """Print stats for the current iteration."""
    console.print(f"  [bold]Iteration {iteration} stats:[/bold]")
    console.print(f"    Questions extracted: {num_extracted}")
    if num_selected:
        console.print(f"    Questions selected: {num_selected}")
    if num_answered:
        console.print(f"    Questions answered: {num_answered}")
    console.print()


def print_final_summary(
    iteration_history: list[IterationState],
    final_rubric_text: str,
    final_rubric_version: int,
    convergence_reason: str,
) -> None:
    """Print the final summary after convergence."""
    console.print()
    console.print("=" * 80)
    console.print("[bold green]CONVERGENCE SUMMARY[/bold green]")
    console.print("=" * 80)
    console.print()

    # Show iteration history
    console.print("[bold]Iteration History:[/bold]")
    for state in iteration_history:
        num_questions = len(state.extracted_questions or [])
        num_answered = len(state.user_answers or [])
        console.print(
            f"  Iteration {state.iteration}: "
            f"{num_questions} questions extracted, "
            f"{num_answered} answered"
        )
    console.print()

    # Show convergence reason
    reason_display = {
        "no_questions": "No ambiguities found in rubric",
        "user_skipped": "User skipped all questions (satisfied with rubric)",
        "max_iterations": "Reached maximum iteration limit",
    }.get(convergence_reason, convergence_reason)
    console.print(f"[bold]Convergence reason:[/bold] {reason_display}")
    console.print(f"[bold]Final rubric version:[/bold] {final_rubric_version}")
    console.print()

    # Show final rubric
    console.print("[bold]Final Rubric:[/bold]")
    console.print(
        Panel(
            final_rubric_text,
            title=f"[green]Version {final_rubric_version}[/green]",
        )
    )
    console.print("=" * 80 + "\n")


def display_interactive_results(
    user_answers: list[UserAnswerWithContext],
    bottleneck_results: list[BottleneckExtractionResult],
    aggregated_result: AggregatedRubricResult,
):
    """Display results from interactive mode."""
    console.print("\n" + "=" * 80)
    console.print("[bold cyan]INTERACTIVE MODE RESULTS[/bold cyan]")
    console.print("=" * 80 + "\n")

    # Show collected answers
    console.print("[bold]Collected Answers:[/bold]\n")
    for answer in user_answers:
        console.print(f"  Q{answer.question_index + 1}: {answer.answer_text[:80]}...")
        if answer.is_custom_response:
            console.print("       [dim](custom response)[/dim]")
    console.print()

    # Show extracted bottlenecks
    console.print("[bold]Extracted Insights:[/bold]\n")
    for result in bottleneck_results:
        if result.error:
            console.print(f"  Q{result.question_index + 1}: [red]Error: {result.error}[/red]")
        elif result.bottleneck:
            b = result.bottleneck
            console.print(f"  Q{result.question_index + 1}: [{b.confidence}] {b.change_type}")
            console.print(f"       [dim]Insight: {b.key_insight[:60]}...[/dim]")
    console.print()

    # Show aggregated result
    if aggregated_result.error:
        console.print(f"[red]Aggregation Error: {aggregated_result.error}[/red]\n")
    else:
        console.print("[bold]Change Summary:[/bold]")
        console.print(Panel(aggregated_result.change_summary, expand=False))
        console.print()

        console.print("[bold]Updated Rubric:[/bold]")
        console.print(
            Panel(
                aggregated_result.updated_rubric.rubric_text,
                title=f"[green]Version {aggregated_result.updated_rubric.version}[/green]",
            )
        )

    console.print("=" * 80 + "\n")


async def run_elicitation(
    collection_id: str,
    rubric_description: str,
    num_samples: int = 50,
    max_questions: int = 10,
    resume_from: Path | None = None,
    resume_step: str | None = None,
    max_iterations: int = 10,
    max_questions_per_run: int = 5,
):
    """
    Main pipeline for iterative rubric elicitation.

    The pipeline iteratively refines the rubric until convergence:
    1. Initialize clients and sample agent runs (once at start)
    2. Loop until convergence:
       a. Extract questions from agent runs using current rubric
       b. If no questions extracted → converged (rubric is unambiguous)
       c. Deduplicate and select top K questions
       d. Collect user answers interactively
       e. If all questions skipped → converged (user is satisfied)
       f. Extract bottlenecks from user answers
       g. Aggregate bottlenecks into updated rubric
       h. Use updated rubric for next iteration
    3. Print final convergence summary

    Args:
        collection_id: Collection to sample from
        rubric_description: Description of the rubric to evaluate against
        num_samples: Number of agent runs to sample (default: 50)
        max_questions: Maximum questions to select per iteration (default: 10).
            This is an upper limit - the LLM may return fewer based on quality.
        resume_from: Path to checkpoint file to resume from
        resume_step: "I.S" format string specifying iteration.step to resume from
        max_iterations: Maximum iterations before stopping (default: 10)
    """
    print(f"Starting iterative rubric elicitation for collection: {collection_id}")
    print(
        f"Sampling {num_samples} agent runs, selecting up to {max_questions} questions per iteration"
    )
    print(f"Max iterations: {max_iterations}")
    print()

    # Initialize or load checkpoint
    if resume_from:
        print(f"Resuming from checkpoint: {resume_from}")
        checkpoint = load_checkpoint(resume_from)
        checkpoint_path = resume_from

        # Validate parameters match
        if checkpoint.collection_id != collection_id:
            raise ValueError(
                f"Collection ID mismatch: checkpoint has {checkpoint.collection_id}, "
                f"but {collection_id} was provided"
            )
        if checkpoint.rubric_description != rubric_description:
            print("Warning: Rubric description differs from checkpoint. Using checkpoint version.")
            rubric_description = checkpoint.rubric_description

        # Use checkpoint's max_iterations if set, otherwise use provided value
        if checkpoint.max_iterations != max_iterations:
            print(
                f"Note: Using max_iterations={checkpoint.max_iterations} from checkpoint "
                f"(provided: {max_iterations})"
            )
            max_iterations = checkpoint.max_iterations

        # Require --resume-step when resuming
        if not resume_step:
            raise ValueError(
                "--resume-step is required when using --resume. "
                "Use --resume-step I.S to specify iteration and step (e.g., '2.3')."
            )

        print(
            f"Resuming from iteration {checkpoint.current_iteration} "
            f"(completed {len(checkpoint.iteration_history)} iteration(s))"
        )
        print()
    else:
        checkpoint_path = create_checkpoint_path(collection_id)
        checkpoint = PipelineCheckpoint(
            created_at=datetime.now(timezone.utc),
            last_updated=datetime.now(timezone.utc),
            completed_step=0,
            collection_id=collection_id,
            rubric_description=rubric_description,
            num_samples=num_samples,
            max_questions=max_questions,
            max_iterations=max_iterations,
        )
        print(f"Checkpoint will be saved to: {checkpoint_path}")
        print()

    # Initialize clients
    print("Initializing clients...")
    api_key = ENV.get("DOCENT_API_KEY")
    domain = ENV.get("DOCENT_DOMAIN")

    if not api_key or not domain:
        raise ValueError("DOCENT_API_KEY and DOCENT_DOMAIN must be set in environment variables")

    dc = Docent(api_key=api_key, domain=domain, server_url="http://localhost:8901")
    llm_svc = BaseLLMService(max_concurrency=50)
    print("✓ Clients initialized\n")

    # Sample agent runs ONCE at start (or load IDs from checkpoint)
    if resume_from and checkpoint.agent_run_ids:
        print(f"Loading {len(checkpoint.agent_run_ids)} agent run IDs from checkpoint...")
        agent_runs: list[AgentRun] = []
        for agent_run_id in checkpoint.agent_run_ids:
            agent_run = dc.get_agent_run(collection_id, agent_run_id)
            if agent_run is not None:
                agent_runs.append(agent_run)
            else:
                print(f"Warning: Could not fetch agent run {agent_run_id}")
        print(f"✓ Retrieved {len(agent_runs)} agent runs from checkpoint\n")

        # Enforce minimum agent runs on resume (same guard as fresh sampling)
        if len(agent_runs) < 10:
            raise ValueError(
                f"Only retrieved {len(agent_runs)} valid agent runs from checkpoint. "
                "Need at least 10 for meaningful analysis."
            )
    else:
        agent_runs = sample_agent_runs(dc, collection_id, num_samples=num_samples)
        checkpoint.agent_run_ids = [run.id for run in agent_runs]
        checkpoint.last_updated = datetime.now(timezone.utc)
        save_checkpoint(checkpoint_path, checkpoint)
        print(f"✓ Retrieved {len(agent_runs)} agent runs\n")

    # Determine resume state (iteration + step to start at)
    if resume_from:
        # resume_step is guaranteed to be set (validated above)
        assert resume_step is not None
        target_iteration, target_step, existing_iter_state = get_resume_state(
            checkpoint, resume_step
        )
        print(f"✓ Will resume at iteration {target_iteration}, step {target_step}")
        if existing_iter_state:
            print(f"  (loading existing state from iteration {existing_iter_state.iteration})")

        # Truncate iteration history if resuming earlier than the latest iteration
        # This prevents stale later iterations from remaining in the checkpoint
        if target_iteration <= len(checkpoint.iteration_history):
            checkpoint.iteration_history = checkpoint.iteration_history[:target_iteration]
            checkpoint.final_rubric_text = None
            checkpoint.final_rubric_version = None
            checkpoint.convergence_reason = None
            print(
                f"  (truncated iteration history to {len(checkpoint.iteration_history)} iteration(s))"
            )

        print()
    else:
        # Fresh start: iteration 1, step 1
        target_iteration, target_step, existing_iter_state = 1, 1, None

    # Initialize rubric based on where we're resuming
    if existing_iter_state and target_iteration <= len(checkpoint.iteration_history):
        # Resuming within an existing iteration - use that iteration's rubric
        current_rubric = Rubric(
            rubric_text=existing_iter_state.rubric_text,
            version=existing_iter_state.rubric_version,
        )
        print(f"✓ Using rubric v{current_rubric.version} from iteration {target_iteration}\n")
    elif checkpoint.iteration_history:
        # Starting a new iteration - use last completed iteration's result
        last_state = checkpoint.iteration_history[-1]
        if last_state.aggregated_result:
            current_rubric = last_state.aggregated_result.updated_rubric
            print(f"✓ Using rubric v{current_rubric.version} from iteration history\n")
        else:
            current_rubric = Rubric(rubric_text=rubric_description)
            print(f"✓ Starting with initial rubric (version {current_rubric.version})\n")
    else:
        current_rubric = Rubric(rubric_text=rubric_description)
        print(f"✓ Starting with initial rubric (version {current_rubric.version})\n")

    # Track iteration state
    # Start iteration counter at target_iteration - 1 so the loop begins at target_iteration
    iteration = target_iteration - 1
    iteration_history = list(checkpoint.iteration_history)
    convergence_reason: str | None = None

    # Track if this is the first iteration (may need to skip steps when resuming mid-iteration)
    is_first_loop_iteration = True

    # Helper to save checkpoint after each step
    def save_step_checkpoint(
        iter_state: IterationState,
        step_num: int,
        iter_history: list[IterationState],
        is_in_history: bool,
    ) -> bool:
        """Save checkpoint after completing a step.

        Returns:
            bool: True if iter_state is now in history (for updating iter_in_history flag)
        """
        iter_state.current_step = step_num
        checkpoint.current_step = step_num
        checkpoint.current_iteration = iter_state.iteration

        # Update iteration_history with current state
        if is_in_history:
            # Replace the existing entry
            iter_history[iter_state.iteration - 1] = iter_state
        else:
            # Add new iteration to history
            iter_history.append(iter_state)

        checkpoint.iteration_history = iter_history
        checkpoint.last_updated = datetime.now(timezone.utc)
        save_checkpoint(checkpoint_path, checkpoint)

        return True  # State is now in history

    # ========================================================================
    # MAIN ITERATION LOOP
    # ========================================================================
    while iteration < max_iterations:
        iteration += 1
        checkpoint.current_iteration = iteration

        # Determine the starting step for this iteration
        if is_first_loop_iteration and existing_iter_state and iteration == target_iteration:
            # Resuming mid-iteration: load existing state and start at target_step
            start_step = target_step
            iter_state = existing_iter_state.model_copy(deep=True)
            # Track whether this iteration is already in history (for checkpoint updates)
            iter_in_history = True
        else:
            # Fresh iteration: start at step 1
            start_step = 1
            iter_state = IterationState(
                iteration=iteration,
                rubric_text=current_rubric.rubric_text,
                rubric_version=current_rubric.version,
            )
            iter_in_history = False

        is_first_loop_iteration = False

        print_iteration_header(iteration, current_rubric.version, max_iterations)

        if start_step > 1:
            console.print(
                f"[dim]Resuming at step {start_step} (steps 1-{start_step - 1} already complete)[/dim]\n"
            )

        # ------------------------------------------------------------------
        # Step 1: Extract questions with CURRENT rubric
        # ------------------------------------------------------------------
        if start_step <= 1:
            console.print("[bold]Step 1: Extracting questions...[/bold]")

            direct_questions = await extract_questions_from_agent_runs(
                agent_runs=agent_runs,
                rubric_description=current_rubric.rubric_text,  # Use CURRENT rubric
                llm_svc=llm_svc,
                max_questions_per_run=max_questions_per_run,
            )

            iter_state.extracted_questions = direct_questions

            # Check for valid questions (no errors)
            valid_questions = [q for q in direct_questions if q.error is None]
            num_errors = len(direct_questions) - len(valid_questions)

            console.print(
                f"  Extracted {len(valid_questions)} valid questions ({num_errors} errors)\n"
            )

            # Display extracted questions with ambiguity explanations
            display_direct_extraction_results(direct_questions)

            # Convergence check #1: No questions extracted
            if not valid_questions:
                console.print(
                    "[bold green]✓ Converged![/bold green] No ambiguities found in rubric.\n"
                )
                convergence_reason = "no_questions"
                iter_state.current_step = 1
                if iter_in_history:
                    iteration_history[iteration - 1] = iter_state
                else:
                    iteration_history.append(iter_state)
                checkpoint.iteration_history = iteration_history
                checkpoint.current_step = 1
                save_checkpoint(checkpoint_path, checkpoint)
                break

            # Save checkpoint after step 1
            iter_in_history = save_step_checkpoint(
                iter_state, 1, iteration_history, iter_in_history
            )
        else:
            # Load from existing state
            direct_questions = iter_state.extracted_questions or []
            valid_questions = [q for q in direct_questions if q.error is None]
            console.print(f"[dim]Step 1 (cached): {len(valid_questions)} valid questions[/dim]\n")

        # ------------------------------------------------------------------
        # Step 2: Deduplicate and select top questions
        # ------------------------------------------------------------------
        if start_step <= 2:
            console.print("[bold]Step 2: Deduplicating questions...[/bold]")

            selected_questions, dedup_metadata = await deduplicate_and_select_questions(
                questions=direct_questions,
                llm_svc=llm_svc,
                rubric_description=current_rubric.rubric_text,
                max_questions=max_questions,
            )

            iter_state.selected_questions = selected_questions
            iter_state.dedup_metadata = dedup_metadata

            console.print(
                f"  Selected {len(selected_questions)} questions from "
                f"{len(valid_questions)} candidates\n"
            )

            if not selected_questions:
                console.print(
                    "[bold green]✓ Converged![/bold green] "
                    "No questions selected after deduplication.\n"
                )
                convergence_reason = "no_questions"
                iter_state.current_step = 2
                if iter_in_history:
                    iteration_history[iteration - 1] = iter_state
                else:
                    iteration_history.append(iter_state)
                checkpoint.iteration_history = iteration_history
                checkpoint.current_step = 2
                save_checkpoint(checkpoint_path, checkpoint)
                break

            # Save checkpoint after step 2
            iter_in_history = save_step_checkpoint(
                iter_state, 2, iteration_history, iter_in_history
            )
        else:
            # Load from existing state
            selected_questions = iter_state.selected_questions or []
            console.print(
                f"[dim]Step 2 (cached): {len(selected_questions)} selected questions[/dim]\n"
            )

        # ------------------------------------------------------------------
        # Step 3: Collect user answers interactively
        # ------------------------------------------------------------------
        if start_step <= 3:
            console.print("[bold]Step 3: Collecting user answers...[/bold]\n")

            user_answers = collect_interactive_answers(
                selected_questions, iter_state.dedup_metadata
            )

            iter_state.user_answers = user_answers

            # Convergence check #2: User skipped all questions
            if not user_answers:
                console.print(
                    "\n[bold green]✓ Converged![/bold green] "
                    "User skipped all questions (satisfied with rubric).\n"
                )
                convergence_reason = "user_skipped"
                iter_state.current_step = 3
                if iter_in_history:
                    iteration_history[iteration - 1] = iter_state
                else:
                    iteration_history.append(iter_state)
                checkpoint.iteration_history = iteration_history
                checkpoint.current_step = 3
                save_checkpoint(checkpoint_path, checkpoint)
                break

            # Save checkpoint after step 3
            iter_in_history = save_step_checkpoint(
                iter_state, 3, iteration_history, iter_in_history
            )
        else:
            # Load from existing state
            user_answers = iter_state.user_answers or []
            console.print(f"[dim]Step 3 (cached): {len(user_answers)} user answers[/dim]\n")

        # ------------------------------------------------------------------
        # Step 4: Extract bottlenecks from user answers
        # ------------------------------------------------------------------
        if start_step <= 4:
            console.print("\n[bold]Step 4: Extracting insights from answers...[/bold]")

            extraction_inputs = [
                BottleneckExtractionInput(
                    question_index=answer.question_index,
                    agent_run_id=answer.question.agent_run_id,
                    original_question=answer.question.framed_question or "",
                    user_answer=answer.answer_text,
                )
                for answer in user_answers
            ]

            bottleneck_results = await extract_all_bottlenecks(
                inputs=extraction_inputs,
                agent_runs=agent_runs,
                rubric=current_rubric,
                llm_svc=llm_svc,
            )

            iter_state.bottleneck_results = bottleneck_results

            num_bottlenecks = sum(1 for r in bottleneck_results if r.bottleneck is not None)
            console.print(
                f"  Extracted {num_bottlenecks} insights from {len(user_answers)} answers\n"
            )

            # Save checkpoint after step 4
            iter_in_history = save_step_checkpoint(
                iter_state, 4, iteration_history, iter_in_history
            )
        else:
            # Load from existing state
            bottleneck_results = iter_state.bottleneck_results or []
            num_bottlenecks = sum(1 for r in bottleneck_results if r.bottleneck is not None)
            console.print(f"[dim]Step 4 (cached): {num_bottlenecks} bottlenecks[/dim]\n")

        # ------------------------------------------------------------------
        # Step 5: Aggregate bottlenecks into rubric update
        # ------------------------------------------------------------------
        console.print("[bold]Step 5: Aggregating into rubric update...[/bold]")

        aggregated_result = await aggregate_bottlenecks_into_rubric(
            bottleneck_results=bottleneck_results,
            rubric=current_rubric,
            llm_svc=llm_svc,
        )

        iter_state.aggregated_result = aggregated_result

        if aggregated_result.error:
            console.print(f"  [yellow]Warning: {aggregated_result.error}[/yellow]\n")
        else:
            console.print(
                f"  Updated rubric to version {aggregated_result.updated_rubric.version}\n"
            )
            console.print(f"  [dim]Summary: {aggregated_result.change_summary}[/dim]\n")

        # Update rubric for next iteration
        current_rubric = aggregated_result.updated_rubric

        # Print iteration stats
        print_iteration_stats(
            iteration=iteration,
            num_extracted=len(valid_questions),
            num_selected=len(selected_questions),
            num_answered=len(user_answers),
        )

        # Save checkpoint after completing iteration (step 5)
        iter_in_history = save_step_checkpoint(iter_state, 5, iteration_history, iter_in_history)

    # ========================================================================
    # POST-LOOP: Check if hit max iterations
    # ========================================================================
    if iteration >= max_iterations and convergence_reason is None:
        console.print(
            f"\n[bold yellow]Reached max iterations ({max_iterations}). Stopping.[/bold yellow]\n"
        )
        convergence_reason = "max_iterations"

    # ========================================================================
    # FINAL: Save final state and print summary
    # ========================================================================
    checkpoint.final_rubric_text = current_rubric.rubric_text
    checkpoint.final_rubric_version = current_rubric.version
    checkpoint.convergence_reason = convergence_reason
    checkpoint.iteration_history = iteration_history
    checkpoint.last_updated = datetime.now(timezone.utc)
    save_checkpoint(checkpoint_path, checkpoint)

    print_final_summary(
        iteration_history=iteration_history,
        final_rubric_text=current_rubric.rubric_text,
        final_rubric_version=current_rubric.version,
        convergence_reason=convergence_reason or "unknown",
    )


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Elicit rubric ambiguities from agent runs (interactive mode)"
    )
    parser.add_argument("collection_id", type=str, help="Collection ID to sample agent runs from")
    parser.add_argument(
        "rubric_description",
        type=str,
        help="Description of the rubric to evaluate against (can be a multi-line string)",
    )
    parser.add_argument(
        "--num-samples",
        type=int,
        default=50,
        help="Number of agent runs to sample from the collection (default: 50)",
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        default=10,
        help="Maximum number of questions to select per iteration (default: 10). "
        "This is an upper limit - the LLM may return fewer based on quality.",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="Path to checkpoint file to resume from",
    )
    parser.add_argument(
        "--resume-step",
        type=str,
        default=None,
        help="Iteration.step to resume from, e.g., '2.3' for iteration 2 step 3",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Maximum number of iterations before stopping (default: 10)",
    )
    parser.add_argument(
        "--max-questions-per-run",
        type=int,
        default=3,
        help="Maximum questions to extract per agent run (default: 3)",
    )
    args = parser.parse_args()

    try:
        asyncio.run(
            run_elicitation(
                args.collection_id,
                args.rubric_description,
                args.num_samples,
                args.max_questions,
                resume_from=args.resume,
                resume_step=args.resume_step,
                max_iterations=args.max_iterations,
                max_questions_per_run=args.max_questions_per_run,
            )
        )
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
