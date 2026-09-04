"""
core/logging.py — Structured application logging setup.

Configures a consistent logging format across the entire application.
Call configure_logging() once at application startup in main.py.

Design decisions:
- Uses Python's stdlib logging (no extra deps like loguru).
- JSON-line format in production is preferable for log aggregators; plain
  text is used here for readability during development.
- Sensitive document content should NOT be logged at INFO or above.
"""
import logging
import sys
from typing import Literal


LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# Named loggers for key subsystems — import these in other modules
logger = logging.getLogger("fintel")
ingestion_logger = logging.getLogger("fintel.ingestion")
retrieval_logger = logging.getLogger("fintel.retrieval")
llm_logger = logging.getLogger("fintel.llm")
db_logger = logging.getLogger("fintel.db")


def configure_logging(level: LogLevel = "INFO", *, debug: bool = False) -> None:
    """Configure root and application-level loggers.

    Args:
        level: Minimum log level for application loggers.
        debug: If True, also enable DEBUG on all fintel.* loggers and
               reduce SQLAlchemy engine noise.
    """
    effective_level = "DEBUG" if debug else level

    # Root handler — writes to stdout so Docker/container runtimes capture it
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )

    # Configure root (catches everything not explicitly set)
    root = logging.getLogger()
    root.setLevel(logging.WARNING)  # Keep noisy libs quiet by default
    root.addHandler(handler)

    # Application loggers
    for name in ("fintel",):
        log = logging.getLogger(name)
        log.setLevel(effective_level)
        log.propagate = True

    # SQLAlchemy: only show warnings unless debug mode
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if debug else logging.WARNING
    )
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

    logger.info("Logging configured | level=%s | debug=%s", effective_level, debug)
