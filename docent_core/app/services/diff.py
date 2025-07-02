from typing import Any

from docent.data_models.agent_run import AgentRun
from docent_core._ai_tools.search_paired import (
    SearchPairedResultStreamingCallback,
    execute_search_paired,
)
from docent_core._db_service.db import DocentDB
from docent_core._db_service.service import DBService
from docent_core._server._rest.router import ViewContext


class DiffService:
    def __init__(self, db: DocentDB, service: DBService):
        self.db = db
        self.service = service

    #################
    # Paired search #
    #################

    async def compute_paired_search(
        self,
        ctx: ViewContext,
        # How to pair the runs up
        grouping_md_fields: list[str],
        identifying_md_field_value_1: tuple[str, Any],
        identifying_md_field_value_2: tuple[str, Any],
        # What to search for
        shared_context: str,
        action_1: str,
        action_2: str,
        # Callback
        search_result_callback: SearchPairedResultStreamingCallback | None = None,
    ):
        # Pair agent runs up
        agent_runs = await self.service.get_agent_runs(ctx)
        m: dict[tuple[Any, ...], dict[tuple[str, Any], AgentRun]] = {}
        for run in agent_runs:
            key = tuple(run.metadata.get(field) for field in grouping_md_fields)
            if key not in m:
                m[key] = {}
            if run.metadata.get(identifying_md_field_value_1[0]) == identifying_md_field_value_1[1]:
                m[key][identifying_md_field_value_1] = run
            elif (
                run.metadata.get(identifying_md_field_value_2[0]) == identifying_md_field_value_2[1]
            ):
                m[key][identifying_md_field_value_2] = run
            else:
                raise ValueError(f"Run {run.id} does not match any identifying field value")

        paired_list: list[tuple[AgentRun, AgentRun]] = []
        for k, v in m.items():
            if len(v) > 2:
                raise ValueError(f"Paired failed. Found {len(v)} runs for key {k}")
            paired_list.append((v[identifying_md_field_value_1], v[identifying_md_field_value_2]))

        return await execute_search_paired(
            paired_list,
            shared_context,
            action_1,
            action_2,
            search_result_callback=search_result_callback,
        )

    # #########
    # # Diffs #
    # #########

    # async def get_diffs_report(self, diffs_report_id: str) -> SQLADiffsReport:
    #     async with self.db.session() as session:
    #         result = await session.execute(
    #             select(SQLADiffsReport).where(SQLADiffsReport.id == diffs_report_id)
    #         )
    #     return result.scalar_one()

    # async def compute_diffs(
    #     self,
    #     ctx: ViewContext,
    #     diffs_report_id: str,
    #     diff_callback: Callable[[TranscriptDiff | None], Coroutine[Any, Any, None]] | None = None,
    #     should_include_existing_diffs: bool = False,
    #     should_persist: bool = True,
    # ):
    #     # TODO(vincent): intersect with a filter, maybe allow user to pass in attribute as well
    #     # get pairs of datapoints from collection_id where (sample_id, task_id, epoch_id) match
    #     # and the datapoints have the corresponding experiment_id's

    #     # TODO(vincent): flexible binning and comparisons

    #     agent_runs = await self.get_agent_runs(ctx)
    #     from docent_core._ai_tools.diffs.models import SQLADiffsReport

    #     async with self.db.session() as session:
    #         result = await session.execute(
    #             select(SQLADiffsReport).where(SQLADiffsReport.id == diffs_report_id)
    #         )
    #         diffs_report = result.scalar_one()

    #     experiment_id_1 = diffs_report.experiment_id_1
    #     experiment_id_2 = diffs_report.experiment_id_2

    #     logger.info(f"have {len(agent_runs)} datapoints", experiment_id_1, experiment_id_2)

    #     # group by sample_id, task_id, epoch_id
    #     agent_runs_by_sample_task_epoch: dict[tuple[str, str, str], list[AgentRun]] = {}
    #     for dp in agent_runs:
    #         key = (
    #             str(dp.metadata.get("sample_id")),
    #             str(dp.metadata.get("task_id")),
    #             str(dp.metadata.get("epoch_id")),
    #         )
    #         if key not in agent_runs_by_sample_task_epoch:
    #             agent_runs_by_sample_task_epoch[key] = []
    #         agent_runs_by_sample_task_epoch[key].append(dp)

    #     existing_diff_pairs = {}
    #     from docent_core._ai_tools.diffs.models import SQLATranscriptDiff

    #     if should_include_existing_diffs:
    #         # Get existing diff results from database
    #         async with self.db.session() as session:
    #             result = await session.execute(
    #                 select(SQLATranscriptDiff).where(
    #                     SQLATranscriptDiff.collection_id == ctx.collection_id,
    #                 )
    #             )
    #             existing_diffs = result.scalars().all()
    #             # TODO(vincent): we didn't actually check for exp_ids...

    #         # Stream existing diffs
    #         if diff_callback is not None:
    #             for diff in existing_diffs:
    #                 print(diff)
    #                 await diff_callback(diff.to_pydantic())

    #     tasks: list[Coroutine[Any, Any, TranscriptDiff]] = []
    #     pairs_to_compute: list[tuple[str, str]] = []

    #     for agent_run_lists in agent_runs_by_sample_task_epoch.values():
    #         first_pair_candidates = [
    #             dp for dp in agent_run_lists if dp.metadata.get("experiment_id") == experiment_id_1
    #         ]
    #         second_pair_candidates = [
    #             dp for dp in agent_run_lists if dp.metadata.get("experiment_id") == experiment_id_2
    #         ]

    #         if len(first_pair_candidates) > 0 and len(second_pair_candidates) > 0:
    #             first_dp = first_pair_candidates[0]
    #             second_dp = second_pair_candidates[0]

    #             # Check if we already have results for this pair
    #             if (first_dp.id, second_dp.id) not in existing_diff_pairs:
    #                 tasks.append(compute_transcript_diff(first_dp, second_dp, diffs_report_id))
    #                 pairs_to_compute.append((first_dp.id, second_dp.id))

    #     logger.info(f"Computing diffs for {len(tasks)} new pairs")

    #     # Compute diffs for pairs that don't have results yet
    #     results = await asyncio.gather(*tasks)

    #     # Store results in database if should_persist is True
    #     from docent_core._ai_tools.diffs.models import SQLATranscriptDiff

    #     transcript_diffs_models: list[SQLATranscriptDiff] = []
    #     for transcript_diff in results:
    #         transcript_diffs_models.append(SQLATranscriptDiff.from_pydantic(transcript_diff, ctx))
    #         if diff_callback is not None:
    #             await diff_callback(transcript_diff)

    #     print("tdms", transcript_diffs_models)
    #     if transcript_diffs_models and should_persist:
    #         for transcript_diff in transcript_diffs_models:
    #             transcript_diff.diffs_report_id = diffs_report.id

    #         async with self.db.session() as session:
    #             session.add_all(transcript_diffs_models)
    #             session.add(diffs_report)

    #         logger.info(
    #             f"Pushed {len(transcript_diffs_models)} diff attributes and updated Report{diffs_report.id}"
    #         )
    #     return transcript_diffs_models

    # #########################
    # # Clustering diffs
    # #########################

    # async def compute_diff_clusters(
    #     self,
    #     ctx: ViewContext,
    #     claims: list[Claim],
    # ):
    #     # datapoints = await self.get_agent_runs(ctx)
    #     # expid_by_datapoint = {d.id: d.metadata.get("experiment_id") for d in datapoints}
    #     # async with self.db.session() as session:
    #     #     result = await session.execute(
    #     #         select(SQLADiffAttribute)
    #     #         .where(
    #     #             SQLADiffAttribute.collection_id == ctx.collection_id,
    #     #         )
    #     #         .order_by(SQLADiffAttribute.id)
    #     #     )
    #     #     existing_diffs = result.scalars().all()
    #     # valid_existing_diffs = [
    #     #     d.to_diff_attribute()
    #     #     for d in existing_diffs
    #     #     if expid_by_datapoint.get(d.data_id_1) == experiment_id_1
    #     #     and expid_by_datapoint.get(d.data_id_2) == experiment_id_2
    #     # ]
    #     # print(f"have {len(valid_existing_diffs)} valid existing diffs")
    #     print("-------------------------------- Claims --------------------------------")
    #     print(claims)

    #     clusters = await cluster_diff_claims(claims)
    #     return clusters

    # async def compute_diff_search(
    #     self,
    #     ctx: ViewContext,
    #     experiment_id_1: str,
    #     experiment_id_2: str,
    #     search_query: str,
    #     search_result_callback: (
    #         Callable[[tuple[str, int]], Coroutine[Any, Any, None]] | None
    #     ) = None,
    # ) -> list[tuple[str, int]]:
    #     datapoints = await self.get_agent_runs(ctx)
    #     expid_by_datapoint = {d.id: d.metadata.get("experiment_id") for d in datapoints}
    #     async with self.db.session() as session:
    #         result = await session.execute(
    #             select(SQLADiffAttribute)
    #             .where(
    #                 SQLADiffAttribute.collection_id == ctx.collection_id,
    #             )
    #             .order_by(SQLADiffAttribute.id)
    #         )
    #         existing_diffs = result.scalars().all()
    #     valid_existing_diffs = [
    #         d.to_diff_attribute()
    #         for d in existing_diffs
    #         if expid_by_datapoint.get(d.data_id_1) == experiment_id_1
    #         and expid_by_datapoint.get(d.data_id_2) == experiment_id_2
    #     ]

    #     results = await search_over_diffs(
    #         search_query,
    #         [d.claim or "" for d in valid_existing_diffs],
    #         search_result_callback=search_result_callback,
    #     )

    #     # TODO(vincent): stream the results
    #     return results
