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

cid = "96fad7bd-eb81-4da6-95d9-d66e94ff1533"
dc.tag_transcript(cid, "deddf2de-a9f8-4bd5-a47f-9d63fb5d579c", "hello")

# %%

result = dc.execute_dql(
    cid, "SELECT a.id, a.metadata_json ->> 'model_name' as model_name FROM agent_runs a"
)
rows = result["rows"]

import random

for id, model_name in rows:
    if "30B-A3B" in model_name and random.random() < 0.5:
        dc.tag_transcript(cid, id, "smaller-model")

# %%
# %%
