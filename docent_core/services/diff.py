from typing import Any, AsyncContextManager, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from docent.data_models.agent_run import AgentRun
from docent_core._ai_tools.search_paired import (
    SearchPairedQuery,
    SearchPairedResult,
    SearchPairedResultStreamingCallback,
    execute_search_paired,
)
from docent_core._db_service.schemas.tables import (
    SQLAPairedSearchQuery,
    SQLAPairedSearchResult,
)
from docent_core._db_service.service import DBService
from docent_core._server._rest.router import ViewContext


class DiffService:
    def __init__(
        self,
        session: AsyncSession,
        writer_session_ctx: Callable[[], AsyncContextManager[AsyncSession]],
        service: DBService,
    ):
        """The `writer_session_ctx` creates new sessions that commit writes immediately.
        This is helpful if you don't want to wait for results to be written."""

        self.session = session
        self.writer_session_ctx = writer_session_ctx
        self.service = service

    #################
    # Paired search #
    #################

    def pair_runs(
        self,
        agent_runs: list[AgentRun],
        grouping_md_fields: list[str],
        identifying_md_field_value_1: tuple[str, Any],
        identifying_md_field_value_2: tuple[str, Any],
    ):
        # Map from the grouping key (determined by grouping_md_fields) to
        #   a dict of field values to matching agent runs.
        m: dict[tuple[Any, ...], dict[tuple[str, Any], list[AgentRun]]] = {}
        for run in agent_runs:
            key = tuple(run.metadata.get(field) for field in grouping_md_fields)
            if key not in m:
                m[key] = {}
            if run.metadata.get(identifying_md_field_value_1[0]) == identifying_md_field_value_1[1]:
                m[key].setdefault(identifying_md_field_value_1, []).append(run)
            elif (
                run.metadata.get(identifying_md_field_value_2[0]) == identifying_md_field_value_2[1]
            ):
                m[key].setdefault(identifying_md_field_value_2, []).append(run)
            else:
                raise ValueError(f"Run {run.id} does not match any identifying field value")

        return m

    async def add_paired_search_query(self, ctx: ViewContext, query: SearchPairedQuery):
        sqla_query = SQLAPairedSearchQuery.from_pydantic(query, ctx.collection_id)
        self.session.add(sqla_query)
        await self.session.commit()  # Ensure writer session can see this query
        return sqla_query.id

    async def compute_paired_search(
        self,
        ctx: ViewContext,
        query_id: str,
        search_result_callback: SearchPairedResultStreamingCallback | None = None,
    ):
        # Get query
        result = await self.session.execute(
            select(SQLAPairedSearchQuery).where(SQLAPairedSearchQuery.id == query_id)
        )
        sqla_query = result.scalar_one()
        query, query_id = sqla_query.to_pydantic(), sqla_query.id
        agent_runs = await self.service.get_agent_runs(ctx)

        # Aggregate agent runs up according to the query
        m = self.pair_runs(
            agent_runs,
            query.grouping_md_fields,
            query.md_field_value_1,
            query.md_field_value_2,
        )

        # Pair agent runs up; raise error if there are more than 2 runs for a key
        paired_list: list[tuple[AgentRun, AgentRun]] = []
        for k, v in m.items():
            if len(v) > 2:
                raise ValueError(f"Pairing failed. Found {len(v)} runs for key {k}")

            runs_1, runs_2 = v[query.md_field_value_1], v[query.md_field_value_2]
            if not (len(runs_1) == 1 and len(runs_2) == 1):
                raise ValueError(
                    f"Pairing failed. Found {len(runs_1)} runs for {query.md_field_value_1} and {len(runs_2)} runs for {query.md_field_value_2}"
                )
            paired_list.append((runs_1[0], runs_2[0]))

        async def _callback(search_results: list[SearchPairedResult]):
            if search_result_callback is not None:
                await search_result_callback(search_results)

            sqla_results = [
                SQLAPairedSearchResult.from_pydantic(result, query_id) for result in search_results
            ]
            # Use a separate writer session that commits changes immediately
            async with self.writer_session_ctx() as write_session:
                write_session.add_all(sqla_results)

        await execute_search_paired(paired_list, query, search_result_callback=_callback)

    async def get_paired_search_results(self, query_id: str) -> list[SearchPairedResult]:
        result = await self.session.execute(
            select(SQLAPairedSearchResult).where(
                SQLAPairedSearchResult.paired_search_query_id == query_id
            )
            # Eager-load instances to avoid downstream errors
            .options(selectinload(SQLAPairedSearchResult.instances))
        )
        sqla_results = result.scalars().all()
        return [sqla_result.to_pydantic() for sqla_result in sqla_results]
