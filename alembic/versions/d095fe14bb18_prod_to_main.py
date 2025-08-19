"""prod to main

Revision ID: d095fe14bb18
Revises:
Create Date: 2025-07-21 19:31:29.834692

"""

from typing import Sequence, Union

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d095fe14bb18"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # this first section (up to line 507) is a separate revision that was added later to back-populate the initial table definitions
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("job_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "RUNNING", "CANCELED", "COMPLETED", name="jobstatus"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("is_anonymous", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    # op.create_index(op.f("ix_users_is_anonymous"), "users", ["is_anonymous"], unique=False)
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # op.create_index(op.f("ix_api_keys_disabled_at"), "api_keys", ["disabled_at"], unique=False)
    # op.create_index(op.f("ix_api_keys_key_hash"), "api_keys", ["key_hash"], unique=True)
    # op.create_index(op.f("ix_api_keys_last_used_at"), "api_keys", ["last_used_at"], unique=False)
    # op.create_index(op.f("ix_api_keys_user_id"), "api_keys", ["user_id"], unique=False)
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("messages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("agent_run_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # op.create_index(
    #     op.f("ix_chat_sessions_updated_at"), "chat_sessions", ["updated_at"], unique=False
    # )
    # op.create_index(op.f("ix_chat_sessions_user_id"), "chat_sessions", ["user_id"], unique=False)
    op.create_table(
        "collections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # op.create_index(op.f("ix_collections_created_by"), "collections", ["created_by"], unique=False)
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # op.create_index(op.f("ix_sessions_expires_at"), "sessions", ["expires_at"], unique=False)
    # op.create_index(op.f("ix_sessions_is_active"), "sessions", ["is_active"], unique=False)
    # op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False)
    op.create_table(
        "user_organizations",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("user_id", "organization_id"),
    )
    # op.create_index(
    #     op.f("ix_user_organizations_organization_id"),
    #     "user_organizations",
    #     ["organization_id"],
    #     unique=False,
    # )
    # op.create_index(
    #     op.f("ix_user_organizations_user_id"), "user_organizations", ["user_id"], unique=False
    # )
    op.create_table(
        "agent_runs",
        sa.Column("collection_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("text_for_search", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_agent_runs_metadata_json_gin",
        "agent_runs",
        ["metadata_json"],
        unique=False,
        postgresql_using="gin",
    )
    # op.create_index(
    #     op.f("ix_agent_runs_collection_id"), "agent_runs", ["collection_id"], unique=False
    # )
    op.create_table(
        "analytics_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("collection_id", sa.String(length=36), nullable=True),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column(
            "endpoint",
            sa.Enum(
                "SIGNUP",
                "CREATE_ANONYMOUS_SESSION",
                "CREATE_FG",
                "GET_AGENT_RUN",
                "POST_AGENT_RUNS",
                "JOIN",
                "SET_IO_BIN_KEYS",
                "SET_IO_BIN_KEY_WITH_METADATA_KEY",
                "POST_BASE_FILTER",
                "CLONE_OWN_VIEW",
                "APPLY_EXISTING_VIEW",
                "GET_EXISTING_SEARCH_RESULTS",
                "GET_REGEX_SNIPPETS_ENDPOINT",
                "UPSERT_COLLABORATOR",
                "DELETE_FILTER",
                "POST_FILTER",
                "START_COMPUTE_SEARCH",
                "RESUME_COMPUTE_SEARCH",
                "GET_EXISTING_CLUSTERS",
                "START_CLUSTER_SEARCH_RESULTS",
                "GET_TA_MESSAGE",
                "GET_DIFFS_REPORT",
                "START_COMPUTE_DIFFS",
                "COMPUTE_DIFF_CLUSTERS",
                "GET_TRANSCRIPT_DIFF",
                "CREATE_CHART",
                "UPDATE_CHART",
                "DELETE_CHART",
                "MAKE_COLLECTION_PUBLIC",
                "SHARE_COLLECTION_WITH_EMAIL",
                name="endpointtype",
            ),
            nullable=False,
        ),
        sa.Column("called_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # op.create_index(
    #     op.f("ix_analytics_events_called_at"), "analytics_events", ["called_at"], unique=False
    # )
    # op.create_index(
    #     op.f("ix_analytics_events_collection_id"),
    #     "analytics_events",
    #     ["collection_id"],
    #     unique=False,
    # )
    # op.create_index(
    #     op.f("ix_analytics_events_endpoint"), "analytics_events", ["endpoint"], unique=False
    # )
    # op.create_index(
    #     op.f("ix_analytics_events_user_id"), "analytics_events", ["user_id"], unique=False
    # )
    op.create_table(
        "search_clusters",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("collection_id", sa.String(length=36), nullable=False),
        sa.Column("centroid", sa.Text(), nullable=False),
        sa.Column("search_query", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # op.create_index(
    #     op.f("ix_search_clusters_collection_id"), "search_clusters", ["collection_id"], unique=False
    # )
    # op.create_index(
    #     op.f("ix_search_clusters_search_query"), "search_clusters", ["search_query"], unique=False
    # )
    op.create_table(
        "search_queries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("collection_id", sa.String(length=36), nullable=False),
        sa.Column("search_query", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # op.create_index(
    #     op.f("ix_search_queries_collection_id"), "search_queries", ["collection_id"], unique=False
    # )
    # op.create_index(
    #     op.f("ix_search_queries_search_query"), "search_queries", ["search_query"], unique=False
    # )
    op.create_table(
        "views",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("collection_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("base_filter_dict", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("inner_bin_key", sa.Text(), nullable=True),
        sa.Column("outer_bin_key", sa.Text(), nullable=True),
        sa.Column("for_sharing", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_view_collection_user_unique_non_sharing",
        "views",
        ["collection_id", "user_id"],
        unique=True,
        postgresql_where="for_sharing = false",
    )
    # op.create_index(op.f("ix_views_collection_id"), "views", ["collection_id"], unique=False)
    # op.create_index(op.f("ix_views_user_id"), "views", ["user_id"], unique=False)
    op.create_table(
        "access_control_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("collection_id", sa.String(length=36), nullable=True),
        sa.Column("view_id", sa.String(length=36), nullable=True),
        sa.Column("permission", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "(collection_id IS NOT NULL)::int + (view_id IS NOT NULL)::int = 1",
            name="check_exactly_one_resource",
        ),
        sa.CheckConstraint(
            "(user_id IS NOT NULL)::int + (organization_id IS NOT NULL)::int + is_public::int = 1",
            name="check_exactly_one_subject",
        ),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(["view_id"], ["views.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "organization_id",
            "is_public",
            "collection_id",
            "view_id",
            "permission",
            name="uq_access_control_entry_combination",
        ),
    )
    # op.create_index(
    #     op.f("ix_access_control_entries_collection_id"),
    #     "access_control_entries",
    #     ["collection_id"],
    #     unique=False,
    # )
    # op.create_index(
    #     op.f("ix_access_control_entries_is_public"),
    #     "access_control_entries",
    #     ["is_public"],
    #     unique=False,
    # )
    # op.create_index(
    #     op.f("ix_access_control_entries_organization_id"),
    #     "access_control_entries",
    #     ["organization_id"],
    #     unique=False,
    # )
    # op.create_index(
    #     op.f("ix_access_control_entries_permission"),
    #     "access_control_entries",
    #     ["permission"],
    #     unique=False,
    # )
    # op.create_index(
    #     op.f("ix_access_control_entries_user_id"),
    #     "access_control_entries",
    #     ["user_id"],
    #     unique=False,
    # )
    # op.create_index(
    #     op.f("ix_access_control_entries_view_id"),
    #     "access_control_entries",
    #     ["view_id"],
    #     unique=False,
    # )
    op.create_table(
        "search_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("collection_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=False),
        sa.Column("search_query", sa.Text(), nullable=False),
        sa.Column("search_result_idx", sa.Integer(), nullable=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "collection_id",
            "agent_run_id",
            "search_query",
            "search_result_idx",
            name="uq_search_result_key_combination",
        ),
    )
    # op.create_index(
    #     op.f("ix_search_results_agent_run_id"), "search_results", ["agent_run_id"], unique=False
    # )
    # op.create_index(
    #     op.f("ix_search_results_collection_id"), "search_results", ["collection_id"], unique=False
    # )
    # op.create_index(
    #     op.f("ix_search_results_search_query"), "search_results", ["search_query"], unique=False
    # )
    # op.create_index(
    #     op.f("ix_search_results_search_result_idx"),
    #     "search_results",
    #     ["search_result_idx"],
    #     unique=False,
    # )
    op.create_table(
        "transcript_embeddings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("collection_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=False),
        sa.Column("embedding", Vector(dim=512), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # op.create_index(
    #     op.f("ix_transcript_embeddings_agent_run_id"),
    #     "transcript_embeddings",
    #     ["agent_run_id"],
    #     unique=False,
    # )
    # op.create_index(
    #     op.f("ix_transcript_embeddings_collection_id"),
    #     "transcript_embeddings",
    #     ["collection_id"],
    #     unique=False,
    # )
    op.create_table(
        "transcripts",
        sa.Column("collection_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=False),
        sa.Column("dict_key", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("messages", sa.LargeBinary(), nullable=False),
        sa.Column("metadata_json", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # op.create_index(
    #     op.f("ix_transcripts_agent_run_id"), "transcripts", ["agent_run_id"], unique=False
    # )
    # op.create_index(
    #     op.f("ix_transcripts_collection_id"), "transcripts", ["collection_id"], unique=False
    # )
    op.create_table(
        "search_result_clusters",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("search_result_id", sa.String(length=36), nullable=False),
        sa.Column("cluster_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["cluster_id"],
            ["search_clusters.id"],
        ),
        sa.ForeignKeyConstraint(
            ["search_result_id"],
            ["search_results.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("search_result_id", "cluster_id", name="uq_search_result_cluster"),
    )
    # op.create_index(
    #     op.f("ix_search_result_clusters_cluster_id"),
    #     "search_result_clusters",
    #     ["cluster_id"],
    #     unique=False,
    # )
    # op.create_index(
    #     op.f("ix_search_result_clusters_search_result_id"),
    #     "search_result_clusters",
    #     ["search_result_id"],
    #     unique=False,
    # )
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "diff_queries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("collection_id", sa.String(length=36), nullable=False),
        sa.Column("grouping_md_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("md_field_value_1", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("md_field_value_2", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("focus", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            name=op.f("fk_diff_queries__collection_id__collections"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diff_queries")),
    )
    op.create_index(
        op.f("ix_diff_queries__collection_id"), "diff_queries", ["collection_id"], unique=False
    )
    op.create_table(
        "rubrics",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("collection_id", sa.String(length=36), nullable=False),
        sa.Column("high_level_description", sa.Text(), nullable=False),
        sa.Column("inclusion_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("exclusion_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            name=op.f("fk_rubrics__collection_id__collections"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rubrics")),
    )
    op.create_index(op.f("ix_rubrics__collection_id"), "rubrics", ["collection_id"], unique=False)
    op.create_table(
        "charts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("view_id", sa.String(length=36), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("series_key", sa.Text(), nullable=True),
        sa.Column("x_key", sa.Text(), nullable=True),
        sa.Column("y_key", sa.Text(), nullable=True),
        sa.Column("sql_query", sa.Text(), nullable=True),
        sa.Column("chart_type", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_charts__created_by__users")
        ),
        sa.ForeignKeyConstraint(["view_id"], ["views.id"], name=op.f("fk_charts__view_id__views")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_charts")),
    )
    op.create_index(op.f("ix_charts__created_by"), "charts", ["created_by"], unique=False)
    op.create_index(op.f("ix_charts__view_id"), "charts", ["view_id"], unique=False)
    op.create_table(
        "diff_claims_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("diff_query_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["diff_query_id"],
            ["diff_queries.id"],
            name=op.f("fk_diff_claims_results__diff_query_id__diff_queries"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diff_claims_results")),
    )
    op.create_index(
        op.f("ix_diff_claims_results__diff_query_id"),
        "diff_claims_results",
        ["diff_query_id"],
        unique=False,
    )
    op.create_table(
        "diff_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("diff_query_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_1_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_2_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_run_1_id"],
            ["agent_runs.id"],
            name=op.f("fk_diff_results__agent_run_1_id__agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_2_id"],
            ["agent_runs.id"],
            name=op.f("fk_diff_results__agent_run_2_id__agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["diff_query_id"],
            ["diff_queries.id"],
            name=op.f("fk_diff_results__diff_query_id__diff_queries"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diff_results")),
    )
    op.create_index(
        op.f("ix_diff_results__agent_run_1_id"), "diff_results", ["agent_run_1_id"], unique=False
    )
    op.create_index(
        op.f("ix_diff_results__agent_run_2_id"), "diff_results", ["agent_run_2_id"], unique=False
    )
    op.create_index(
        op.f("ix_diff_results__diff_query_id"), "diff_results", ["diff_query_id"], unique=False
    )
    op.create_table(
        "judge_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=False),
        sa.Column("rubric_id", sa.String(length=36), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            name=op.f("fk_judge_results__agent_run_id__agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["rubric_id"], ["rubrics.id"], name=op.f("fk_judge_results__rubric_id__rubrics")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_judge_results")),
    )
    op.create_index(
        op.f("ix_judge_results__agent_run_id"), "judge_results", ["agent_run_id"], unique=False
    )
    op.create_index(
        op.f("ix_judge_results__rubric_id"), "judge_results", ["rubric_id"], unique=False
    )
    op.create_table(
        "rubric_centroids",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("collection_id", sa.String(length=36), nullable=False),
        sa.Column("rubric_id", sa.String(length=36), nullable=False),
        sa.Column("centroid", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            name=op.f("fk_rubric_centroids__collection_id__collections"),
        ),
        sa.ForeignKeyConstraint(
            ["rubric_id"], ["rubrics.id"], name=op.f("fk_rubric_centroids__rubric_id__rubrics")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rubric_centroids")),
    )
    op.create_index(
        op.f("ix_rubric_centroids__collection_id"),
        "rubric_centroids",
        ["collection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_rubric_centroids__rubric_id"), "rubric_centroids", ["rubric_id"], unique=False
    )
    op.create_table(
        "diff_instances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("paired_diff_result_id", sa.String(length=36), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("shared_context", sa.Text(), nullable=False),
        sa.Column("agent_1_action", sa.Text(), nullable=False),
        sa.Column("agent_1_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("agent_2_action", sa.Text(), nullable=False),
        sa.Column("agent_2_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["paired_diff_result_id"],
            ["diff_results.id"],
            name=op.f("fk_diff_instances__paired_diff_result_id__diff_results"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diff_instances")),
    )
    op.create_index(
        op.f("ix_diff_instances__paired_diff_result_id"),
        "diff_instances",
        ["paired_diff_result_id"],
        unique=False,
    )
    op.create_table(
        "judge_result_centroids",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("judge_result_id", sa.String(length=36), nullable=False),
        sa.Column("centroid_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["centroid_id"],
            ["rubric_centroids.id"],
            name=op.f("fk_judge_result_centroids__centroid_id__rubric_centroids"),
        ),
        sa.ForeignKeyConstraint(
            ["judge_result_id"],
            ["judge_results.id"],
            name=op.f("fk_judge_result_centroids__judge_result_id__judge_results"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_judge_result_centroids")),
        sa.UniqueConstraint("judge_result_id", "centroid_id", name="uq_judge_result_centroid"),
    )
    op.create_index(
        op.f("ix_judge_result_centroids__centroid_id"),
        "judge_result_centroids",
        ["centroid_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_judge_result_centroids__judge_result_id"),
        "judge_result_centroids",
        ["judge_result_id"],
        unique=False,
    )
    op.create_table(
        "paired_search_query",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("collection_id", sa.String(length=36), nullable=False),
        sa.Column("diff_claims_result_id", sa.String(length=36), nullable=True),
        sa.Column("grouping_md_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("md_field_value_1", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("md_field_value_2", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("action_1", sa.Text(), nullable=False),
        sa.Column("action_2", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            name=op.f("fk_paired_search_query__collection_id__collections"),
        ),
        sa.ForeignKeyConstraint(
            ["diff_claims_result_id"],
            ["diff_claims_results.id"],
            name=op.f("fk_paired_search_query__diff_claims_result_id__diff_claims_results"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paired_search_query")),
    )
    op.create_index(
        op.f("ix_paired_search_query__collection_id"),
        "paired_search_query",
        ["collection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_paired_search_query__diff_claims_result_id"),
        "paired_search_query",
        ["diff_claims_result_id"],
        unique=False,
    )
    op.create_table(
        "paired_search_result",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("paired_search_query_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_1_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_2_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_run_1_id"],
            ["agent_runs.id"],
            name=op.f("fk_paired_search_result__agent_run_1_id__agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_2_id"],
            ["agent_runs.id"],
            name=op.f("fk_paired_search_result__agent_run_2_id__agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["paired_search_query_id"],
            ["paired_search_query.id"],
            name=op.f("fk_paired_search_result__paired_search_query_id__paired_search_query"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paired_search_result")),
    )
    op.create_index(
        op.f("ix_paired_search_result__agent_run_1_id"),
        "paired_search_result",
        ["agent_run_1_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_paired_search_result__agent_run_2_id"),
        "paired_search_result",
        ["agent_run_2_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_paired_search_result__paired_search_query_id"),
        "paired_search_result",
        ["paired_search_query_id"],
        unique=False,
    )
    op.create_table(
        "paired_search_instance",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("paired_search_result_id", sa.String(length=36), nullable=False),
        sa.Column("shared_context", sa.Text(), nullable=False),
        sa.Column("agent_1_action_1", sa.Boolean(), nullable=False),
        sa.Column("agent_1_action_1_explanation", sa.Text(), nullable=True),
        sa.Column("agent_1_action_2", sa.Boolean(), nullable=False),
        sa.Column("agent_1_action_2_explanation", sa.Text(), nullable=True),
        sa.Column("agent_2_action_1", sa.Boolean(), nullable=False),
        sa.Column("agent_2_action_1_explanation", sa.Text(), nullable=True),
        sa.Column("agent_2_action_2", sa.Boolean(), nullable=False),
        sa.Column("agent_2_action_2_explanation", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["paired_search_result_id"],
            ["paired_search_result.id"],
            name=op.f("fk_paired_search_instance__paired_search_result_id__paired_search_result"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paired_search_instance")),
    )
    op.create_index(
        op.f("ix_paired_search_instance__paired_search_result_id"),
        "paired_search_instance",
        ["paired_search_result_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_access_control_entries__collection_id"),
        "access_control_entries",
        ["collection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_access_control_entries__is_public"),
        "access_control_entries",
        ["is_public"],
        unique=False,
    )
    op.create_index(
        op.f("ix_access_control_entries__organization_id"),
        "access_control_entries",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_access_control_entries__permission"),
        "access_control_entries",
        ["permission"],
        unique=False,
    )
    op.create_index(
        op.f("ix_access_control_entries__user_id"),
        "access_control_entries",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_access_control_entries__view_id"),
        "access_control_entries",
        ["view_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_runs__collection_id"), "agent_runs", ["collection_id"], unique=False
    )
    op.create_index(
        op.f("ix_analytics_events__called_at"), "analytics_events", ["called_at"], unique=False
    )
    op.create_index(
        op.f("ix_analytics_events__collection_id"),
        "analytics_events",
        ["collection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_analytics_events__endpoint"), "analytics_events", ["endpoint"], unique=False
    )
    op.create_index(
        op.f("ix_analytics_events__user_id"), "analytics_events", ["user_id"], unique=False
    )
    op.create_index(op.f("ix_api_keys__disabled_at"), "api_keys", ["disabled_at"], unique=False)
    op.create_index(op.f("ix_api_keys__key_hash"), "api_keys", ["key_hash"], unique=True)
    op.create_index(op.f("ix_api_keys__last_used_at"), "api_keys", ["last_used_at"], unique=False)
    op.create_index(op.f("ix_api_keys__user_id"), "api_keys", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_chat_sessions__updated_at"), "chat_sessions", ["updated_at"], unique=False
    )
    op.create_index(op.f("ix_chat_sessions__user_id"), "chat_sessions", ["user_id"], unique=False)
    op.create_index(op.f("ix_collections__created_by"), "collections", ["created_by"], unique=False)
    op.create_index(
        op.f("ix_search_clusters__collection_id"),
        "search_clusters",
        ["collection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_search_clusters__search_query"), "search_clusters", ["search_query"], unique=False
    )
    op.create_index(
        op.f("ix_search_queries__collection_id"), "search_queries", ["collection_id"], unique=False
    )
    op.create_index(
        op.f("ix_search_queries__search_query"), "search_queries", ["search_query"], unique=False
    )
    op.create_index(
        op.f("ix_search_result_clusters__cluster_id"),
        "search_result_clusters",
        ["cluster_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_search_result_clusters__search_result_id"),
        "search_result_clusters",
        ["search_result_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_search_results__agent_run_id"), "search_results", ["agent_run_id"], unique=False
    )
    op.create_index(
        op.f("ix_search_results__collection_id"), "search_results", ["collection_id"], unique=False
    )
    op.create_index(
        op.f("ix_search_results__search_query"), "search_results", ["search_query"], unique=False
    )
    op.create_index(
        op.f("ix_search_results__search_result_idx"),
        "search_results",
        ["search_result_idx"],
        unique=False,
    )
    op.create_index(op.f("ix_sessions__expires_at"), "sessions", ["expires_at"], unique=False)
    op.create_index(op.f("ix_sessions__is_active"), "sessions", ["is_active"], unique=False)
    op.create_index(op.f("ix_sessions__user_id"), "sessions", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_transcript_embeddings__agent_run_id"),
        "transcript_embeddings",
        ["agent_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transcript_embeddings__collection_id"),
        "transcript_embeddings",
        ["collection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transcripts__agent_run_id"), "transcripts", ["agent_run_id"], unique=False
    )
    op.create_index(
        op.f("ix_transcripts__collection_id"), "transcripts", ["collection_id"], unique=False
    )
    op.create_index(
        op.f("ix_user_organizations__organization_id"),
        "user_organizations",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_organizations__user_id"), "user_organizations", ["user_id"], unique=False
    )
    op.create_index(op.f("ix_users__email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users__is_anonymous"), "users", ["is_anonymous"], unique=False)
    op.create_index(op.f("ix_views__collection_id"), "views", ["collection_id"], unique=False)
    op.create_index(op.f("ix_views__user_id"), "views", ["user_id"], unique=False)


def downgrade() -> None:
    raise NotImplementedError("Downgrade not implemented")
