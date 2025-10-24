import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from docent._llm_util.data_models.llm_output import LLMOutput
from docent._log_util import get_logger
from docent.data_models.chat import ChatMessage, ToolInfo

logger = get_logger(__name__)


class LLMCache:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            llm_cache_path = os.getenv("LLM_CACHE_PATH")
            if llm_cache_path is None or llm_cache_path == "":
                raise ValueError("LLM_CACHE_PATH is not set")
            else:
                cache_dir = Path(llm_cache_path)
                cache_dir.mkdir(parents=True, exist_ok=True)
                db_path = str(cache_dir / "llm_cache.db")

        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_cache (
                    key TEXT PRIMARY KEY,
                    completion TEXT,
                    model_name TEXT,
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
        messages: list[ChatMessage],
        model_name: str,
        *,
        tools: list[ToolInfo] | None = None,
        tool_choice: Literal["auto", "required"] | None = None,
        reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None,
        temperature: float = 1.0,
        logprobs: bool = False,
        top_logprobs: int | None = None,
    ) -> str:
        """Create a deterministic hash key from messages and model."""
        # Convert messages to a stable string representation
        message_str = json.dumps(
            [msg.model_dump(exclude={"id"}) for msg in messages], sort_keys=True
        )

        # Convert tools to a stable string representation if present
        tools_str = (
            json.dumps([tool.model_dump() for tool in tools], sort_keys=True) if tools else None
        )

        # Combine all parameters into a single string
        key_str = (
            f"{message_str}:{model_name}:{tools_str}:{tool_choice}:{reasoning_effort}:{temperature}"
        )
        if logprobs:
            key_str += f":{top_logprobs}"
        return hashlib.sha256(key_str.encode()).hexdigest()

    def get(
        self,
        messages: list[ChatMessage],
        model_name: str,
        *,
        tools: list[ToolInfo] | None = None,
        tool_choice: Literal["auto", "required"] | None = None,
        reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None,
        temperature: float = 1.0,
        logprobs: bool = False,
        top_logprobs: int | None = None,
    ) -> LLMOutput | None:
        """Get cached completion for a conversation if it exists."""

        key = self._create_key(
            messages,
            model_name,
            tools=tools,
            tool_choice=tool_choice,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
            logprobs=logprobs,
            top_logprobs=top_logprobs,
        )

        with self._get_connection() as conn:
            cursor = conn.execute("SELECT completion FROM llm_cache WHERE key = ?", (key,))
            result = cursor.fetchone()
            if not result:
                return None
            out = LLMOutput.from_dict(json.loads(result[0]))
            out.from_cache = True
            return out

    def set(
        self,
        messages: list[ChatMessage],
        model_name: str,
        llm_output: LLMOutput,
        *,
        tools: list[ToolInfo] | None = None,
        tool_choice: Literal["auto", "required"] | None = None,
        reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None,
        temperature: float = 1.0,
        logprobs: bool = False,
        top_logprobs: int | None = None,
    ) -> None:
        """Cache a completion for a conversation."""

        key = self._create_key(
            messages,
            model_name,
            tools=tools,
            tool_choice=tool_choice,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
            logprobs=logprobs,
            top_logprobs=top_logprobs,
        )

        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO llm_cache (key, completion, model_name) VALUES (?, ?, ?)",
                (key, json.dumps(llm_output.to_dict()), model_name),
            )
            conn.commit()

    def set_batch(
        self,
        messages_list: list[list[ChatMessage]],
        model_name: str,
        llm_output_list: list[LLMOutput],
        *,
        tools: list[ToolInfo] | None = None,
        tool_choice: Literal["auto", "required"] | None = None,
        reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None,
        temperature: float = 1.0,
        logprobs: bool = False,
        top_logprobs: int | None = None,
    ) -> None:
        """Cache a completion for a conversation."""

        keys: list[str] = []
        for messages in messages_list:
            key = self._create_key(
                messages,
                model_name,
                tools=tools,
                tool_choice=tool_choice,
                reasoning_effort=reasoning_effort,
                temperature=temperature,
                logprobs=logprobs,
                top_logprobs=top_logprobs,
            )
            keys.append(key)

        with self._get_connection() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO llm_cache (key, completion, model_name) VALUES (?, ?, ?)",
                [
                    (key, json.dumps(llm_output.to_dict()), model_name)
                    for key, llm_output in zip(keys, llm_output_list)
                ],
            )
            conn.commit()

    def clear(self) -> None:
        """Clear all cached completions."""

        with self._get_connection() as conn:
            conn.execute("DELETE FROM llm_cache")
            conn.commit()
