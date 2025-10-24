# autoflake: skip_file
# pyright: ignore
# fmt: off

# pseudocode

active_collection_id = "4707073b-2e3b-444b-a2e1-5248beaaaa62"
# pass into SDK function that sets up syncing maybe
# perhaps it does some local caching and syncing
# now you have the "collection loaded"

# define a labelset
labelset = LabelSet(
    id=str(uuid4()),
    name="swe_bench_sandbox",
    description="Label set for the SWE Bench Sandbox",
    schema={},
)
docent.create_labelset(labelset)

raw_labels: list[dict[str, Any]] = [
    {
        "key": {
            "model_name": "20250805-openhands-Qwen3-Coder-30B-A3B-Instruct",
            "instance_id": "django__django-12965",
        },
        "value": {
            "label": "cheating",
            "explanation": "The agent cheated",
        }
    },
]

# could be nicer if we want!
for rl in raw_labels:
    docent.dql(f"select id from agent_runs where metadata")
    docent.add_label(labelset.id, Label(rl["value"]))

# at this point the UI should show all the labels now

#  if this is ur first tiem, define a judge
judge = Judge()  # have printouts that clarify that a new judge was being created
docent.add_judge(judge)

# if not,
judge = docent.ls_judges()[0]
judge = docent.get_judge_by_name("asdf")

# now run the judge on the collection, but not everything!
agent_run_ids = docent.dql(f"select id from agent_runs join labels and stuff")
agent_runs = docent.get_agent_runs(agent_run_ids)
# TODO(mengk): say something about do you need to run it on agent runs or is raw text ok

def hack_string_into_agent_run(string: str) -> AgentRun:
    return AgentRun(
        id=agent_run.id,
        transcript=agent_run.transcript + [UserMessage(content=string)],
    )

# experiment where i run the judge a bunch of times on each
for agent_run in agent_runs:
    for _ in range(10):
        judge(agent_run)  # auto-logs judgeresults and metadata back into docent
        # TODO(mengk): do judges deserve their own collection?

# at this point, the judge result page shows all the results like it does today

# now i want to do analysis
# agent_run_id, judge_id, judge_result (dict), judge_metadata (dict), labelset_id, label (dict),
analysis_data: list[dict[str, Any]] = docent.dql(f"give me cols")

df = pd.DataFrame(analysis_data)

# i write a function to do group by
df2 = df.groupby("agent_run_id").agg({
    "judge_result": "first",
    "judge_metadata": "first",
    "labelset_id": "first",
    "label": "first",
    "judge_result_id": list,
    # computed data from agg
    "entropy": None,
    "p_correct": None,
    "log_loss": None,
    "argmax_judge_result": None,
    "argmax_correct": None,
    "gold_label": None,
    "distr": None,
    "distr_entropy": None,
    "distr_p_correct": None,
    "distr_log_loss": None,
})

# i sort by p_correct asc.
# i want to view the differences between the rollouts
# also lets you "chat with the rollouts"
for index, row in df2.iterrows():
    cur_judge_result_ids = row["judge_result_id"]
    docent.give_me_links(cur_judge_result_ids)

    all_rollout_texts = []
    for id in cur_judge_result_ids:
        # this is json object contains everything about the judge result
        judge_reuslt_obj = docent.get_judge_result(id)
        all_rollout_texts.append(judge_reuslt_obj.rollout_texts)

    docent.llm(f"""what are idfferences between these rollouts: {all_rollout_texts}""")

########## END ##############


"""
other operations that are useful for sdk
* computed fields
*
"""

# fmt: on
