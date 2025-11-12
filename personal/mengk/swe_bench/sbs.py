# autoflake: skip_file
# pyright: ignore

# %%

import IPython

IPython.get_ipython().run_line_magic("load_ext", "autoreload")  # type: ignore
IPython.get_ipython().run_line_magic("autoreload", "2")  # type: ignore

# %%

from docent import Docent
from docent_core._env_util import ENV

DOCENT_API_KEY = ENV.get("DOCENT_API_KEY")
DOCENT_SERVER_URL = ENV.get("NEXT_PUBLIC_API_HOST")
if not DOCENT_SERVER_URL or not DOCENT_API_KEY:
    raise ValueError("DOCENT_API_KEY and DOCENT_SERVER_URL must be set")
dc = Docent(api_key=DOCENT_API_KEY, server_url=DOCENT_SERVER_URL)

cid = "2a40857c-8593-4818-aa2c-bbafa0f65f2c"

# %%

##############
# Add labels #
##############

from pprint import pprint

# Collect mapping from (model_name, instance_id) to agent run id
result = dc.execute_dql(
    cid,
    "select a.id, a.metadata_json ->> 'model_name' as model_name, a.metadata_json ->> 'instance_id' as instance_id from agent_runs a",
)
cols, rows = result["columns"], result["rows"]
coord_to_id: dict[tuple[str, str], str] = {}
for ar_id, model_name, instance_id in rows:
    if model_name is None or instance_id is None:
        print(f"warn: model_name or instance_id is None for ar_id {ar_id}")
    coord_to_id[(model_name, instance_id)] = ar_id

pprint(coord_to_id)

# Create a label set


# %%

rows

# %%
