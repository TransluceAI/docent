import logging
import logging.config
from datetime import datetime
from pathlib import Path

import yaml

from inspect_evals.vas.src.config import CRS_SCRATCH_SPACE


class MultiLineFormatter(logging.Formatter):
    """Multi-line formatter.
    https://stackoverflow.com/a/66855071
    """

    def get_header_length(self, record):
        """Get the header length of a given record."""
        return len(
            super().format(
                logging.LogRecord(
                    name=record.name,
                    level=record.levelno,
                    pathname=record.pathname,
                    lineno=record.lineno,
                    msg="",
                    args=(),
                    exc_info=None,
                )
            )
        )

    def format(self, record):
        """Format a record with added indentation."""
        indent = " " * self.get_header_length(record)
        head, *trailing = super().format(record).splitlines(True)
        return head + "".join(indent + line for line in trailing)


def filter_maker(level):
    level = getattr(logging, level)

    def filter(record):
        return record.levelno <= level

    return filter


def make_logger():
    log_conf = yaml.safe_load(Path(Path(__file__).parent / "logging.yaml").read_text())
    log_conf["handlers"]["file"]["filename"] = CRS_SCRATCH_SPACE / f"crs.{datetime.today().isoformat()}.log"
    logging.config.dictConfig(log_conf)
    return logging.getLogger("CRS")


logger = make_logger()


class PrefixAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"[{self.extra['prefix']}] {msg}", kwargs  # type: ignore


def add_prefix_to_logger(logger: logging.Logger, prefix: str):
    return PrefixAdapter(logger, {"prefix": prefix})
