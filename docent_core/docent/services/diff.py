from typing import Any, AsyncContextManager, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent_core.docent.ai_tools.diff.diff import (
    DiffQuery,
    DiffResult,
    DiffResultStreamingCallback,
    execute_diff,
)
from docent_core.docent.ai_tools.diff.propose_claims import (
    DiffClaimsResult,
    execute_propose_claims,
)
from docent_core.docent.ai_tools.search_paired import (
    SearchPairedQuery,
    SearchPairedResult,
    SearchPairedResultStreamingCallback,
    execute_search_paired,
)
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.diff import (
    SQLADiffClaimsResult,
    SQLADiffQuery,
    SQLADiffResult,
    SQLAPairedSearchQuery,
    SQLAPairedSearchResult,
)
from docent_core.docent.services.monoservice import MonoService

logger = get_logger(__name__)


class DiffService:
    def __init__(
        self,
        session: AsyncSession,
        session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
        service: MonoService,
    ):
        """The `session_cm_factory` creates new sessions that commit writes immediately.
        This is helpful if you don't want to wait for results to be written."""

        self.session = session
        self.session_cm_factory = session_cm_factory
        self.service = service

    #################
    # Paired search #
    #################

    def pair_runs(
        self,
        agent_runs: list[AgentRun],
        grouping_md_fields: list[str],
        md_field_value_1: tuple[str, Any],
        md_field_value_2: tuple[str, Any],
        sample_if_multiple: bool = True,
        errors_ok: bool = True,
    ):
        # Map from the grouping key (determined by grouping_md_fields) to
        #   a dict of field values to matching agent runs.
        m: dict[tuple[Any, ...], dict[tuple[str, Any], list[AgentRun]]] = {}
        for run in agent_runs:
            key = tuple(run.metadata.get(field) for field in grouping_md_fields)
            if key not in m:
                m[key] = {}
            if run.metadata.get(md_field_value_1[0]) == md_field_value_1[1]:
                m[key].setdefault(md_field_value_1, []).append(run)
            elif run.metadata.get(md_field_value_2[0]) == md_field_value_2[1]:
                m[key].setdefault(md_field_value_2, []).append(run)

        # Pair agent runs up; raise error if there are more than 2 runs for a key
        paired_list: list[tuple[AgentRun, AgentRun]] = []
        for v in m.values():
            runs_1, runs_2 = v.get(md_field_value_1, []), v.get(md_field_value_2, [])

            # If there are exactly one for each, pair without errors
            if len(runs_1) == 1 and len(runs_2) == 1:
                paired_list.append((runs_1[0], runs_2[0]))

            # If there are more than one for each, sample one
            elif len(runs_1) > 0 and len(runs_2) > 0 and sample_if_multiple:
                paired_list.append((runs_1[0], runs_2[0]))

            # Otherwise, there's an error
            else:
                err_msg = f"Pairing failed. Found {len(runs_1)} runs for {md_field_value_1} and {len(runs_2)} runs for {md_field_value_2}"
                if errors_ok:
                    logger.warning(f"{err_msg} (continuing)")
                else:
                    raise ValueError(err_msg)

        return paired_list

    async def add_paired_search_query(self, ctx: ViewContext, query: SearchPairedQuery):
        sqla_query = SQLAPairedSearchQuery.from_pydantic(query, ctx.collection_id)
        self.session.add(sqla_query)
        return sqla_query.id

    async def compute_paired_search(
        self,
        ctx: ViewContext,
        query_id: str,
        search_result_callback: SearchPairedResultStreamingCallback | None = None,
    ):
        """Note: make sure `query_id` is *committed* before calling this function.
        The writer session needs to have access to it."""

        # Get query
        result = await self.session.execute(
            select(SQLAPairedSearchQuery).where(SQLAPairedSearchQuery.id == query_id)
        )
        sqla_query = result.scalar_one()
        query, query_id = sqla_query.to_pydantic(), sqla_query.id

        # Pair agent runs up
        agent_runs = await self.service.get_agent_runs(ctx)
        raw_paired_list = self.pair_runs(
            agent_runs,
            query.grouping_md_fields,
            query.md_field_value_1,
            query.md_field_value_2,
        )

        # Only compute search results for agent runs that don't have results yet
        cur_results = await self.get_paired_search_results(query_id)
        pairs_with_results = set(
            (result.agent_run_1_id, result.agent_run_2_id) for result in cur_results
        )
        paired_list = [
            pair for pair in raw_paired_list if (pair[0].id, pair[1].id) not in pairs_with_results
        ]

        # Early exit if nothing to do
        if len(paired_list) == 0:
            logger.warning(
                f"Skipping compute_paired_search for query {query_id}, all pairs already have results"
            )
            return

        async def _callback(search_results: list[SearchPairedResult]):
            if search_result_callback is not None:
                await search_result_callback(search_results)

            sqla_results = [
                SQLAPairedSearchResult.from_pydantic(result, query_id) for result in search_results
            ]
            # Use a separate writer session that commits changes immediately
            async with self.session_cm_factory() as write_session:
                write_session.add_all(sqla_results)

        logger.info(f"Computing search results for {len(paired_list)}/{len(raw_paired_list)} pairs")
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

    ######################################
    # Computing low-level diff instances #
    ######################################

    async def add_diff_query(self, ctx: ViewContext, query: DiffQuery):
        sqla_query = SQLADiffQuery.from_pydantic(query, ctx.collection_id)
        self.session.add(sqla_query)
        return sqla_query.id

    async def get_diff_query(self, query_id: str) -> SQLADiffQuery:
        result = await self.session.execute(
            select(SQLADiffQuery).where(SQLADiffQuery.id == query_id)
        )
        return result.scalar_one()

    async def get_all_diff_queries(self, ctx: ViewContext) -> list[DiffQuery]:
        """Get all diff queries for a collection."""
        result = await self.session.execute(
            select(SQLADiffQuery).where(SQLADiffQuery.collection_id == ctx.collection_id)
        )
        sqla_queries = result.scalars().all()
        return [sqla_query.to_pydantic() for sqla_query in sqla_queries]

    async def compute_diff(
        self,
        ctx: ViewContext,
        query_id: str,
        diff_result_callback: DiffResultStreamingCallback | None = None,
    ):
        """Only computes diffs for agent runs that don't have results yet.

        Note: make sure `query_id` is *committed* before calling this function.
        The writer session needs to have access to it.
        """

        # Get query
        query = (await self.get_diff_query(query_id)).to_pydantic()

        # Pair agent runs up
        agent_runs = await self.service.get_agent_runs(ctx)
        raw_paired_list = self.pair_runs(
            agent_runs,
            query.grouping_md_fields,
            query.md_field_value_1,
            query.md_field_value_2,
        )

        # Only compute diffs for agent runs that don't have results yet
        cur_results = await self.get_diff_results(query_id)
        pairs_with_results = set(
            (result.agent_run_1_id, result.agent_run_2_id) for result in cur_results
        )
        paired_list = [
            pair for pair in raw_paired_list if (pair[0].id, pair[1].id) not in pairs_with_results
        ]

        # Early exit if nothing to do
        if len(paired_list) == 0:
            logger.warning(
                f"Skipping compute_diff for query {query_id}, all pairs already have results"
            )
            return

        async def _callback(diff_results: list[DiffResult]):
            if diff_result_callback is not None:
                await diff_result_callback(diff_results)

            sqla_results = [
                SQLADiffResult.from_pydantic(result, query_id) for result in diff_results
            ]
            # Use a separate writer session that commits changes immediately
            async with self.session_cm_factory() as write_session:
                write_session.add_all(sqla_results)

        logger.info(f"Computing diffs for {len(paired_list)}/{len(raw_paired_list)} pairs")
        await execute_diff(paired_list, query.focus, diff_result_callback=_callback)

    async def get_diff_results(self, query_id: str) -> list[DiffResult]:
        result = await self.session.execute(
            select(SQLADiffResult).where(SQLADiffResult.diff_query_id == query_id)
            # Eager-load instances to avoid downstream errors
            .options(selectinload(SQLADiffResult.instances))
        )
        sqla_results = result.scalars().all()
        return [sqla_result.to_pydantic() for sqla_result in sqla_results]

    async def delete_diff_results(self, query_id: str):
        """Uses ORM delete to trigger cascade."""
        result = await self.session.execute(
            select(SQLADiffResult).where(SQLADiffResult.diff_query_id == query_id)
        )
        diff_results = result.scalars().all()
        for diff_result in diff_results:
            await self.session.delete(diff_result)

    ########################################
    # Proposing diff claims from instances #
    ########################################

    async def propose_diff_claims(self, query_id: str):
        """Only proposes claims if there aren't any already."""

        # Are there existing claim results?
        existing_claims = await self.get_diff_claims(query_id)
        if existing_claims is not None:
            logger.warning(
                f"Skipping propose_diff_claims for query {query_id}, already have claims"
            )
            return

        # Get query and results
        sqla_query = await self.get_diff_query(query_id)
        query = sqla_query.to_pydantic()
        results = await self.get_diff_results(query_id)

        # Feed them all into a language model to propose high-level claims
        claims_result = await execute_propose_claims(results, query)

        # Persist the claims result to the database
        sqla_claims_result = SQLADiffClaimsResult.from_pydantic(
            claims_result, query_id, sqla_query.collection_id
        )
        self.session.add(sqla_claims_result)

    async def delete_diff_claims(self, query_id: str):
        """Uses ORM delete to trigger cascade."""
        result = await self.session.execute(
            select(SQLADiffClaimsResult).where(SQLADiffClaimsResult.diff_query_id == query_id)
        )
        claims_results = result.scalars().all()

        for claims_result in claims_results:
            await self.session.delete(claims_result)

    async def get_diff_claims(self, query_id: str) -> DiffClaimsResult | None:
        result = await self.session.execute(
            select(SQLADiffClaimsResult).where(SQLADiffClaimsResult.diff_query_id == query_id)
            # Eager-load the paired search queries to avoid downstream errors
            .options(selectinload(SQLADiffClaimsResult.paired_search_queries))
        )
        # `one_or_none` is fine since we always maintain that there's only one
        sqla_claims_result = result.scalar_one_or_none()
        return sqla_claims_result.to_pydantic() if sqla_claims_result is not None else None


"""
select
    agent_1_action_1,
    agent_1_action_2,
    agent_2_action_1,
    agent_2_action_2
from paired_search_result r
join paired_search_instance i on r.id = i.paired_search_result_id
where r.paired_search_query_id = 'c09af043-0de1-475a-8fa2-8a4e396def65';

select
    count(*) filter (where agent_1_action_1 = true and agent_2_action_1 = false) as agent1_only,
    count(*) filter (where agent_1_action_1 = false and agent_2_action_1 = true) as agent2_only,
    count(*) filter (where agent_1_action_1 = false and agent_2_action_1 = false) as neither,
    count(*) filter (where agent_1_action_1 = true and agent_2_action_1 = true) as both
from paired_search_result r
join paired_search_instance i on r.id = i.paired_search_result_id
where r.paired_search_query_id = 'c8e8662e-7c10-4831-9679-a82664ef460f';

select
    count(*) filter (where agent_1_action_2 = true and agent_2_action_2 = false) as agent1_only,
    count(*) filter (where agent_1_action_2 = false and agent_2_action_2 = true) as agent2_only,
    count(*) filter (where agent_1_action_2 = false and agent_2_action_2 = false) as neither,
    count(*) filter (where agent_1_action_2 = true and agent_2_action_2 = true) as both
from paired_search_result r
join paired_search_instance i on r.id = i.paired_search_result_id
-- where r.paired_search_query_id = 'c09af043-0de1-475a-8fa2-8a4e396def65';
where r.paired_search_query_id = 'f7ace840-0db0-4859-bd3b-971f4baaf1da';


select *
from paired_search_result r
join paired_search_instance i on r.id = i.paired_search_result_id
where
    r.paired_search_query_id = 'c8e8662e-7c10-4831-9679-a82664ef460f'
    and agent_1_action_1 = true and agent_2_action_1 = false;
"""
