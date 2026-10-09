"""Structured logging helpers for ExitVector Agent."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Any


class JsonFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.__dict__.get("event"):
            payload["event"] = record.event
        if record.__dict__.get("context"):
            payload["context"] = record.context
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(name: str, level: str = "INFO") -> logging.Logger:
    """Create a module logger with a JSON formatter and console handler."""

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)

    return logger


class SafeJsonFormatter(JsonFormatter):
    def __init__(self, secrets=()):
        super().__init__()
        self.secrets = tuple(str(s) for s in secrets if s)

    def format(self, record):
        output = super().format(record)
        for secret in self.secrets:
            output = output.replace(secret, "[REDACTED]")
            output = output.replace(json.dumps(secret)[1:-1], "[REDACTED]")
        return re.sub(r'(?i)((?:api[_-]?key|token|secret|password|authorization)[\\"\s:=]+)[^\\"\s,}]+',
                      r'\1[REDACTED]', output)


def configure_operational_logging(settings, *, quiet=False, dry_run=False):
    """One namespace handler tree, rotating local files, sanitized diagnostics."""
    logger = logging.getLogger("exitvector")
    for name in ["exitvector", *[n for n in logging.Logger.manager.loggerDict if n.startswith("exitvector.")]]:
        child = logging.getLogger(name)
        for handler in child.handlers[:]:
            child.removeHandler(handler); handler.close()
        child.propagate = name != "exitvector"
        child.setLevel(settings.agent_log_level)
    logger.setLevel(settings.agent_log_level)
    formatter = SafeJsonFormatter([settings.regivion_api_key, settings.telegram_bot_token,
                                   settings.llm_api_key, settings.reddit_client_secret, settings.reddit_client_id])
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING if quiet else logging.ERROR)
    console.setFormatter(formatter)
    logger.addHandler(console)
    if not dry_run:
        folder = Path(settings.agent_log_dir)
        folder.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(folder / "exitvector.log", maxBytes=2 * 1024 * 1024,
                                     backupCount=3, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger
