# %%

from docent import Docent
from personal.mengk.bw.util import dql_to_df

DOCENT_API_KEY = "dk_OAsemTbrmXIonGIk_76PQIMTadPq3iA80txM9j1ZNYXk410MZsMZMnOvUQs2ZGM"
DOCENT_TRACING_ENDPOINT = "https://api.docent-bridgewater.transluce.org/rest/telemetry"
DOCENT_API_URL = "https://api.docent-bridgewater.transluce.org"
# DOCENT_COLLECTION_ID="aedca6e5-34ec-4edb-b97b-403fc2aff3ae"  # overnight
DOCENT_COLLECTION_ID = "c1ecffe7-9f5b-459b-b70a-e8435ed7686e"  # kalshi-liquid-2

dc = Docent(api_key=DOCENT_API_KEY, server_url=DOCENT_API_URL)

# %%

from pprint import pprint

schema = dc.get_dql_schema(DOCENT_COLLECTION_ID)
pprint(schema)

# %%

dr = dc.execute_dql(
    DOCENT_COLLECTION_ID,
    """
SELECT
    a.id,
    a.metadata_json ->> 'final_probability' AS final_probability,
    a.metadata_json ->> 'gold_probability' AS gold_probability,
    a.metadata_json ->> 'finished' AS finished,
    a.metadata_json ->> 'question' AS question,
    a.metadata_json ->> 'post_consistency_confidence_level' AS post_consistency_confidence_level,
    a.metadata_json ->> 'post_consistency_probability' AS post_consistency_probability,
    a.metadata_json ->> 'post_platt_scaling_probability' AS post_platt_scaling_probability,
    a.metadata_json ->> 'pre_platt_scaling_probability' AS pre_platt_scaling_probability
FROM agent_runs a
WHERE
    a.metadata_json ->> 'finished' = 'true' AND
    a.metadata_json ->> 'gold_probability' IS NOT NULL AND
    a.metadata_json ->> 'final_probability' IS NOT NULL
""".strip(),
)
cols, rows = dr["columns"], dr["rows"]

# %%

df = dql_to_df(cols, rows)
df["brier_score"] = (df["final_probability"] - df["gold_probability"]) ** 2

# %%

import matplotlib.pyplot as plt
import pandas as pd

plt.figure(figsize=(8, 5))
plt.hist(df["brier_score"].dropna(), bins=30, edgecolor="k", alpha=0.7)
plt.xlabel("Brier Score")
plt.ylabel("Frequency")
plt.title("Distribution of Brier Scores")
plt.grid(axis="y", alpha=0.3)
plt.show()

plt.figure(figsize=(8, 5))
plt.boxplot(df["brier_score"].dropna(), vert=True)
plt.ylabel("Brier Score")
plt.title("Boxplot of Brier Scores")
plt.grid(axis="y", alpha=0.3)
plt.show()

pd.set_option("display.float_format", lambda x: f"{x:.3f}")
df["brier_score"].describe().round(3)

# %%

dr = dc.execute_dql(
    DOCENT_COLLECTION_ID,
    """
SELECT
    a.id,
    tg.id,
    tg.name,
    tg.metadata_json
FROM agent_runs a
JOIN transcript_groups tg ON a.id = tg.agent_run_id
WHERE tg.metadata_json ->> 'prediction' IS NOT NULL
""".strip(),
)
cols, rows = dr["columns"], dr["rows"]
df_tg = dql_to_df(cols, rows)
# %%

df_tg


# %%

df.sort_values(by="brier_score", ascending=False).head(10)
# %%
