# autoflake: skip_file
# pyright: ignore

# %%

import IPython

IPython.get_ipython().run_line_magic("load_ext", "autoreload")
IPython.get_ipython().run_line_magic("autoreload", "2")


# %%

from docent_core._db_service.db import DocentDB
from docent_core._db_service.service import DBService
from docent_core.services.diff import DiffService

db = await DocentDB.init()
service = await DBService.init()
ts = await db.get_test_session()
ds = DiffService(ts, db.session, service)


# %%

fg_id = "7f99cfc1-bc5b-4979-968f-9e837193d1a9"
user = await service.get_user_by_email("mengk@mit.edu")
ctx = await service.get_default_view_ctx(fg_id, user)


# %%


ds.pair_runs(
    await service.get_agent_runs(ctx),
    grouping_md_fields=["sample_id"],
    identifying_md_field_value_1=("model", "anthropic/claude-3-7-sonnet-latest"),
    identifying_md_field_value_2=("model", "anthropic/claude-3-5-sonnet-latest"),
)


# %%


from docent_core._ai_tools.search_paired import SearchPairedQuery

query = SearchPairedQuery(
    grouping_md_fields=["sample_id"],
    md_field_value_1=("model", "anthropic/claude-3-7-sonnet-latest"),
    md_field_value_2=("model", "anthropic/claude-3-5-sonnet-latest"),
    context="Both agents knew the name of the specific file or function they needed to find.",
    action_1="Agent used tools like grep or find to search for the object",
    action_2="Agent searched manually without tools",
)

query_id = await ds.add_paired_search_query(ctx, query)

# %%

results = await ds.compute_paired_search(ctx, query_id)


# %%


await ts.commit()


# %%


query_id


# %%


results[0]


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
