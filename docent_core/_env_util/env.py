import os
from pathlib import Path

from dotenv import dotenv_values

from docent._log_util import get_logger

logger = get_logger(__name__)


def load_dotenv():
    # Navigate to project root (3 levels up) by default
    fpath = Path(__file__).parent.parent.parent.absolute() / ".env"
    if not fpath.exists():
        raise FileNotFoundError(
            f"No .env file found at {fpath}. "
            "Make sure you've created one, then put it at project root."
        )

    # Determine how to resolve conflicts between .env and os.environ
    env_resolution_strategy = os.getenv("ENV_RESOLUTION_STRATEGY", "exception")
    if env_resolution_strategy not in ["exception", "dotenv", "os_environ"]:
        raise ValueError(f"Invalid ENV_RESOLUTION_STRATEGY: {env_resolution_strategy}")
    logger.info(
        f"Using strategy={env_resolution_strategy} to resolve conflicts between .env and os.environ"
    )

    # Load the .env file and ensure all values are strings
    env_dict = dotenv_values(fpath)
    for k, v in env_dict.items():
        if v is None:
            logger.warning(f"Skipping {k} because it is not set in the .env file")
        elif k in os.environ and os.environ[k] != v:
            if env_resolution_strategy == "exception":
                raise ValueError(
                    f"Conflict found for {k}: {v} in .env and {os.environ[k]} in environment"
                )
            elif env_resolution_strategy == "dotenv":
                logger.warning(
                    f"Found conflict for {k}: {v} in .env and {os.environ[k]} in environment. "
                    f"Using .env value: {v}"
                )
                os.environ[k] = v
            elif env_resolution_strategy == "os_environ":
                logger.warning(
                    f"Found conflict for {k}: {v} in .env and {os.environ[k]} in environment. "
                    f"Using environment value: {os.environ[k]}"
                )
        else:
            os.environ[k] = v
    logger.info(f"Loaded .env file from {fpath}")

    return os.environ


ENV = load_dotenv()


def get_deployment_id() -> str | None:
    deployment_id = ENV.get("DEPLOYMENT_ID")

    # Any falsy value is treated as a local deployment
    if not deployment_id:
        return None

    return deployment_id
