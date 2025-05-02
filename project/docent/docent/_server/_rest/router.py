import hashlib
import json
from functools import partial
from typing import Any, Literal, TypedDict, cast
from uuid import uuid4

import anyio
from docent._frames.clustering.cluster_generator import ClusterFeedback
from docent._frames.db.service import DBService
from docent._frames.filters import (
    ComplexFrameFilter,
    FrameDimension,
    FrameFilterTypes,
    FramePredicate,
    PrimitiveFilter,
    parse_filter_dict,
)
from docent._frames.transcript import Citation, parse_citations_single_transcript
from docent._frames.types import Datapoint
from docent._server._assistant.chat import make_single_tasst_system_prompt
from docent._server._assistant.feedback import generate_new_queries
from docent._server._assistant.summarizer import (
    HighLevelAction,
    LowLevelAction,
    ObservationType,
    group_actions_into_high_level_steps,
    interesting_agent_observations,
    summarize_agent_actions,
    summarize_intended_solution,
)
from docent._server._rest.send_state import (
    publish_datapoints_updated,
    publish_dims,
    publish_marginals,
    publish_state,
)
from docent._server.util import sse_event_stream
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from llm_util.prod_llms import get_llm_completions_async
from llm_util.types import LLMOutput
from log_util.logger import get_logger
from pydantic import BaseModel
from sqlalchemy.inspection import inspect as sqla_inspect

logger = get_logger(__name__)


rest_router = APIRouter()
DB = None


async def get_db():
    global DB
    if DB is None:
        DB = await DBService.init()
    return DB


@rest_router.get("/ping")
async def ping():
    return {"status": "ok", "message": "pong"}


async def _check_fg_exists(db: DBService, fg_id: str):
    if not await db.exists(fg_id):
        raise HTTPException(status_code=404, detail=f"Frame grid with ID {fg_id} not found")


@rest_router.get("/framegrids")
async def get_framegrids():
    db = await get_db()
    sqla_fgs = await db.get_fgs()

    return [
        {c.key: getattr(obj, c.key) for c in sqla_inspect(obj).mapper.column_attrs}
        for obj in sqla_fgs
    ]


class CreateFrameGridRequest(BaseModel):
    eval_id: str | None = None
    name: str | None = None
    description: str | None = None


@rest_router.post("/create")
async def create(request: CreateFrameGridRequest = CreateFrameGridRequest()):
    db = await get_db()

    # Starting from an existing eval
    fg_id, sample_dim_id, experiment_dim_id = None, None, None
    if request.eval_id:
        raise NotImplementedError(
            "This functionality is deprecated. Load using the client SDK instead."
        )
    else:
        fg_id = await db.create(name=request.name, description=request.description)

    return {"fg_id": fg_id, "sample_dim_id": sample_dim_id, "experiment_dim_id": experiment_dim_id}


class JoinFrameGridRequest(BaseModel):
    fg_id: str


@rest_router.post("/join")
async def join(request: JoinFrameGridRequest):
    db = await get_db()
    if not await db.exists(request.fg_id):
        raise HTTPException(status_code=404, detail=f"Frame grid with ID {request.fg_id} not found")
    return {
        "fg_id": request.fg_id,
        "sample_dim_id": await db.get_sample_dim_id(request.fg_id),
        "experiment_dim_id": await db.get_experiment_dim_id(request.fg_id),
    }


@rest_router.get("/transcript_metadata_fields")
async def transcript_metadata_fields(fg_id: str):
    db = await get_db()

    # Get any datapoint to get the metadata fields
    any_data = await db.get_any_datapoint(fg_id)
    if any_data:
        score_types = [
            {
                "name": f"metadata.scores.{k}",
                "type": type(v).__name__,
            }
            for k, v in any_data.metadata.scores.items()
        ]
    else:
        score_types = []

    return {
        "fields": [
            {
                "name": "text",
                "type": "str",
            },
            {
                "name": "metadata.task_id",
                "type": "str",
            },
            {
                "name": "metadata.sample_id",
                "type": "str",
            },
            {
                "name": "metadata.epoch_id",
                "type": "int",
            },
            {
                "name": "metadata.experiment_id",
                "type": "str",
            },
            {
                "name": "metadata.model",
                "type": "str",
            },
        ]
        + score_types,
    }


class PostDatapointsRequest(BaseModel):
    fg_id: str
    datapoints: list[Datapoint]


@rest_router.post("/datapoints")
async def post_datapoints(request: PostDatapointsRequest):
    db = await get_db()

    async with db.advisory_lock(request.fg_id, action_id="mutation"):
        num_added = await db.add_datapoints(request.fg_id, request.datapoints)
        await publish_state(db, request.fg_id)
        await publish_datapoints_updated(request.fg_id, None)
        return {"num_added": num_added}


class PostDimensionRequest(BaseModel):
    fg_id: str
    dim: FrameDimension
    is_sample_dim: bool = False
    is_experiment_dim: bool = False


@rest_router.post("/dimension")
async def post_dimension(request: PostDimensionRequest):
    db = await get_db()

    await db.upsert_dim(request.fg_id, request.dim)

    # Set special dimension if applicable
    if request.is_sample_dim and request.is_experiment_dim:
        raise ValueError("Cannot set both sample and experiment dimensions")
    if request.is_sample_dim:
        await db.set_sample_dim(request.fg_id, request.dim.id)
    if request.is_experiment_dim:
        await db.set_experiment_dim(request.fg_id, request.dim.id)

    await publish_dims(db, request.fg_id)
    # await publish_all_marginals(db, request.fg_id, ensure_fresh=True)

    return request.dim.id


class PostBaseFilterRequest(BaseModel):
    fg_id: str
    filter: ComplexFrameFilter | None


@rest_router.post("/base_filter")
async def post_base_filter(request: PostBaseFilterRequest):
    db = await get_db()

    async with db.advisory_lock(request.fg_id, action_id="mutation"):
        # Parse and set filter
        await db.set_base_filter(request.fg_id, request.filter)

        # Publish updated state while recomputing marginals
        await publish_state(db, request.fg_id)

        return request.filter.id if request.filter else None


class GetRegexSnippetsRequest(BaseModel):
    fg_id: str
    filter_id: str
    datapoint_ids: list[str]


@rest_router.post("/get_regex_snippets")
async def get_regex_snippets(request: GetRegexSnippetsRequest):
    db = await get_db()
    fg_id, filter_id, datapoint_ids = request.fg_id, request.filter_id, request.datapoint_ids

    filter = await db.get_filter(fg_id, filter_id)
    if filter is None:
        raise ValueError(f"Filter {filter_id} is not found")

    # Collect all patterns from the filter
    patterns = []
    if filter.type == "primitive" and filter.op == "~*":
        patterns.append(str(filter.value))
    elif filter.type == "complex":

        # Recursively search for all primitive filters
        def _search(f: FrameFilterTypes):
            if f.type == "primitive" and f.op == "~*":
                patterns.append(str(f.value))
            elif f.type == "complex":
                for child in f.filters:
                    _search(child)

        _search(filter)

    if not patterns:
        return {}

    datapoints = await db.get_datapoints_by_ids(fg_id, datapoint_ids)
    return dict(
        (d.id, [item for p in patterns for item in PrimitiveFilter.get_regex_snippets(d.text, p)])
        for d in datapoints
    )


@rest_router.get("/state")
async def get_state(fg_id: str):
    db = await get_db()
    await publish_state(db, fg_id)


@rest_router.get("/dimensions")
async def get_dimensions(fg_id: str):
    db = await get_db()
    return await db.get_dims(fg_id)


@rest_router.delete("/dimension")
async def delete_dimension(fg_id: str, dim_id: str):
    db = await get_db()

    async with db.advisory_lock(fg_id, action_id="mutation"):
        await db.delete_dimension(fg_id, dim_id)
        await publish_dims(db, fg_id)


@rest_router.delete("/filter")
async def delete_filter(fg_id: str, dim_id: str, filter_id: str):
    db = await get_db()

    async with db.advisory_lock(fg_id, action_id="mutation"):
        await db.delete_filter(fg_id, filter_id)
        await publish_dims(db, fg_id)
        await publish_marginals(db, fg_id, dim_ids=[dim_id], ensure_fresh=True)


class PostFilterRequest(BaseModel):
    fg_id: str
    dim_id: str | None = None
    filter_id: str
    new_predicate: str


@rest_router.post("/filter")
async def post_filter(request: PostFilterRequest):
    db = await get_db()
    fg_id, bin_id, new_predicate = request.fg_id, request.filter_id, request.new_predicate

    async with db.advisory_lock(fg_id, action_id="mutation"):
        old_filter = await db.get_filter(fg_id, bin_id)
        if old_filter is None:
            raise ValueError(f"Filter {bin_id} not found")

        # Push filter (takes care of clearing related judgments)
        new_filter = old_filter.model_copy(
            update={"name": new_predicate, "predicate": new_predicate}
        )
        await db.set_filter(fg_id, bin_id, new_filter)

        # If the filter is part of a dimension, we need to publish the marginals for that dimension
        if request.dim_id:
            # Publish the initial marginals (without recompute) which should be empty for the new filter
            # Otherwise the frontend will show the old filter's marginals
            await publish_marginals(db, fg_id, dim_ids=[request.dim_id], ensure_fresh=False)
            await publish_dims(db, fg_id)
            await publish_marginals(db, fg_id, dim_ids=[request.dim_id], ensure_fresh=True)

        return new_filter.id


@rest_router.get("/datapoint")
async def get_datapoint(fg_id: str, datapoint_id: str):
    db = await get_db()
    return await db.get_datapoint(fg_id, datapoint_id)


class DatapointMetadataRequest(BaseModel):
    fg_id: str
    datapoint_ids: list[str]


@rest_router.post("/datapoint_metadata")
async def get_datapoint_metadata(request: DatapointMetadataRequest):
    db = await get_db()
    data = await db.get_datapoints_by_ids(request.fg_id, request.datapoint_ids)
    return {d.id: d.metadata for d in data}


class AttributeWithCitation(TypedDict):
    attribute: str
    citations: list[Citation]


class StreamedAttribute(TypedDict):
    datapoint_id: str | None
    attribute: str | None
    attributes: list[AttributeWithCitation] | None
    num_datapoints_done: int
    num_datapoints_total: int


class ComputeAttributesRequest(BaseModel):
    fg_id: str
    attribute: str


@rest_router.post("/start_compute_attributes")
async def start_compute_attributes(request: ComputeAttributesRequest):
    db = await get_db()
    job_id = await db.add_job(
        {
            "type": "compute_attributes",
            "fg_id": request.fg_id,
            "attribute": request.attribute,
        }
    )
    return job_id


@rest_router.get("/listen_compute_attributes")
async def listen_compute_attributes(job_id: str):
    db = await get_db()

    # Retrieve job arguments
    job = await db.get_job(job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    fg_id, attribute = job["fg_id"], job["attribute"]

    # Create AnyIO queue that we can write intermediate results to
    # At the max size of the queue, the producer will block
    send_stream, recv_stream = anyio.create_memory_object_stream(max_buffer_size=100_000)

    # Track intermediate progress
    progress_lock = anyio.Lock()
    num_done, num_total = 0, len(await db.get_base_data(fg_id))

    async def _ws_attribute_streaming_callback(
        datapoint_id: str, attribute: str, attributes: list[str] | None
    ) -> None:
        nonlocal num_done

        if attributes is None:
            return

        async with progress_lock:
            num_done += 1
            payload: StreamedAttribute = {
                "datapoint_id": datapoint_id,
                "attribute": attribute,
                "attributes": [
                    {
                        "attribute": attr,
                        "citations": parse_citations_single_transcript(attr),
                    }
                    for attr in attributes
                ],
                "num_datapoints_done": num_done,
                "num_datapoints_total": num_total,
            }

        # Send to event_stream so it can be sent back to the client
        await send_stream.send(payload)

        if num_done == num_total:
            # Terminate the stream so the event_stream stops waiting
            await send_stream.aclose()

    async def _execute():
        async with db.advisory_lock(fg_id, action_id="mutation"):
            # Send initial 0% state message
            init_data = StreamedAttribute(
                datapoint_id=None,
                attribute=None,
                attributes=None,
                num_datapoints_done=0,
                num_datapoints_total=num_total,
            )
            await send_stream.send(init_data)

            # Compute attributes
            await db.compute_attributes(fg_id, attribute, _ws_attribute_streaming_callback)

            # Final refresh of state
            await publish_state(db, fg_id)

    return StreamingResponse(
        sse_event_stream(_execute, recv_stream), media_type="text/event-stream"
    )


class AttributeFeedback(BaseModel):
    attribute: str
    vote: Literal["up", "down"]


class SubmitAttributeFeedbackRequest(BaseModel):
    original_query: str
    attribute_feedback: list[AttributeFeedback]
    missing_queries: str


@rest_router.post("/submit_attribute_feedback")
async def submit_attribute_feedback(request: SubmitAttributeFeedbackRequest):
    rewritten_query = await generate_new_queries(
        request.original_query,
        [a.attribute for a in request.attribute_feedback if a.vote == "down"],
        [a.attribute for a in request.attribute_feedback if a.vote == "up"],
        request.missing_queries,
    )
    return {"rewritten_query": rewritten_query}


class ClusterDimensionRequest(BaseModel):
    fg_id: str
    dim_id: str
    feedback: str | None


@rest_router.post("/start_cluster_dimension")
async def start_cluster_dimension(request: ClusterDimensionRequest):
    db = await get_db()
    job_id = await db.add_job(
        {
            "type": "cluster_dimension",
            "fg_id": request.fg_id,
            "dim_id": request.dim_id,
            "feedback": request.feedback,
        }
    )
    return job_id


@rest_router.get("/listen_cluster_dimension")
async def listen_cluster_dimension(job_id: str):
    """[Setter] Create clusters for a dimension."""
    db = await get_db()

    # Retrieve job arguments
    job = await db.get_job(job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    fg_id, dim_id, feedback = job["fg_id"], job["dim_id"], job["feedback"]

    dim = await db.get_dim(fg_id, dim_id)
    if dim is None:
        raise ValueError(f"Dimension {dim_id} not found")

    if feedback:
        assert dim.bins is not None
        bin_predicates = [c.predicate for c in dim.bins if isinstance(c, FramePredicate)]
        new_feedback = ClusterFeedback(
            clusters=bin_predicates,
            feedback=feedback,
        )
    else:
        new_feedback = None

    async def event_stream():
        async with db.advisory_lock(fg_id, action_id="mutation"):
            try:
                # Send new dim state indicating that clusters are being loaded
                await db.set_dim_loading_state(fg_id, dim_id, loading_clusters=True)
                await publish_dims(db, fg_id)

                # TODO(mengk): assert that all datapoints have the associated attribute
                # This should be guaranteed by the frontend, but just make sure.

                # Create clusters with websocket interaction asynchronously
                await db.cluster_attributes(
                    fg_id,
                    dim_id,
                    n_clusters=1,
                    # new_feedback=new_feedback,
                    # llm_api_keys=cm.get_api_keys(fg_id),
                )

                # Upload loading state and send updated bins
                await db.set_dim_loading_state(
                    fg_id, dim_id, loading_clusters=False, loading_marginals=True
                )
                await publish_dims(db, fg_id)

                # Compute marginals while sending them to the client
                async with anyio.create_task_group() as tg:
                    is_done = False

                    async def _run():
                        nonlocal is_done
                        await publish_marginals(
                            db, fg_id, dim_ids=[dim_id], ensure_fresh=True
                        )  # Force recompute
                        is_done = True

                    # Get state in the background
                    tg.start_soon(_run)

                    # While polling marginals and sending them to the client
                    while not is_done:
                        await publish_marginals(db, fg_id, dim_ids=[dim_id], ensure_fresh=False)
                        await anyio.sleep(1)

                yield "data: [DONE]\n\n"

            # Even if the task was cancelled, we want to publish the latest dims and marginals
            finally:
                logger.info("Cleaning up cluster dimension task")

                # Prevent cascading cancellation if this task was killed
                with anyio.CancelScope(shield=True):
                    # Publish latest marginals in case there was an update
                    await publish_marginals(db, fg_id, dim_ids=[dim_id], ensure_fresh=False)

                    # Update loading state to show current state
                    await db.set_dim_loading_state(
                        fg_id, dim_id, loading_clusters=False, loading_marginals=False
                    )
                    await publish_dims(db, fg_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@rest_router.get("/actions_summary")
async def get_actions_summary(fg_id: str, datapoint_id: str):
    db = await get_db()

    datapoint = await db.get_datapoint(fg_id, datapoint_id)
    if not datapoint:
        raise ValueError(f"Datapoint {datapoint_id} not found")
    transcript = datapoint.obj

    # Result variables; hashes prevent updating with identical content multiple times
    low_level_actions: list[LowLevelAction] = []
    high_level_actions: list[HighLevelAction] = []
    agent_observations: list[ObservationType] = []
    prev_hash: str | None = None

    # AnyIO queue that we can write intermediate results to
    send_stream, recv_stream = anyio.create_memory_object_stream(max_buffer_size=100_000)
    lock = anyio.Lock()  # Only one payload can be sent at a time

    def _get_payload():
        nonlocal low_level_actions, high_level_actions, agent_observations, datapoint_id

        payload = {
            "low_level": low_level_actions,
            "high_level": high_level_actions,
            "observations": agent_observations,
            "datapoint_id": datapoint_id,
        }
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return payload, payload_hash

    async def _send_payload_if_new():
        nonlocal prev_hash
        async with lock:
            payload, payload_hash = _get_payload()

            # Only send if hash is different from previous hash
            if payload_hash != prev_hash:
                await send_stream.send(payload)
                prev_hash = payload_hash

    async def _actions_callback(actions: list[LowLevelAction]):
        nonlocal low_level_actions
        low_level_actions = actions
        await _send_payload_if_new()  # TODO: does this slow things down? should be run in the background, i think

    async def _high_level_actions_callback(actions: list[HighLevelAction]):
        nonlocal high_level_actions
        high_level_actions = actions
        await _send_payload_if_new()

    async def _observations_callback(observations: list[ObservationType]):
        nonlocal agent_observations
        agent_observations = observations
        await _send_payload_if_new()

    # Run agent observations concurrently with the other tasks
    async def _execute():
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                partial(
                    interesting_agent_observations,
                    transcript,
                    streaming_callback=_observations_callback,
                    # api_keys=api_keys,
                )
            )

            # Concurrently, get the low-level actions
            low_level_actions = await summarize_agent_actions(
                transcript,
                streaming_callback=_actions_callback,
                # api_keys=api_keys
            )
            # Wait for low-level actions, then group them into high-level steps
            if low_level_actions:
                await group_actions_into_high_level_steps(
                    low_level_actions,
                    transcript,
                    streaming_callback=_high_level_actions_callback,
                    # api_keys=api_keys,
                )

        # At the very end, close the recv_stream
        await send_stream.aclose()

    return StreamingResponse(
        sse_event_stream(_execute, recv_stream), media_type="text/event-stream"
    )


@rest_router.get("/solution_summary")
async def get_solution_summary(fg_id: str, datapoint_id: str):
    db = await get_db()

    datapoint = await db.get_datapoint(fg_id, datapoint_id)
    if not datapoint:
        raise ValueError(f"Datapoint {datapoint_id} not found")
    transcript = datapoint.obj

    # AnyIO queue that we can write intermediate results to
    send_stream, recv_stream = anyio.create_memory_object_stream(max_buffer_size=100_000)

    async def _solution_callback(summary: str, parts: list[str]):
        await send_stream.send(
            {
                "summary": summary,
                "parts": parts,
                "datapoint_id": datapoint_id,
            }
        )

    async def _execute():
        await summarize_intended_solution(
            transcript,
            streaming_callback=_solution_callback,  # api_keys=api_keys
        )
        await recv_stream.aclose()

    return StreamingResponse(
        sse_event_stream(_execute, recv_stream), media_type="text/event-stream"
    )


class CreateTASessionRequest(BaseModel):
    fg_id: str
    base_filter: dict[str, Any] | None


class TaChatMessage(TypedDict):
    role: str
    content: str
    citations: list[Citation]


class TASession(BaseModel):
    id: str
    messages: list[TaChatMessage]
    datapoint_ids: list[str]


TA_SESSIONS: dict[str, TASession] = {}  # session_id -> TASession


@rest_router.post("/ta_session")
async def create_ta_session(request: CreateTASessionRequest):
    db = await get_db()
    base_filter_raw = request.base_filter
    base_filter = parse_filter_dict(base_filter_raw) if base_filter_raw else None

    datapoints = await db.get_base_data(request.fg_id)
    if not datapoints:
        raise ValueError("No matching transcripts found")

    if base_filter:
        judgments = await base_filter.apply(data=datapoints, return_all=False)
        if len(judgments) > 1:
            raise ValueError("Multiple transcripts found for TA session")
        elif len(judgments) == 0:
            raise ValueError("No transcripts found for TA session")
        datapoints = [d for d in datapoints if d.id == judgments[0][0].data_id]

    # Create system prompt with all matching transcripts
    system_prompt = make_single_tasst_system_prompt(datapoints[0])

    # Generate session ID and store session
    session_id = str(uuid4())
    TA_SESSIONS[session_id] = TASession(
        id=session_id,
        messages=[{"role": "system", "content": system_prompt, "citations": []}],
        datapoint_ids=[datapoint.id for datapoint in datapoints],
    )

    return {
        "session_id": session_id,
        "num_transcripts": len(datapoints),
    }


@rest_router.get("/ta_message")
async def get_ta_message(session_id: str, message: str):
    session = TA_SESSIONS[session_id]
    # api_keys = cm.get_api_keys(fg_id)

    # Add user message to session
    prompt_msgs = session.messages + [{"role": "user", "content": message, "citations": []}]
    continuation_text = ""

    # AnyIO queue that we can write intermediate results to
    send_stream, recv_stream = anyio.create_memory_object_stream(max_buffer_size=100_000)

    def _get_complete_message_list():
        nonlocal continuation_text
        current_assistant_message: TaChatMessage = {
            "role": "assistant",
            "content": continuation_text,
            "citations": parse_citations_single_transcript(continuation_text),
        }
        return prompt_msgs + [current_assistant_message]

    async def _send_state():
        nonlocal prompt_msgs, continuation_text
        await send_stream.send(
            {
                "text": continuation_text,
                "messages": _get_complete_message_list(),
            }
        )

    async def _llm_callback(batch_index: int, llm_output: LLMOutput):
        nonlocal continuation_text
        text = llm_output.first_text
        if text:
            continuation_text = text
            await _send_state()

    async def _execute():
        # Immediately send back the initial message state
        await _send_state()

        # Get LLM response
        await get_llm_completions_async(
            [cast(list[dict[str, Any]], prompt_msgs)],
            model_category="reasoning_smart",
            max_new_tokens=8192,
            timeout=180.0,
            streaming_callback=_llm_callback,
            use_cache=True,
            # llm_api_keys=api_keys,
        )

        # After generation completes, update the session with the new messages
        session.messages = _get_complete_message_list()

        # Close the stream
        await recv_stream.aclose()

    return StreamingResponse(
        sse_event_stream(_execute, recv_stream), media_type="text/event-stream"
    )


# def _make_forest_for_sample(sample_id: str | int, datapoints: list[Datapoint]):
#     # Create a TranscriptForest from the FrameGrid data
#     forest = TranscriptForest()

#     # Filter and add transcripts with the matching sample_id
#     at_least_one_transcript = False
#     for d in datapoints:
#         # Cast sample_id: str | int to the same type as d_sample_id for proper comparison
#         d_sample_id = d.obj.metadata.sample_id
#         if isinstance(d_sample_id, int):
#             sample_id = int(sample_id)
#         else:
#             sample_id = str(sample_id)

#         if d_sample_id == sample_id:
#             forest.add_transcript(
#                 d.id,
#                 {},  # Empty environment config
#                 d.obj.messages,
#                 metadata=d.obj.metadata.model_dump()
#                 | {"forest_label": d.obj.metadata.intervention_description},
#                 compute_derivations=False,
#             )
#             at_least_one_transcript = True

#     forest.recompute_all_derivations()

#     if not at_least_one_transcript:
#         raise ValueError(f"No transcripts found with sample_id: {sample_id}")

#     return forest


# @rest_router.get("/merged_experiment_tree")
# async def get_merged_experiment_tree(fg_id: str, sample_id: str):
#     db = await get_db()
#     datapoints = await db.get_base_data(fg_id)
#     if not datapoints:
#         raise ValueError("No matching transcripts found")
#     forest = _make_forest_for_sample(sample_id, datapoints)

#     # Build the merged experiment tree
#     G, experiment_to_transcripts = forest.build_merged_experiment_tree()
#     nodes, edges = G.export()

#     return {
#         "sample_id": sample_id,
#         "nodes": nodes,
#         "edges": edges,
#         "experiment_to_transcripts": experiment_to_transcripts,
#     }


# @rest_router.get("/transcript_derivation_tree")
# async def handle_get_transcript_derivation_tree(fg_id: str, sample_id: str):
#     db = await get_db()
#     datapoints = await db.get_base_data(fg_id)
#     if not datapoints:
#         raise ValueError("No matching transcripts found")

#     forest = _make_forest_for_sample(sample_id, datapoints)

#     # Build the transcript derivation tree
#     G = forest.build_transcript_derivation_tree()
#     nodes, edges = G.export()

#     return {
#         "sample_id": sample_id,
#         "nodes": nodes,
#         "edges": edges,
#     }


# async def handle_conversation_intervention(
#     cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage, socket_fg_id: str
# ):
#     """[Setter] Start a conversation intervention.

#     Expected payload:
#     {
#         "datapoint_id": str,  # ID of the datapoint to modify
#         "message_index": int,  # Index of the message to replace/insert at
#         "new_message": dict,   # New message object to insert with format matching ChatMessage
#         "insert": bool = False # If True, insert the message at index, otherwise replace
#     }

#     Raises:
#         ValueError: If payload is incomplete or malformed.
#     """
#     datapoint_id = msg.payload["datapoint_id"]
#     message_index = msg.payload["message_index"]
#     new_message_data = msg.payload["new_message"]
#     num_additional_messages = msg.payload.get("num_additional_messages", None)
#     num_epochs = msg.payload.get("num_epochs", 5)
#     is_insert = msg.payload.get("insert", False)

#     api_keys = cm.get_api_keys(socket_fg_id)

#     logger.info(f"Received conversation intervention: {msg.payload}")

#     # Make sure user is not requesting too much stuff
#     if num_additional_messages and num_additional_messages > 50:
#         raise ValueError("num_additional_messages must be less than 50")
#     if num_epochs and num_epochs > 10:
#         raise ValueError("num_epochs must be less than 10")

#     logger.info(f"Received conversation intervention: {msg.payload}")

#     if not isinstance(datapoint_id, str):
#         raise ValueError("datapoint_id must be a string")
#     if not isinstance(message_index, int):
#         raise ValueError("message_index must be an integer")
#     if not isinstance(new_message_data, dict):
#         raise ValueError("new_message must be a dict")
#     if not isinstance(is_insert, bool):
#         raise ValueError("insert must be a boolean")

#     # Get the transcript from the datapoint
#     datapoint = fg.all_data_dict[datapoint_id]
#     transcript = datapoint.obj

#     # Parameters for the experiment
#     task_id = transcript.metadata.task_id
#     sample_id = transcript.metadata.sample_id
#     experiment_id = f"exp_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]}"
#     epochs = num_epochs

#     # Create TaskArgs for this particular task
#     if task_id not in TASK_ARGS_DICT:
#         raise ValueError(
#             f"Task {task_id} not supported; shape of TaskArgs not known. You need to manually specify these in docent/types.py."
#         )
#     task_args_dict = transcript.metadata.task_args

#     # Parse the new message based on its role
#     if "role" not in new_message_data or not isinstance(new_message_data["role"], str):
#         raise ValueError("new_message must be a dict with a str 'role' field")
#     role = new_message_data["role"]
#     if role not in ("system", "user", "assistant", "tool"):
#         raise ValueError(f"Invalid message role: {role}")
#     new_message = parse_chat_message(cast(dict[str, Any], new_message_data))

#     # Create deep copy of the transcript and modify messages
#     new_messages: list[ChatMessage] | None = deepcopy(transcript.messages)
#     if (
#         message_index < 0
#         or (is_insert and message_index > len(new_messages))  # For insertion, allow up to len
#         or (not is_insert and message_index >= len(new_messages))  # For replacement, must be < len
#     ):
#         raise ValueError(f"Invalid message index {message_index}")
#     if is_insert:
#         assert new_message.role != "system", "Cannot insert a new system message"

#         # Insert the new message at message_index and remove subsequent messages
#         new_messages.insert(message_index, new_message)
#         new_messages = new_messages[: message_index + 1]

#         # Describe the intervention
#         intervention_description = await describe_insertion_intervention(
#             new_message, transcript.messages[:message_index], api_keys
#         )
#     else:
#         if new_message.role == "system":
#             assert message_index == 0, "Cannot replace a non-first message with a system message"

#             # Replace the system message, and don't do anything else
#             task_args_dict["solver_system_message"] = new_message.content
#             new_messages = None

#             intervention_description = await describe_replacement_intervention(
#                 transcript.messages[message_index], new_message, [], api_keys
#             )
#         else:
#             # Replace the message at message_index and delete all subsequent messages
#             new_messages[message_index] = new_message
#             new_messages = new_messages[: message_index + 1]

#             # Describe the intervention
#             intervention_description = await describe_replacement_intervention(
#                 transcript.messages[message_index],
#                 new_message,
#                 transcript.messages[:message_index],
#                 api_keys,
#             )
#     logger.info(f"Intervention description: {intervention_description}")

#     # Add the new messages to the task args if they exist
#     if new_messages:
#         if new_messages[0].role == "system":
#             new_messages = new_messages[1:]
#         task_args_dict |= {"per_sample_inits": [(sample_id, new_messages)]}

#     # Set max messages to the number of additional messages minus the number of new messages
#     if num_additional_messages is not None:
#         task_args_dict |= {
#             "solver_max_messages": num_additional_messages
#             + (len(new_messages) if new_messages else 0)
#             + 1
#         }

#     # {sample_id: {epoch_id: transcript}}
#     timestamp = datetime.now().isoformat()
#     result_datapoints: dict[str | int, dict[int, Datapoint]] = {
#         sample_id: {
#             epoch_id: Datapoint.from_transcript(
#                 Transcript(
#                     messages=[],
#                     metadata=TranscriptMetadata(
#                         task_id=task_id,
#                         sample_id=sample_id,
#                         epoch_id=epoch_id,
#                         experiment_id=experiment_id,
#                         intervention_description=intervention_description,
#                         intervention_timestamp=timestamp,
#                         intervention_index=message_index,
#                         model=transcript.metadata.model,
#                         task_args=task_args_dict,
#                         is_loading_messages=True,
#                         scores={k: 0 for k in transcript.metadata.scores.keys()},
#                         default_score_key=transcript.metadata.default_score_key,
#                         additional_metadata=transcript.metadata.additional_metadata,
#                         scoring_metadata=transcript.metadata.scoring_metadata,
#                     ),
#                 )
#             )
#             for epoch_id in range(1, epochs + 1)
#         }
#     }
#     # Send the new datapoints to the client
#     await fg.add_datapoints(
#         [d for epoch_datapoints in result_datapoints.values() for d in epoch_datapoints.values()]
#     )
#     await handle_get_state(cm, websocket, fg)

#     async def _message_stream_callback(
#         task_id: str, sample_id: str | int, epoch_id: int, messages: list[ChatMessage]
#     ):
#         """Create temporary datapoints for each message in the stream, update its data, and send it to the client."""

#         logger.info(
#             "Message update from task_id %s, sample_id %s, epoch_id %s",
#             task_id,
#             sample_id,
#             epoch_id,
#         )

#         dp = result_datapoints[sample_id][epoch_id]
#         await fg.update_datapoint_content(dp.id, messages=messages)
#         await send_datapoints_updated(cm, websocket, [dp.id])

#     # Validate args and run experiment
#     task_args = TASK_ARGS_DICT[task_id].model_validate(task_args_dict)
#     api_keys = cm.get_api_keys(socket_fg_id)
#     env_vars: dict[str, str] = {}
#     if api_keys["anthropic_key"]:
#         env_vars["ANTHROPIC_API_KEY"] = api_keys["anthropic_key"]
#     if api_keys["openai_key"]:
#         env_vars["OPENAI_API_KEY"] = api_keys["openai_key"]
#     experiment_result = await run_experiment_in_subprocess(
#         task_id=task_id,
#         task_args=task_args,
#         model=transcript.metadata.model,
#         sample_ids=[sample_id],
#         epochs=epochs,
#         message_stream_callback=_message_stream_callback,
#         use_cache=True,
#         api_keys=env_vars,
#     )
#     logger.info("Experiment result paths: %s", experiment_result["results"])

#     # Update the existing datapoints with the new transcripts
#     if experiment_result["results"]:
#         new_transcripts: list[Transcript] = []
#         for result_fpath in experiment_result["results"]:
#             new_transcripts.extend(load_inspect_experiment(experiment_id, result_fpath))

#         # Update existing datapoints
#         for t in new_transcripts:
#             sample_id = t.metadata.sample_id
#             epoch_id = t.metadata.epoch_id

#             # Get the datapoint ID
#             dp_id = result_datapoints[sample_id][epoch_id].id

#             # Re-add metadata fields so they're not dropped
#             metadata_dict = t.metadata.model_dump() | {
#                 "intervention_description": intervention_description,
#                 "intervention_index": message_index,
#                 "intervention_timestamp": timestamp,
#                 "is_loading_messages": False,
#             }
#             metadata = TranscriptMetadata.model_validate(metadata_dict)

#             # Use the lightweight update_datapoint method to update with the new transcript data
#             await fg.update_datapoint_content(
#                 dp_id,
#                 messages=t.messages,
#                 metadata=metadata,
#             )

#         # Send updated state; this should include the updated datapoints
#         await handle_get_state(cm, websocket, fg)

#     # fg.to_json("/home/ubuntu/scratch/fg.json")


# class TranscriptDiffNode(TypedDict):
#     id: str
#     data: Any


#     datapoint_id: str
#     action_unit_idx: int
#     starting_block_idx: int


# class TranscriptDiffEdge(TypedDict):
#     id: str
#     source: str
#     target: str
#     type: Literal["chain", "exact_match", "near_match"]
#     explanation: str


# def _create_graph(
#     datapoint_1: Datapoint,
#     summary_1: dict[int, LowLevelAction],
#     datapoint_2: Datapoint,
#     summary_2: dict[int, LowLevelAction],
#     all_diff_results: dict[int, list[DiffResult | None]],
# ):
#     nodes: list[TranscriptDiffNode] = []
#     edges: list[TranscriptDiffEdge] = []

#     # Create nodes
#     for datapoint, summary in [(datapoint_1, summary_1), (datapoint_2, summary_2)]:
#         for unit_idx, action in summary.items():
#             nodes.append(
#                 {
#                     "id": f"{datapoint.id}-{unit_idx}",
#                     "data": action,
#                     "datapoint_id": datapoint.id,
#                     "action_unit_idx": unit_idx,
#                     "starting_block_idx": datapoint.obj.units_of_action[unit_idx][0],
#                 }
#             )

#     # Add chain edges for both datapoints
#     for idx, (datapoint, summary) in enumerate(
#         [(datapoint_1, summary_1), (datapoint_2, summary_2)]
#     ):
#         transcript_num = idx + 1
#         for i in range(len(summary) - 1):
#             action_1, action_2 = summary[i], summary[i + 1]
#             unit_idx_1, unit_idx_2 = action_1["action_unit_idx"], action_2["action_unit_idx"]
#             edges.append(
#                 {
#                     "id": f"{datapoint.id}-edge-{unit_idx_1}-{unit_idx_2}",
#                     "source": f"{datapoint.id}-{unit_idx_1}",
#                     "target": f"{datapoint.id}-{unit_idx_2}",
#                     "type": "chain",
#                     "explanation": f"Sequential action in transcript {transcript_num}: {i} → {i+1}",
#                 }
#             )

#     # Add matching edges for matching action units
#     for t1_idx, diff_results in all_diff_results.items():
#         for diff_result in diff_results:
#             if diff_result and diff_result["matches"]:
#                 for match_info in diff_result["matches"]:
#                     t2_idx = match_info["index"]
#                     match_type = (
#                         "exact_match" if match_info["match_type"] == "exact" else "near_match"
#                     )
#                     explanation = match_info.get("explanation", "")

#                     # Add edge between matching action units
#                     edges.append(
#                         {
#                             "id": f"match-{datapoint_1.id}-{t1_idx}-{datapoint_2.id}-{t2_idx}",
#                             "source": f"{datapoint_1.id}-{t1_idx}",
#                             "target": f"{datapoint_2.id}-{t2_idx}",
#                             "type": match_type,
#                             "explanation": explanation,
#                         }
#                     )

#     return nodes, edges


# async def handle_diff_transcripts(
#     cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid, msg: WSMessage, socket_fg_id: str
# ):
#     """Handle diff_transcripts action by comparing two transcripts.

#     Expected payload:
#     {
#         "datapoint_id_1": str,  # ID of the first transcript
#         "datapoint_id_2": str,  # ID of the second transcript
#     }
#     """
#     datapoint_1 = fg.all_data_dict[msg.payload["datapoint_id_1"]]
#     datapoint_2 = fg.all_data_dict[msg.payload["datapoint_id_2"]]

#     async def compare_callback(batch_index: int, results: ComparisonResult):
#         await cm.send(
#             websocket,
#             WSMessage(
#                 action="compare_transcripts_update",
#                 payload=cast(dict[str, Any], results),
#             ),
#         )

#     # First get textual comparison
#     asyncio.create_task(
#         compare_transcripts(datapoint_1.obj, datapoint_2.obj, streaming_callback=compare_callback)
#     )

#     summary_1: dict[int, LowLevelAction] = {}
#     summary_2: dict[int, LowLevelAction] = {}
#     diff_result: dict[int, list[DiffResult | None]] = {}

#     async def _create_graph_and_send():
#         nonlocal summary_1, summary_2, diff_result
#         nodes, edges = _create_graph(datapoint_1, summary_1, datapoint_2, summary_2, diff_result)
#         await cm.send(
#             websocket,
#             WSMessage(
#                 action="transcript_diff_result",
#                 payload={
#                     "nodes": nodes,
#                     "edges": edges,
#                 },
#             ),
#         )

#     prev_s1_hash, prev_s2_hash = None, None

#     async def actions_callback(actions: list[LowLevelAction], which_summary: Literal["1", "2"]):
#         nonlocal summary_1, summary_2, prev_s1_hash, prev_s2_hash

#         # Update summary
#         cur_summary = summary_1 if which_summary == "1" else summary_2
#         for action in actions:
#             cur_summary[action["action_unit_idx"]] = action

#         # Hash the summaries to compare with previous hashes
#         cur_json = json.dumps(cur_summary, sort_keys=True)
#         cur_hash = hashlib.sha256(cur_json.encode()).hexdigest()
#         cur_prev_hash = prev_s1_hash if which_summary == "1" else prev_s2_hash

#         # Only send if hash differs
#         if cur_prev_hash is None or cur_hash != cur_prev_hash:
#             await _create_graph_and_send()
#             if which_summary == "1":
#                 prev_s1_hash = cur_hash
#             else:
#                 prev_s2_hash = cur_hash

#     async def diff_callback(batch_index: int, results: list[DiffResult | None]):
#         nonlocal diff_result
#         diff_result[batch_index] = results
#         await _create_graph_and_send()

#     api_keys = cm.get_api_keys(socket_fg_id)

#     # Dispatch tasks to compute all these in parallel
#     await asyncio.gather(
#         summarize_agent_actions(
#             datapoint_1.obj,
#             streaming_callback=lambda actions: actions_callback(actions, "1"),
#             api_keys=api_keys,
#         ),
#         summarize_agent_actions(
#             datapoint_2.obj,
#             streaming_callback=lambda actions: actions_callback(actions, "2"),
#             api_keys=api_keys,
#         ),
#         diff_transcripts(
#             datapoint_1.obj, datapoint_2.obj, completion_callback=diff_callback, api_keys=api_keys
#         ),
#     )
