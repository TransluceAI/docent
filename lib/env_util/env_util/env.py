import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from log_util import get_logger
from pydantic import BaseModel

logger = get_logger(__name__)


class EnvironmentVariables(BaseModel):
    OPENAI_API_KEY: str | None
    ANTHROPIC_API_KEY: str | None
    HF_TOKEN: str | None

    TOGETHER_API_KEY: str | None
    PERPLEXITY_API_KEY: str | None

    MORPH_API_KEY: str | None

    PG_USER: str | None
    PG_PASSWORD: str | None
    PG_HOST: str | None
    PG_PORT: str | None
    PG_DATABASE: str | None

    LLM_CACHE_PATH: str | None
    INSPECT_EXPERIMENT_CACHE_PATH: str | None

    DD_API_KEY: str | None
    DD_APP_KEY: str | None

    EVAL_LOGS_DIR: str | None
    ENV_TYPE: (
        Literal["dev", "prod", "staging"] | str | None
    )  # Extra str is for custom deployments for other people

    @classmethod
    def load_from_env(cls):
        env_file = find_dotenv()
        load_dotenv(env_file)

        openai_api_key = os.getenv("OPENAI_API_KEY")
        anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        hf_token = os.getenv("HF_TOKEN")
        together_api_key = os.getenv("TOGETHER_API_KEY")
        perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")
        morph_api_key = os.getenv("MORPH_API_KEY")
        pg_user = os.getenv("PG_USER")
        pg_password = os.getenv("PG_PASSWORD")
        pg_host = os.getenv("PG_HOST")
        pg_port = os.getenv("PG_PORT")
        pg_database = os.getenv("PG_DATABASE")
        llm_cache_path = os.getenv("LLM_CACHE_PATH")
        inspect_experiment_cache_path = os.getenv("INSPECT_EXPERIMENT_CACHE_PATH")
        dd_api_key = os.getenv("DD_API_KEY")
        dd_app_key = os.getenv("DD_APP_KEY")
        eval_logs_dir = os.getenv("EVAL_LOGS_DIR")
        env_type = os.getenv("ENV_TYPE")

        logger.info(f"ENV_TYPE: {env_type}")

        return cls(
            OPENAI_API_KEY=openai_api_key,
            ANTHROPIC_API_KEY=anthropic_api_key,
            HF_TOKEN=hf_token,
            TOGETHER_API_KEY=together_api_key,
            PERPLEXITY_API_KEY=perplexity_api_key,
            MORPH_API_KEY=morph_api_key,
            PG_USER=pg_user,
            PG_PASSWORD=pg_password,
            PG_HOST=pg_host,
            PG_PORT=pg_port,
            PG_DATABASE=pg_database,
            LLM_CACHE_PATH=llm_cache_path,
            INSPECT_EXPERIMENT_CACHE_PATH=inspect_experiment_cache_path,
            DD_API_KEY=dd_api_key,
            DD_APP_KEY=dd_app_key,
            EVAL_LOGS_DIR=eval_logs_dir,
            ENV_TYPE=env_type,
        )


def find_dotenv():
    """
    Find the .env file in the project directory. Stops ascending at the project root.
    Raises an error with the list of paths explored if no .env file is found.
    """
    current_dir = Path(__file__).parent.resolve()
    paths_explored: list[str] = []

    while True:
        paths_explored.append(str(current_dir))
        env_file = current_dir / ".env"
        if env_file.is_file():
            return str(env_file)
        if is_project_root(current_dir):
            break
        if current_dir == current_dir.parent:
            break
        current_dir = current_dir.parent

    raise FileNotFoundError(f"No .env file found. Paths explored: {', '.join(paths_explored)}")


def is_project_root(directory: Path):
    return (directory / ".root").exists()


ENV = EnvironmentVariables.load_from_env()
