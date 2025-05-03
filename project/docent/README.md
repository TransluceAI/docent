[![License: LGPL v3](https://img.shields.io/badge/License-LGPL%20v3-blue.svg)](https://www.gnu.org/licenses/lgpl-3.0)

The Docent code preview is licensed under LGPL.

# Docent Onboarding Notes

- [Running the Docent server + UI](#running-the-docent-server--ui)
  - [Environment variables](#environment-variables)
  - [Option 1: Docker (recommended)](#option-1-docker-recommended)
  - [Option 2: Manual](#option-2-manual)
- [Installing the Docent Python SDK](#installing-the-docent-python-sdk)
  - [Ingesting your own logs](#ingesting-your-own-logs)
- [Customizing LLM calls](#customizing-llm-calls)

## Running the Docent server + UI

### Environment variables

We store important environment variables in a `.env` file at the root of the project. A `.env.template` example is provided; please copy it to `.env` and fill in the necessary values.

### Option 1: Docker (recommended)

First install Docker if it's not already on your system. Then run (with `sudo` if on Linux):

```bash
./project/docent/scripts/docker_build.sh -a 8889 -w 3001
./project/docent/scripts/docker_run.sh -a 8889 -w 3001
```

The API will run on port 8889, and the frontend will run on port 3001. Build + cold start should take a few minutes.

### Option 2: Manual

You must have Postgres and Redis both installed and running.

- [[Official Postgres instructions](https://www.postgresql.org/download/)] On Debian Linux, that's `sudo apt install postgresql`.
  - By default, Postgres ships with the `postgres` user. Access the Postgres CLI with `sudo -u postgres psql`.
  - Then run `CREATE USER $user WITH PASSWORD '$password';` to create a new user. Record the user and password in `.env`. Ensure that the user has permissions to create a database, using `ALTER USER $user WITH SUPERUSER;`.
- [[Official Redis instructions](https://redis.io/docs/latest/operate/oss_and_stack/install/archive/install-redis/)] For Linux, specific instructions are [here](https://redis.io/docs/latest/operate/oss_and_stack/install/archive/install-redis/install-redis-on-linux/).
  - To verify that Redis is running, run `redis-cli ping`.

Next, run:

```bash
pip install -e lib/log_util lib/llm_util project/docent
```

to install the relevant packages, then

```bash
docent server --port 8889 -w 4
```

to start the server on port 8889 with 4 workers and

```bash
docent web --build --port 3001
```

to build and serve the frontend on port 3001. You should be able to access the Docent UI at `http://localhost:3001`.

## Installing the Docent Python SDK

In order to load transcripts into Docent, you'll need to install the Docent Python SDK.

Run this command if you haven't already (yes, it's the same as above), and you should be all set:

```bash
pip install -e lib/log_util lib/llm_util project/docent
```

You can now create a new session by running:

```python
from docent import DocentClient
client = DocentClient(server_url="http://localhost:8889", web_url="http://localhost:3001")

# Create a new FrameGrid (an object you can stick transcripts into)
fg_id = client.create_frame_grid()
```

You should see a new FrameGrid in the Docent UI upon refresh.

### Ingesting your own logs

See [`examples/ingest.ipynb`](project/docent/examples/ingest.ipynb) for an example of how to ingest your own logs. Tl;dr, the SDK supports `add_datapoints`, which expects a list of `Datapoint` objects.

```python
from docent._frames.transcript import Transcript
from docent._frames.types import Datapoint

transcripts = ...  # Load your transcripts here
datapoints = [
  Datapoint.from_transcript(transcript)
  for transcript in transcripts
]
client.add_datapoints(fg_id, datapoints)
```

See [`transcript.py`](project/docent/docent/_frames/transcript.py#L105) for the `Transcript` object definition. Note that `Transcript`s have [`metadata` with a particular schema](project/docent/docent/_frames/transcript.py#L19). Most fields are pretty straightforward. Some clarifications:

- We borrowed terminology from Inspect, in which each eval is called a **task**, each eval task is called a **sample**, and each stochastic run of an agent on a sample is an **epoch**. That's what `task_id`, `sample_id`, and `epoch_id` refer to, respectively.
- An **experiment** is one invocation of the agent evaluation harness. That's what `experiment_id` refers to. For example, running Claude Sonnet 3.5 on an entire benchmark would be one experiment; running Sonnet 3.7 on the same benchmark would be another experiment; running one particular sample with a modified agent prompt would be a third experiment. Each eval might have multiple experiments.
- Since tasks often have custom scorers that output scores in their own formats, we allow you to pass in scoring data as arbitrary dictionaries in `Transcript.metadata.scores`. You'll have to tell Docent the default score to render in the frontend (`Transcript.metadata.default_score_key`)
- For regular logs you can leave the intervention fields (`Transcript.metadata.intervention_description`, `Transcript.metadata.intervention_timestamp`, `Transcript.metadata.intervention_index`) empty; they'll get populated by Docent when you run interventions on tasks.
- `task_args` is specific to Inspect and not necessary for most logs.
- You can stick any additional task metadata in the `TranscriptMetadata.additional_metadata` field.

You can see existing loaders for inspiration:

- [For general Inspect logs](project/docent/docent/_loader/load_inspect.py)
- [For OpenHands SWE-Bench logs](project/docent/docent/_loader/load_oh_swe_bench.py)
- [For Tau-Bench logs](project/docent/docent/_loader/load_tau_bench.py)

## Customizing LLM Calls

Many users have requested a simpler way to manage LLM providers and API calls. This is now done in [`provider_preferences.py`](lib/llm_util/llm_util/provider_preferences.py). This file reads from an _LLM preferences config_, expected to be located at [`docent_llm_prefs.json`](lib/llm_util/llm_util/docent_llm_prefs.json); for convenience, we've provided an example config (containing the settings we use in the deployed Docent) that you can start with. The `docent_llm_prefs.json` config controls which LLM providers and models are used for each Docent feature. In the `model_options` field you should specify a list of models you would like to use (along with the provider and the `reasoning_effort` parameter if applicable), in order of priority; by default the first model in the list will be used for each query, and the other models in the list exist for fallback reasons (eg. in case an API is unavailable).

We have implemented providers for the OpenAI and Anthropic APIs; you can find the implementations in [`openai.py`](lib/llm_util/llm_util/openai.py) and [`anthropic.py`](lib/llm_util/llm_util/anthropic.py). If you'd like to add a new LLM provider, you can do so by implementing the `SingleOutputGetter` and `SingleStreamingOutputGetter` protocols for the new provider (see our example implementations as a reference) and registering a new `ProviderConfig` in the `LLMManager`'s `self.providers` (located in [`prod_llms.py`](lib/llm_util/llm_util/prod_llms.py)).
