Technical overview of the label elicitation pipeline (`label_elicitation.py`) — how we figure out what a user cares about, then pick the most useful runs to send them for labeling.

The pipeline has two stages: first we ask the user questions to learn their preferences, then we use that to decide which runs are worth labeling.

*Stage 1 — Learning user preferences*
* We sample a batch of agent runs and look for places where the rubric is ambiguous — things reasonable evaluators might disagree on
* Each ambiguity becomes a question, rated on two axes: how much it matters for scoring (relevance) and how much we don't already know the answer (novelty)
* We rank questions using a Pareto sort on those two axes, so we don't have to choose between "important" and "new" — questions that score well on both rise to the top
    * When we need to break ties, we lean slightly toward relevance (60/40 weighting)
* An LLM pass deduplicates the list and orders remaining questions so that prerequisite questions come first
* The user's answers get folded into a user model, which is a collection of annotated examples (not abstract rules)
    * When answers contradict each other, we keep both and note the tension — this lets the model represent preferences that depend on context

*Stage 2 — Picking runs to label*
* For each candidate run, we estimate two distributions: `p_j(y | x, r)` (the rubric judge's prediction) and `p_u(y | x, z, r)` (what the user would predict given inferred user model `z`)
* We measure disagreement using cross-entropy `H[p_u, p_j]`
    * We only score on categorical fields (enums and booleans) to keep the comparison tractable
    * Epsilon smoothing (default 1e-2) prevents the score from blowing up when `p_j` assigns zero mass to outcomes `p_u` considers plausible
* Runs with the highest disagreement go to the top of the queue — those are the ones where a human label teaches us the most
* For each top-ranked run, we generate a labeling request that explains *why* it matters: what the judge and user model each predict, where they disagree, and which parts of the run to focus on
    * Everything is backed by citations into the actual run content so the user can verify claims directly

*Why it works this way*
* The user model stores concrete examples rather than principles — this gives downstream LLMs real cases to reason from instead of vague guidelines
* Pareto ranking lets us balance exploring blind spots in the user model against targeting questions that directly affect scores
* Citations run through the whole pipeline, so every question, rationale, and recommendation traces back to specific evidence
* Distribution estimation and request generation run in parallel to keep things fast
