#!/usr/bin/env python3
"""
Feedback Elicitation Script

This script iteratively extracts and aggregates questions from agent runs to identify
ambiguities in rubric interpretation that would affect judging outcomes. It collects
user feedback to refine the user model until convergence or max iterations.

Pipeline (per iteration):
1. Extract questions from each agent run (identifying ambiguities)
2. Deduplicate and select top K most diverse/important questions
3. Collect user answers interactively
4. Update UserData with QA pairs
5. Update UserModel via LLM

Convergence occurs when:
- No ambiguities are found in the rubric
- User skips all questions (satisfied with current rubric)
- Maximum iterations reached

Usage:
    python feedback_elicitation.py <collection_id> <rubric_description> [options]

Options:
    --num-samples <int>           Number of agent runs to sample (default: 50)
    --max-questions <int>         Number of top questions to select per iteration (default: 10)
    --max-questions-per-run <int> Max questions to extract per run (default: 3)
    --max-iterations <int>        Maximum iterations before stopping (default: 10)
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from rich.console import Console
from rich.panel import Panel

from docent import Docent
from docent._llm_util.llm_svc import BaseLLMService
from docent.data_models.agent_run import AgentRun
from docent_core._env_util import ENV
from docent_core.docent.ai_tools.rubric.elicit import (
    DecompositionProposal,
    ElicitedQuestion,
    analyze_rubric_decomposition,
    deduplicate_and_select_questions,
    extract_questions_from_agent_runs,
    sort_questions_by_relevance_novelty_pareto,
    update_user_model,
)
from docent_core.docent.ai_tools.rubric.user_model import UserData, UserModel

console = Console()


def print_iteration_header(iteration: int, version: int, max_iterations: int) -> None:
    """Print a header for the start of an iteration."""
    console.print()
    console.print("=" * 80)
    console.print(
        f"[bold cyan]ITERATION {iteration}/{max_iterations}[/bold cyan] "
        f"[dim](User Model v{version})[/dim]"
    )
    console.print("=" * 80)
    console.print()


class UserAnswerWithContext(BaseModel):
    """Represents a user's answer to an elicited question."""

    question_index: int
    question: ElicitedQuestion
    answer_text: str  # Either selected option text or custom response
    is_custom_response: bool
    timestamp: datetime


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


def display_extracted_questions(questions: list[ElicitedQuestion]) -> None:
    """Display questions from extraction, organized by agent run."""
    print("\n" + "=" * 80)
    print("EXTRACTED QUESTIONS (BY AGENT RUN)")
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
        print("-" * 80)
        print(f"AGENT RUN {run_num}: {run_id}")
        print(f"Questions from this run: {len(run_questions)}")
        print("-" * 80 + "\n")

        for i, q in enumerate(run_questions, 1):
            print(f"  Question {i}/{len(run_questions)}")
            if q.relevance_rating:
                print(f"    Relevance: {q.relevance_rating}")
                if q.relevance_rationale:
                    print(f"    Relevance Rationale: {q.relevance_rationale}")
            if q.novelty_rating:
                print(f"    Novelty: {q.novelty_rating}")
                if q.novelty_rationale:
                    print(f"    Novelty Rationale: {q.novelty_rationale}")
            if q.quote_title:
                print(f"    Title: {q.quote_title}")
            if q.question_context:
                context_preview = (
                    q.question_context[:200] + "..."
                    if len(q.question_context) > 200
                    else q.question_context
                )
                print(f"    Context: {context_preview}")
            print(f"    Question: {q.framed_question}")
            print()

    # Display errors
    if errors:
        print("-" * 80)
        print(f"Errors ({len(errors)}):")
        print("-" * 80 + "\n")
        for err in errors:
            print(f"  - Agent run {err.agent_run_id}: {err.error}")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total questions: {total_questions}")
    print(f"Runs with questions: {runs_with_questions}")
    print(f"Errors: {len(errors)}")
    print()


def display_selected_questions(
    selected_questions: list[ElicitedQuestion],
    dedup_metadata: dict[str, Any],
) -> None:
    """Display the deduplicated/selected questions."""
    print("\n" + "=" * 80)
    print("SELECTED QUESTIONS (AFTER DEDUPLICATION)")
    print("=" * 80 + "\n")

    if dedup_metadata.get("error"):
        print(f"Note: {dedup_metadata['error']}\n")

    if not selected_questions:
        print("No questions were selected.")
        return

    print(f"Selected {len(selected_questions)} question(s):\n")

    selected_ids = dedup_metadata.get("selected_ids", [])

    for i, q in enumerate(selected_questions, 1):
        print("-" * 80)
        print(f"SELECTED QUESTION {i}/{len(selected_questions)}")
        print("-" * 80 + "\n")

        q_id = selected_ids[i - 1] if i - 1 < len(selected_ids) else None

        if q.quote_title:
            print(f"Title: {q.quote_title}\n")

        if q.question_context:
            print(f"Context: {q.question_context}\n")

        print(f"Question: {q.framed_question}\n")

        print(f"From Agent Run: {q.agent_run_id}")

        if q_id and q_id in dedup_metadata.get("rationales", {}):
            rationale = dedup_metadata["rationales"][q_id]
            print(f"Selection Rationale: {rationale}")

        if q.novelty_rating:
            print(f"Novelty Rating: {q.novelty_rating}")
        if q.relevance_rating:
            print(f"Relevance Rating: {q.relevance_rating}")

        if q.example_options:
            print("\nSuggested options:")
            for j, option in enumerate(q.example_options, 1):
                print(f"  {j}. {option.title}")
                if option.description:
                    print(f"     {option.description}")

        print()

    print("=" * 80)
    print("DEDUPLICATION SUMMARY")
    print("=" * 80)
    print(f"Questions selected: {len(selected_questions)}")
    print(f"Question IDs: {', '.join(dedup_metadata.get('selected_ids', []))}")
    print()


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
            selection rationales

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

    # Debug: Print all question titles for inspection
    console.print("\n[bold yellow]DEBUG: All Question Titles[/bold yellow]")
    for idx, q in enumerate(questions):
        title = q.quote_title or "[No title]"
        relevance = q.relevance_rating or "N/A"
        novelty = q.novelty_rating or "N/A"
        console.print(f"  {idx + 1}. {title} (relevance={relevance}, novelty={novelty})")
    console.print()

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
        novelty = question.novelty_rating
        relevance = question.relevance_rating
        rationale = ""
        if dedup_metadata:
            selected_ids = dedup_metadata.get("selected_ids", [])
            q_id = selected_ids[idx] if idx < len(selected_ids) else None
            if q_id:
                rationale = dedup_metadata.get("rationales", {}).get(q_id, "")
        if relevance or novelty or rationale:
            if relevance:
                console.print(f"[dim]Relevance: {relevance}[/dim]")
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


class DecompositionFeedback(BaseModel):
    """Result of collecting user feedback on a decomposition proposal."""

    choice: str  # "yes", "no", or "feedback"
    feedback_text: str | None = None  # Optional user-provided feedback


def display_decomposition_proposal(proposal: DecompositionProposal) -> None:
    """
    Display a decomposition proposal using rich panels and formatting.

    Args:
        proposal: The DecompositionProposal to display
    """
    console.print("\n" + "=" * 80)
    console.print("[bold magenta]RUBRIC DECOMPOSITION ANALYSIS[/bold magenta]")
    console.print("=" * 80 + "\n")

    # Summary and recommendation
    console.print(
        Panel(
            f"[bold]Summary:[/bold] {proposal.summary}\n\n"
            f"[bold]Recommendation:[/bold] {proposal.recommendation}\n\n"
            f"[bold]Confidence:[/bold] {proposal.confidence}",
            title="[bold cyan]Analysis Overview[/bold cyan]",
            expand=False,
        )
    )

    # Proposed sub-rubrics
    if proposal.proposed_sub_rubrics:
        console.print(
            f"\n[bold]Proposed Sub-Rubrics ({len(proposal.proposed_sub_rubrics)}):[/bold]"
        )

        for i, sub_rubric in enumerate(proposal.proposed_sub_rubrics, 1):
            console.print("\n" + "-" * 60)
            console.print(f"[bold cyan]Sub-Rubric {i}: {sub_rubric.name}[/bold cyan]")
            console.print("-" * 60)

            console.print(f"\n[bold]Description:[/bold] {sub_rubric.description}")

            if sub_rubric.key_indicators:
                console.print("\n[bold]Key Indicators:[/bold]")
                for indicator in sub_rubric.key_indicators:
                    console.print(f"  - {indicator}")
    else:
        # This should not be reached since LLM is instructed to always propose at least one
        console.print("\n[yellow]Warning: No sub-rubrics proposed (unexpected).[/yellow]")

    console.print("\n" + "=" * 80)


def collect_decomposition_feedback(proposal: DecompositionProposal) -> DecompositionFeedback:
    """
    Collect user feedback on a decomposition proposal.

    Presents options to the user:
    - Yes, proceed with decomposition
    - No, keep as single rubric
    - Let me provide feedback

    Args:
        proposal: The DecompositionProposal to get feedback on

    Returns:
        DecompositionFeedback with the user's choice and optional feedback text
    """
    import beaupy
    from rich.prompt import Prompt

    console.print("\n[bold]Would you like to split this rubric into sub-rubrics?[/bold]\n")

    options = [
        "Yes, proceed with decomposition",
        "No, keep as single rubric",
        "Let me provide feedback",
    ]

    # Use beaupy for selection
    selected = beaupy.select(options, cursor="→ ", cursor_style="cyan")  # pyright: ignore[reportArgumentType]

    if selected is None or selected == options[1]:
        console.print("[dim]Keeping rubric as single unit.[/dim]\n")
        return DecompositionFeedback(choice="no")

    if selected == options[0]:
        console.print("[green]Proceeding with decomposition.[/green]\n")
        return DecompositionFeedback(choice="yes")

    # User wants to provide feedback
    feedback_text = Prompt.ask("\n[bold]Enter your feedback[/bold]")
    feedback_text = feedback_text.strip() if feedback_text else None
    console.print("[dim]Feedback recorded.[/dim]\n")
    return DecompositionFeedback(choice="feedback", feedback_text=feedback_text)


async def run_feedback_elicitation(
    collection_id: str,
    rubric_description: str,
    num_samples: int = 50,
    max_questions: int = 10,
    max_questions_per_run: int = 3,
    max_iterations: int = 10,
) -> tuple[list[ElicitedQuestion], UserData, UserModel]:
    """
    Main function for feedback elicitation.

    Iteratively extracts questions from agent runs, collects user answers,
    and updates the user model until convergence or max iterations is reached.

    Args:
        collection_id: Collection to sample from
        rubric_description: Description of the rubric to evaluate against
        num_samples: Number of agent runs to sample (default: 50)
        max_questions: Maximum questions to select per iteration (default: 10)
        max_questions_per_run: Maximum questions per agent run (default: 3)
        max_iterations: Maximum number of iterations before stopping (default: 10)

    Returns:
        Tuple of (selected_questions, user_data, user_model)
    """
    print(f"Starting feedback elicitation for collection: {collection_id}")
    print(
        f"Sampling {num_samples} agent runs, selecting up to {max_questions} questions per iteration"
    )
    print(f"Max questions per run: {max_questions_per_run}")
    print(f"Max iterations: {max_iterations}")
    print()

    # ========================================================================
    # ONE-TIME INITIALIZATION (before loop)
    # ========================================================================

    # Initialize clients
    print("Initializing clients...")
    api_key = ENV.get("DOCENT_API_KEY")
    domain = ENV.get("DOCENT_DOMAIN")

    if not api_key or not domain:
        raise ValueError("DOCENT_API_KEY and DOCENT_DOMAIN must be set in environment variables")

    dc = Docent(api_key=api_key, domain=domain, server_url="http://localhost:8902")
    llm_svc = BaseLLMService(max_concurrency=50)
    print("Clients initialized\n")

    # Sample agent runs (once at start)
    agent_runs = sample_agent_runs(dc, collection_id, num_samples=num_samples)

    # Initialize UserData (U) with initial rubric
    user_data = UserData(initial_rubric=rubric_description)

    # Initialize UserModel (z_0 = r, where r is the initial rubric)
    user_model = UserModel(
        model_text=rubric_description,
        user_data=user_data,
    )
    print(f"Initialized UserModel (z_0) with version {user_model.version}")

    # Track last selected questions for return
    selected_questions: list[ElicitedQuestion] = []

    # ========================================================================
    # MAIN ITERATION LOOP
    # ========================================================================
    for iteration in range(1, max_iterations + 1):
        print_iteration_header(iteration, user_model.version, max_iterations)

        current_model_text = user_model.model_text

        # Step 1: Extract questions from each agent run
        print("Extracting questions from agent runs...")
        extracted_questions = await extract_questions_from_agent_runs(
            agent_runs=agent_runs,
            rubric_description=user_data.initial_rubric,
            user_model_text=current_model_text,
            llm_svc=llm_svc,
            max_questions_per_run=max_questions_per_run,
        )

        display_extracted_questions(extracted_questions)

        # Sort questions by Pareto frontier over relevance+novelty before deduplication.
        sorted_questions = sort_questions_by_relevance_novelty_pareto(extracted_questions)

        # Step 2: Deduplicate and select questions
        print("\nDeduplicating and selecting questions...")
        selected_questions, dedup_metadata = await deduplicate_and_select_questions(
            questions=sorted_questions,
            llm_svc=llm_svc,
            rubric_description=user_data.initial_rubric,
            user_model_text=current_model_text,
            max_questions=max_questions,
        )

        display_selected_questions(selected_questions, dedup_metadata)

        # Convergence check #1: No questions selected
        if not selected_questions:
            console.print("\n[bold green]Converged![/bold green] No ambiguities found in rubric.\n")
            break

        # Step 3: Collect answers interactively
        print("\nCollecting user answers...")
        user_answers = collect_interactive_answers(selected_questions, dedup_metadata)

        # Convergence check #2: User skipped all questions
        if not user_answers:
            console.print(
                "\n[bold green]Converged![/bold green] "
                "User skipped all questions (satisfied with rubric).\n"
            )
            break

        # Step 4: Update UserData (U) with QA pairs
        for answer in user_answers:
            user_data.add_qa_pair(
                agent_run_id=answer.question.agent_run_id or "",
                question=answer.question.framed_question or "",
                answer=answer.answer_text,
                question_context=answer.question.question_context,
                is_custom_response=answer.is_custom_response,
            )

        # Step 5: Update UserModel (z) via LLM
        print("\nUpdating user model...")
        new_model_text = await update_user_model(
            user_data=user_data,
            current_model_text=user_model.model_text,
            llm_svc=llm_svc,
        )
        user_model.update_model(new_model_text)
        print(f"User model updated to version {user_model.version}")

        # Display the updated user model
        console.print("\n" + "=" * 80)
        console.print("[bold cyan]UPDATED USER MODEL[/bold cyan]")
        console.print("=" * 80)
        console.print(user_model.model_text)
        console.print("=" * 80 + "\n")

        # Step 6: Analyze potential decomposition (prototype)
        print("Analyzing potential rubric decomposition...")
        decomposition = await analyze_rubric_decomposition(
            user_data=user_data,
            current_model_text=user_model.model_text,
            llm_svc=llm_svc,
        )

        if decomposition:
            while True:
                display_decomposition_proposal(decomposition)
                feedback = collect_decomposition_feedback(decomposition)

                if feedback.choice == "yes":
                    console.print("[green]Proceeding with decomposition.[/green]\n")
                    # TODO: In future, actually implement the decomposition
                    break
                elif feedback.choice == "no":
                    console.print("[dim]Keeping rubric as single unit.[/dim]\n")
                    break
                else:
                    # feedback.choice == "feedback"
                    if feedback.feedback_text:
                        console.print("\n[dim]Refining decomposition based on feedback...[/dim]")
                        refined = await analyze_rubric_decomposition(
                            user_data=user_data,
                            current_model_text=user_model.model_text,
                            llm_svc=llm_svc,
                            previous_proposal=decomposition,
                            user_feedback=feedback.feedback_text,
                        )
                        if refined:
                            decomposition = refined
                        else:
                            console.print(
                                "[yellow]Refinement failed, showing previous proposal.[/yellow]"
                            )
                    else:
                        console.print("[yellow]No feedback provided, please try again.[/yellow]")
        else:
            console.print("[dim]Decomposition analysis skipped or failed.[/dim]\n")

    # ========================================================================
    # POST-LOOP: Check if hit max iterations
    # ========================================================================
    else:
        # Loop completed without break (reached max iterations)
        console.print(
            f"\n[bold yellow]Reached max iterations ({max_iterations}). Stopping.[/bold yellow]\n"
        )

    # ========================================================================
    # FINAL SUMMARY
    # ========================================================================
    console.print("\n" + "=" * 80)
    console.print("[bold green]FINAL USER MODEL[/bold green]")
    console.print("=" * 80)
    console.print(f"Version: {user_model.version}")
    console.print(f"Total QA pairs collected: {len(user_data.qa_pairs)}")
    console.print()
    console.print(user_model.model_text)
    console.print("=" * 80 + "\n")

    return selected_questions, user_data, user_model


def main() -> None:
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Extract and aggregate questions from agent runs for feedback elicitation"
    )
    parser.add_argument("collection_id", type=str, help="Collection ID to sample agent runs from")
    parser.add_argument(
        "rubric_description",
        type=str,
        help="Description of the rubric to evaluate against",
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
        default=25,
        help="Maximum number of questions to select (default: 25)",
    )
    parser.add_argument(
        "--max-questions-per-run",
        type=int,
        default=5,
        help="Maximum questions to extract per agent run (default: 5)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Maximum number of iterations before stopping (default: 10)",
    )
    args = parser.parse_args()

    try:
        asyncio.run(
            run_feedback_elicitation(
                args.collection_id,
                args.rubric_description,
                args.num_samples,
                args.max_questions,
                args.max_questions_per_run,
                args.max_iterations,
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
