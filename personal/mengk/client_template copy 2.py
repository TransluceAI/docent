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
dc = Docent(api_key=DOCENT_API_KEY, server_url="http://localhost:8890")

# %%

dc.list_collections()

# %%

collection_id = "96fad7bd-eb81-4da6-95d9-d66e94ff1533"
rubric_id = "292b1543-ce9c-454f-aaa0-1d2fad7a21e6"

result = dc.execute_dql(
    collection_id,
    f"""
SELECT
    a.id as ar_id,
    a.metadata_json -> 'scores' ->> 'resolved' as reward,
    jr.output ->> 'label' as label,
    jrc.centroid_id as centroid_id,
    rc.centroid as centroid_text,
FROM agent_runs a
JOIN judge_results jr ON a.id = jr.agent_run_id
JOIN judge_result_centroids jrc ON jr.id = jrc.judge_result_id
JOIN rubric_centroids rc ON jrc.centroid_id = rc.id
WHERE
    jr.rubric_id = '{rubric_id}' AND
    jrc.decision = true
ORDER BY
    ar_id
""".strip(),
)
df = dc.dql_result_to_df_experimental(result)
df


# %%

dc.get_dql_schema(collection_id)
# %%
