#!/usr/bin/env python3
"""
Label Elicitation (Entropy-Only)

Standalone entropy-prioritized label elicitation runner that only:
1. Loads rubric/user model context.
2. Samples agent runs.
3. Estimates user output distributions p_u(y | x, z, r).
4. Computes Shannon entropy H[p_u] on rubric agreement keys.
5. Prints highest-entropy runs (descending).
6. Generates labeling requests for top-ranked runs from p_u outcomes + reasoning.
7. Interactively collects user labels for top-ranked runs.
8. Dumps collected labels to a JSON artifact.

This script never runs the rubric judge distribution p_j and never computes cross-entropy.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel
from rich.console import Console
from rich.panel import Panel
from tqdm import tqdm

from docent import Docent
from docent._llm_util.llm_svc import BaseLLMService
from docent.data_models.agent_run import AgentRun
from docent.data_models.citation import InlineCitation
from docent.judges.types import Rubric
from docent_core._env_util import ENV
from docent_core.docent.ai_tools.rubric.elicit import (
    LabelingRequestResult,
    OutputDistribution,
    RunDistributionEstimate,
    SchemaSelectableField,
    build_agent_run_dashboard_url,
    build_user_model_inference_prompt_with_agent_runs,
    estimate_user_distributions_for_agent_runs,
    generate_labeling_requests,
    get_enum_boolean_fields_from_schema,
    infer_user_model_from_user_data,
    normalize_output_distribution,
    render_text_with_citation_footnotes,
)
from docent_core.docent.ai_tools.rubric.user_model import LabelingRequest, UserData

console = Console()
AGENT_RUN_FETCH_MAX_CONCURRENCY = 25


class EntropyLabelMetadata(BaseModel):
    user_distribution: OutputDistribution
    entropy_nats: float


class CollectedEntropyLabel(BaseModel):
    agent_run_id: str
    label_value: dict[str, Any]
    explanation: str | None = None
    metadata: EntropyLabelMetadata
    labeling_request: LabelingRequest | None = None


def _coerce_string_keyed_dict(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    parsed: dict[str, Any] = {}
    for key, item in cast(dict[object, object], value).items():
        if not isinstance(key, str):
            return None
        parsed[key] = item
    return parsed


def _require_docent_client() -> Docent:
    _ = ENV  # load env
    return Docent()


def _require_openai_api_key() -> str:
    openai_api_key = ENV.get("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY must be set in environment variables")
    return openai_api_key


def _load_user_data(initial_rubric: str, user_data_json_path: str | None) -> UserData:
    if user_data_json_path is None:
        console.print("No user data JSON provided; user model will be inferred from rubric only")
        return UserData(initial_rubric=initial_rubric)

    path = Path(user_data_json_path)
    if not path.exists():
        raise ValueError(f"--user-data-json file does not exist: {path}")

    payload_raw = json.loads(path.read_text(encoding="utf-8"))
    payload_dict = _coerce_string_keyed_dict(payload_raw)
    if payload_dict is None:
        raise ValueError("--user-data-json must contain a JSON object matching UserData")

    user_data = UserData.model_validate(payload_dict)
    if user_data.initial_rubric != initial_rubric:
        console.print(
            "[yellow]Loaded user_data.initial_rubric differs from current rubric; "
            "overriding with current rubric text.[/yellow]"
        )
    user_data.initial_rubric = initial_rubric
    console.print(
        f"Loaded user data JSON with {len(user_data.labels)} label(s) "
        f"and {len(user_data.qa_pairs)} QA pair(s): {path}"
    )
    return user_data


def _get_user_data_agent_run_ids(user_data: UserData) -> list[str]:
    run_ids = {qa_pair.agent_run_id for qa_pair in user_data.qa_pairs}
    run_ids.update(label.agent_run_id for label in user_data.labels)
    return sorted(run_ids)


def _load_user_data_agent_runs(
    dc: Docent,
    collection_id: str,
    user_data: UserData,
) -> dict[str, AgentRun]:
    run_ids = _get_user_data_agent_run_ids(user_data)
    if not run_ids:
        return {}

    console.print(f"Loading {len(run_ids)} user-data agent run(s) for prompt summaries")
    agent_runs_by_id = _load_agent_runs_by_ids(
        dc=dc,
        collection_id=collection_id,
        run_ids=run_ids,
        progress_desc="Fetching user-data runs",
        missing_run_template="[red]Error:[/red] missing user-data agent run {run_id}",
    )

    missing = len(run_ids) - len(agent_runs_by_id)
    if missing > 0:
        console.print(
            f"[yellow]Skipped {missing} user-data item(s) because their agent run was missing.[/yellow]"
        )
    return agent_runs_by_id


def _load_agent_runs_by_ids(
    dc: Docent,
    collection_id: str,
    run_ids: Sequence[str],
    progress_desc: str,
    missing_run_template: str = "[yellow]Warning:[/yellow] missing agent run {run_id}",
) -> dict[str, AgentRun]:
    if not run_ids:
        return {}

    agent_runs_by_id: dict[str, AgentRun] = {}
    with ThreadPoolExecutor(max_workers=AGENT_RUN_FETCH_MAX_CONCURRENCY) as executor:
        future_to_run_id = {
            executor.submit(dc.get_agent_run, collection_id, run_id): run_id for run_id in run_ids
        }
        for future in tqdm(
            as_completed(future_to_run_id),
            total=len(future_to_run_id),
            desc=progress_desc,
        ):
            run_id = future_to_run_id[future]
            run = future.result()
            if run is None:
                console.print(missing_run_template.format(run_id=run_id))
                continue
            agent_runs_by_id[run_id] = run
    return agent_runs_by_id


def _sample_agent_runs(
    dc: Docent,
    collection_id: str,
    num_samples: int,
    excluded_agent_run_ids: set[str],
    seed: int,
    where_clause: str | None,
) -> list[AgentRun]:
    all_agent_run_ids = dc.select_agent_run_ids(
        collection_id,
        where_clause=where_clause,
        limit=1_000,
    )
    print(f"Loaded {len(all_agent_run_ids)} agent runs from DQL")
    eligible_ids = [rid for rid in all_agent_run_ids if rid not in excluded_agent_run_ids]
    if not eligible_ids:
        return []

    sample_size = min(num_samples, len(eligible_ids))
    sampled_ids = random.Random(seed).sample(eligible_ids, k=sample_size)

    agent_runs_by_id = _load_agent_runs_by_ids(
        dc=dc,
        collection_id=collection_id,
        run_ids=sampled_ids,
        progress_desc="Fetching sampled runs",
    )
    return [agent_runs_by_id[run_id] for run_id in sampled_ids if run_id in agent_runs_by_id]


def _render_current_rubric(rubric: Rubric) -> None:
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


def _render_user_model(user_model_text: str) -> None:
    console.print("\n[bold cyan]INFERRED USER MODEL[/bold cyan]")
    console.print(
        Panel(
            user_model_text,
            title="[bold]Initial User Model[/bold]",
            expand=False,
        )
    )


def _render_user_data_prompt_summary(user_data_summary: str) -> None:
    console.print("\n[bold cyan]USER DATA FOR INFERENCE[/bold cyan]")
    console.print(
        Panel(
            user_data_summary,
            title="[bold]Constructed User Data (U)[/bold]",
            expand=False,
        )
    )


def _stable_json_dict(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _get_schema_property_keys(output_schema: dict[str, Any]) -> list[str]:
    properties = _coerce_string_keyed_dict(output_schema.get("properties"))
    if properties is None:
        return []
    return list(properties.keys())


def _get_entropy_agreement_keys(output_schema: dict[str, Any]) -> list[str]:
    return list(get_enum_boolean_fields_from_schema(output_schema).keys())


def _project_output_for_entropy(output: dict[str, Any], agreement_keys: set[str]) -> dict[str, Any]:
    return {key: output[key] for key in agreement_keys if key in output}


def _aggregate_projected_items(
    distribution: OutputDistribution,
    agreement_keys: set[str],
) -> list[tuple[dict[str, Any], float]]:
    normalized = normalize_output_distribution(distribution)
    if not normalized.outcomes:
        return []

    projected_prob_map: dict[str, tuple[dict[str, Any], float]] = {}
    for outcome in normalized.outcomes:
        projected_output = _project_output_for_entropy(outcome.output, agreement_keys)
        projected_key = _stable_json_dict(projected_output)
        existing = projected_prob_map.get(projected_key)
        if existing is None:
            projected_prob_map[projected_key] = (
                projected_output,
                outcome.probability,
            )
        else:
            projected_prob_map[projected_key] = (
                projected_output,
                existing[1] + outcome.probability,
            )

    total_mass = sum(prob for _, prob in projected_prob_map.values())
    if total_mass <= 0:
        return []

    projected = [(output, prob / total_mass) for output, prob in projected_prob_map.values()]
    return sorted(projected, key=lambda item: item[1], reverse=True)


def _compute_entropy(distribution: OutputDistribution, agreement_keys: set[str]) -> float:
    if not agreement_keys:
        return 0.0

    aggregated = _aggregate_projected_items(distribution, agreement_keys)
    if not aggregated:
        return 0.0

    entropy = 0.0
    for _, probability in aggregated:
        if probability > 0:
            entropy -= probability * math.log(probability)
    return entropy


def _format_projected_distribution(
    distribution: OutputDistribution,
    agreement_keys: set[str],
    max_outcomes: int = 3,
) -> str:
    aggregated = _aggregate_projected_items(distribution, agreement_keys)
    if not aggregated:
        return "No outcomes"

    lines: list[str] = []
    for output, probability in aggregated[:max_outcomes]:
        lines.append(f"{probability:.3f} -> {json.dumps(output, sort_keys=True)}")
    return "\n".join(lines)


def _run_reference_lines(
    frontend_url: str,
    collection_id: str,
    agent_run_id: str,
) -> list[str]:
    run_url = build_agent_run_dashboard_url(
        frontend_url=frontend_url,
        collection_id=collection_id,
        agent_run_id=agent_run_id,
    )
    return [
        f"[bold]Run ID:[/bold] [link={run_url}]{agent_run_id}[/link]",
        f"[bold]Run URL:[/bold] {run_url}",
    ]


def _render_entropy_rankings(
    ranked: list[tuple[RunDistributionEstimate, float]],
    agreement_keys: list[str],
    top_n: int,
    collection_id: str,
    frontend_url: str,
) -> None:
    console.print("\n" + "=" * 80)
    console.print("[bold cyan]HIGHEST ENTROPY USER DISTRIBUTIONS[/bold cyan]")
    console.print("=" * 80 + "\n")

    if not ranked:
        console.print("[yellow]No valid user distributions were estimated.[/yellow]")
        return

    console.print(
        f"Scoring keys ({len(agreement_keys)}): "
        f"{', '.join(agreement_keys) if agreement_keys else '(none)'}"
    )
    console.print(f"Showing top {min(top_n, len(ranked))} of {len(ranked)} valid run(s)\n")

    key_set = set(agreement_keys)
    for idx, (estimate, entropy) in enumerate(ranked[:top_n], 1):
        user_distribution = _require_user_distribution(estimate)
        distribution_reasoning = (user_distribution.reasoning or "").strip() or None
        body_lines = [
            *_run_reference_lines(
                frontend_url=frontend_url,
                collection_id=collection_id,
                agent_run_id=estimate.agent_run_id,
            ),
            f"[bold]Entropy H[p_u]:[/bold] {entropy:.6f} nats",
            "",
            "[bold]p_u projected to agreement keys[/bold]",
            _format_projected_distribution(user_distribution, key_set),
        ]
        if distribution_reasoning:
            reasoning_text, reasoning_footnotes = render_text_with_citation_footnotes(
                text=distribution_reasoning,
                citations=user_distribution.reasoning_citations,
            )
            body_lines.extend(["", "[bold]p_u reasoning[/bold]", reasoning_text])
            if reasoning_footnotes:
                body_lines.append("[dim]Citations:[/dim]")
                for footnote in reasoning_footnotes:
                    body_lines.append(f"  [dim]{footnote}[/dim]")
        console.print(
            Panel(
                "\n".join(body_lines),
                title=f"[bold]{idx}[/bold]",
                expand=False,
            )
        )


def _append_section_with_citations(
    body_lines: list[str],
    title: str,
    text: str,
    citations: Sequence[InlineCitation],
    line_prefix: str = "",
) -> None:
    rendered_text, footnotes = render_text_with_citation_footnotes(text=text, citations=citations)
    body_lines.append(f"{line_prefix}[bold]{title}:[/bold] {rendered_text}")
    if footnotes:
        body_lines.append(f"{line_prefix}[dim]Citations:[/dim]")
        for footnote in footnotes:
            body_lines.append(f"{line_prefix}  [dim]{footnote}[/dim]")


def _render_generated_labeling_requests(
    ranked: list[tuple[RunDistributionEstimate, float]],
    request_results: list[LabelingRequestResult],
    agreement_keys: list[str],
    collection_id: str,
    frontend_url: str,
) -> None:
    console.print("\n" + "=" * 80)
    console.print("[bold cyan]GENERATED LABELING REQUESTS[/bold cyan]")
    console.print("=" * 80 + "\n")

    if not request_results:
        console.print("[yellow]No labeling requests were generated.[/yellow]")
        return

    estimates_by_id = {estimate.agent_run_id: (estimate, entropy) for estimate, entropy in ranked}
    agreement_key_set = set(agreement_keys)
    for idx, request_result in enumerate(request_results, 1):
        estimate_tuple = estimates_by_id.get(request_result.agent_run_id)
        entropy_text = "N/A"
        user_distribution: OutputDistribution | None = None
        if estimate_tuple is not None:
            estimate, entropy = estimate_tuple
            entropy_text = f"{entropy:.6f}"
            user_distribution = estimate.user_distribution

        if request_result.error is not None or request_result.request is None:
            run_url = build_agent_run_dashboard_url(
                frontend_url=frontend_url,
                collection_id=collection_id,
                agent_run_id=request_result.agent_run_id,
            )
            console.print(
                f"{idx}. {request_result.agent_run_id} ({run_url}) "
                f"[red]ERROR[/red]: {request_result.error}"
            )
            continue

        request = request_result.request
        body_lines = [
            *_run_reference_lines(
                frontend_url=frontend_url,
                collection_id=collection_id,
                agent_run_id=request.agent_run_id,
            ),
            f"[bold]Entropy H[p_u]:[/bold] {entropy_text} nats",
            "",
        ]
        _append_section_with_citations(
            body_lines=body_lines,
            title="Review Context",
            text=request.review_context,
            citations=request.review_context_citations,
        )
        body_lines.extend(["", "[bold]Review Focus:[/bold]"])
        if request.review_focus:
            for focus in request.review_focus:
                focus_text, focus_footnotes = render_text_with_citation_footnotes(
                    text=focus.text,
                    citations=focus.citations,
                )
                body_lines.append(f"- {focus_text}")
                if focus_footnotes:
                    body_lines.append("  [dim]Citations:[/dim]")
                    for footnote in focus_footnotes:
                        body_lines.append(f"    [dim]{footnote}[/dim]")
        else:
            body_lines.append("- (No focus items returned)")

        if user_distribution is not None:
            distribution_reasoning = (user_distribution.reasoning or "").strip() or None
            body_lines.extend(
                [
                    "",
                    "[bold]p_u projected to agreement keys[/bold]",
                    _format_projected_distribution(user_distribution, agreement_key_set),
                ]
            )
            if distribution_reasoning:
                reasoning_text, reasoning_footnotes = render_text_with_citation_footnotes(
                    text=distribution_reasoning,
                    citations=user_distribution.reasoning_citations,
                )
                body_lines.extend(["", "[bold]p_u reasoning[/bold]", reasoning_text])
                if reasoning_footnotes:
                    body_lines.append("[dim]Citations:[/dim]")
                    for footnote in reasoning_footnotes:
                        body_lines.append(f"  [dim]{footnote}[/dim]")

        console.print(
            Panel(
                "\n".join(body_lines),
                title=f"[bold]{idx}. {request.title}[/bold]",
                expand=False,
            )
        )


def _format_option_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def _require_user_distribution(estimate: RunDistributionEstimate) -> OutputDistribution:
    user_distribution = estimate.user_distribution
    if user_distribution is None:
        raise ValueError(f"Missing user distribution for run {estimate.agent_run_id}")
    return user_distribution


def _build_label_metadata(
    estimate: RunDistributionEstimate,
    entropy: float,
) -> EntropyLabelMetadata:
    return EntropyLabelMetadata(
        user_distribution=_require_user_distribution(estimate),
        entropy_nats=entropy,
    )


def _build_label_explanation(explicit_explanation: str) -> str | None:
    stripped_explanation = explicit_explanation.strip()
    if stripped_explanation:
        return stripped_explanation
    return None


def _collect_labels_for_run(
    rank_idx: int,
    estimate: RunDistributionEstimate,
    entropy: float,
    all_schema_keys: list[str],
    selectable_fields: dict[str, SchemaSelectableField],
    agreement_keys: set[str],
    labeling_request: LabelingRequest | None,
    collection_id: str,
    frontend_url: str,
) -> tuple[CollectedEntropyLabel | None, bool]:
    import beaupy
    from rich.prompt import Prompt

    user_distribution = _require_user_distribution(estimate)

    body_lines = [
        *_run_reference_lines(
            frontend_url=frontend_url,
            collection_id=collection_id,
            agent_run_id=estimate.agent_run_id,
        ),
        f"[bold]Entropy H[p_u]:[/bold] {entropy:.6f} nats",
    ]
    if labeling_request is not None:
        body_lines.extend(
            [
                "",
                f"[bold]Labeling Request:[/bold] {labeling_request.title}",
                "",
            ]
        )
        _append_section_with_citations(
            body_lines=body_lines,
            title="Review Context",
            text=labeling_request.review_context,
            citations=labeling_request.review_context_citations,
        )
        body_lines.extend(["", "[bold]Review Focus:[/bold]"])
        if labeling_request.review_focus:
            for focus in labeling_request.review_focus:
                focus_text, focus_footnotes = render_text_with_citation_footnotes(
                    text=focus.text,
                    citations=focus.citations,
                )
                body_lines.append(f"- {focus_text}")
                if focus_footnotes:
                    body_lines.append("  [dim]Citations:[/dim]")
                    for footnote in focus_footnotes:
                        body_lines.append(f"    [dim]{footnote}[/dim]")
        else:
            body_lines.append("- (No focus items returned)")
    else:
        body_lines.extend(
            [
                "",
                "[yellow]No labeling request available for this run.[/yellow]",
            ]
        )

    distribution_reasoning = (user_distribution.reasoning or "").strip() or None
    body_lines.extend(
        [
            "",
            "[bold]p_u projected to agreement keys[/bold]",
            _format_projected_distribution(user_distribution, agreement_keys),
        ]
    )
    if distribution_reasoning:
        reasoning_text, reasoning_footnotes = render_text_with_citation_footnotes(
            text=distribution_reasoning,
            citations=user_distribution.reasoning_citations,
        )
        body_lines.extend(["", "[bold]p_u reasoning[/bold]", reasoning_text])
        if reasoning_footnotes:
            body_lines.append("[dim]Citations:[/dim]")
            for footnote in reasoning_footnotes:
                body_lines.append(f"  [dim]{footnote}[/dim]")
    console.print()
    console.print(
        Panel(
            "\n".join(body_lines),
            title=f"[bold]Labeling Run {rank_idx}[/bold]",
            expand=False,
        )
    )

    skip_run_option = "[Skip this run]"
    skip_future_runs_option = "[Skip this and all future runs]"
    restart_run_option = "[Restart this run]"
    run_selection = beaupy.select(
        ["[Label this run]", skip_run_option, skip_future_runs_option],
        cursor="> ",
        cursor_style="cyan",
    )  # pyright: ignore[reportArgumentType]
    if run_selection is None or str(run_selection) == skip_run_option:
        return None, False

    if str(run_selection) == skip_future_runs_option:
        return None, True

    restart_reasoning_commands = {"/restart", "/undo", "/refresh"}

    while True:
        label_value: dict[str, Any] = {}
        should_restart_run = False
        for key in all_schema_keys:
            field_info = selectable_fields.get(key)
            if field_info is None:
                continue

            raw_options = field_info.options
            if not raw_options:
                continue

            console.print(f"\n[bold]Select value for key:[/bold] {key}")
            option_display = [_format_option_value(option) for option in raw_options]
            skip_key_option = "[Skip this key]"
            option_display.append(skip_key_option)
            option_display.append(restart_run_option)

            selected_option = beaupy.select(
                option_display,
                cursor="> ",
                cursor_style="cyan",
            )  # pyright: ignore[reportArgumentType]

            if str(selected_option) == restart_run_option:
                should_restart_run = True
                break

            if selected_option is None or str(selected_option) == skip_key_option:
                continue

            selected_idx = option_display.index(str(selected_option))
            label_value[key] = raw_options[selected_idx]

        if should_restart_run:
            console.print("[yellow]Restarting this run from the first key.[/yellow]")
            continue

        if not label_value:
            return None, False

        explicit_explanation = Prompt.ask(
            "[bold]Overall explanation for this run[/bold] "
            "[dim](optional; press Enter to skip, or /restart to redo this run)[/dim]",
            default="",
        ).strip()
        if explicit_explanation.lower() in restart_reasoning_commands:
            console.print("[yellow]Restarting this run from the first key.[/yellow]")
            continue

        label_explanation = _build_label_explanation(explicit_explanation=explicit_explanation)
        metadata = _build_label_metadata(
            estimate=estimate,
            entropy=entropy,
        )
        return (
            CollectedEntropyLabel(
                agent_run_id=estimate.agent_run_id,
                label_value=label_value,
                explanation=label_explanation,
                metadata=metadata,
                labeling_request=labeling_request,
            ),
            False,
        )


def _collect_entropy_labels(
    ranked: list[tuple[RunDistributionEstimate, float]],
    output_schema: dict[str, Any],
    agreement_keys: list[str],
    labeling_requests_by_run_id: dict[str, LabelingRequest],
    collection_id: str,
    frontend_url: str,
) -> tuple[list[CollectedEntropyLabel], bool, int]:
    import beaupy

    if not ranked:
        return [], False, 0

    all_schema_keys = _get_schema_property_keys(output_schema)
    selectable_fields = get_enum_boolean_fields_from_schema(output_schema)

    console.print("\n" + "=" * 80)
    console.print("[bold cyan]INTERACTIVE LABEL COLLECTION[/bold cyan]")
    console.print("=" * 80)
    console.print(
        "This phase records answers in memory and supports skipping runs/keys at any point."
    )

    if not all_schema_keys:
        console.print("[yellow]Rubric output_schema has no top-level properties to label.[/yellow]")

    skip_stage_option = "[Skip labeling phase]"
    stage_selection = beaupy.select(
        ["[Start labeling phase]", skip_stage_option],
        cursor="> ",
        cursor_style="cyan",
    )  # pyright: ignore[reportArgumentType]
    if stage_selection is None or str(stage_selection) == skip_stage_option:
        console.print("[yellow]Labeling phase skipped.[/yellow]")
        return [], True, 0

    collected_labels: list[CollectedEntropyLabel] = []
    displayed_runs = 0
    agreement_key_set = set(agreement_keys)
    for rank_idx, (estimate, entropy) in enumerate(ranked, 1):
        displayed_runs += 1
        collected_label, should_skip_future_runs = _collect_labels_for_run(
            rank_idx=rank_idx,
            estimate=estimate,
            entropy=entropy,
            all_schema_keys=all_schema_keys,
            selectable_fields=selectable_fields,
            agreement_keys=agreement_key_set,
            labeling_request=labeling_requests_by_run_id.get(estimate.agent_run_id),
            collection_id=collection_id,
            frontend_url=frontend_url,
        )
        if collected_label is not None:
            collected_labels.append(collected_label)
        if should_skip_future_runs:
            console.print("[yellow]Skipping all remaining runs.[/yellow]")
            break

    return collected_labels, False, displayed_runs


def _default_output_json_path() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return str(Path("outputs") / f"user_data_{timestamp}_gitignore.json")


def write_user_data_json(user_data: UserData, output_json_path: str | None) -> Path:
    path = (
        Path(output_json_path)
        if output_json_path is not None
        else Path(_default_output_json_path())
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = user_data.model_dump(mode="json")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


async def run_entropy_elicitation(
    collection_id: str,
    rubric_id: str,
    user_data_json_path: str | None,
    where_clause: str | None,
    label_num_samples: int,
    seed: int,
    top_n: int,
    output_json_path: str | None,
) -> None:
    if label_num_samples <= 0:
        raise ValueError("label_num_samples must be > 0")
    if top_n <= 0:
        raise ValueError("top_n must be > 0")

    console.print("[bold]Initializing clients...[/bold]")
    dc = _require_docent_client()
    _require_openai_api_key()
    llm_svc = BaseLLMService(max_concurrency=100)

    rubric = dc.get_rubric(collection_id, rubric_id)
    console.print(f"Loaded rubric {rubric.id} v{rubric.version}")
    _render_current_rubric(rubric)

    user_data = _load_user_data(
        initial_rubric=rubric.rubric_text,
        user_data_json_path=user_data_json_path,
    )
    user_data_agent_runs = _load_user_data_agent_runs(dc, collection_id, user_data)
    user_data_summary, _ = await build_user_model_inference_prompt_with_agent_runs(
        user_data=user_data,
        agent_runs_by_id=user_data_agent_runs,
        llm_svc=llm_svc,
    )
    _render_user_data_prompt_summary(user_data_summary)
    user_model_text = await infer_user_model_from_user_data(
        user_data,
        llm_svc,
        user_data_summary=user_data_summary,
    )
    _render_user_model(user_model_text)

    excluded_ids = {label.agent_run_id for label in user_data.labels}

    console.print(
        f"\n[bold]Entropy stage:[/bold] sampling up to {label_num_samples} run(s); "
        f"excluding {len(excluded_ids)} labeled run(s)"
    )
    agent_runs = _sample_agent_runs(
        dc,
        collection_id,
        num_samples=label_num_samples,
        excluded_agent_run_ids=excluded_ids,
        seed=seed,
        where_clause=where_clause,
    )
    if not agent_runs:
        raise ValueError("No agent runs available after filtering/sampling.")

    console.print(f"Estimating p_u for {len(agent_runs)} run(s) in parallel")
    estimates = await estimate_user_distributions_for_agent_runs(
        agent_runs=agent_runs,
        rubric=rubric,
        user_model_text=user_model_text,
        llm_svc=llm_svc,
    )

    # # TODO(mengk): remove this temporary p_u reasoning JSON dump once debugging is done.
    # sampled_p_u_reasoning_blocks = [
    #     (estimate.user_distribution.reasoning or "").strip()
    #     for estimate in estimates
    #     if estimate.user_distribution is not None
    # ]
    # p_u_reasoning_dump_path = (
    #     Path("outputs")
    #     / f"p_u_reasoning_blocks_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_gitignore.json"
    # )
    # p_u_reasoning_dump_path.parent.mkdir(parents=True, exist_ok=True)
    # p_u_reasoning_dump_path.write_text(
    #     json.dumps(sampled_p_u_reasoning_blocks, indent=2) + "\n",
    #     encoding="utf-8",
    # )
    # console.print(
    #     f"Wrote temporary p_u reasoning JSON dump to: [bold]{p_u_reasoning_dump_path}[/bold]"
    # )
    # raise

    agreement_keys = _get_entropy_agreement_keys(rubric.output_schema)

    ranked: list[tuple[RunDistributionEstimate, float]] = []
    for estimate in estimates:
        if estimate.error is not None or estimate.user_distribution is None:
            continue
        entropy = _compute_entropy(estimate.user_distribution, set(agreement_keys))
        ranked.append((estimate, entropy))
    ranked.sort(key=lambda item: item[1], reverse=True)

    num_errors = sum(1 for estimate in estimates if estimate.error is not None)
    console.print(
        f"Computed entropy for {len(ranked)}/{len(estimates)} run(s); errors: {num_errors}"
    )
    if num_errors:
        console.print(
            "[yellow]Some runs failed p_u estimation and were excluded from ranking.[/yellow]"
        )

    frontend_url = dc.frontend_url
    _render_entropy_rankings(
        ranked,
        agreement_keys=agreement_keys,
        top_n=top_n,
        collection_id=collection_id,
        frontend_url=frontend_url,
    )

    top_ranked = ranked[:top_n]
    top_estimates = [estimate for estimate, _ in top_ranked]
    top_entropies_by_run_id = {estimate.agent_run_id: entropy for estimate, entropy in top_ranked}
    runs_by_id = {run.id: run for run in agent_runs}
    top_runs = [
        runs_by_id[estimate.agent_run_id]
        for estimate in top_estimates
        if estimate.agent_run_id in runs_by_id
    ]

    console.print(
        f"Generating labeling requests for top {len(top_estimates)} entropy-ranked run(s)"
    )
    request_results = await generate_labeling_requests(
        agent_runs=top_runs,
        estimates=top_estimates,
        rubric=rubric,
        user_model_text=user_model_text,
        llm_svc=llm_svc,
        max_requests=len(top_estimates),
        priority_scores_by_run_id=top_entropies_by_run_id,
        priority_metric_name="H[p_u]",
    )
    _render_generated_labeling_requests(
        ranked=top_ranked,
        request_results=request_results,
        agreement_keys=agreement_keys,
        collection_id=collection_id,
        frontend_url=frontend_url,
    )
    labeling_requests_by_run_id = {
        result.agent_run_id: result.request
        for result in request_results
        if result.request is not None
    }

    collected_labels, stage_skipped, displayed_runs = _collect_entropy_labels(
        ranked=top_ranked,
        output_schema=rubric.output_schema,
        agreement_keys=agreement_keys,
        labeling_requests_by_run_id=labeling_requests_by_run_id,
        collection_id=collection_id,
        frontend_url=frontend_url,
    )
    for collected_label in collected_labels:
        user_data.add_label(
            collected_label.agent_run_id,
            collected_label.label_value,
            explanation=collected_label.explanation,
            labeling_request=collected_label.labeling_request,
            metadata=collected_label.metadata.model_dump(mode="json"),
        )
    output_path = write_user_data_json(user_data, output_json_path)

    labeled_run_count = len(collected_labels)
    answered_key_count = sum(
        len(collected_label.label_value) for collected_label in collected_labels
    )
    console.print(f"\nWrote user data JSON to: [bold]{output_path}[/bold]")
    if stage_skipped:
        console.print("Labeling phase was skipped; persisted the current user data state.")
    console.print(
        f"Collected labels for {labeled_run_count}/{displayed_runs} displayed run(s); "
        f"recorded {answered_key_count} key answer(s)."
    )

    console.print("\n" + "=" * 80)
    console.print("[bold green]DONE[/bold green]")
    console.print("=" * 80)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Estimate user output distributions p_u, print highest-entropy runs, "
            "collect interactive labels, and write a JSON record."
        )
    )
    parser.add_argument("collection_id", type=str, help="Collection ID")
    parser.add_argument("rubric_id", type=str, help="Rubric ID")
    parser.add_argument(
        "--user-data-json",
        type=str,
        default=None,
        help=(
            "Optional path to an existing UserData JSON file. "
            "If provided, labels/QA history are loaded before user model inference."
        ),
    )
    parser.add_argument(
        "--where-clause",
        type=str,
        default=None,
        help="Optional DQL WHERE clause used to filter sampled agent runs",
    )
    parser.add_argument(
        "--label-num-samples",
        type=int,
        default=50,
        help="Number of agent runs sampled for entropy ranking (default: 50)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Random seed for subsampling (default: 0)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=20,
        help="Number of highest-entropy runs to print and collect labels for (default: 20)",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default=None,
        help=(
            "Optional output path for UserData JSON. "
            "If omitted, a timestamped file is written under outputs/."
        ),
    )
    args = parser.parse_args()

    try:
        asyncio.run(
            run_entropy_elicitation(
                collection_id=args.collection_id,
                rubric_id=args.rubric_id,
                user_data_json_path=args.user_data_json,
                where_clause=args.where_clause,
                label_num_samples=args.label_num_samples,
                seed=args.seed,
                top_n=args.top_n,
                output_json_path=args.output_json,
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
