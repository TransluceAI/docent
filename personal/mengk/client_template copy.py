# autoflake: skip_file
# pyright: ignore

# %%

import IPython

IPython.get_ipython().run_line_magic("load_ext", "autoreload")
IPython.get_ipython().run_line_magic("autoreload", "2")

# %%

from docent import Docent
from docent_core._env_util import ENV

DOCENT_API_KEY = ENV.get("DOCENT_API_KEY")
DOCENT_SERVER_URL = ENV.get("NEXT_PUBLIC_API_HOST")
if not DOCENT_SERVER_URL or not DOCENT_API_KEY:
    raise ValueError("DOCENT_API_KEY and DOCENT_SERVER_URL must be set")
dc = Docent(api_key=DOCENT_API_KEY, server_url=DOCENT_SERVER_URL)

# %%

ar = dc.get_agent_run(
    "5eb33693-e934-4573-8041-6afb51e74f53", "1ab5d9b4-882a-4e1b-912e-8aa6d0254d8f"
)

# %%

_t = ar.transcript_dict["5f9074db-7463-49a4-bfd6-3cdbcc9a50a0"]
tg = ar.transcript_group_dict[_t.transcript_group_id]
par_tg = ar.transcript_group_dict[tg.parent_transcript_group_id]

# get its children

t_sibling = None
for t in ar.transcript_dict.values():
    if t.transcript_group_id == par_tg.id:
        t_sibling = t
        break

# %%

print(t_sibling.model_dump_json(exclude={"messages"}, indent=1))
print(tg.model_dump_json(indent=1))


print(t_sibling.created_at, tg.created_at, t_sibling.created_at < tg.created_at)

# %%
