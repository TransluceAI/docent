# autoflake: skip_file
# pyright: ignore

# %%

from docent import Docent

d = Docent(
    api_key="dk_0Z9C_AefELmbnuzK5tsG7r7qX8pSSIVLd-SDXi9q9Ps",
    server_url="https://api.docent-bridgewater.transluce.org",
)
collection_id = "d13a0171-e81c-41f4-9da8-f2659a1a281a"

# %%


ids = d.list_agent_run_ids(collection_id)

# %%

from tqdm import tqdm

out = {}

for id in tqdm(ids[:]):
    ar = d.get_agent_run(collection_id, id)
    out[id] = ar


# %%

import json

out_prc = [json.loads(item.model_dump_json()) for id, item in out.items()]


with open("agent_runs_gitignore.json", "w") as f:
    json.dump(out_prc, f)

# %%

print(out[ids[0]])
# %%
