from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, AsyncContextManager, Callable, Mapping, cast

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from docent._llm_util.model_registry import estimate_cost_cents
from docent._log_util import get_logger
from docent_core._env_util import ENV
from docent_core.docent.db.schemas.tables import SQLAModelUsage

logger = get_logger(__name__)


RATE_LIMIT_WINDOW_SECONDS = 24 * 60 * 60


def _get_free_cap_cents() -> int | None:
    free_cap_cents_str = ENV.get("FREE_USAGE_CAP_CENTS")
    if not free_cap_cents_str:
        return None
    # Could result from tostring(null) in terraform
    if free_cap_cents_str == "null":
        return None
    return int(free_cap_cents_str)


FREE_CAP_CENTS = _get_free_cap_cents()


def check_spend_within_limit(spend_cents: float) -> bool:
    if FREE_CAP_CENTS is None:
        return True
    return spend_cents < FREE_CAP_CENTS


def _truncate_datetime(ts: datetime) -> datetime:
    """Bucket times by the hour to reduce number of rows in the model_usage table"""
    return ts.replace(minute=0, second=0, microsecond=0)


class UsageService:
    def __init__(
        self,
        session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
    ):
        self.session_cm_factory = session_cm_factory

    async def get_free_spend_cents(
        self, user_id: str, window_seconds: int = RATE_LIMIT_WINDOW_SECONDS
    ) -> float:
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=window_seconds)

        stmt = select(SQLAModelUsage.model, SQLAModelUsage.metric_name, SQLAModelUsage.value).where(
            and_(
                SQLAModelUsage.user_id == user_id,
                SQLAModelUsage.api_key_id.is_(None),
                SQLAModelUsage.bucket_start >= cutoff,
            )
        )
        async with self.session_cm_factory() as session:
            result = await session.execute(stmt)
            results = result.fetchall()

        total_cost_cents = 0
        for model_json, metric_name, value in results:
            model_name = model_json.get("model_name")
            total_cost_cents += estimate_cost_cents(model_name, value, metric_name)

        return total_cost_cents

    async def check_within_free_limit(
        self,
        user_id: str,
    ) -> bool:
        # If no cap is set, always allow usage
        if FREE_CAP_CENTS is None:
            return True
        spent_cents = await self.get_free_spend_cents(user_id)
        return spent_cents < FREE_CAP_CENTS

    async def upsert_usage(
        self,
        *,
        user_id: str,
        api_key_id: str | None,
        model: Mapping[str, object],
        when: datetime | None,
        metrics: Mapping[str, int],
    ) -> None:
        bucket_start = _truncate_datetime(when or datetime.now(UTC).replace(tzinfo=None))

        async with self.session_cm_factory() as session:
            for metric_name, raw_value in metrics.items():
                value = int(raw_value)
                stmt = insert(SQLAModelUsage).values(
                    user_id=user_id,
                    api_key_id=api_key_id,
                    model=dict(model),
                    bucket_start=bucket_start,
                    metric_name=metric_name,
                    value=value,
                )
                if api_key_id is None:
                    # Match partial unique index for free usage (api_key_id IS NULL)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=[
                            SQLAModelUsage.user_id,
                            SQLAModelUsage.bucket_start,
                            SQLAModelUsage.metric_name,
                            SQLAModelUsage.model,
                        ],
                        index_where=SQLAModelUsage.api_key_id.is_(None),
                        set_={"value": SQLAModelUsage.value + value},
                    )
                else:
                    # Match partial unique index for BYOK usage (api_key_id IS NOT NULL)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=[
                            SQLAModelUsage.user_id,
                            SQLAModelUsage.api_key_id,
                            SQLAModelUsage.bucket_start,
                            SQLAModelUsage.metric_name,
                            SQLAModelUsage.model,
                        ],
                        index_where=SQLAModelUsage.api_key_id.is_not(None),
                        set_={"value": SQLAModelUsage.value + value},
                    )

                await session.execute(stmt)

    async def get_free_usage_breakdown(
        self, user_id: str, window_seconds: int
    ) -> tuple[float, list[dict[str, Any]]]:
        """
        Aggregate free (Docent-provided key) usage by model and metric within a window.

        Returns:
            total_cents: Estimated total cost in cents
            models: List of per-model breakdown dicts with input/output tokens and cents
        """
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=window_seconds)

        stmt = select(SQLAModelUsage.model, SQLAModelUsage.metric_name, SQLAModelUsage.value).where(
            and_(
                SQLAModelUsage.user_id == user_id,
                SQLAModelUsage.api_key_id.is_(None),
                SQLAModelUsage.bucket_start >= cutoff,
            )
        )
        async with self.session_cm_factory() as session:
            result = await session.execute(stmt)
            results = result.fetchall()

        # Aggregate by model/metric
        by_model: defaultdict[str, float] = defaultdict(float)
        total_cents = 0.0
        for model_json, metric_name, value in results:
            model_name = self._extract_model_name(model_json)
            cost = estimate_cost_cents(model_name, int(value), metric_name)  # type: ignore[arg-type]
            by_model[model_name] += cost
            total_cents += cost

        # Build models list
        models: list[dict[str, Any]] = []
        for model_name, cost in by_model.items():
            model_entry: dict[str, Any] = {
                "model": model_name,
                "total_cents": cost,
            }
            if FREE_CAP_CENTS is not None:
                model_entry["fraction_used"] = cost / FREE_CAP_CENTS
            models.append(model_entry)

        models.sort(key=lambda m: m["total_cents"], reverse=True)
        return total_cents, models

    async def get_byok_usage_by_key(
        self, user_id: str, window_seconds: int
    ) -> list[dict[str, Any]]:
        """
        Aggregate BYOK usage grouped by api_key_id and model within a window.

        Returns:
            List of key usage dicts: { api_key_id, total_cents, models: [...] }
        """
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=window_seconds)

        stmt = select(
            SQLAModelUsage.api_key_id,
            SQLAModelUsage.model,
            SQLAModelUsage.metric_name,
            SQLAModelUsage.value,
        ).where(
            and_(
                SQLAModelUsage.user_id == user_id,
                SQLAModelUsage.api_key_id.is_not(None),
                SQLAModelUsage.bucket_start >= cutoff,
            )
        )
        async with self.session_cm_factory() as session:
            result = await session.execute(stmt)
            results = result.fetchall()

        # Aggregate into nested structure {api_key_id: {model: {input, output}}}
        by_key: dict[str, dict[str, dict[str, int]]] = {}
        for api_key_id, model_json, metric_name, value in results:
            if api_key_id is None:
                continue
            model_name = self._extract_model_name(model_json)

            key = str(api_key_id)
            by_key.setdefault(key, {})
            by_key[key].setdefault(model_name, {})
            by_key[key][model_name][metric_name] = int(value)

        # Build response list
        keys_response: list[dict[str, Any]] = []
        for key_id, models in by_key.items():
            models_list: list[dict[str, Any]] = []
            total_cents_for_key = 0
            for model_name, metrics in models.items():
                input_tokens = int(metrics.get("input", 0))
                output_tokens = int(metrics.get("output", 0))
                input_cents = estimate_cost_cents(model_name, input_tokens, "input")
                output_cents = estimate_cost_cents(model_name, output_tokens, "output")
                total_cents = input_cents + output_cents
                total_cents_for_key += total_cents
                models_list.append(
                    {
                        "model": model_name,
                        "total_cents": total_cents,
                    }
                )

            models_list.sort(key=lambda m: m["total_cents"], reverse=True)
            keys_response.append(
                {
                    "api_key_id": key_id,
                    "total_cents": total_cents_for_key,
                    "models": models_list,
                }
            )

        keys_response.sort(key=lambda k: k["total_cents"], reverse=True)
        return keys_response

    def _extract_model_name(self, model_json: Any) -> str:
        """Best-effort extraction of a model name string from JSONB field."""
        if isinstance(model_json, dict):
            # Assert types to satisfy the type checker
            d = cast(dict[str, Any], model_json)
            name = d.get("model_name")
            if isinstance(name, str) and name:
                return name
            provider = d.get("provider")
            option = d.get("option")
            parts: list[str] = []
            if isinstance(provider, str) and provider:
                parts.append(provider)
            if isinstance(option, str) and option:
                parts.append(option)
            if parts:
                return "/".join(parts)
        return "unknown"
