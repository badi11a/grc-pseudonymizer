"""
Structured JSON logger for SIEM ingestion via Docker log driver.

Every log record is emitted as a single JSON line to stdout so that
Docker captures it verbatim.  The banner and human-readable summary
are kept on stderr (pipeline.py) to stay out of the machine-readable
stream.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class _JSONFormatter(logging.Formatter):
    """Emit one JSON object per line with fixed SIEM fields."""

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self._run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "run_id": self._run_id,
            "level": record.levelname,
            "module": record.name,
            "event": record.getMessage(),
        }
        # Merge any extra fields passed via the `extra=` kwarg
        for key, value in record.__dict__.items():
            if key not in logging.LogRecord.__init__.__code__.co_varnames and \
               key not in (
                   "name", "msg", "args", "levelname", "levelno", "pathname",
                   "filename", "module", "exc_info", "exc_text", "stack_info",
                   "lineno", "funcName", "created", "msecs", "relativeCreated",
                   "thread", "threadName", "processName", "process", "message",
                   "taskName",
               ):
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


def get_logger(run_id: str, module: str = "pipeline") -> logging.Logger:
    """Return a logger whose output is a JSON stream on stdout.

    Safe to call multiple times per run (idempotent) and across successive
    runs in the same process (UI mode): the handler is replaced whenever the
    run_id changes so every line carries the correct correlation key.
    """
    logger = logging.getLogger(module)
    logger.setLevel(logging.DEBUG)

    # Replace any existing stdout handler whose run_id differs from this run
    for h in list(logger.handlers):
        if isinstance(h, logging.StreamHandler) and h.stream is sys.stdout:
            if isinstance(h.formatter, _JSONFormatter) and h.formatter._run_id == run_id:
                # Already configured for this run — nothing to do
                logger.propagate = False
                return logger
            logger.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JSONFormatter(run_id))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
