#!/usr/bin/env python3
"""
Label Elicitation Script

Runs a two-stage pipeline:
1. Feedback elicitation rounds to build an initial user model via QA.
2. Label queue construction by ranking runs using H[p_u, p_j], where:
- p_j(y | x, r) is the rubric judge distribution (point-estimate by default)
- p_u(y | x, z, r) is the anticipated user-label distribution from inferred user model z

For top-ranked runs, the script generates structured labeling requests with citations
to important evidence in each run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from typing import Any, cast

from rich.console import Console
from rich.panel import Panel

from docent import Docent
from docent._llm_util.llm_svc import BaseLLMService
from docent.data_models.agent_run import AgentRun
from elicit import (
    ElicitedQuestion,
    LabelingRequestResult,
    OutputDistribution,
    RunDistributionEstimate,
    deduplicate_and_select_questions,
    estimate_label_distributions_for_agent_runs,
    extract_questions_from_agent_runs,
    generate_labeling_requests,
    infer_user_model_from_user_data,
    normalize_output_distribution,
    sort_questions_by_novelty,
    sort_runs_by_cross_entropy,
    update_user_model,
)
from user_model import UserData

console = Console()


def _require_docent_client(server_url: str) -> Docent:
    api_key = os.environ.get("DOCENT_API_KEY")
    domain = os.environ.get("DOCENT_DOMAIN")
    if not api_key or not domain:
        raise ValueError("DOCENT_API_KEY and DOCENT_DOMAIN must be set in environment variables")
    return Docent(api_key=api_key, domain=domain, server_url=server_url)


def _load_existing_labels(
    dc: Docent,
    collection_id: str,
    label_set_id: str | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if label_set_id is None:
        return None, []

    label_sets = dc.get_label_sets(collection_id)
    matching_label_set = next((ls for ls in label_sets if ls.get("id") == label_set_id), None)
    if matching_label_set is None:
        raise ValueError(f"Label set {label_set_id} not found in collection {collection_id}")

    labels = dc.get_labels(collection_id, label_set_id, filter_valid_labels=True)
    label_schema = matching_label_set.get("label_schema")
    if not isinstance(label_schema, dict):
        raise ValueError(f"Label set {label_set_id} did not include a valid label_schema")

    return cast(dict[str, Any], label_schema), labels


def _sample_agent_runs(
    dc: Docent,
    collection_id: str,
    num_samples: int,
    excluded_agent_run_ids: set[str],
    seed: int,
) -> list[AgentRun]:
    all_agent_run_ids = dc.list_agent_run_ids(collection_id)
    eligible_ids = [rid for rid in all_agent_run_ids if rid not in excluded_agent_run_ids]
    if not eligible_ids:
        return []

    sample_size = min(num_samples, len(eligible_ids))
    sampled_ids = random.Random(seed).sample(eligible_ids, k=sample_size)

    agent_runs: list[AgentRun] = []
    for idx, run_id in enumerate(sampled_ids, 1):
        run = dc.get_agent_run(collection_id, run_id)
        if run is None:
            console.print(f"[yellow]Warning:[/yellow] missing agent run {run_id}")
            continue
        agent_runs.append(run)
        if idx % 10 == 0 or idx == sample_size:
            console.print(f"Fetched {idx}/{sample_size} sampled runs")

    return agent_runs


def _build_user_data(
    initial_rubric: str,
    labels: list[dict[str, Any]],
) -> UserData:
    user_data = UserData(initial_rubric=initial_rubric)
    for label in labels:
        run_id = label.get("agent_run_id")
        label_value = label.get("label_value")
        if not isinstance(run_id, str) or not isinstance(label_value, dict):
            continue
        user_data.add_label(run_id, cast(dict[str, Any], label_value))
    return user_data


def _format_distribution(
    distribution: OutputDistribution,
    max_outcomes: int = 3,
    include_explanations: bool = False,
) -> str:
    normalized = normalize_output_distribution(distribution)
    if not normalized.outcomes:
        return "No outcomes"

    lines: list[str] = []
    for outcome in normalized.outcomes[:max_outcomes]:
        output_json = json.dumps(outcome.output, sort_keys=True)
        lines.append(f"{outcome.probability:.3f} -> {output_json}")
        if include_explanations:
            explanation = (outcome.explanation or "").strip() or "(no explanation)"
            lines.append(f"  why: {explanation}")
    return "\n".join(lines)


def _citation_preview(citations: list[Any], max_items: int = 3) -> str:
    if not citations:
        return "none"

    previews: list[str] = []
    for citation in citations[:max_items]:
        target = citation.target.item
        item_type = getattr(target, "item_type", "unknown")
        block_idx = getattr(target, "block_idx", None)
        transcript_id = getattr(target, "transcript_id", None)
        if transcript_id is not None and block_idx is not None:
            previews.append(f"{item_type}:{transcript_id}:B{block_idx}")
        elif transcript_id is not None:
            previews.append(f"{item_type}:{transcript_id}")
        else:
            previews.append(item_type)

    suffix = "" if len(citations) <= max_items else f" (+{len(citations) - max_items} more)"
    return ", ".join(previews) + suffix


def _render_labeling_requests(
    ranked_estimates: list[RunDistributionEstimate],
    request_results: list[LabelingRequestResult],
) -> None:
    estimates_by_id = {estimate.agent_run_id: estimate for estimate in ranked_estimates}

    console.print("\n" + "=" * 80)
    console.print("[bold cyan]RANKED LABELING QUEUE[/bold cyan]")
    console.print("=" * 80 + "\n")

    for idx, request_result in enumerate(request_results, 1):
        estimate = estimates_by_id.get(request_result.agent_run_id)
        if request_result.error is not None or request_result.request is None:
            console.print(
                f"{idx}. {request_result.agent_run_id} [red]ERROR[/red]: {request_result.error}"
            )
            continue

        request = request_result.request
        cross_entropy = estimate.cross_entropy if estimate is not None else None
        ce_text = f"{cross_entropy:.6f}" if cross_entropy is not None else "N/A"

        body_lines = [
            f"[bold]Run ID:[/bold] {request.agent_run_id}",
            f"[bold]H[p_u, p_j]:[/bold] {ce_text}",
            "",
            f"[bold]Review Context:[/bold] {request.review_context}",
            f"[dim]Citations: {_citation_preview(request.review_context_citations)}[/dim]",
            "",
            f"[bold]Priority Rationale:[/bold] {request.priority_rationale}",
            f"[dim]Citations: {_citation_preview(request.priority_rationale_citations)}[/dim]",
            "",
            "[bold]Review Focus:[/bold]",
        ]

        if request.review_focus:
            for focus in request.review_focus:
                body_lines.append(f"- {focus.text}")
                body_lines.append(f"  [dim]Citations: {_citation_preview(focus.citations)}[/dim]")
        else:
            body_lines.append("- (No focus items returned)")

        if estimate and estimate.judge_distribution and estimate.user_distribution:
            body_lines.extend(
                [
                    "",
                    "[bold]p_j (judge)[/bold]",
                    _format_distribution(estimate.judge_distribution),
                    "",
                    "[bold]p_u (anticipated user)[/bold]",
                    _format_distribution(estimate.user_distribution, include_explanations=True),
                ]
            )

        console.print(
            Panel(
                "\n".join(body_lines),
                title=f"[bold]{idx}. {request.title}[/bold]",
                expand=False,
            )
        )


def _render_current_rubric(rubric: Any) -> None:
    schema_text = json.dumps(rubric.output_schema, indent=2, sort_keys=True)
    console.print("\n[bold cyan]CURRENT RUBRIC[/bold cyan]")
    console.print(
        Panel(
            rubric.rubric_text,
            title=f"[bold]Rubric {rubric.id} v{rubric.version}[/bold]",
            expand=False,
        )
    )
    console.print("\n[bold cyan]CURRENT RUBRIC SCHEMA[/bold cyan]")
    console.print(Panel(schema_text, title="[bold]output_schema[/bold]", expand=False))


def _render_user_model(user_model_text: str, round_idx: int) -> None:
    console.print("\n[bold cyan]UPDATED USER MODEL[/bold cyan]")
    console.print(
        Panel(
            user_model_text,
            title=f"[bold]After Feedback Round {round_idx}[/bold]",
            expand=False,
        )
    )


def _render_feedback_questions(
    selected_questions: list[ElicitedQuestion],
    round_idx: int,
    total_rounds: int,
) -> None:
    console.print("\n" + "=" * 80)
    console.print(f"[bold cyan]FEEDBACK ROUND {round_idx}/{total_rounds}[/bold cyan]")
    console.print("=" * 80 + "\n")

    if not selected_questions:
        console.print("[yellow]No questions selected this round.[/yellow]")
        return

    console.print(f"Selected {len(selected_questions)} question(s):\n")
    for idx, question in enumerate(selected_questions, 1):
        title = question.quote_title or "Untitled ambiguity"
        context = question.question_context or "No context provided."
        prompt = question.framed_question or "No question text."
        novelty = question.novelty_rating or "N/A"
        body = (
            f"[bold]Context[/bold]\n{context}\n\n"
            f"[bold]Question[/bold]\n{prompt}\n\n"
            f"[dim]Novelty: {novelty}[/dim]"
        )
        console.print(Panel(body, title=f"[bold]{idx}. {title}[/bold]", expand=False))


def _collect_feedback_answers(
    questions: list[ElicitedQuestion],
) -> list[tuple[ElicitedQuestion, str, bool]]:
    import beaupy
    from rich.prompt import Prompt

    console.print("\n[bold]Answer feedback questions (or skip) to update the user model.[/bold]\n")
    answers: list[tuple[ElicitedQuestion, str, bool]] = []

    for idx, question in enumerate(questions, 1):
        console.print("─" * 80)
        console.print(f"[bold]Question {idx}/{len(questions)}[/bold]")
        console.print("─" * 80 + "\n")
        if question.quote_title:
            console.print(
                Panel(question.quote_title, title="[bold cyan]Title[/bold cyan]", expand=False)
            )
        if question.question_context:
            console.print(
                Panel(
                    question.question_context, title="[bold blue]Context[/bold blue]", expand=False
                )
            )
        console.print(
            Panel(
                question.framed_question or "No question text.",
                title="[bold green]Question[/bold green]",
                expand=False,
            )
        )
        console.print()

        option_display: list[str] = []
        option_values: list[str] = []
        for option in question.example_options:
            title = option.title or "Untitled option"
            description = (option.description or "").strip()
            display = f"{title}: {description}" if description else title
            option_display.append(display)
            option_values.append(display)

        custom_option = "[Write my own response]"
        skip_option = "[Skip this question]"
        option_display.append(custom_option)
        option_display.append(skip_option)

        selected = beaupy.select(
            option_display,
            cursor="→ ",
            cursor_style="cyan",
        )  # pyright: ignore[reportArgumentType]

        if selected is None or selected == skip_option:
            console.print("[dim]Skipped[/dim]\n")
            continue

        if selected == custom_option:
            custom_answer = Prompt.ask("[bold]Enter your response[/bold]").strip()
            if not custom_answer:
                console.print("[dim]Empty response, skipping[/dim]\n")
                continue
            answers.append((question, custom_answer, True))
            console.print("[green]Recorded custom response.[/green]\n")
            continue

        selected_idx = option_display.index(str(selected))
        answers.append((question, option_values[selected_idx], False))
        console.print("[green]Recorded selected option.[/green]\n")

    console.print(f"[bold]Collected {len(answers)} answer(s).[/bold]")
    return answers


async def _run_feedback_elicitation_rounds(
    agent_runs: list[AgentRun],
    feedback_rounds: int,
    feedback_max_questions: int,
    feedback_max_questions_per_run: int,
    user_data: UserData,
    user_model_text: str,
    llm_svc: BaseLLMService,
) -> str:
    current_model_text = user_model_text

    for round_idx in range(1, feedback_rounds + 1):
        extracted_questions = await extract_questions_from_agent_runs(
            agent_runs=agent_runs,
            rubric_description=current_model_text,
            llm_svc=llm_svc,
            max_questions_per_run=feedback_max_questions_per_run,
        )

        sorted_questions = sort_questions_by_novelty(extracted_questions)
        selected_questions, dedup_metadata = await deduplicate_and_select_questions(
            questions=sorted_questions,
            llm_svc=llm_svc,
            rubric_description=current_model_text,
            max_questions=feedback_max_questions,
        )

        _render_feedback_questions(selected_questions, round_idx, feedback_rounds)
        dedup_error = dedup_metadata.get("error")
        if isinstance(dedup_error, str):
            console.print(f"[yellow]Deduplication note:[/yellow] {dedup_error}")

        if not selected_questions:
            console.print(
                "[bold green]Feedback stage converged:[/bold green] no unresolved questions."
            )
            break

        answers = _collect_feedback_answers(selected_questions)
        if not answers:
            console.print("[bold yellow]Feedback stage ended:[/bold yellow] all questions skipped.")
            break

        for question, answer_text, is_custom in answers:
            user_data.add_qa_pair(
                agent_run_id=question.agent_run_id or "",
                question=question.framed_question or "",
                answer=answer_text,
                question_context=question.question_context,
                is_custom_response=is_custom,
            )

        current_model_text = await update_user_model(
            user_data=user_data,
            current_model_text=current_model_text,
            llm_svc=llm_svc,
        )
        console.print(
            f"[green]Updated user model from feedback.[/green] "
            f"Total QA pairs: {len(user_data.qa_pairs)}"
        )
        _render_user_model(current_model_text, round_idx)

    return current_model_text


async def run_label_elicitation(
    collection_id: str,
    rubric_id: str,
    label_set_id: str | None,
    server_url: str,
    feedback_rounds: int,
    feedback_num_samples: int,
    feedback_max_questions: int,
    feedback_max_questions_per_run: int,
    label_num_samples: int,
    max_label_requests: int,
    seed: int,
    include_labeled_runs: bool,
    cross_entropy_epsilon: float,
) -> None:
    if feedback_rounds < 1:
        raise ValueError("feedback_rounds must be >= 1")
    if feedback_num_samples <= 0:
        raise ValueError("feedback_num_samples must be > 0")
    if feedback_max_questions <= 0:
        raise ValueError("feedback_max_questions must be > 0")
    if feedback_max_questions_per_run <= 0:
        raise ValueError("feedback_max_questions_per_run must be > 0")
    if label_num_samples <= 0:
        raise ValueError("label_num_samples must be > 0")
    if max_label_requests <= 0:
        raise ValueError("max_label_requests must be > 0")
    if cross_entropy_epsilon <= 0:
        raise ValueError("cross_entropy_epsilon must be > 0")

    console.print("[bold]Initializing clients...[/bold]")
    dc = _require_docent_client(server_url)
    llm_svc = BaseLLMService(max_concurrency=50)

    rubric = dc.get_rubric(collection_id, rubric_id)
    console.print(f"Loaded rubric {rubric.id} v{rubric.version}")
    _render_current_rubric(rubric)

    label_schema, labels = _load_existing_labels(dc, collection_id, label_set_id)
    if label_schema is not None:
        console.print(f"Loaded label set {label_set_id} with {len(labels)} label(s)")
    else:
        console.print("No label set provided; user model will be inferred from rubric only")

    user_data = _build_user_data(rubric.rubric_text, labels)
    user_model_text = await infer_user_model_from_user_data(user_data, llm_svc)

    console.print(
        "\n[bold]Feedback stage:[/bold] "
        f"up to {feedback_rounds} round(s), sample size {feedback_num_samples}"
    )
    feedback_agent_runs = _sample_agent_runs(
        dc,
        collection_id,
        num_samples=feedback_num_samples,
        excluded_agent_run_ids=set(),
        seed=seed,
    )
    if not feedback_agent_runs:
        raise ValueError("No agent runs available for feedback elicitation sampling.")

    user_model_text = await _run_feedback_elicitation_rounds(
        agent_runs=feedback_agent_runs,
        feedback_rounds=feedback_rounds,
        feedback_max_questions=feedback_max_questions,
        feedback_max_questions_per_run=feedback_max_questions_per_run,
        user_data=user_data,
        user_model_text=user_model_text,
        llm_svc=llm_svc,
    )
    if not user_data.qa_pairs:
        console.print(
            "[yellow]No feedback answers collected.[/yellow] "
            "Continuing with model inferred from rubric/labels."
        )

    if include_labeled_runs:
        excluded_ids: set[str] = set()
    else:
        excluded_ids = {label.agent_run_id for label in user_data.labels}

    console.print(
        f"\n[bold]Label stage:[/bold] sampling up to {label_num_samples} run(s); "
        f"excluding {len(excluded_ids)} labeled run(s)"
    )
    agent_runs = _sample_agent_runs(
        dc,
        collection_id,
        num_samples=label_num_samples,
        excluded_agent_run_ids=excluded_ids,
        seed=seed,
    )
    if not agent_runs:
        raise ValueError("No agent runs available after filtering/sampling.")

    console.print(
        f"Estimating p_j and p_u for {len(agent_runs)} run(s) in parallel (judge is point-estimate)"
    )
    estimates = await estimate_label_distributions_for_agent_runs(
        agent_runs=agent_runs,
        rubric=rubric,
        user_model_text=user_model_text,
        user_data=user_data,
        llm_svc=llm_svc,
        judge_point_estimate=True,
        cross_entropy_epsilon=cross_entropy_epsilon,
    )
    ranked_estimates = sort_runs_by_cross_entropy(estimates)

    num_valid = sum(
        1
        for estimate in ranked_estimates
        if estimate.error is None and estimate.cross_entropy is not None
    )
    console.print(f"Computed disagreement scores for {num_valid}/{len(ranked_estimates)} run(s)")

    console.print(f"Generating labeling requests for top {max_label_requests} run(s)")
    request_results = await generate_labeling_requests(
        agent_runs=agent_runs,
        estimates=ranked_estimates,
        user_model_text=user_model_text,
        llm_svc=llm_svc,
        max_requests=max_label_requests,
    )
    _render_labeling_requests(ranked_estimates, request_results)

    console.print("\n" + "=" * 80)
    console.print("[bold green]DONE[/bold green]")
    console.print("=" * 80)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run feedback elicitation rounds to build a user model, then rank agent runs "
            "for human labeling via H[p_u, p_j]."
        )
    )
    parser.add_argument("collection_id", type=str, help="Collection ID")
    parser.add_argument("rubric_id", type=str, help="Rubric ID")
    parser.add_argument(
        "--label-set-id",
        type=str,
        default=None,
        help="Optional label set ID used to build user data U",
    )
    parser.add_argument(
        "--server-url",
        type=str,
        default="http://localhost:8902",
        help="Docent API server URL (default: http://localhost:8902)",
    )
    parser.add_argument(
        "--feedback-rounds",
        type=int,
        default=1,
        help="Number of initial feedback elicitation rounds (default: 1, minimum: 1)",
    )
    parser.add_argument(
        "--feedback-num-samples",
        type=int,
        default=50,
        help="Number of agent runs sampled for feedback elicitation (default: 50)",
    )
    parser.add_argument(
        "--feedback-max-questions",
        type=int,
        default=10,
        help="Max selected feedback questions per round (default: 10)",
    )
    parser.add_argument(
        "--feedback-max-questions-per-run",
        type=int,
        default=3,
        help="Max extracted feedback questions per sampled run (default: 3)",
    )
    parser.add_argument(
        "--label-num-samples",
        type=int,
        default=50,
        help="Number of agent runs sampled for label queue ranking (default: 50)",
    )
    parser.add_argument(
        "--max-label-requests",
        type=int,
        default=20,
        help="Max ranked runs to generate labeling requests for (default: 20)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Random seed for subsampling (default: 0)",
    )
    parser.add_argument(
        "--include-labeled-runs",
        action="store_true",
        help="Include already-labeled runs in the subsample",
    )
    parser.add_argument(
        "--cross-entropy-epsilon",
        type=float,
        default=1e-2,
        help="Epsilon smoothing constant for H[p_u, p_j] (default: 1e-2)",
    )
    args = parser.parse_args()

    try:
        asyncio.run(
            run_label_elicitation(
                collection_id=args.collection_id,
                rubric_id=args.rubric_id,
                label_set_id=args.label_set_id,
                server_url=args.server_url,
                feedback_rounds=args.feedback_rounds,
                feedback_num_samples=args.feedback_num_samples,
                feedback_max_questions=args.feedback_max_questions,
                feedback_max_questions_per_run=args.feedback_max_questions_per_run,
                label_num_samples=args.label_num_samples,
                max_label_requests=args.max_label_requests,
                seed=args.seed,
                include_labeled_runs=args.include_labeled_runs,
                cross_entropy_epsilon=args.cross_entropy_epsilon,
            )
        )
    except KeyboardInterrupt:
        console.print("\nInterrupted by user")
        sys.exit(1)
    except Exception as exc:
        console.print(f"\n[red]ERROR:[/red] {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
