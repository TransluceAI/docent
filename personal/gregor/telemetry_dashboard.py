#!/usr/bin/env python3
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Mapping, Sequence

from sqlalchemy import Integer, and_, case
from sqlalchemy import cast as sa_cast
from sqlalchemy import func, or_, select

from docent_core._worker.constants import WorkerFunction
from docent_core.docent.db.schemas.tables import (
    JobStatus,
    SQLAJob,
    SQLATelemetryAgentRunStatus,
    TelemetryAgentRunStatus,
)
from docent_core.docent.services.monoservice import MonoService

try:
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.reactive import reactive
    from textual.widgets import DataTable, Footer, Static
except ImportError as exc:  # pragma: no cover - Textual is optional
    raise SystemExit(
        "Telemetry dashboard requires the 'textual' package. Install it with 'pip install textual'."
    ) from exc


@dataclass(slots=True)
class JobInfo:
    id: str
    type: str
    status: str
    created_at: datetime
    collection_id: str | None
    user_email: str | None
    payload: Mapping[str, Any]


@dataclass(slots=True)
class JobQueueStats:
    job_type: str
    pending: int
    running: int
    completed: int
    recent_completed: int
    completion_rate_per_min: float

    @property
    def queued(self) -> int:
        return self.pending + self.running


@dataclass(slots=True)
class CollectionStatusRow:
    collection_id: str
    awaiting: int
    processing: int
    completed: int
    errored: int
    total: int
    recent_completed: int
    completion_rate_per_min: float
    last_completed_at: datetime | None

    @property
    def needs_work(self) -> bool:
        return self.awaiting > 0


@dataclass(slots=True)
class AgentRunStatusRow:
    agent_run_id: str
    status: str
    current_version: int
    processed_version: int
    updated_at: datetime | None
    requires_processing: bool
    error_message: str | None


# Sentinel datetime used when ordering missing timestamps
DATETIME_FLOOR = datetime.min.replace(tzinfo=None)

JobSortKey = Callable[[JobInfo], Any]
CollectionSortKey = Callable[[CollectionStatusRow], Any]
AgentRunSortKey = Callable[[AgentRunStatusRow], Any]
IngestSortKey = Callable[[JobInfo], Any]

JOB_SORT_MAP: dict[int, JobSortKey] = {
    0: lambda job: job.status,
    1: lambda job: job.type,
    2: lambda job: job.collection_id or "",
    3: lambda job: job.user_email or "",
    4: lambda job: job.created_at,
    5: lambda job: job.id,
}

COLLECTION_SORT_MAP: dict[int, CollectionSortKey] = {
    0: lambda row: row.collection_id,
    1: lambda row: row.awaiting,
    2: lambda row: row.processing,
    3: lambda row: row.completed,
    4: lambda row: row.errored,
    5: lambda row: row.total,
    6: lambda row: row.completion_rate_per_min,
    7: lambda row: row.last_completed_at or DATETIME_FLOOR,
}

RUN_SORT_MAP: dict[int, AgentRunSortKey] = {
    0: lambda row: row.agent_run_id,
    1: lambda row: row.status,
    2: lambda row: row.current_version - row.processed_version,
    3: lambda row: row.current_version,
    4: lambda row: row.processed_version,
    5: lambda row: row.updated_at or DATETIME_FLOOR,
    6: lambda row: row.error_message or "",
}

INGEST_SORT_MAP: dict[int, IngestSortKey] = {
    0: lambda job: job.status,
    1: lambda job: job.payload.get("telemetry_log_id") or "",
    2: lambda job: job.collection_id or "",
    3: lambda job: job.user_email or "",
    4: lambda job: job.created_at,
    5: lambda job: job.id,
}


def utcnow_naive() -> datetime:
    """Return naive UTC timestamps so comparisons match DB defaults."""
    return datetime.now(UTC).replace(tzinfo=None)


def humanize_timedelta(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    return f"{days}d"


def format_ago(timestamp: datetime | None) -> str:
    if timestamp is None:
        return "—"
    return f"{humanize_timedelta(utcnow_naive() - timestamp)} ago"


def truncate(text: str, max_length: int = 60) -> str:
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 1]}…"


def _telemetry_needs_work_case():
    statuses = SQLATelemetryAgentRunStatus
    errored_version = func.coalesce(
        sa_cast(statuses.metadata_json["errored_version"].astext, Integer),
        0,
    )
    return case(
        (statuses.status == TelemetryAgentRunStatus.NEEDS_PROCESSING.value, 1),
        (
            and_(
                statuses.current_version > statuses.processed_version,
                or_(
                    statuses.status != TelemetryAgentRunStatus.ERROR.value,
                    statuses.current_version > errored_version,
                ),
            ),
            1,
        ),
        else_=0,
    )


def _telemetry_recent_completion_case(cutoff: datetime):
    statuses = SQLATelemetryAgentRunStatus
    return case(
        (
            and_(
                statuses.status == TelemetryAgentRunStatus.COMPLETED.value,
                statuses.updated_at >= cutoff,
            ),
            1,
        ),
        else_=0,
    )


def _status_priority_case():
    statuses = SQLATelemetryAgentRunStatus
    return case(
        (statuses.status == TelemetryAgentRunStatus.NEEDS_PROCESSING.value, 0),
        (statuses.status == TelemetryAgentRunStatus.PROCESSING.value, 1),
        (statuses.status == TelemetryAgentRunStatus.ERROR.value, 2),
        else_=3,
    )


class TelemetryDataProvider:
    """Async helper for fetching telemetry state snapshots."""

    RECENT_COMPLETION_MINUTES = 15

    def __init__(self) -> None:
        self._mono_svc: MonoService | None = None

    async def ensure_ready(self) -> None:
        if self._mono_svc is None:
            self._mono_svc = await MonoService.init()

    @property
    def mono_svc(self) -> MonoService:
        if self._mono_svc is None:
            raise RuntimeError("MonoService is not initialized")
        return self._mono_svc

    async def fetch_job_stats(self) -> dict[str, JobQueueStats]:
        job_types = [
            WorkerFunction.TELEMETRY_INGEST_JOB.value,
            WorkerFunction.TELEMETRY_PROCESSING_JOB.value,
        ]
        recent_cutoff = utcnow_naive() - timedelta(minutes=self.RECENT_COMPLETION_MINUTES)

        async with self.mono_svc.db.session() as session:
            pending_label = func.sum(case((SQLAJob.status == JobStatus.PENDING, 1), else_=0)).label(
                "pending_count"
            )
            running_label = func.sum(case((SQLAJob.status == JobStatus.RUNNING, 1), else_=0)).label(
                "running_count"
            )
            completed_label = func.sum(
                case((SQLAJob.status == JobStatus.COMPLETED, 1), else_=0)
            ).label("completed_count")
            recent_completed_label = func.sum(
                case(
                    (
                        and_(
                            SQLAJob.status == JobStatus.COMPLETED,
                            SQLAJob.created_at >= recent_cutoff,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("recent_completed_count")

            stmt = (
                select(
                    SQLAJob.type,
                    pending_label,
                    running_label,
                    completed_label,
                    recent_completed_label,
                )
                .where(SQLAJob.type.in_(job_types))
                .group_by(SQLAJob.type)
            )
            result = await session.execute(stmt)
            records = result.fetchall()

        stats: dict[str, JobQueueStats] = {
            job_type: JobQueueStats(
                job_type=job_type,
                pending=0,
                running=0,
                completed=0,
                recent_completed=0,
                completion_rate_per_min=0.0,
            )
            for job_type in job_types
        }

        for record in records:
            pending = int(record.pending_count or 0)
            running = int(record.running_count or 0)
            completed = int(record.completed_count or 0)
            recent_completed = int(record.recent_completed_count or 0)
            rate = (
                recent_completed / self.RECENT_COMPLETION_MINUTES
                if self.RECENT_COMPLETION_MINUTES > 0
                else 0.0
            )
            stats[record.type] = JobQueueStats(
                job_type=record.type,
                pending=pending,
                running=running,
                completed=completed,
                recent_completed=recent_completed,
                completion_rate_per_min=rate,
            )

        return stats

    async def fetch_jobs(self, limit: int = 50) -> list[JobInfo]:
        job_types = [
            WorkerFunction.TELEMETRY_PROCESSING_JOB.value,
            WorkerFunction.TELEMETRY_INGEST_JOB.value,
        ]
        async with self.mono_svc.db.session() as session:
            stmt = (
                select(SQLAJob)
                .where(SQLAJob.type.in_(job_types))
                .order_by(SQLAJob.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            jobs = result.scalars().all()

        job_infos: list[JobInfo] = []
        for job in jobs:
            job_json: Mapping[str, Any] = job.job_json or {}
            status_value = (
                job.status.value if isinstance(job.status, JobStatus) else str(job.status)
            )
            target_id = (
                job_json.get("collection_id")
                or job_json.get("telemetry_log_id")
                or job_json.get("log_id")
            )
            job_infos.append(
                JobInfo(
                    id=job.id,
                    type=job.type,
                    status=status_value,
                    created_at=job.created_at,
                    collection_id=str(target_id) if target_id else None,
                    user_email=(
                        str(job_json.get("user_email")) if job_json.get("user_email") else None
                    ),
                    payload=job_json,
                )
            )
        return job_infos

    async def fetch_collection_statuses(self) -> list[CollectionStatusRow]:
        async with self.mono_svc.db.session() as session:
            statuses = SQLATelemetryAgentRunStatus
            needs_case = _telemetry_needs_work_case()
            awaiting_label = func.sum(needs_case).label("awaiting_count")
            processing_label = func.sum(
                case((statuses.status == TelemetryAgentRunStatus.PROCESSING.value, 1), else_=0)
            ).label("processing_count")
            completed_label = func.sum(
                case((statuses.status == TelemetryAgentRunStatus.COMPLETED.value, 1), else_=0)
            ).label("completed_count")
            errored_label = func.sum(
                case((statuses.status == TelemetryAgentRunStatus.ERROR.value, 1), else_=0)
            ).label("errored_count")

            recent_cutoff = utcnow_naive() - timedelta(minutes=self.RECENT_COMPLETION_MINUTES)
            recent_completed_label = func.sum(
                _telemetry_recent_completion_case(recent_cutoff)
            ).label("recent_completed")
            last_completed_label = func.max(
                case(
                    (
                        statuses.status == TelemetryAgentRunStatus.COMPLETED.value,
                        statuses.updated_at,
                    ),
                    else_=None,
                )
            ).label("last_completed_at")

            stmt = (
                select(
                    statuses.collection_id,
                    awaiting_label,
                    processing_label,
                    completed_label,
                    errored_label,
                    func.count().label("total_count"),
                    recent_completed_label,
                    last_completed_label,
                )
                .group_by(statuses.collection_id)
                .order_by(
                    awaiting_label.desc(), processing_label.desc(), statuses.collection_id.asc()
                )
            )
            result = await session.execute(stmt)
            records = result.fetchall()

        rows: list[CollectionStatusRow] = []
        for record in records:
            awaiting = int(record.awaiting_count or 0)
            processing = int(record.processing_count or 0)
            completed = int(record.completed_count or 0)
            errored = int(record.errored_count or 0)
            total = int(record.total_count or 0)
            recent_completed = int(record.recent_completed or 0)
            rate = (
                recent_completed / self.RECENT_COMPLETION_MINUTES
                if self.RECENT_COMPLETION_MINUTES > 0
                else 0.0
            )
            rows.append(
                CollectionStatusRow(
                    collection_id=record.collection_id,
                    awaiting=awaiting,
                    processing=processing,
                    completed=completed,
                    errored=errored,
                    total=total,
                    recent_completed=recent_completed,
                    completion_rate_per_min=rate,
                    last_completed_at=record.last_completed_at,
                )
            )
        return rows

    async def fetch_agent_run_statuses(
        self, collection_id: str, limit: int = 250
    ) -> list[AgentRunStatusRow]:
        async with self.mono_svc.db.session() as session:
            statuses = SQLATelemetryAgentRunStatus
            needs_case = _telemetry_needs_work_case()
            needs_case_labeled = needs_case.label("needs_work")
            status_priority = _status_priority_case()

            stmt = (
                select(
                    statuses.agent_run_id,
                    statuses.status,
                    statuses.current_version,
                    statuses.processed_version,
                    statuses.metadata_json,
                    statuses.updated_at,
                    needs_case_labeled,
                )
                .where(statuses.collection_id == collection_id)
                .order_by(
                    needs_case.desc(),
                    status_priority.asc(),
                    statuses.updated_at.desc(),
                )
                .limit(limit)
            )
            result = await session.execute(stmt)
            records = result.fetchall()

        agent_rows: list[AgentRunStatusRow] = []
        for record in records:
            metadata: Mapping[str, Any] | None = record.metadata_json
            error_message: str | None = None
            if metadata:
                history = metadata.get("error_history")
                if isinstance(history, Sequence) and history:
                    last_entry = history[-1]
                    if isinstance(last_entry, Mapping):
                        error_val = last_entry.get("error")
                        if isinstance(error_val, str):
                            error_message = error_val
            requires_processing = bool(record.needs_work)
            agent_rows.append(
                AgentRunStatusRow(
                    agent_run_id=record.agent_run_id,
                    status=record.status,
                    current_version=int(record.current_version or 0),
                    processed_version=int(record.processed_version or 0),
                    updated_at=record.updated_at,
                    requires_processing=requires_processing,
                    error_message=error_message,
                )
            )
        return agent_rows


class TelemetryDashboardApp(App[None]):
    """Textual dashboard showing telemetry processing progress."""

    DEFAULT_DESC_COLUMNS = {
        "jobs-table": {4},
        "ingestion-table": {4},
        "collections-table": {7},
        "runs-table": {5},
    }

    CSS = """
    Screen {
        layout: vertical;
    }

    #dashboard-title {
        padding: 1 2;
        content-align: left middle;
        text-style: bold;
    }

    #jobs-panel, #ingestion-panel, #collections-panel, #runs-panel {
        border: tall $primary;
        padding: 0 1;
    }

    #jobs-panel {
        height: 13;
    }

    #jobs-panel DataTable {
        height: 1fr;
    }

    #main-panels {
        layout: horizontal;
        height: 1fr;
    }

    #ingestion-panel, #collections-panel, #runs-panel {
        width: 1fr;
    }
    #ingestion-panel {
        width: 0.8fr;
    }

    .panel-title {
        padding: 0 0 0 0;
        text-style: bold;
    }

    .panel-subtitle {
        color: $text-muted;
        padding-bottom: 0;
    }

    DataTable {
        height: 1fr;
    }

    #status-bar {
        height: 1;
        padding: 0 1;
        border: tall $surface;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh now"),
        ("a", "toggle_auto_refresh", "Auto refresh"),
    ]

    AUTO_REFRESH_SECONDS = 5
    status_message = reactive("Connecting…")

    def __init__(self) -> None:
        super().__init__()
        self.data_provider = TelemetryDataProvider()
        self.jobs_table: DataTable | None = None
        self.ingestion_table: DataTable | None = None
        self.collections_table: DataTable | None = None
        self.runs_table: DataTable | None = None
        self.jobs_summary: Static | None = None
        self.ingestion_summary: Static | None = None
        self.collections_summary: Static | None = None
        self.runs_summary: Static | None = None
        self.status_label: Static | None = None
        self.collection_rows: dict[str, CollectionStatusRow] = {}
        self.selected_collection_id: str | None = None
        self._refresh_lock = asyncio.Lock()
        self._runs_task: asyncio.Task[None] | None = None
        self.auto_refresh_enabled = True
        self._jobs_data: list[JobInfo] = []
        self._ingestion_data: list[JobInfo] = []
        self._job_stats_data: dict[str, JobQueueStats] = {}
        self._collections_data: list[CollectionStatusRow] = []
        self._runs_data: list[AgentRunStatusRow] = []
        self._jobs_sort_state: tuple[int, bool] | None = None
        self._ingestion_sort_state: tuple[int, bool] | None = None
        self._collections_sort_state: tuple[int, bool] | None = None
        self._runs_sort_state: tuple[int, bool] | None = None

    def compose(self) -> ComposeResult:
        yield Static("Telemetry Control Room", id="dashboard-title")
        with Vertical(id="jobs-panel"):
            yield Static("Worker Queue", classes="panel-title")
            yield Static("—", classes="panel-subtitle", id="jobs-summary")
            yield DataTable(id="jobs-table")
        with Horizontal(id="main-panels"):
            with Vertical(id="ingestion-panel"):
                yield Static("Ingestion", classes="panel-title")
                yield Static("—", classes="panel-subtitle", id="ingestion-summary")
                yield DataTable(id="ingestion-table")
            with Vertical(id="collections-panel"):
                yield Static("Collections", classes="panel-title")
                yield Static("—", classes="panel-subtitle", id="collections-summary")
                yield DataTable(id="collections-table")
            with Vertical(id="runs-panel"):
                yield Static("Agent Runs", classes="panel-title")
                yield Static(
                    "Select a collection to load agent runs",
                    classes="panel-subtitle",
                    id="runs-summary",
                )
                yield DataTable(id="runs-table")
        yield Static("", id="status-bar")
        yield Footer()

    async def on_mount(self) -> None:
        self.jobs_table = self.query_one("#jobs-table", DataTable)
        self.ingestion_table = self.query_one("#ingestion-table", DataTable)
        self.collections_table = self.query_one("#collections-table", DataTable)
        self.runs_table = self.query_one("#runs-table", DataTable)
        self.jobs_summary = self.query_one("#jobs-summary", Static)
        self.ingestion_summary = self.query_one("#ingestion-summary", Static)
        self.collections_summary = self.query_one("#collections-summary", Static)
        self.runs_summary = self.query_one("#runs-summary", Static)
        self.status_label = self.query_one("#status-bar", Static)
        self.watch_status_message(self.status_message)

        self.jobs_table.zebra_stripes = True
        self.ingestion_table.zebra_stripes = True
        self.collections_table.zebra_stripes = True
        self.runs_table.zebra_stripes = True

        self.jobs_table.cursor_type = "row"
        self.ingestion_table.cursor_type = "row"
        self.collections_table.cursor_type = "row"
        self.runs_table.cursor_type = "row"

        self.jobs_table.add_columns("Status", "Type", "Target", "User", "Age", "Job ID")
        self.ingestion_table.add_columns(
            "Status",
            "Log",
            "Collection",
            "User",
            "Age",
            "Job ID",
        )
        self.collections_table.add_columns(
            "Collection",
            "Awaiting",
            "Processing",
            "Done",
            "Errored",
            "Total",
            "Recent/min",
            "Last Done",
        )
        self.runs_table.add_columns(
            "Agent Run",
            "Status",
            "Δ",
            "Current",
            "Processed",
            "Updated",
            "Error",
        )

        self.collections_table.focus()
        await self.data_provider.ensure_ready()
        await self.refresh_all()
        self.set_interval(self.AUTO_REFRESH_SECONDS, self._handle_auto_refresh)

    def watch_status_message(self, message: str) -> None:
        if self.status_label is not None:
            self.status_label.update(message)

    async def action_refresh(self) -> None:
        await self.refresh_all()

    async def action_toggle_auto_refresh(self) -> None:
        self.auto_refresh_enabled = not self.auto_refresh_enabled
        state = "enabled" if self.auto_refresh_enabled else "paused"
        self.status_message = f"Auto-refresh {state}"

    def _handle_auto_refresh(self) -> None:
        if not self.auto_refresh_enabled:
            return
        if self._refresh_lock.locked():
            return
        asyncio.create_task(self.refresh_all(from_timer=True))

    async def refresh_all(self, from_timer: bool = False) -> None:
        if self._refresh_lock.locked():
            if not from_timer:
                self.status_message = "Refresh already in progress"
            return

        async with self._refresh_lock:
            self.status_message = "Refreshing telemetry state…"
            try:
                jobs_task = asyncio.create_task(self.data_provider.fetch_jobs())
                job_stats_task = asyncio.create_task(self.data_provider.fetch_job_stats())
                collections_task = asyncio.create_task(
                    self.data_provider.fetch_collection_statuses()
                )
                jobs, job_stats, collections = await asyncio.gather(
                    jobs_task, job_stats_task, collections_task
                )
            except Exception as exc:
                self.status_message = f"Refresh failed: {exc}"
                raise
            self._render_jobs(jobs, job_stats)
            ingestion_jobs = [
                job for job in jobs if job.type == WorkerFunction.TELEMETRY_INGEST_JOB.value
            ]
            self._render_ingestion(ingestion_jobs)
            self._render_collections(collections)
            if self.selected_collection_id:
                self._start_agent_runs_task(self.selected_collection_id)
            self.status_message = "Telemetry state updated"

    def _render_jobs(
        self,
        jobs: Sequence[JobInfo],
        job_stats: Mapping[str, JobQueueStats] | None = None,
    ) -> None:
        assert self.jobs_table is not None and self.jobs_summary is not None
        cursor, scroll = self._capture_table_state(self.jobs_table)
        self._jobs_data = list(jobs)
        if job_stats is not None:
            self._job_stats_data = dict(job_stats)
        self.jobs_table.clear()
        sorted_jobs = self._sorted_jobs()
        now = utcnow_naive()
        for job in sorted_jobs:
            age = humanize_timedelta(now - job.created_at)
            job_type = job.type.replace("_", " ").title()
            self.jobs_table.add_row(
                job.status.upper(),
                job_type,
                job.collection_id or "—",
                job.user_email or "—",
                age,
                job.id,
                key=job.id,
            )
        self.jobs_summary.update(self._build_job_summary())
        self._restore_table_state(self.jobs_table, cursor, scroll)

    def _render_ingestion(self, jobs: Sequence[JobInfo]) -> None:
        assert self.ingestion_table is not None and self.ingestion_summary is not None
        cursor, scroll = self._capture_table_state(self.ingestion_table)
        self._ingestion_data = list(jobs)
        self.ingestion_table.clear()
        ordered = self._sorted_ingestion()
        now = utcnow_naive()
        for job in ordered:
            age = humanize_timedelta(now - job.created_at)
            log_id = job.payload.get("telemetry_log_id") or "—"
            collection = job.payload.get("collection_id") or "—"
            self.ingestion_table.add_row(
                job.status.upper(),
                log_id,
                collection,
                job.user_email or "—",
                age,
                job.id,
                key=job.id,
            )
        self.ingestion_summary.update(self._build_ingestion_summary())
        self._restore_table_state(self.ingestion_table, cursor, scroll)

    def _build_job_summary(self) -> str:
        recent_window = self.data_provider.RECENT_COMPLETION_MINUTES
        ingest_stats = self._job_stats_data.get(WorkerFunction.TELEMETRY_INGEST_JOB.value)
        processing_stats = self._job_stats_data.get(WorkerFunction.TELEMETRY_PROCESSING_JOB.value)

        parts: list[str] = []
        if ingest_stats:
            parts.append(self._format_job_stats("Ingest", ingest_stats, recent_window))
        if processing_stats:
            parts.append(self._format_job_stats("Processing", processing_stats, recent_window))

        if parts:
            return " | ".join(parts)

        pending = sum(1 for job in self._jobs_data if job.status == JobStatus.PENDING.value)
        running = sum(1 for job in self._jobs_data if job.status == JobStatus.RUNNING.value)
        return f"{len(self._jobs_data)} jobs · {pending} pending · {running} running"

    @staticmethod
    def _format_job_stats(label: str, stats: JobQueueStats, recent_window: int) -> str:
        rate_display = f"{stats.completion_rate_per_min:.2f}/m"
        return (
            f"{label}: queued {stats.queued} (pending {stats.pending}, running {stats.running})"
            f" · done {stats.completed} · {stats.recent_completed} in last {recent_window}m"
            f" ({rate_display})"
        )

    def _build_ingestion_summary(self) -> str:
        ingest_stats = self._job_stats_data.get(WorkerFunction.TELEMETRY_INGEST_JOB.value)
        if ingest_stats:
            rate_display = f"{ingest_stats.completion_rate_per_min:.2f}/m"
            return (
                f"{ingest_stats.queued} queued · {ingest_stats.pending} pending · "
                f"{ingest_stats.running} running · {ingest_stats.recent_completed} in last "
                f"{self.data_provider.RECENT_COMPLETION_MINUTES}m ({rate_display})"
            )
        pending = sum(1 for job in self._ingestion_data if job.status == JobStatus.PENDING.value)
        running = sum(1 for job in self._ingestion_data if job.status == JobStatus.RUNNING.value)
        return f"{len(self._ingestion_data)} jobs · {pending} pending · {running} running"

    def _render_collections(self, collections: Sequence[CollectionStatusRow]) -> None:
        assert self.collections_table is not None and self.collections_summary is not None
        _cursor, scroll = self._capture_table_state(self.collections_table)
        previous_selection = self.selected_collection_id
        self._collections_data = list(collections)
        self.collection_rows = {row.collection_id: row for row in self._collections_data}

        self.collections_table.clear()
        ordered_rows = self._sorted_collections()
        for row in ordered_rows:
            rate_display = f"{row.completion_rate_per_min:.2f}/m" if row.recent_completed else "—"
            self.collections_table.add_row(
                row.collection_id,
                str(row.awaiting),
                str(row.processing),
                str(row.completed),
                str(row.errored),
                str(row.total),
                rate_display,
                format_ago(row.last_completed_at),
                key=row.collection_id,
            )

        needs_work = sum(1 for row in self._collections_data if row.needs_work)
        self.collections_summary.update(
            f"{needs_work} collections need work · tracking {len(self._collections_data)} total"
        )

        if self.selected_collection_id not in self.collection_rows:
            self.selected_collection_id = (
                self._collections_data[0].collection_id if self._collections_data else None
            )
        elif previous_selection:
            self.selected_collection_id = previous_selection

        if not self.selected_collection_id or self.collections_table.row_count == 0:
            self._clear_runs_table()
        else:
            highlighted = self._highlight_collection_row()
            if not highlighted:
                self._clear_runs_table()
        self._restore_table_state(self.collections_table, None, scroll)

    def _clear_runs_table(self) -> None:
        if self.runs_table is not None:
            self.runs_table.clear()
        if self.runs_summary is not None:
            self.runs_summary.update("Select a collection to load agent runs")
        self._runs_data = []

    def _start_agent_runs_task(self, collection_id: str) -> None:
        if not collection_id:
            return
        self.selected_collection_id = collection_id
        if self._runs_task and not self._runs_task.done():
            self._runs_task.cancel()
        self._runs_task = asyncio.create_task(self._load_agent_runs(collection_id))

    async def _load_agent_runs(self, collection_id: str) -> None:
        self.status_message = f"Loading agent runs for {collection_id}…"
        try:
            rows = await self.data_provider.fetch_agent_run_statuses(collection_id)
        except asyncio.CancelledError:  # pragma: no cover - cancellation is expected
            return
        except Exception as exc:
            self.status_message = f"Agent run fetch failed: {exc}"
            return

        if self.selected_collection_id != collection_id:
            return

        self._render_agent_runs(rows)
        self.status_message = f"Loaded {len(rows)} agent runs for {collection_id}"

    def _highlight_collection_row(self) -> bool:
        if self.collections_table is None or not self.selected_collection_id:
            return False
        try:
            row_index = self.collections_table.get_row_index(self.selected_collection_id)
        except KeyError:
            return False
        try:
            self.collections_table.cursor_coordinate = (row_index, 0)
        except Exception:
            return False
        return True

    def _render_agent_runs(self, runs: Sequence[AgentRunStatusRow]) -> None:
        assert self.runs_table is not None and self.runs_summary is not None
        cursor, scroll = self._capture_table_state(self.runs_table)
        self._runs_data = list(runs)
        self.runs_table.clear()
        ordered_rows = self._sorted_runs()
        urgent = sum(1 for row in self._runs_data if row.requires_processing)
        for row in ordered_rows:
            delta = row.current_version - row.processed_version
            delta_display = f"+{delta}" if delta >= 0 else str(delta)

            status_display = row.status.replace("_", " ").title()

            error_text = truncate(row.error_message, 80) if row.error_message else ""

            self.runs_table.add_row(
                row.agent_run_id,
                status_display,
                delta_display,
                str(row.current_version),
                str(row.processed_version),
                format_ago(row.updated_at),
                error_text or "—",
                key=row.agent_run_id,
            )

        self.runs_summary.update(
            f"{urgent} runs waiting · showing {len(self._runs_data)} most recent rows"
        )
        self._restore_table_state(self.runs_table, cursor, scroll)

    async def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "collections-table":
            return
        row_key = getattr(event.row_key, "value", event.row_key)
        collection_id = str(row_key)
        self._start_agent_runs_task(collection_id)

    async def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        table_id = event.data_table.id
        if table_id is None:
            return
        self._handle_sort_request(table_id, event.column_index)

    def _handle_sort_request(self, table_id: str, column_index: int) -> None:
        if table_id == "jobs-table":
            self._jobs_sort_state = self._next_sort_state(
                self._jobs_sort_state, column_index, table_id
            )
            self._render_jobs(self._jobs_data, self._job_stats_data)
        elif table_id == "ingestion-table":
            self._ingestion_sort_state = self._next_sort_state(
                self._ingestion_sort_state, column_index, table_id
            )
            self._render_ingestion(self._ingestion_data)
        elif table_id == "collections-table":
            self._collections_sort_state = self._next_sort_state(
                self._collections_sort_state, column_index, table_id
            )
            self._render_collections(self._collections_data)
        elif table_id == "runs-table":
            self._runs_sort_state = self._next_sort_state(
                self._runs_sort_state, column_index, table_id
            )
            self._render_agent_runs(self._runs_data)

    def _next_sort_state(
        self,
        current: tuple[int, bool] | None,
        column_index: int,
        table_id: str,
    ) -> tuple[int, bool]:
        default_desc = self.DEFAULT_DESC_COLUMNS.get(table_id, set())
        if current and current[0] == column_index:
            return (column_index, not current[1])
        return (column_index, column_index in default_desc)

    @staticmethod
    def _capture_table_state(
        table: DataTable | None,
    ) -> tuple[tuple[int, int] | None, Any]:
        if table is None:
            return None, None
        cursor = getattr(table, "cursor_coordinate", None)
        scroll_offset = getattr(table, "scroll_offset", None)
        return cursor, scroll_offset

    @staticmethod
    def _restore_table_state(
        table: DataTable | None,
        cursor: tuple[int, int] | None,
        scroll_offset: Any,
    ) -> None:
        if table is None:
            return
        if cursor is not None:
            row, col = cursor
            row_count = getattr(table, "row_count", None)
            if row_count is None:
                try:
                    row_count = len(table.rows)
                except Exception:
                    row_count = 0
            col_count = getattr(table, "column_count", None)
            if col_count is None:
                try:
                    col_count = len(table.columns)
                except Exception:
                    col_count = 0
            max_row = max(row_count - 1, 0)
            max_col = max(col_count - 1, 0)
            safe_row = min(row, max_row)
            safe_col = min(col, max_col)
            try:
                table.cursor_coordinate = (safe_row, safe_col)
            except Exception:
                pass
        if scroll_offset is not None:
            try:
                scroll_to = getattr(table, "scroll_to", None)
                if callable(scroll_to):
                    x = getattr(scroll_offset, "x", 0)
                    y = getattr(scroll_offset, "y", scroll_offset)
                    scroll_to(x=x, y=y, animate=False)
                elif hasattr(table, "scroll_offset"):
                    table.scroll_offset = scroll_offset
            except Exception:
                pass

    def _sorted_jobs(self) -> list[JobInfo]:
        data = list(self._jobs_data)
        if not data:
            return data
        if self._jobs_sort_state is None:
            self._jobs_sort_state = (4, True)
        column, reverse = self._jobs_sort_state
        key_func = JOB_SORT_MAP.get(column)
        if key_func is None:
            return data
        return sorted(data, key=key_func, reverse=reverse)

    def _sorted_ingestion(self) -> list[JobInfo]:
        data = list(self._ingestion_data)
        if not data:
            return data
        if self._ingestion_sort_state is None:
            self._ingestion_sort_state = (4, True)
        column, reverse = self._ingestion_sort_state
        key_func = INGEST_SORT_MAP.get(column)
        if key_func is None:
            return data
        return sorted(data, key=key_func, reverse=reverse)

    def _sorted_collections(self) -> list[CollectionStatusRow]:
        data = list(self._collections_data)
        if not data:
            return data
        if self._collections_sort_state is None:
            self._collections_sort_state = (7, True)
        column, reverse = self._collections_sort_state
        key_func = COLLECTION_SORT_MAP.get(column)
        if key_func is None:
            return data
        return sorted(data, key=key_func, reverse=reverse)

    def _sorted_runs(self) -> list[AgentRunStatusRow]:
        data = list(self._runs_data)
        if not data:
            return data
        if self._runs_sort_state is None:
            self._runs_sort_state = (5, True)
        column, reverse = self._runs_sort_state
        key_func = RUN_SORT_MAP.get(column)
        if key_func is None:
            return data
        return sorted(data, key=key_func, reverse=reverse)


def main() -> None:
    TelemetryDashboardApp().run()


if __name__ == "__main__":
    main()
