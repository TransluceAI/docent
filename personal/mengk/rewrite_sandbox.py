# autoflake: skip_file
# pyright: ignore

# %%

import IPython

IPython.get_ipython().run_line_magic("load_ext", "autoreload")  # type: ignore
IPython.get_ipython().run_line_magic("autoreload", "2")  # type: ignore

# %%

from docent import Docent
from docent_core._env_util import ENV

# DOCENT_API_KEY = ENV.get("DOCENT_API_KEY")
# DOCENT_SERVER_URL = ENV.get("NEXT_PUBLIC_API_HOST")
# if not DOCENT_SERVER_URL or not DOCENT_API_KEY:
#     raise ValueError("DOCENT_API_KEY and DOCENT_SERVER_URL must be set")

DOCENT_API_KEY = ENV.get("DOCENT_API_KEY")
DOCENT_DOMAIN = ENV.get("DOCENT_DOMAIN")
if not DOCENT_DOMAIN or not DOCENT_API_KEY:
    raise ValueError("DOCENT_API_KEY and DOCENT_DOMAIN must be set")
dc = Docent(api_key=DOCENT_API_KEY, domain=DOCENT_DOMAIN, server_url="http://localhost:8890")

# %%

cid = "92f56474-687b-4989-a949-d6929c4a73e5"
comments = dc.get_comments(cid)
comments
# dr = dc.execute_dql(
#     cid,
#     """
# SELECT
#     a.id as agent_run_id
# FROM agent_runs a
# ORDER BY a.id ASC
# LIMIT 50
#     """.strip(),
# )
# rows = dc.dql_result_to_dicts(dr)
# rows

# %%

from docent.judges import Rubric

rubric = Rubric(
    rubric_text="""
I'm looking for more cases of the agent being confused about the distinction between testbed and workspace
    """.strip(),
    output_schema={
        "type": "object",
        "properties": {
            "label": {"type": "string", "enum": ["match", "no match"]},
            "explanation": {"type": "string"},
        },
        "required": ["label", "explanation"],
    },
)

# %%

from docent.data_models.agent_run import AgentRunView
from docent.data_models.citation import Comment

agent_runs_to_comments: dict[str, list[Comment]] = {}
for comment in comments:
    agent_runs_to_comments.setdefault(comment["agent_run_id"], []).append(
        Comment.model_validate(comment)
    )

arvs: list[AgentRunView] = []
for agent_run_id, ar_comments in agent_runs_to_comments.items():
    agent_run = dc.get_agent_run(cid, agent_run_id)
    if agent_run is None:
        print(f"warn: agent run {agent_run_id} not found")
        continue
    arv = AgentRunView.from_agent_run(agent_run, ar_comments)

    arvs.append(arv)

# %%

for arv in arvs:
    print(arv.to_text(indent=1))
    dc.open_agent_run(cid, arv.agent_run.id)
    print("-" * 100)

# %%

# %%

# %%

"""
What seems to be done:
* We have a pure function from rubric, schema, instructions, selection -> updated rubric, updated schema. We can in principle add annotation information to the context.
* It seems easy to support multiple samples of rubric generation; can then let users pick.

What needs to be done:
* ✅ Figure out how to format comments alongside AgentRuns
    - mostly vibecoded, not thoroughly tested...
* ✅ Because AgentRuns are long, figure out how to go from AgentRun/annotation combinations to rubrics
* How do we 80/20 this into the UI?
    - ✅ the refinement chat should use the new rewriter; no more stupid sysprompt and can probably use a faster model, like GPT-5.1-chat
    - ✅ labels and comments can just be passed into this function once it is supported
    - 🟡 very basic controls over whether comments are included or not; if so, information about how many and where.
        - it would be nice if selecting them by tag was supported, but it's unfortunately not.
        - I think this is AI-able; write the instruction
        - ✅ expose option in backend API
        - 🟡 integrate into FE
    - 🟡 show intermediate progress when the annotation stuff is running
        - I think this is AI-able too.
    - ✅ ensure that there is no regression in performance when someone just does vanilla guided search. Experiment with "preindexed" agent run structure and context

For the future
* Think about the UI for multiple rubric proposals: it is not yet clear how to support sampling many different rubrics and then letting the user pick one
- Support highlighting a selection of the rubric and having it rewrite that part by adding it as "chat context" -- but i don't think this is that important
- Rewriter should be able to take into account labels as well, similar to how we do for annotations
"""
