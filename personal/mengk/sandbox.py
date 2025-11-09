# autoflake: skip_file
# pyright: ignore

# %%

import IPython

IPython.get_ipython().run_line_magic("load_ext", "autoreload")
IPython.get_ipython().run_line_magic("autoreload", "2")

# %%

from docent_core._db_service.db import DocentDB

db = await DocentDB.init()


# %%


async def print_pool_stats(tag: str = ""):
    pool = db.engine.sync_engine.pool
    print(
        f"{tag} | status={pool.status()} | "
        f"size={pool.size()} | in={pool.checkedin()} | out={pool.checkedout()} | overflow={pool.overflow()}"
    )


await print_pool_stats("initial")


# %%

import anyio


async def _f():
    from sqlalchemy import text

    async with db.session() as session:
        print("session opened")
        result = await session.execute(
            text("SELECT t.* from agent_runs a JOIN transcripts t on a.id = t.agent_run_id")
        )
        print("got result")
        rows = result.all()
        print(len(rows))
        print("got results; sleeping")
        await anyio.sleep(5)

    print("session closed")


async def _c(tg):
    await anyio.sleep(1)
    print("triggered cancel")
    tg.cancel_scope.cancel()


async def _leave_conn_hanging():
    async with anyio.create_task_group() as tg:
        tg.start_soon(_f)
        tg.start_soon(_c, tg)


async with anyio.create_task_group() as tg:
    for _ in range(1):
        tg.start_soon(_leave_conn_hanging)

print("done")


# %%


# %%


from contextlib import asynccontextmanager


@asynccontextmanager
async def dummy_context_manager():
    print("entering context")
    try:
        yield
    except anyio.get_cancelled_exc_class():
        print("cancelled inside of context")
        raise
    finally:
        print("exiting context")


async def _subwork():
    try:
        print("subwork started")
        await anyio.sleep(10)
        print("subwork finished")
    except anyio.get_cancelled_exc_class():
        print("cancelled inside of subwork")
        raise


async def _work():
    async with dummy_context_manager():
        try:
            print("inside context")
            await _subwork()
        except anyio.get_cancelled_exc_class():
            print("cancelled inside of work")
            raise


async def _cancel(tg):
    await anyio.sleep(1)
    print("triggered cancel")
    tg.cancel_scope.cancel()


async with anyio.create_task_group() as tg:
    tg.start_soon(_work)
    tg.start_soon(_cancel, tg)


# %%

c  # %%


from docent.data_models import AgentRun, Transcript
from docent.data_models.chat import AssistantMessage, UserMessage

ar = AgentRun(
    transcripts=[
        Transcript(
            messages=[
                UserMessage(content="Hello, can you help?"),
                AssistantMessage(content="I understand the task and will help you."),
                UserMessage(content="Great, let's proceed."),
            ]
        ),
        Transcript(
            messages=[
                UserMessage(content="Hello, can you help?"),
                AssistantMessage(content="I understand the task and will help you."),
                UserMessage(content="Great, let's proceed."),
            ]
        ),
    ]
)
print(ar.to_text_new(full_tree=True))


# %%


from docent import Docent
from docent_core._env_util import ENV

docent_client = Docent(api_key=ENV.get("DOCENT_API_KEY"), server_url="http://localhost:8890")

# %%

collection_id = "4707073b-2e3b-444b-a2e1-5248beaaaa62"
# docent_client.get_dql_schema(collection_id)
# docent_client.execute_dql(collection_id, "SELECT id FROM agent_runs")
arids = docent_client.select_agent_run_ids(
    collection_id,
    # "metadata_json ->> 'model_name' = '20250805-openhands-Qwen3-Coder-30B-A3B-Instruct'",
    "metadata_json ->> 'instance_id' = 'astropy__astropy-14365'",
)
print(arids)
ars = [docent_client.get_agent_run(collection_id, arid) for arid in arids]
print(ars)


# %%

collection_id = docent_client.create_collection(
    name="inspect example", description="example inspect log that comes with the Docent repo"
)

# %%

docent_client.recursively_ingest_inspect_logs(
    collection_id, "/Users/mengk/Downloads/eval logs subset"
)


# %%


docent_client.list_agent_run_ids("8e8ebe90-c506-4826-b02f-ea201e45f040")


# %%

from docent import Docent

DOCENT_API_KEY = "dk_dv2itpQ6xW0cHV6xfdT5YOOUWLUUhZj3qao56XtVkWs"
docent_client = Docent(api_key=DOCENT_API_KEY, server_url="http://localhost:8890")

docent_client.get_rubric_run_state(
    # "d760a957-9343-49b0-8be6-535d516e3ef9", "b6c6943b-5095-4e52-b5d8-b30fee0e56ab"
    "b244d5be-37b9-4797-b746-a664722d540b",
    "b01f1d44-930f-4c5f-bf4b-a18334146399",
)

docent_client.get_cluster_centroids(
    "b244d5be-37b9-4797-b746-a664722d540b",
    "b01f1d44-930f-4c5f-bf4b-a18334146399",
)

docent_client.get_cluster_assignments(
    "b244d5be-37b9-4797-b746-a664722d540b",
    "b01f1d44-930f-4c5f-bf4b-a18334146399",
)

# %%

# %%


from docent._llm_util.prod_llms import get_llm_completions_async
from docent._llm_util.providers.preference_types import ModelOption


async def test():
    result = await get_llm_completions_async(
        [
            lambda: [
                {
                    "role": "user",
                    "content": "Hello, world! Give me a paragraph about the history of this phrase.",
                }
            ],
            lambda: [
                {
                    "role": "user",
                    "content": "Explain the significance of the phrase 'carpe diem' in literature.",
                }
            ],
            lambda: [
                {
                    "role": "user",
                    "content": "What is the origin of the phrase 'break a leg' and how is it used today?",
                }
            ],
            lambda: [
                {
                    "role": "user",
                    "content": "Describe the meaning and history of the phrase 'the pen is mightier than the sword.'",
                }
            ],
            lambda: [
                {
                    "role": "user",
                    "content": "Where does the phrase 'once in a blue moon' come from, and what does it mean?",
                }
            ],
            lambda: [
                {
                    "role": "user",
                    "content": "Tell me about the phrase 'raining cats and dogs' and its possible origins.",
                }
            ],
            lambda: [
                {
                    "role": "user",
                    "content": "What does 'barking up the wrong tree' mean, and where did it originate?",
                }
            ],
            lambda: [
                {
                    "role": "user",
                    "content": "Give a brief history of the phrase 'let the cat out of the bag.'",
                }
            ],
            lambda: [
                {
                    "role": "user",
                    "content": "Explain the phrase 'kick the bucket' and its etymology.",
                }
            ],
            lambda: [
                {
                    "role": "user",
                    "content": "What is the story behind the phrase 'costs an arm and a leg'?",
                }
            ],
        ],
        [ModelOption(provider="openai", model_name="gpt-4o")],
        use_cache=True,
    )
    print(result)


await test()


# %%


async def setup():
    from docent_core._db_service.db import DocentDB
    from docent_core._db_service.service import MonoService
    from docent_core.services.setup import SetupService

    db = await DocentDB.init()
    mono_svc = await MonoService.init()
    async with db.session() as s:
        ds = SetupService(s, mono_svc)
        return await ds.setup_dummy_user()


result = await setup()
result


# %%

from docent_core._db_service.db import DocentDB
from docent_core._db_service.service import MonoService
from docent_core.services.diff import DiffService

db = await DocentDB.init()
service = await MonoService.init()


# %%

fg_id = "0e4a0318-e072-4dce-ac41-ba97d988b903"
user = await service.get_user_by_email("a@b.com")
ctx = await service.get_default_view_ctx(fg_id, user)


# %%


from docent_core._ai_tools.diff.diff import DiffQuery


async def execute_diff(query: DiffQuery):
    async with db.session() as session:
        ds = DiffService(session, db.session, service)
        query_id = await ds.add_diff_query(ctx, query)
        print(query_id)
        await session.commit()
        # query_id = "a8639497-2297-4863-92d5-5dda651927a3"
        results = await ds.compute_diff(ctx, query_id)
        return results


query = DiffQuery(
    grouping_md_fields=["sample_id"],
    md_field_value_1=("model", "anthropic/claude-3-7-sonnet-latest"),
    md_field_value_2=("model", "anthropic/claude-3-5-sonnet-latest"),
    focus="exploration strategies",
)
query = DiffQuery(
    grouping_md_fields=["task_id"],
    md_field_value_1=("step", 65),
    md_field_value_2=("step", 85),
    focus=None,
)
query = DiffQuery(
    grouping_md_fields=["task_id"],
    md_field_value_1=("model", "harmony_v4.0.15_berry_v3_1mil_orion_no_budget"),
    md_field_value_2=(
        "model",
        "harmony_v4.0.16_berry_v3_1mil_orion_lpe_no_budget_commentary_cs_cross_msg_msc",
    ),
    # focus="high level problem solving strategies",
    focus=None,
)

results = await execute_diff(query)
results


# %%


async with db.session() as session:
    ds = DiffService(session, db.session, service)
    results = await ds.get_diff_results("9194af28-8f63-4a7c-b3f0-46e0ad81372f")

    from pprint import pprint

    for result in results:
        print(result.agent_run_1_id, result.agent_run_2_id)
        for instance in result.instances:
            pprint(instance.model_dump())


# %%


async with db.session() as session:
    ds = DiffService(session, db.session, service)
    await ds.propose_diff_claims("9194af28-8f63-4a7c-b3f0-46e0ad81372f")


# %%


async with db.session() as session:
    ds = DiffService(session, db.session, service)
    await ds.delete_diff_claims("9194af28-8f63-4a7c-b3f0-46e0ad81372f")


# %%


async with db.session() as session:
    ds = DiffService(session, db.session, service)
    claims = await ds.get_diff_claims("9194af28-8f63-4a7c-b3f0-46e0ad81372f")


from pprint import pprint

for instance in claims.instances:
    pprint(instance.model_dump())


# %%


async with db.session() as session:
    ds = DiffService(session, db.session, service)
    await ds.compute_paired_search(ctx, claims.instances[0].id)


# %%


async with db.session() as session:
    ds = DiffService(session, db.session, service)
    results = await ds.get_paired_search_results(claims.instances[0].id)
    print(results)


# %%


# %%


from docent_core._ai_tools.search_paired import SearchPairedQuery


async def execute_query(query: SearchPairedQuery):
    async with db.session() as session:
        ds = DiffService(session, db.session, service)
        query_id = await ds.add_paired_search_query(ctx, query)
        print(query_id)
        await session.commit()
        results = await ds.compute_paired_search(ctx, query_id)
        return results


query = SearchPairedQuery(
    grouping_md_fields=["sample_id"],
    md_field_value_1=("model", "anthropic/claude-3-7-sonnet-latest"),
    md_field_value_2=("model", "anthropic/claude-3-5-sonnet-latest"),
    context="Both agents knew the name of the specific file or function they needed to find.",
    action_1="Agent used tools like grep or find to search for the object",
    action_2="Agent searched manually without tools",
)

query = SearchPairedQuery(
    grouping_md_fields=["sample_id"],
    md_field_value_1=("model", "anthropic/claude-3-7-sonnet-latest"),
    md_field_value_2=("model", "anthropic/claude-3-5-sonnet-latest"),
    context="Both agents were trying to use/call the same function",
    action_1="Agent looked up documentation for the function",
    action_2="Agent guessed arguments to the function",
)

query = SearchPairedQuery(
    grouping_md_fields=["sample_id"],
    md_field_value_1=("model", "anthropic/claude-3-7-sonnet-latest"),
    md_field_value_2=("model", "anthropic/claude-3-5-sonnet-latest"),
    context="Both agents had just been given a task that involves debugging an issue",
    action_1="Agent reproduced the issue",
    action_2="Agent began fixing the issue without reproducing it",
)

query = SearchPairedQuery(
    grouping_md_fields=["sample_id"],
    md_field_value_1=("model", "anthropic/claude-3-7-sonnet-latest"),
    md_field_value_2=("model", "anthropic/claude-3-5-sonnet-latest"),
    context="Both agents were trying to fix the same issue",
    action_1="Agent modified existing functions",
    action_2="Agent created new functions that were not present in the original codebase",
)

query = SearchPairedQuery(
    grouping_md_fields=["sample_id"],
    md_field_value_1=("model", "anthropic/claude-3-7-sonnet-latest"),
    md_field_value_2=("model", "anthropic/claude-3-5-sonnet-latest"),
    context="Both agents are given a specific file or function to modify",
    # action_1="Agent jumps directly to the relevant code without exploring the repository",
    # action_2="Agent explores the repository first, including files that are not obviously relevant",
    action_1="Agent 1 explores more files than agent 2",
    action_2="Agent 2 explores more files than agent 1",
)

await execute_query(query)


# %%


await ds.get_paired_search_results(query_id)


# %%


query_id


# %%

user = await db.get_user_by_email("mengk@mit.edu")
assert user is not None
user


# %%

fgs = await db.get_collections()
collection_id = [fg.id for fg in fgs if fg.name == "oai"][0]
ctx = await db.get_default_view_ctx(collection_id, user)
print(ctx)
runs = await db.get_agent_runs(ctx)
len(runs)

# %%


query = "cases where the agent acted in a strange or unexpected way"
await db.cluster_search_results_direct(ctx, query)


# %%


await db.run_raw_query("SELECT count(*) FROM search_results limit 1")
await db.run_raw_query(
    """
SELECT
  metadata_json ->> 'sample_id' AS sample_id,
  metadata_json ->> 'model' AS model,
  AVG(
    CASE
      WHEN (metadata_json -> 'scores' ->> 'correct') = 'true' THEN 1
      WHEN (metadata_json -> 'scores' ->> 'correct') = 'false' THEN 0
      ELSE NULL
    END
  )
FROM agent_runs
WHERE collection_id = 'e91db3aa-9430-4739-a205-041ab1512cab'
GROUP BY sample_id, model;
"""
)


# %%


users = await db.get_users()
user = users[0]


# %%

fgs = await db.get_collections()
fgs
collection_id = [fg.id for fg in fgs if fg.name][0]
ctx = await db.get_default_view_ctx(collection_id, user)


# %%


run = await db.get_any_agent_run(ctx)
print(run.text)


# %%


runs = await db.get_agent_runs(ctx)
len(runs)


# %%


await db.compute_paired_search(
    ctx,
    grouping_md_fields=["sample_id"],
    identifying_md_field_value_1=("model", "anthropic/claude-3-7-sonnet-latest"),
    identifying_md_field_value_2=("model", "anthropic/claude-3-5-sonnet-latest"),
    shared_context="Both agents knew the name of the specific file or function they needed to find.",
    action_1="Agent used tools like grep or find to search for the object",
    action_2="Agent searched manually without tools",
)


# %%%


from docent.data_models.agent_run import AgentRun

# runs_37 = [run for run in runs if run.metadata.get("model") == "anthropic/claude-3-7-sonnet-latest"]
# runs_35 = [run for run in runs if run.metadata.get("model") == "anthropic/claude-3-5-sonnet-latest"]

runs = sorted(runs, key=lambda x: x.metadata.get("model"))

run_dict: dict[str, list[AgentRun]] = {}
for run in runs:
    model = run.metadata.get("model")
    sample_id = run.metadata.get("sample_id")
    assert model and sample_id
    run_dict.setdefault(sample_id, []).append(run)

paired_runs = list(run_dict.values())


# %%


for runs in paired_runs:
    print(runs[0].metadata.get("model"), runs[1].metadata.get("model"))


# %%


from docent_core._ai_tools.search_paired import execute_search_paired

all_results = await execute_search_paired(
    paired_runs[:50],
    "Both agents were trying to find the same specific file or function",
    "Agent used tools like grep or find to search for the object",
    "Agent searched manually without tools",
    # "Both agents had just been asked to perform the same task",
    # "Agent explores the codebase first",
    # "Agent writes a reproduction script immediately",
    # "Both agents were testing their solutions",
    # "Agent writes comprehensive tests considering more edge cases",
    # "Agent writes a comparatively less comprehensive test with fewer considerations",
)


# %%

from pprint import pprint

for results in all_results:
    for result in results or []:
        pprint(result.model_dump())


# %%


import matplotlib.pyplot as plt

# Count occurrences for each combination of agent actions
combination_counts = {}
total_instances = 0

for results in all_results:
    if results is None:
        continue
    for result in results:
        total_instances += 1

        # Get the state of each agent's actions
        agent_1_action_1 = getattr(result, "agent_1_action_1").performed
        agent_1_action_2 = getattr(result, "agent_1_action_2").performed
        agent_2_action_1 = getattr(result, "agent_2_action_1").performed
        agent_2_action_2 = getattr(result, "agent_2_action_2").performed

        # Create a tuple representing the combination
        combination = (agent_1_action_1, agent_1_action_2, agent_2_action_1, agent_2_action_2)

        # Count this combination
        if combination not in combination_counts:
            combination_counts[combination] = 0
        combination_counts[combination] += 1


# Create labels for all 16 possible combinations
def format_combination_label(combo):
    a1_a1, a1_a2, a2_a1, a2_a2 = combo

    # Format agent 1 actions
    if a1_a1 and a1_a2:
        agent_1_part = "A1: Both"
    elif a1_a1:
        agent_1_part = "A1: Act1"
    elif a1_a2:
        agent_1_part = "A1: Act2"
    else:
        agent_1_part = "A1: None"

    # Format agent 2 actions
    if a2_a1 and a2_a2:
        agent_2_part = "A2: Both"
    elif a2_a1:
        agent_2_part = "A2: Act1"
    elif a2_a2:
        agent_2_part = "A2: Act2"
    else:
        agent_2_part = "A2: None"

    return f"{agent_1_part}\n{agent_2_part}"


# Generate all 16 possible combinations
all_combinations = []
for a1_a1 in [False, True]:
    for a1_a2 in [False, True]:
        for a2_a1 in [False, True]:
            for a2_a2 in [False, True]:
                all_combinations.append((a1_a1, a1_a2, a2_a1, a2_a2))

# Get counts for all combinations (0 if not observed)
labels = [format_combination_label(combo) for combo in all_combinations]
values = [combination_counts.get(combo, 0) for combo in all_combinations]

# Visualization
plt.figure(figsize=(16, 8))
bars = plt.bar(range(len(labels)), values, color=plt.cm.tab20(range(len(labels))))
plt.ylabel("Count")
plt.title("Count of All 16 Possible Agent Action Combinations")
plt.xticks(range(len(labels)), labels, rotation=45, ha="right")
plt.grid(axis="y", linestyle="--", alpha=0.5)

# Annotate bars with counts
for i, (bar, value) in enumerate(zip(bars, values)):
    if value > 0:  # Only annotate non-zero bars
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(values) * 0.01,
            f"{value}",
            ha="center",
            va="bottom",
            fontsize=8,
        )

plt.tight_layout()
plt.show()

print(f"Total instances: {total_instances}")
print(f"Non-zero combinations: {sum(1 for v in values if v > 0)}/16")


# %%


[run.metadata.get("model") for run in runs_35]


# %%

ctx = await db.get_default_view_ctx(fgs[0].id)
run = await db.get_any_agent_run(ctx)
print(run.text)

# %%

from docent_core._db_service.schemas.auth_models import Permission, ResourceType, SubjectType

collection_id = fgs[1].id
await db.set_acl_permission(
    SubjectType.PUBLIC, "*", ResourceType.COLLECTION, collection_id, Permission.READ
)
views = await db.get_all_view_ctxs(collection_id)
for view in views:
    await db.set_acl_permission(
        SubjectType.PUBLIC, "*", ResourceType.VIEW, view.view_id, Permission.READ
    )


# %%

ctx = await db.get_default_view_ctx(collection_id)

# %%

ctx

# %%


collection_id = "677791bc-0891-4605-9cfa-150e6187543d"
run = await db.get_any_agent_run(ctx)
