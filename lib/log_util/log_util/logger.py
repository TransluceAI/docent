import logging
import sys
from dataclasses import dataclass


@dataclass
class ColorCode:
    fore: str
    style: str = ""


class Colors:
    # Foreground colors
    BLACK = ColorCode("\033[30m")
    RED = ColorCode("\033[31m")
    GREEN = ColorCode("\033[32m")
    YELLOW = ColorCode("\033[33m")
    BLUE = ColorCode("\033[34m")
    MAGENTA = ColorCode("\033[35m")
    CYAN = ColorCode("\033[36m")
    WHITE = ColorCode("\033[37m")

    # Styles
    BOLD = "\033[1m"
    RESET = "\033[0m"

    @staticmethod
    def apply(text: str, color: ColorCode) -> str:
        return f"{color.style}{color.fore}{text}{Colors.RESET}"


class ColoredFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: Colors.BLUE,
        logging.INFO: Colors.GREEN,
        logging.WARNING: Colors.YELLOW,
        logging.ERROR: Colors.RED,
        logging.CRITICAL: ColorCode("\033[31m", Colors.BOLD),
    }

    def __init__(self, fmt: str | None = None):
        super().__init__(
            fmt or "%(asctime)s [%(levelname)s] %(namespace)s: %(message)s", datefmt="%H:%M:%S"
        )

    def format(self, record: logging.LogRecord) -> str:
        # Add namespace to extra fields if not present
        if not getattr(record, "namespace", None):
            record.__dict__["namespace"] = record.name

        # Color the level name
        record.levelname = Colors.apply(record.levelname, self.COLORS[record.levelno])

        # Color the namespace
        record.__dict__["namespace"] = Colors.apply(record.__dict__["namespace"], Colors.CYAN)

        return super().format(record)


def get_logger(namespace: str) -> logging.Logger:
    """
    Get a colored logger for the specified namespace.

    Args:
        namespace: The namespace for the logger

    Returns:
        A configured logger instance
    """
    logger = logging.getLogger(namespace)

    # Only add handler if it doesn't exist
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(ColoredFormatter())
        logger.addHandler(handler)

        # Set default level to INFO
        logger.setLevel(logging.INFO)

    return logger
