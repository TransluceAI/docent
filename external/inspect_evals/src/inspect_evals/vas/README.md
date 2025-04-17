# HonestCyberEval

HonestCyberEval focuses on models' ability to detect vulnerabilities
in real-world software by generating structured inputs that trigger known
sanitizers.

The vulnerability exploitation task is based on the challenge project released
for the DARPA AIxCC competition.

## Setup

- Install dependencies:

  ```shell
  sudo apt install make
  ```

- [Install `yq`](https://github.com/mikefarah/yq?tab=readme-ov-file#install)
  - E.g.:

    ```shell
    sudo snap install yq
    ```

Install the package with `uv pip install -e .`. This will override the local inspect_ai package, so you'll then want to run `uv pip uninstall inspect_ai` and `luce install inspect_ai`.

- To avoid issues with address randomisation ([more info](https://github.com/aixcc-public/challenge-004-nginx-cp/blob/bd4490502e9e8f42b45e536cbc05d78ebc41aa0e/README.md?plain=1#L53)), run:

  ```shell
  sudo sysctl vm.mmap_rnd_bits=28
  echo "vm.mmap_rnd_bits=28" | sudo tee -a /etc/sysctl.conf
  ```

- Set up the environment variables and API keys:
  - Rename the `.env.example` file:

  ```shell
  cp .env.example .env
  ```

  - Generate a new personal access token (PAT) (<https://github.com/settings/tokens>) with `read:packages` permissions.
    Fill in the `GITHUB_USER` and `GITHUB_TOKEN` values.
  - Fill in API keys for the LLM(s) that are to be evaluated (`ANTHROPIC_API_KEY`, `AZURE_API_KEY`, `OPENAI_API_KEY`).

### Docker

The evaluation challenge projects are run inside Docker containers.
If Docker is unavailable, installing it by following the [documentation](https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository).
Then, enable [managing Docker as a non-root user](https://docs.docker.com/engine/install/linux-postinstall/#manage-docker-as-a-non-root-user).

To be able to pull Docker images for the challenge projects, log into `ghcr.io` using your PAT, run:

  ```shell
  echo "<token>" | docker login ghcr.io -u <user> --password-stdin
  ```

replacing `<user>` and `<token>` with your generated PAT.

## Running the evaluation

First, configure which challenge project should be downloaded by (un)commenting the appropriate entries in
[`config/cp_config.yaml`](./config/cp_config.yaml).

Run the `make cps` command to download the code and docker images associated with challenge projects defined in
`cp_config.yaml`. The code will be downloaded to [cp_root](cp_root).

Finally, run the evaluation using `inspect eval exploit.py --model=<model> -T cp=<challenge project> -S max_iterations=<num>` e.g.

For example:

```shell
inspect eval exploit.py --model=openai/o1 -T cp=nginx-cp
```

will run the `nginx-cp` project with the default 5 reflexion loops and 3 epochs.
A successful attempt will terminate the current loop and skip future epochs.

The optional `critique_model` solver parameter allows a different model to be called for the critique component of the solver:

```shell
inspect eval exploit.py --model=openai/o1-mini -S critique_model=openai/o1
```

The first run will be slower as it will patch and build multiple copied of the project.
We recommend starting a mock run first to create the test projects before running the eval, but it is not required:

```shell
inspect eval exploit.py --model=mockllm/model -T cp=nginx-cp -S max_iterations=1
```

## Future work

- Use Inspect Docker sandbox instead of AIxCC Docker scripts for better integration
- Support challenge projects that expect input as bytes
- More tasks
