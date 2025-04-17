[![License: LGPL v3](https://img.shields.io/badge/License-LGPL%20v3-blue.svg)](https://www.gnu.org/licenses/lgpl-3.0)

The Docent code preview is licensed under LGPL.

# Docent Onboarding Notes

- [Running Docent](#running-docent)
  - [Environment variables](#environment-variables)
  - [Option 1: Docker](#option-1-docker)
  - [Option 2: Manual](#option-2-manual)
- [Docent Codebase Notes](#docent-codebase-notes)
- [Ingesting your own logs](#ingesting-your-own-logs)
  - [Parsing logs](#parsing-logs)
  - [Interventions](#interventions)

## Running Docent

*Estimated time, if nothing goes wrong: ~5 minutes*

### Environment variables

We store important environment variables in a `.env` file at the root of the project. A `.env.template` example is provided; you need to create a new `.env` file with your OpenAI/Anthropic keys, and you should also specify paths of your choice for caching LLM calls and Inspect experiment results

### Option 1: Docker

> [!NOTE]
> Docker can make iteration times slower, so this may not be convenient for development.
> Additionally, running interventions in the Docker container does not work well yet, as it requires spawning more Docker containers.

First install Docker if it's not already on your system. Then run:

```bash
./project/docent/scripts/docker_build.sh -a 8889 -w 3001
./project/docent/scripts/docker_run.sh -a 8889 -w 3001
```

If on Linux, you'll need to use `sudo`.

The API will run on port 8889 and the frontend will run on port 3001. Build + cold start should take ~2 minutes.

### Option 2: Manual

We assume you're in a Linux environment with access to apt. In that case, you can run

```bash
source project/docent/scripts/server_setup.sh --transluce_home /path/to/docent_repo
```

to set up dependencies. Afterwards you can run

```bash
./project/docent/scripts/api.sh -p 8888
```

to start the server on port 8888.

Then run

```bash
./project/docent/scripts/web.sh -p 3000 -h http://localhost:8888 # auto-reload mode
```

or

```bash
./project/docent/scripts/build_and_serve.sh --skip_posthog -p 3000 -h http://localhost:8888 # production build
```

to start the frontend on port 3000.

## Ingesting your own logs

*Estimated time: ~15-30 minutes*

### Parsing logs

The main entrypoint for loading logs into Docent is in [`load.py`](project/docent/docent/loader/load.py).
- Notice the different *environments*; you can easily modulate which evals get loaded based on the `ENV_TYPE` environment variable.
- `EVALS_SPECS_DICT` maps, for each environment, `eval_id`s to functions that load transcripts for each eval.
- The `EVALS` variable is a dictionary mapping `eval_ids` to lists of `Transcript` objects, based on `ENV_TYPE`.


For a quick-and-dirty quickstart, **simply implement `load_custom()` in [`load_custom.py`](project/docent/docent/loader/load_custom.py)**. [As you can see](project/docent/docent/loader/load.py#L33), we've pre-added the custom loader to the `custom` environment. You can simply restart your API server with `ENV_TYPE=custom` set:
- For Docker: Use `./project/docent/scripts/docker_build.sh -a 8889 -w 3001 -e custom`, kill the existing container, then re-run `docker_run.sh`
- For manual: `ENV_TYPE=custom ./project/docent/scripts/api.sh -p 8888`

> [!NOTE]
> If you're on a manual installation, you can run `python3 project/docent/docent/loader/load_custom.py` to check your loading function. We added an `if __name__ == "__main__"` block to make this easy.

See [`transcript.py`](lib/frames/frames/transcript.py#L105) for the `Transcript` object definition. Note that `Transcript`s have [`metadata` with a particular schema](lib/frames/frames/transcript.py#L19). Most fields are pretty straightforward. Some clarifications:

- We borrowed terminology from Inspect, in which each eval is called a **task**, each eval task is called a **sample**, and each stochastic run of an agent on a sample is an **epoch**. That's what `task_id`, `sample_id`, and `epoch_id` refer to, respectively.
- An **experiment** is one invocation of the agent evaluation harness. That's what `experiment_id` refers to. For example, running Claude Sonnet 3.5 on an entire benchmark would be one experiment; running Sonnet 3.7 on the same benchmark would be another experiment; running one particular sample with a modified agent prompt would be a third experiment. Each eval might have multiple experiments.
- Since tasks often have custom scorers that output scores in their own formats, we allow you to pass in scoring data as arbitrary dictionaries in `Transcript.metadata.scores`. You'll have to tell Docent the default score to render in the frontend (`Transcript.metadata.default_score_key`)
- For regular logs you can leave the intervention fields (`Transcript.metadata.intervention_description`, `Transcript.metadata.intervention_timestamp`, `Transcript.metadata.intervention_index`) empty; they'll get populated by Docent when you run interventions on tasks.
- `task_args` is specific to Inspect and not necessary for most logs.
- You can stick any additional task metadata in the `TranscriptMetadata.additional_metadata` field.

You can see existing loaders for inspiration:
- [For general Inspect logs](project/docent/docent/loader/load_inspect.py)
- [For OpenHands SWE-Bench logs](project/docent/docent/loader/load_oh_swe_bench.py)
- [For Tau-Bench logs](project/docent/docent/loader/load_tau_bench.py)

### Interventions

One of the unique features of Docent is the ability to intervene in the middle of agent transcripts and re-run experiments to answer counterfactuals

To support intervening in the middle of agent transcripts, we have to modify the Inspect task setup to take in a `LuceTaskArgs` object as input. So far we've only done this for Cybench and Intercode; you can see an example of how this works in [`external/inspect_evals/src/inspect_evals/cybench/cybench.py`](external/inspect_evals/src/inspect_evals/cybench/cybench.py). If you want to intervene on other tasks, you'll need to modify the task setup in the corresponding `inspect_evals` subdirectory accordingly. Most tasks will also require installing Docker and Docker Compose on the server to build and start environment containers.

If you'd like help supporting this for your own tasks, reach out over email/Slack!

## Docent Codebase Notes

Here's a quick guide to the codebase:

- The Docent frontend lives in [`project/docent/web`](project/docent/web). It's a standard Typescript + Next.js project
- The Docent server code lives in [`project/docent/docent`](project/docent/docent). It's a standard Python FastAPI server that uses WebSockets to manage client connections and operates on `Frame`s as the underlying data storage format
- The `lib` folder has some helpful libraries. The most relevant ones are:
  - [`lib/frames`](lib/frames) is a library that defines methods for interacting with Frame objects. Frame objects allow us to assign attributes to datapoints (the attributes can be structured data or the result of LLM judgements), filter a dataset by attributes, and compose filters to form complex queries (eg. "find all datapoints where the model made a mistake AND the model eventually solved the task"). The `clustering` subfolder uses LLM calls to cluster text attributes.
  - [`lib/llm_util`](lib/llm_util) has some utilities for LLM API calls.
- The `external` folder contains forks of external libraries:
  - In particular, we use [`external/inspect_ai`](external/inspect_ai) as the backend for running agent evaluations. Inspect provides a standardized data format and a standardized way of sandboxing and evaluating models. The Docent backend integrates with Inspect via [`run_inspect_experiment.sh`](project/docent/docent/experiments/run_inspect_experiment.sh), allowing the Docent to spawn new Inspect tasks.
  - [`external/inspect_evals`](external/inspect_evals) contains common benchmarks that already have Inspect integrations. If the task you're studying doesn't already have an Inspect implementation, you can add it here.
- We use `uv` to manage Python dependencies. In addition, we've written `luce`, a helpful command-line utility which makes it easy to install projects and enter virtual environments

This is an early preview of the codebase, so we apologize for any messiness! Let us know if you see obvious room for improvement.
