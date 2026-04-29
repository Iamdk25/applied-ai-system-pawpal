"""Structured JSON logging for the PawPal+ Planner Agent.

Emits one JSON object per event to pawpal_agent.log so we can replay agent
runs after the fact and pull metrics for the reliability writeup.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

LOG_PATH = Path(__file__).parent / "pawpal_agent.log"
_LEVEL = os.getenv("PAWPAL_AGENT_LOG_LEVEL", "INFO").upper()


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, default=str)


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("pawpal_agent")
    if logger.handlers:
        return logger  # already configured
    logger.setLevel(_LEVEL)
    handler = logging.FileHandler(LOG_PATH, mode="a", encoding="utf-8")
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


_logger = _build_logger()


def log_event(event: str, level: str = "INFO", **fields: Any) -> None:
    """Emit one structured event. fields land in the JSON payload."""
    _logger.log(getattr(logging, level.upper(), logging.INFO), event,
                extra={"fields": fields})


def tail(n: int = 50) -> list[str]:
    """Return the last N lines of the log file (for the Streamlit trace view)."""
    if not LOG_PATH.exists():
        return []
    with LOG_PATH.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    return [line.rstrip("\n") for line in lines[-n:]]
