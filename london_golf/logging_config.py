"""Configure the london_golf logger: rotating file and optional stderr."""

import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_LOG_NAME = "london_golf"


class _LoggingState:  # pylint: disable=too-few-public-methods
    """Process-local flag: file handlers are attached only once per process."""

    configured = False


def get_logger():
    """Return the application logger with rotating file under ./logs/."""
    if _LoggingState.configured:
        return logging.getLogger(_LOG_NAME)

    logger = logging.getLogger(_LOG_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    script_stem = Path(sys.argv[0]).stem
    if script_stem in ("cli", "__main__"):
        script_stem = "londonGolfBook"
    log_file = log_dir / f"{script_stem}.log"
    handler = TimedRotatingFileHandler(
        str(log_file),
        when="midnight",
        interval=1,
        backupCount=100,
        encoding="utf-8",
    )
    handler.suffix = "%Y%m%d"
    handler.setFormatter(logging.Formatter("%(asctime)-15s,%(message)s"))
    logger.addHandler(handler)
    log_stderr = os.environ.get("LONDON_GOLF_LOG_STDERR", "").lower()
    if log_stderr in ("1", "true", "yes"):
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(
            logging.Formatter("%(asctime)-15s,%(levelname)s,%(message)s")
        )
        logger.addHandler(stream_handler)

    _LoggingState.configured = True
    return logger
