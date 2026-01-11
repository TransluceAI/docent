#!/usr/bin/env python3
"""
Preview DQL → SQL: prints each DQL example and the generated SQL from the validator.

Usage:
  source .venv/bin/activate && python scripts/preview_dql.py
"""

from __future__ import annotations

import asyncio
from typing import Any

from docent_core.docent.db.dql import (
    build_collection_sqla_query,
    build_default_registry,
    build_sqla_where_clause,
    get_selected_columns,
)
from docent_core.docent.db.schemas.auth_models import User

TEST_USER = User(id="user-1", email="user@example.com", organization_ids=[], is_anonymous=False)


class _MockMonoService:
    async def has_permission(
        self, *, user: User, resource_type: Any, resource_id: str, permission: Any
    ) -> bool:  # type: ignore[override]
        return True


async def main() -> None:
    collection_id = "test-collection"
    registry = build_default_registry(
        collection_id=collection_id,
        allow_without_collection=True,
    )
    mono = _MockMonoService()

    examples: list[dict[str, str]] = [
        {
            "name": "Basic select with filter, order, limit",
            "dql": (
                "SELECT id, name, created_at FROM agent_runs "
                "WHERE name ILIKE '%eval%' ORDER BY created_at DESC LIMIT 5"
            ),
        },
        {
            "name": "Judge results: basic select",
            "dql": (
                "SELECT agent_run_id, score, created_at FROM judge_results "
                "WHERE score >= 0.8 ORDER BY created_at DESC LIMIT 10"
            ),
        },
        {
            "name": "Judge results joined to agent_runs",
            "dql": (
                "SELECT jr.agent_run_id, jr.score, ar.name FROM judge_results jr "
                "JOIN agent_runs ar ON ar.id = jr.agent_run_id "
                "WHERE jr.score >= 0.9 AND ar.name ILIKE '%eval%' LIMIT 5"
            ),
        },
        {
            "name": "Judge results exists with agent_runs name filter",
            "dql": (
                "SELECT jr.agent_run_id FROM judge_results jr WHERE EXISTS ("
                "SELECT 1 FROM agent_runs ar WHERE ar.id = jr.agent_run_id AND ar.name ILIKE '%baseline%')"
            ),
        },
        {
            "name": "Judge results in subquery (top scores)",
            "dql": (
                "SELECT ar.id, ar.name FROM agent_runs ar WHERE ar.id IN ("
                "SELECT jr.agent_run_id FROM judge_results jr WHERE jr.score >= 0.95)"
            ),
        },
        {
            "name": "DISTINCT",
            "dql": "SELECT DISTINCT name FROM agent_runs WHERE created_at >= '2024-01-01'",
        },
        {
            "name": "Order by multiple columns + OFFSET",
            "dql": (
                "SELECT id, name, created_at FROM agent_runs "
                "WHERE created_at >= '2024-01-01' "
                "ORDER BY created_at DESC, id ASC LIMIT 10 OFFSET 5"
            ),
        },
        {
            "name": "Alias + equality filter",
            "dql": "SELECT ar.id, ar.created_at FROM agent_runs ar WHERE ar.name = 'baseline'",
        },
        {
            "name": "Multiple JOINs (inner + left)",
            "dql": (
                "SELECT ar.id, t.id, tg.id FROM agent_runs ar "
                "JOIN transcripts t ON t.agent_run_id = ar.id "
                "LEFT JOIN transcript_groups tg ON tg.agent_run_id = ar.id "
                "WHERE ar.name ILIKE '%analysis%' LIMIT 10"
            ),
        },
        {
            "name": "EXISTS with subquery",
            "dql": (
                "SELECT ar.id FROM agent_runs ar WHERE EXISTS ("
                "SELECT 1 FROM transcripts t WHERE t.agent_run_id = ar.id AND t.name ILIKE '%conversation%')"
            ),
        },
        {
            "name": "NOT EXISTS correlated",
            "dql": (
                "SELECT ar.id FROM agent_runs ar WHERE NOT EXISTS ("
                "SELECT 1 FROM transcripts t WHERE t.agent_run_id = ar.id AND t.name ILIKE '%private%')"
            ),
        },
        {
            "name": "JOIN",
            "dql": (
                "SELECT ar.id, t.id FROM agent_runs ar "
                "JOIN transcripts t ON t.agent_run_id = ar.id "
                "WHERE ar.created_at >= '2024-01-01' LIMIT 10"
            ),
        },
        {
            "name": "JOIN with additional filters",
            "dql": (
                "SELECT ar.id, t.id, ar.name FROM agent_runs ar "
                "JOIN transcripts t ON t.agent_run_id = ar.id "
                "WHERE (ar.name ILIKE '%run%' AND t.name ILIKE '%segment%') LIMIT 5"
            ),
        },
        {
            "name": "Subquery in FROM (derived table)",
            "dql": (
                "SELECT sub.id FROM (SELECT id, name FROM agent_runs WHERE name ILIKE '%alpha%') sub"
            ),
        },
        {
            "name": "IN + ILIKE",
            "dql": "SELECT id, name FROM agent_runs WHERE id IN ('a','b','c') AND name ILIKE '%report%'",
        },
        {
            "name": "IN (subquery)",
            "dql": (
                "SELECT ar.id, ar.name FROM agent_runs ar WHERE ar.id IN ("
                "SELECT t.agent_run_id FROM transcripts t WHERE t.name ILIKE '%msg%')"
            ),
        },
        {
            "name": "BETWEEN on created_at",
            "dql": (
                "SELECT id, created_at FROM agent_runs "
                "WHERE created_at BETWEEN '2024-01-01' AND '2024-12-31'"
            ),
        },
        {
            "name": "NOT / OR with parentheses",
            "dql": (
                "SELECT id, name FROM agent_runs "
                "WHERE NOT (name ILIKE '%tmp%' OR name ILIKE '%debug%')"
            ),
        },
        {
            "name": "CAST + ORDER BY + OFFSET",
            "dql": (
                "SELECT id, CAST(EXTRACT(EPOCH FROM created_at) AS BIGINT) AS created_epoch "
                "FROM agent_runs ORDER BY created_at DESC LIMIT 5 OFFSET 2"
            ),
        },
        {
            "name": "DISTINCT with ORDER BY",
            "dql": ("SELECT DISTINCT name FROM agent_runs ORDER BY name ASC LIMIT 20"),
        },
    ]

    print("=" * 80)
    print("DQL → SQL Preview (collection_id='" + collection_id + "')")
    print("=" * 80)

    for i, ex in enumerate(examples, 1):
        print(f"\n{i}. {ex['name']}")
        print("-" * 80)
        print("DQL:")
        print(ex["dql"])  # raw input
        try:
            clause = await build_collection_sqla_query(
                mono_service=mono,  # type: ignore[arg-type]
                user=TEST_USER,
                collection_id=collection_id,
                dql=ex["dql"],
                registry=registry,
            )
            print("\nSQL:")
            print(clause.text)

            cols = get_selected_columns(ex["dql"], registry=registry, collection_id=collection_id)
            if cols:
                print("\nSelected Columns:")
                for c in cols:
                    sources = ", ".join(
                        f"{s.table}.{s.column}" if s.table else s.column for s in c.source_columns
                    )
                    print(f"  - {c.output_name}: {c.expression_sql}  (sources: {sources})")
        except Exception as e:  # pragma: no cover - preview utility
            print("\nERROR:")
            print(e)

    print("\n" + "=" * 80)
    print("WHERE Clause Examples")
    print("=" * 80)

    where_examples: list[dict[str, str]] = [
        {"name": "Simple WHERE", "where": "agent_runs.name = 'test-run'"},
        {
            "name": "IN + ILIKE",
            "where": "agent_runs.id IN ('id1','id2') AND agent_runs.name ILIKE '%conversation%'",
        },
        {
            "name": "Date range",
            "where": "agent_runs.created_at BETWEEN '2024-01-01' AND '2024-12-31'",
        },
        {
            "name": "NOT / OR",
            "where": "NOT (agent_runs.name ILIKE '%tmp%' OR agent_runs.name ILIKE '%debug%')",
        },
        {
            "name": "Parenthesized AND/OR",
            "where": "(agent_runs.name ILIKE '%alpha%' OR agent_runs.name ILIKE '%beta%') AND agent_runs.id IN ('x','y')",
        },
    ]

    for i, ex in enumerate(where_examples, 1):
        print(f"\n{i}. {ex['name']}")
        print("-" * 80)
        print("WHERE:")
        print(ex["where"])  # raw input
        try:
            where_clause = build_sqla_where_clause(
                ex["where"],
                registry=registry,
                collection_id=collection_id,
                allow_without_collection=True,
            )
            print("\nSQL:")
            print(where_clause.text)
        except Exception as e:  # pragma: no cover - preview utility
            print("\nERROR:")
            print(e)


if __name__ == "__main__":
    asyncio.run(main())
