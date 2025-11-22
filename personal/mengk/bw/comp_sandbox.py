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
    a.metadata_json ->> 'llm_verbosity' AS verbosity,
    a.metadata_json ->> 'pre_platt_scaling_probability' AS consistency_prob,
    a.metadata_json ->> 'post_platt_scaling_probability' AS scaled_prob,
    a.metadata_json ->> 'resolved_to' AS gold_prob,
    a.metadata_json ->> 'question' AS question,
    ARRAY_AGG(tg.metadata_json ->> 'post_calibration_probability') AS indep_probs
FROM agent_runs a
JOIN transcript_groups tg ON a.id = tg.agent_run_id
WHERE
    tg.name = 'Generating Agentic Forecast' AND
    a.metadata_json ->> 'base_llm_name' != 'sonnet_4_5_thinking' AND
    a.metadata_json ->> 'llm_verbosity' != 'high'
GROUP BY
    a.id,
    a.metadata_json ->> 'base_llm_name',
    a.metadata_json ->> 'llm_reasoning_effort',
    a.metadata_json ->> 'llm_verbosity',
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


df["mean_indep_prob"] = df["indep_probs"].apply(_f)

df["scaled_brier_score"] = (df["scaled_prob"] - df["gold_prob"]) ** 2
df["mean_indep_brier_score"] = (df["mean_indep_prob"] - df["gold_prob"]) ** 2
df["consistency_brier_score"] = (df["consistency_prob"] - df["gold_prob"]) ** 2
df["scaled_accuracy"] = ((df["scaled_prob"] >= 0.5) & (df["gold_prob"] >= 0.5)) | (
    (df["scaled_prob"] < 0.5) & (df["gold_prob"] < 0.5)
)
df["mean_indep_accuracy"] = ((df["mean_indep_prob"] >= 0.5) & (df["gold_prob"] >= 0.5)) | (
    (df["mean_indep_prob"] < 0.5) & (df["gold_prob"] < 0.5)
)
df["consistency_accuracy"] = ((df["consistency_prob"] >= 0.5) & (df["gold_prob"] >= 0.5)) | (
    (df["consistency_prob"] < 0.5) & (df["gold_prob"] < 0.5)
)

df = df[
    [
        "agent_run_id",
        "llm",
        "reasoning_effort",
        "verbosity",
        "question",
        "mean_indep_prob",
        "consistency_prob",
        "scaled_prob",
        "gold_prob",
        "scaled_brier_score",
        "mean_indep_brier_score",
        "consistency_brier_score",
        "scaled_accuracy",
        "mean_indep_accuracy",
        "consistency_accuracy",
    ]
]
# df = df.drop_duplicates(subset=["question", "llm", "reasoning_effort"], keep="first")
df = df.sort_values(by="scaled_brier_score", ascending=False)
df

# %%

############################
# Basic summary statistics #
############################

# %%

# Plot accuracy and brier score by (llm, reasoning_effort, verbosity) combination
import matplotlib.pyplot as plt
import numpy as np

# Get unique combinations of (llm, reasoning_effort, verbosity)
unique_combos = (
    df[["llm", "reasoning_effort", "verbosity"]]
    .drop_duplicates()
    .sort_values(by=["llm", "reasoning_effort", "verbosity"])
)

# Collect data for plotting
plot_data = []
for _, row in unique_combos.iterrows():
    llm = row["llm"]
    reasoning_effort = row["reasoning_effort"]
    verbosity = row["verbosity"]

    mask = (
        (df["llm"] == llm)
        & (df["reasoning_effort"] == reasoning_effort)
        & (df["verbosity"] == verbosity)
    )
    df_filtered = df[mask]

    mean_scaled_accuracy = df_filtered["scaled_accuracy"].mean()
    mean_scaled_brier = df_filtered["scaled_brier_score"].mean()
    mean_indep_accuracy = df_filtered["mean_indep_accuracy"].mean()
    mean_indep_brier = df_filtered["mean_indep_brier_score"].mean()
    mean_consistency_accuracy = df_filtered["consistency_accuracy"].mean()
    mean_consistency_brier = df_filtered["consistency_brier_score"].mean()

    plot_data.append(
        {
            "config": f"{llm}\n{reasoning_effort}\n{verbosity}",
            "scaled_accuracy": mean_scaled_accuracy,
            "scaled_brier_score": mean_scaled_brier,
            "mean_indep_accuracy": mean_indep_accuracy,
            "mean_indep_brier_score": mean_indep_brier,
            "consistency_accuracy": mean_consistency_accuracy,
            "consistency_brier_score": mean_consistency_brier,
        }
    )

# Create bar charts
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

configs = [d["config"] for d in plot_data]
x = np.arange(len(configs))
width = 0.25  # Width of bars

# Accuracy bar chart (mean_indep, consistency, and scaled)
mean_indep_accuracies = [d["mean_indep_accuracy"] for d in plot_data]
consistency_accuracies = [d["consistency_accuracy"] for d in plot_data]
scaled_accuracies = [d["scaled_accuracy"] for d in plot_data]
ax1.bar(x - width, mean_indep_accuracies, width, alpha=0.8, label="Mean Independent")
ax1.bar(x, consistency_accuracies, width, alpha=0.8, label="Consistency")
ax1.bar(x + width, scaled_accuracies, width, alpha=0.8, label="Scaled")
ax1.set_xlabel("Model Configuration")
ax1.set_ylabel("consistency_accuracy")
ax1.set_title("Accuracy by Model Configuration")
ax1.set_xticks(x)
ax1.set_xticklabels(configs, rotation=45, ha="right")
ax1.set_ylim(0.8, 0.9)
ax1.grid(True, alpha=0.3, axis="y")
ax1.legend()

# Brier score bar chart (mean_indep, consistency, and scaled)
mean_indep_brier_scores = [d["mean_indep_brier_score"] for d in plot_data]
consistency_brier_scores = [d["consistency_brier_score"] for d in plot_data]
scaled_brier_scores = [d["scaled_brier_score"] for d in plot_data]
ax2.bar(
    x - width, mean_indep_brier_scores, width, alpha=0.8, color="orange", label="Mean Independent"
)
ax2.bar(x, consistency_brier_scores, width, alpha=0.8, color="darkorange", label="Consistency")
ax2.bar(x + width, scaled_brier_scores, width, alpha=0.8, color="red", label="Scaled")
ax2.set_xlabel("Model Configuration")
ax2.set_ylabel("Brier Score")
ax2.set_title("Brier Score by Model Configuration")
ax2.set_xticks(x)
ax2.set_xticklabels(configs, rotation=45, ha="right")
ax2.grid(True, alpha=0.3, axis="y")
ax2.legend()

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
    df.groupby(["llm", "reasoning_effort", "verbosity", "question"])
    .agg({"scaled_brier_score": list})
    .reset_index()
)

# Create pivot tables for average scaled brier score and accuracy by question and (llm, reasoning_effort)
import numpy as np

# Create a combined column for (llm, reasoning_effort)
df["model_config"] = df["llm"] + "_" + df["reasoning_effort"] + "_" + df["verbosity"]

# Pivot table for average scaled brier score with count
brier_pivot_mean = df.pivot_table(
    values="scaled_brier_score", index="question", columns="model_config", aggfunc="mean"
)
brier_pivot_count = df.pivot_table(
    values="scaled_brier_score", index="question", columns="model_config", aggfunc="count"
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
    verbosity = row["verbosity"]
    model_config = f"{llm}_{effort}_{verbosity}"

    print(f"\n{'='*80}")
    print(f"Model: {llm}, Reasoning Effort: {effort}, Verbosity: {verbosity}")
    print(f"{'='*80}")

    # Calculate relative performance (this model's scaled brier score minus average of all others)
    other_cols = [
        col for col in brier_pivot_mean.columns if col != model_config and col != "variance"
    ]

    if model_config in brier_pivot_mean.columns:
        # Calculate average scaled brier score of other models for each question
        brier_pivot_mean["others_avg"] = brier_pivot_mean[other_cols].mean(axis=1)

        # Calculate relative performance (negative means this model is better)
        brier_pivot_mean["relative_performance"] = (
            brier_pivot_mean[model_config] - brier_pivot_mean["others_avg"]
        )

        # Questions where this model performs BEST (most negative relative performance)
        print(f"\nTop 10 questions where {model_config} performs BEST relative to others:")
        print("(Negative values = better performance, i.e., lower scaled Brier score)")
        best_questions = brier_pivot_mean.nsmallest(10, "relative_performance")[
            [model_config, "others_avg", "relative_performance"]
        ]
        print(best_questions.to_string())

        # Questions where this model performs WORST (most positive relative performance)
        print(f"\nTop 10 questions where {model_config} performs WORST relative to others:")
        print("(Positive values = worse performance, i.e., higher scaled Brier score)")
        worst_questions = brier_pivot_mean.nlargest(10, "relative_performance")[
            [model_config, "others_avg", "relative_performance"]
        ]
        print(worst_questions.to_string())

        # Clean up temporary columns
        brier_pivot_mean.drop(columns=["others_avg", "relative_performance"], inplace=True)
    else:
        print(f"Model configuration {model_config} not found in data")


# %%

##############################################
# WTF is going on with consistency analysis? #
##############################################

# %%

# Create separate scatterplots of pre_brier vs post_brier for each (llm, reasoning, verbosity) combination
import matplotlib.pyplot as plt

# Get unique combinations
unique_combos = (
    df[["llm", "reasoning_effort", "verbosity"]]
    .drop_duplicates()
    .sort_values(by=["llm", "reasoning_effort", "verbosity"])
)

num_combos = len(unique_combos)
cols = 3
rows = (num_combos + cols - 1) // cols  # Calculate rows needed

fig, axes = plt.subplots(rows, cols, figsize=(15, 5 * rows))
axes = axes.flatten() if num_combos > 1 else [axes]

for idx, (_, row) in enumerate(unique_combos.iterrows()):
    llm = row["llm"]
    reasoning_effort = row["reasoning_effort"]
    verbosity = row["verbosity"]

    mask = (
        (df["llm"] == llm)
        & (df["reasoning_effort"] == reasoning_effort)
        & (df["verbosity"] == verbosity)
    )
    df_filtered = df[mask]

    # Calculate average brier scores
    avg_pre_brier = df_filtered["mean_indep_brier_score"].mean()
    avg_post_brier = df_filtered["consistency_brier_score"].mean()
    avg_diff = avg_post_brier - avg_pre_brier

    ax = axes[idx]

    # Add shaded regions to show good/bad quadrants
    # Green: pre > 0.25 and post < 0.25 (lower right quadrant - good)
    ax.axhspan(0, 0.25, xmin=0.25, xmax=1, alpha=0.1, color="green", zorder=0)
    # Red: pre < 0.25 and post > 0.25 (upper left quadrant - bad)
    ax.axhspan(0.25, 1, xmin=0, xmax=0.25, alpha=0.1, color="red", zorder=0)

    # Add reference lines at 0.25
    ax.axhline(y=0.25, color="gray", linestyle=":", alpha=0.5, linewidth=1)
    ax.axvline(x=0.25, color="gray", linestyle=":", alpha=0.5, linewidth=1)

    ax.scatter(
        df_filtered["mean_indep_brier_score"],
        df_filtered["consistency_brier_score"],
        alpha=0.5,
        zorder=2,
    )

    # Add diagonal line (where pre = post)
    min_val = min(
        df_filtered["mean_indep_brier_score"].min(), df_filtered["consistency_brier_score"].min()
    )
    max_val = max(
        df_filtered["mean_indep_brier_score"].max(), df_filtered["consistency_brier_score"].max()
    )
    ax.plot([min_val, max_val], [min_val, max_val], "r--", alpha=0.5, label="x=y", zorder=1)

    ax.set_xlabel("Pre-Brier Score")
    ax.set_ylabel("Post-Brier Score")
    ax.set_title(
        f"{llm}\n{reasoning_effort}, {verbosity}\n(n={len(df_filtered)})\nΔ={avg_diff:.4f}"
    )
    ax.grid(True, alpha=0.3)
    ax.legend()

# Hide any unused subplots
for idx in range(num_combos, len(axes)):
    axes[idx].set_visible(False)

plt.tight_layout()
plt.show()

# %%

# Create confusion matrix-style visualizations for accuracy
import numpy as np
from matplotlib import colors

fig, axes = plt.subplots(rows, cols, figsize=(15, 5 * rows))
axes = axes.flatten() if num_combos > 1 else [axes]

for idx, (_, row) in enumerate(unique_combos.iterrows()):
    llm = row["llm"]
    reasoning_effort = row["reasoning_effort"]
    verbosity = row["verbosity"]

    mask = (
        (df["llm"] == llm)
        & (df["reasoning_effort"] == reasoning_effort)
        & (df["verbosity"] == verbosity)
    )
    df_filtered = df[mask]

    # Create confusion matrix: rows = post_accuracy, cols = pre_accuracy
    # Row 0 = Post Correct, Row 1 = Post Incorrect
    confusion = np.zeros((2, 2))
    confusion[0, 0] = (
        (df_filtered["mean_indep_accuracy"] == False)
        & (df_filtered["consistency_accuracy"] == True)
    ).sum()  # Pre incorrect, Post correct
    confusion[0, 1] = (
        (df_filtered["mean_indep_accuracy"] == True) & (df_filtered["consistency_accuracy"] == True)
    ).sum()  # Both correct
    confusion[1, 0] = (
        (df_filtered["mean_indep_accuracy"] == False)
        & (df_filtered["consistency_accuracy"] == False)
    ).sum()  # Both incorrect
    confusion[1, 1] = (
        (df_filtered["mean_indep_accuracy"] == True)
        & (df_filtered["consistency_accuracy"] == False)
    ).sum()  # Pre correct, Post incorrect

    # Calculate percentage changes
    total = len(df_filtered)
    avg_pre_acc = df_filtered["mean_indep_accuracy"].mean()
    avg_post_acc = df_filtered["consistency_accuracy"].mean()
    acc_diff = avg_post_acc - avg_pre_acc

    ax = axes[idx]

    # Create heatmap
    im = ax.imshow(confusion, cmap="Blues", aspect="auto")

    # Set ticks and labels
    ax.set_xticks([0, 1])
    ax.set_yticks([0, 1])
    ax.set_xticklabels(["Pre Incorrect", "Pre Correct"])
    ax.set_yticklabels(["Post Correct", "Post Incorrect"])
    ax.set_xlabel("Pre-Calibration Accuracy")
    ax.set_ylabel("Post-Calibration Accuracy")

    # Add text annotations with counts and percentages
    for i in range(2):
        for j in range(2):
            count = int(confusion[i, j])
            pct = confusion[i, j] / total * 100
            text = ax.text(
                j,
                i,
                f"{count}\n({pct:.1f}%)",
                ha="center",
                va="center",
                color="black" if confusion[i, j] < confusion.max() / 2 else "white",
                fontsize=12,
                weight="bold",
            )

    # Add colorbar
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    ax.set_title(f"{llm}\n{reasoning_effort}, {verbosity}\n(n={total})\nΔAcc={acc_diff:.4f}")

# Hide any unused subplots
for idx in range(num_combos, len(axes)):
    axes[idx].set_visible(False)

plt.tight_layout()
plt.show()

# %%
