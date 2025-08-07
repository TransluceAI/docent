"""
Shared constants used across multiple modules in the data registry.
"""

# File extension for database restore files
DB_RESTORE_EXTENSION = "pg.tgz"

# Database table names for CSV export/import operations
CSV_TABLES: list[str] = [
    "collections",
    "agent_runs",
    "transcripts",
    "transcript_embeddings",
    "rubrics",
    "rubric_centroids",
    "judge_results",
    "judge_result_centroids",
    "access_control_entries",
]
