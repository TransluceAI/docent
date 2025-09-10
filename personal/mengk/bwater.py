# %%

from docent import Docent

d = Docent(
    api_key="dk_0Z9C_AefELmbnuzK5tsG7r7qX8pSSIVLd-SDXi9q9Ps",
    server_url="https://api.docent-bridgewater.transluce.org",
)
collection_id = "2ee5c238-f03d-4189-a703-b96145bc7231"

# %%


ids = d.list_agent_run_ids(collection_id)
len(ids)

# %%

from tqdm import tqdm

out = {}

for id in tqdm(ids):
    ar = d.get_agent_run(collection_id, id)
    out[id] = ar


# %%

import json

out_prc = [json.loads(item.model_dump_json()) for item in out.values()]


with open("agent_runs_gitignore.json", "w") as f:
    json.dump(out_prc, f)

# %%
