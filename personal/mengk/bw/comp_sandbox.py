# autoflake: skip_file
# pyright: ignore

# %%

import IPython

IPython.get_ipython().run_line_magic("load_ext", "autoreload")  # type: ignore
IPython.get_ipython().run_line_magic("autoreload", "2")  # type: ignore

# %%

from docent import Docent
from docent.data_models.formatted_objects import FormattedAgentRun, FormattedTranscript
from docent.sdk.llm_context import LLMContext
from docent_core._env_util import ENV

# DOCENT_API_KEY = ENV.get("DOCENT_API_KEY")
# DOCENT_SERVER_URL = ENV.get("NEXT_PUBLIC_API_HOST")
# if not DOCENT_SERVER_URL or not DOCENT_API_KEY:
#     raise ValueError("DOCENT_API_KEY and DOCENT_SERVER_URL must be set")

DOCENT_API_KEY = ENV.get("DOCENT_API_KEY")
DOCENT_DOMAIN = ENV.get("DOCENT_DOMAIN")
if not DOCENT_DOMAIN or not DOCENT_API_KEY:
    raise ValueError("DOCENT_API_KEY and DOCENT_DOMAIN must be set")
dc = Docent(api_key=DOCENT_API_KEY, domain=DOCENT_DOMAIN)

# %%

import pandas as pd

pd.set_option("display.float_format", "{:.3f}".format)

cid = "0cdb3b85-0a4d-40de-992b-0c5edaa1ebbf"
df = dc.dql_result_to_df_experimental(
    dc.execute_dql(
        cid,
        """
SELECT
    a.id AS agent_run_id,
    a.metadata_json ->> 'base_llm_name' AS llm,
    a.metadata_json ->> 'llm_reasoning_effort' AS reasoning_effort,
    a.metadata_json ->> 'pre_platt_scaling_probability' AS unscaled_prob,
    a.metadata_json ->> 'post_platt_scaling_probability' AS final_prob,
    a.metadata_json ->> 'resolved_to' AS gold_prob,
    a.metadata_json ->> 'question' AS question,
    ARRAY_AGG(tg.metadata_json ->> 'post_calibration_probability') AS indiv_probs
FROM agent_runs a
JOIN transcript_groups tg ON a.id = tg.agent_run_id
WHERE
    tg.name = 'Generating Agentic Forecast' AND
    a.metadata_json ->> 'base_llm_name' != 'sonnet_4_5_thinking'
GROUP BY
    a.id,
    a.metadata_json ->> 'base_llm_name',
    a.metadata_json ->> 'llm_reasoning_effort',
    a.metadata_json ->> 'pre_platt_scaling_probability',
    a.metadata_json ->> 'post_platt_scaling_probability',
    a.metadata_json ->> 'resolved_to',
    a.metadata_json ->> 'question'
""",
    )
)
rows_before = len(df)
df = df.dropna()
rows_after = len(df)
print(f"Dropped {rows_before - rows_after} rows (from {rows_before} to {rows_after})")


def _f(x: list[str | None]):
    filtered = [float(v) for v in x if v is not None]
    return sum(filtered) / len(filtered) if filtered else None


df["pre_prob"] = df["indiv_probs"].apply(_f)

df["brier_score"] = (df["final_prob"] - df["gold_prob"]) ** 2
df["pre_brier_score"] = (df["pre_prob"] - df["gold_prob"]) ** 2
df["accuracy"] = ((df["final_prob"] >= 0.5) & (df["gold_prob"] >= 0.5)) | (
    (df["final_prob"] < 0.5) & (df["gold_prob"] < 0.5)
)
df["pre_accuracy"] = ((df["pre_prob"] >= 0.5) & (df["gold_prob"] >= 0.5)) | (
    (df["pre_prob"] < 0.5) & (df["gold_prob"] < 0.5)
)

df = df[
    [
        "agent_run_id",
        "llm",
        "reasoning_effort",
        "question",
        "pre_prob",
        "final_prob",
        "gold_prob",
        "brier_score",
        "pre_brier_score",
        "accuracy",
        "pre_accuracy",
        "indiv_probs",
    ]
]
# df = df.drop_duplicates(subset=["question", "llm", "reasoning_effort"], keep="first")
df = df.sort_values(by="brier_score", ascending=False)
df

# %%

############################
# Basic summary statistics #
############################

# Plot accuracy and brier score by (llm, reasoning_effort) combination
import matplotlib.pyplot as plt
import numpy as np

# Get unique combinations of (llm, reasoning_effort)
unique_combos = (
    df[["llm", "reasoning_effort"]].drop_duplicates().sort_values(by=["llm", "reasoning_effort"])
)

# Collect data for plotting
plot_data = []
for _, row in unique_combos.iterrows():
    llm = row["llm"]
    reasoning_effort = row["reasoning_effort"]

    mask = (df["llm"] == llm) & (df["reasoning_effort"] == reasoning_effort)
    df_filtered = df[mask]

    mean_accuracy = df_filtered["accuracy"].mean()
    mean_brier = df_filtered["brier_score"].mean()

    plot_data.append(
        {
            "config": f"{llm}\n{reasoning_effort}",
            "accuracy": mean_accuracy,
            "brier_score": mean_brier,
        }
    )

# Create bar charts
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

configs = [d["config"] for d in plot_data]
x = np.arange(len(configs))

# Accuracy bar chart
accuracies = [d["accuracy"] for d in plot_data]
ax1.bar(x, accuracies, alpha=0.8)
ax1.set_xlabel("Model Configuration")
ax1.set_ylabel("Accuracy")
ax1.set_title("Accuracy by Model Configuration")
ax1.set_xticks(x)
ax1.set_xticklabels(configs, rotation=45, ha="right")
ax1.grid(True, alpha=0.3, axis="y")

# Brier score bar chart
brier_scores = [d["brier_score"] for d in plot_data]
ax2.bar(x, brier_scores, alpha=0.8, color="orange")
ax2.set_xlabel("Model Configuration")
ax2.set_ylabel("Brier Score")
ax2.set_title("Brier Score by Model Configuration")
ax2.set_xticks(x)
ax2.set_xticklabels(configs, rotation=45, ha="right")
ax2.grid(True, alpha=0.3, axis="y")

plt.tight_layout()
plt.show()

# %%

#########################################################################################
# Explain diffs between models                                                          #
# Find questions where models (on average) do substantively differently from each other #
#########################################################################################

# %%

# Group by (llm, reasoning_effort, question) and aggregate brier scores and accuracies
grouped_df = (
    df.groupby(["llm", "reasoning_effort", "question"])
    .agg({"brier_score": list, "accuracy": list})
    .reset_index()
)

# Create pivot tables for average brier score and accuracy by question and (llm, reasoning_effort)
import numpy as np

# Create a combined column for (llm, reasoning_effort)
df["model_config"] = df["llm"] + "_" + df["reasoning_effort"]

# Pivot table for average brier score with count
brier_pivot_mean = df.pivot_table(
    values="brier_score", index="question", columns="model_config", aggfunc="mean"
)
brier_pivot_count = df.pivot_table(
    values="brier_score", index="question", columns="model_config", aggfunc="count"
)

# Combine mean and count into a single display
brier_pivot = brier_pivot_mean.copy()
for col in brier_pivot.columns:
    brier_pivot[col] = (
        brier_pivot_mean[col].apply(lambda x: f"{x:.3f}")
        + " (n="
        + brier_pivot_count[col].astype(str)
        + ")"
    )

# Sort by variance across model configurations (using the mean values)
brier_pivot_mean["variance"] = brier_pivot_mean.var(axis=1)
brier_pivot = brier_pivot.loc[brier_pivot_mean.sort_values(by="variance", ascending=False).index]
brier_pivot

# %%

# For each (llm, reasoning_effort) combination, show where it performs best and worst relative to others
for _, row in unique_combos.iterrows():
    llm = row["llm"]
    effort = row["reasoning_effort"]
    model_config = f"{llm}_{effort}"

    print(f"\n{'='*80}")
    print(f"Model: {llm}, Reasoning Effort: {effort}")
    print(f"{'='*80}")

    # Calculate relative performance (this model's brier score minus average of all others)
    other_cols = [
        col for col in brier_pivot_mean.columns if col != model_config and col != "variance"
    ]

    if model_config in brier_pivot_mean.columns:
        # Calculate average brier score of other models for each question
        brier_pivot_mean["others_avg"] = brier_pivot_mean[other_cols].mean(axis=1)

        # Calculate relative performance (negative means this model is better)
        brier_pivot_mean["relative_performance"] = (
            brier_pivot_mean[model_config] - brier_pivot_mean["others_avg"]
        )

        # Questions where this model performs BEST (most negative relative performance)
        print(f"\nTop 10 questions where {model_config} performs BEST relative to others:")
        print("(Negative values = better performance, i.e., lower Brier score)")
        best_questions = brier_pivot_mean.nsmallest(10, "relative_performance")[
            [model_config, "others_avg", "relative_performance"]
        ]
        print(best_questions.to_string())

        # Questions where this model performs WORST (most positive relative performance)
        print(f"\nTop 10 questions where {model_config} performs WORST relative to others:")
        print("(Positive values = worse performance, i.e., higher Brier score)")
        worst_questions = brier_pivot_mean.nlargest(10, "relative_performance")[
            [model_config, "others_avg", "relative_performance"]
        ]
        print(worst_questions.to_string())

        # Clean up temporary columns
        brier_pivot_mean.drop(columns=["others_avg", "relative_performance"], inplace=True)
    else:
        print(f"Model configuration {model_config} not found in data")


# %%

##########################################################################################
#
#
#######################


# %%


# %%

# Scatterplot of change in accuracy vs change in brier score
import matplotlib.pyplot as plt

# Calculate changes (post - pre)
df["accuracy_change"] = df["accuracy"].astype(float) - df["pre_accuracy"].astype(float)
df["brier_change"] = df["brier_score"] - df["pre_brier_score"]

# Create scatterplot
plt.figure(figsize=(10, 6))
plt.scatter(df["accuracy_change"], df["brier_change"], alpha=0.6)
plt.xlabel("Change in Accuracy (Post - Pre)")
plt.ylabel("Change in Brier Score (Post - Pre)")
plt.title("Change in Accuracy vs Change in Brier Score")
plt.axhline(y=0, color="gray", linestyle="--", alpha=0.5)
plt.axvline(x=0, color="gray", linestyle="--", alpha=0.5)
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()

# %%


# Filter to questions where accuracy didn't change
df[df["accuracy_change"] == 0]
# %%


# %%
# Get unique combinations of (llm, reasoning_effort)
unique_combos = (
    df[["llm", "reasoning_effort"]].drop_duplicates().sort_values(by=["llm", "reasoning_effort"])
)

# Collect data for bar chart
metrics_data = []
for _, row in unique_combos.iterrows():
    llm = row["llm"]
    reasoning_effort = row["reasoning_effort"]

    mask = (df["llm"] == llm) & (df["reasoning_effort"] == reasoning_effort)
    df_filtered = df[mask]

    mean_accuracy = df_filtered["accuracy"].mean()
    mean_pre_accuracy = df_filtered["pre_accuracy"].mean()
    mean_brier = df_filtered["brier_score"].mean()
    mean_pre_brier = df_filtered["pre_brier_score"].mean()

    metrics_data.append(
        {
            "config": f"{llm}\n{reasoning_effort}",
            "pre_accuracy": mean_pre_accuracy,
            "post_accuracy": mean_accuracy,
            "pre_brier": mean_pre_brier,
            "post_brier": mean_brier,
        }
    )

# Create bar charts
import matplotlib.pyplot as plt
import numpy as np

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

configs = [d["config"] for d in metrics_data]
x = np.arange(len(configs))
width = 0.35

# Accuracy bar chart
pre_acc = [d["pre_accuracy"] for d in metrics_data]
post_acc = [d["post_accuracy"] for d in metrics_data]

ax1.bar(x - width / 2, pre_acc, width, label="Pre-consistency", alpha=0.8)
ax1.bar(x + width / 2, post_acc, width, label="Post-consistency", alpha=0.8)
ax1.set_xlabel("Model Configuration")
ax1.set_ylabel("Accuracy")
ax1.set_title("Accuracy by Model Configuration")
ax1.set_xticks(x)
ax1.set_xticklabels(configs, rotation=45, ha="right")
ax1.legend()
ax1.grid(True, alpha=0.3, axis="y")

# Brier score bar chart
pre_brier = [d["pre_brier"] for d in metrics_data]
post_brier = [d["post_brier"] for d in metrics_data]

ax2.bar(x - width / 2, pre_brier, width, label="Pre-consistency", alpha=0.8)
ax2.bar(x + width / 2, post_brier, width, label="Post-consistency", alpha=0.8)
ax2.set_xlabel("Model Configuration")
ax2.set_ylabel("Brier Score")
ax2.set_title("Brier Score by Model Configuration")
ax2.set_xticks(x)
ax2.set_xticklabels(configs, rotation=45, ha="right")
ax2.legend()
ax2.grid(True, alpha=0.3, axis="y")

plt.tight_layout()
plt.show()


# %%
import matplotlib.pyplot as plt

# Get unique combinations of (llm, reasoning_effort)
unique_combos = (
    df[["llm", "reasoning_effort"]].drop_duplicates().sort_values(by=["llm", "reasoning_effort"])
)
n_combos = len(unique_combos)

# Create figure with subplots for each combination
fig, axes = plt.subplots(1, n_combos, figsize=(6 * n_combos, 6))

# Handle case where there's only one combination
if n_combos == 1:
    axes = [axes]

for idx, (_, row) in enumerate(unique_combos.iterrows()):
    llm = row["llm"]
    reasoning_effort = row["reasoning_effort"]

    # Filter data for this combination
    mask = (df["llm"] == llm) & (df["reasoning_effort"] == reasoning_effort)
    df_filtered = df[mask]
    brier_diff = df_filtered["brier_score"] - df_filtered["pre_brier_score"]

    ax = axes[idx]
    ax.hist(brier_diff, bins=30, edgecolor="black", alpha=0.7)
    ax.axvline(
        x=brier_diff.mean(),
        color="r",
        linestyle="--",
        linewidth=2,
        label=f"Mean: {brier_diff.mean():.4f}",
    )
    ax.axvline(
        x=brier_diff.median(),
        color="g",
        linestyle="--",
        linewidth=2,
        label=f"Median: {brier_diff.median():.4f}",
    )
    ax.set_xlabel("Brier Score Difference (post - pre consistency)")
    ax.set_ylabel("Frequency")
    ax.set_title(f"{llm} - {reasoning_effort}")
    ax.legend()
    ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.show()

# %%

# %%
import matplotlib.pyplot as plt
import numpy as np

# Get unique combinations of (llm, reasoning_effort)
unique_combos = (
    df[["llm", "reasoning_effort"]].drop_duplicates().sort_values(by=["llm", "reasoning_effort"])
)
n_combos = len(unique_combos)

# Create figure with subplots - boxplot and histogram for each combination
fig, axes = plt.subplots(2, n_combos, figsize=(4 * n_combos, 10))

# Handle case where there's only one combination
if n_combos == 1:
    axes = axes.reshape(2, 1)

for idx, (_, row) in enumerate(unique_combos.iterrows()):
    llm = row["llm"]
    reasoning_effort = row["reasoning_effort"]

    # Filter data for this combination
    mask = (df["llm"] == llm) & (df["reasoning_effort"] == reasoning_effort)
    data = df[mask]["adj_diff"].dropna()

    # Boxplot (top row)
    ax_box = axes[0, idx]
    ax_box.boxplot([data], vert=True)

    # Plot the average as a red horizontal line
    mean_val = data.mean()
    ax_box.axhline(
        y=mean_val, color="r", linestyle="--", linewidth=2, label=f"Mean: {mean_val:.3f}"
    )

    ax_box.set_title(f"{llm} - {reasoning_effort}")
    ax_box.set_ylabel("Adjustment Difference")
    ax_box.set_xticklabels([""])
    ax_box.set_ylim(-1, 1)
    ax_box.grid(True, alpha=0.3)
    ax_box.legend()

    # Histogram (bottom row)
    ax_hist = axes[1, idx]
    ax_hist.hist(data, bins=20, edgecolor="black", alpha=0.7)
    ax_hist.axvline(
        x=mean_val, color="r", linestyle="--", linewidth=2, label=f"Mean: {mean_val:.3f}"
    )
    ax_hist.set_xlabel("Adjustment Difference")
    ax_hist.set_ylabel("Frequency")
    ax_hist.set_xlim(-1, 1)
    ax_hist.grid(True, alpha=0.3)
    ax_hist.legend()

plt.tight_layout()
plt.show()

# %%


# %%

d = df.to_dict(orient="records")
m = {}
for row in d:
    m.setdefault((row["base_llm_name"], row["llm_reasoning_effort"]), []).append(row["brier_score"])
m


# %%


# %%
df_grouped["model_effort"] = df["base_llm_name"] + "_" + df["llm_reasoning_effort"]
df_pivot = df_grouped.pivot_table(
    index="question", columns="model_effort", values="brier_score", aggfunc="first"
)
rows_before_pivot = len(df_pivot)
df_pivot = df_pivot.dropna()
rows_after_pivot = len(df_pivot)
print(
    f"Dropped {rows_before_pivot - rows_after_pivot} rows (from {rows_before_pivot} to {rows_after_pivot})"
)

# Print mean for each column
for col in df_pivot.columns:
    print(f"{col}: {df_pivot[col].mean()}")

# %%

# %%
# Sort by variance across columns
df_pivot["variance"] = df_pivot.var(axis=1)
df_pivot = df_pivot.sort_values(by="variance", ascending=False)
df_pivot = df_pivot.drop(columns=["variance"])
df_pivot

# %%

# %%
# 1. chat about 2 specific agent runs
run_id_pairs = [
    [
        "0161e220-c317-4520-b0a8-aa7196691c99",
        "5d984a27-afd3-40f1-9e88-e335016ea891",
    ],
]
context = LLMContext()
for run_id in run_ids:
    run = dc.get_agent_run(cid, run_id)
    assert run is not None

    run = FormattedAgentRun.from_agent_run(run)
    for tg in run.transcript_groups:
        if tg.name == "Parallel Forecast Runs":
            print(f"Deleting transcript group {tg.id}")
            run.delete_transcript_group_subtree(tg.id)

    context.add(run)

dc.start_chat(context, model_string="openai/gpt-5-mini", reasoning_effort="low")

# %%

# %%
# 2. chat about individual transcripts (LLM won't see other transcripts in the run)
run_ids = ["da62ab48-ca38-4f29-8a47-fee15fb0ac4c", "8ed11e3b-1c67-4dcd-8078-96c9e0a994b6"]
context = LLMContext()
for run_id in run_ids:
    run = client.get_agent_run(collection_id, run_id)
    assert run is not None
    for transcript in run.transcripts:
        # suppose we only want to analyze the "verification" step and transcripts are named accordingly
        if transcript.name is not None and "verification" in transcript.name.lower():
            context.add(transcript)

client.start_chat(context, model_string="openai/gpt-5-mini", reasoning_effort="low")

# 3. select parts of a transcript to show/hide from the LLM
run_ids = ["da62ab48-ca38-4f29-8a47-fee15fb0ac4c", "8ed11e3b-1c67-4dcd-8078-96c9e0a994b6"]
context = LLMContext()
for run_id in run_ids:
    run = client.get_agent_run(collection_id, run_id)
    assert run is not None
    # FormattedAgentRun/FormattedTranscript let us control how we present runs/transcripts to the LLM
    run = FormattedAgentRun.from_agent_run(run)
    for i, transcript in enumerate(run.transcripts):
        formatted_transcript = FormattedTranscript.from_transcript(transcript)
        # hide the first message of each transcript from the LLM
        # note: the UI will still show the original transcript
        formatted_transcript.messages = formatted_transcript.messages[1:]
        run.transcripts[i] = formatted_transcript
    context.add(run)

client.start_chat(context, model_string="openai/gpt-5-mini", reasoning_effort="low")
