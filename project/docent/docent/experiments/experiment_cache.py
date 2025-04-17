import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from docent.types import ExperimentResult, TaskArgs
from env_util import ENV


class ExperimentCache:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            if ENV.INSPECT_EXPERIMENT_CACHE_PATH is None:
                raise Exception("INSPECT_CACHE_PATH is not set in .env")

            cache_dir = Path(ENV.INSPECT_EXPERIMENT_CACHE_PATH)
            cache_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(cache_dir / "experiment_cache.db")

        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS experiment_cache (
                    key TEXT PRIMARY KEY,
                    results TEXT,
                    captured_stdout TEXT,
                    captured_stderr TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def _create_key(
        self,
        task_id: str,
        task_args: TaskArgs,
        model: str,
        sample_ids: list[str | int] | None,
        epochs: int,
    ) -> str:
        """Create a deterministic hash key from experiment configuration."""
        # Convert configuration to a stable string representation
        config = {
            "task_id": task_id,
            "task_args": task_args.model_dump(),
            "model": model,
            "sample_ids": sample_ids,
            "epochs": epochs,
        }
        config_str = json.dumps(config, sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()

    def get(
        self,
        task_id: str,
        task_args: TaskArgs,
        model: str,
        sample_ids: list[str | int] | None,
        epochs: int,
    ) -> ExperimentResult | None:
        """Get cached experiment result if it exists."""
        key = self._create_key(task_id, task_args, model, sample_ids, epochs)

        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT results, captured_stdout, captured_stderr FROM experiment_cache WHERE key = ?",
                (key,),
            )
            result = cursor.fetchone()
            if result:
                return {
                    "results": json.loads(result[0]),
                    "captured_stdout": result[1],
                    "captured_stderr": result[2],
                }
            return None

    def set(
        self,
        task_id: str,
        task_args: TaskArgs,
        model: str,
        sample_ids: list[str | int] | None,
        epochs: int,
        result: ExperimentResult,
    ) -> None:
        """Cache an experiment result."""
        key = self._create_key(task_id, task_args, model, sample_ids, epochs)

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO experiment_cache
                (key, results, captured_stdout, captured_stderr)
                VALUES (?, ?, ?, ?)
                """,
                (
                    key,
                    json.dumps(result["results"]),
                    result["captured_stdout"],
                    result["captured_stderr"],
                ),
            )
            conn.commit()

    def clear(self) -> None:
        """Clear all cached experiment results."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM experiment_cache")
            conn.commit()
