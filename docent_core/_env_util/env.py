import os
from pathlib import Path

from dotenv import dotenv_values

from docent._log_util import get_logger

logger = get_logger(__name__)


def load_dotenv():
    if (custom_env_path := os.getenv("DOCENT_ENV_PATH")) is not None:
        fpath = Path(custom_env_path)
        if not fpath.is_absolute():
            raise ValueError(f"DOCENT_ENV_PATH must be absolute, got: {custom_env_path}")
    else:
        # Navigate to project root (3 levels up) by default
        fpath = Path(__file__).parent.parent.parent.absolute() / ".env"

    if not fpath.exists():
        raise FileNotFoundError(
            f"No .env file found at {fpath}. "
            "Make sure you've created one, then put it at project root."
        )

    # Load the .env file and ensure all values are strings
    env_dict = dotenv_values(fpath)
    for k, v in env_dict.items():
        if v is None:
            logger.warning(f"Skipping {k} because it is not set in the .env file")
        elif k in os.environ and os.environ[k] != v:
            logger.warning(f"Overwriting {k}, which is already set in the environment")
        else:
            os.environ[k] = v
    logger.info(f"Loaded .env file from {fpath}")

    return os.environ


ENV = load_dotenv()
