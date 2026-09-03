"""Centralized logging configuration with JSON formatter and correlation IDs."""
import contextvars
import logging
import logging.config
import re
import sys
from typing import Optional


# Context variable to store correlation_id across async calls
correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="-")


class CorrelationIdFilter(logging.Filter):
    """Add correlation_id from contextvar to log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get()
        return True


class SensitiveDataFilter(logging.Filter):
    """Sanitize sensitive data from log messages."""

    # Patterns to redact
    PATTERNS = [
        (re.compile(r"(tag=)[^&\s]+"), r"\1***"),
        (re.compile(r"(matt_tool=)[^&\s]+"), r"\1***"),
        (re.compile(r"(aff_trace_key=)[^&\s]+"), r"\1***"),
        (re.compile(r"(utm_[^=]+=)[^&\s]+"), r"\1***"),
        (re.compile(r"(token=)[^&\s]+"), r"\1***"),
        (re.compile(r"(password=)[^&\s]+"), r"\1***"),
        (re.compile(r"(api[_-]?key=)[^&\s]+"), r"\1***"),
        (re.compile(r"(secret=)[^&\s]+"), r"\1***"),
        # Authorization headers
        (re.compile(r"(Authorization:\s*)Bearer\s+[^\s]+"), r"\1Bearer ***"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern, replacement in self.PATTERNS:
                record.msg = pattern.sub(replacement, record.msg)
        return True


def get_logging_config(log_level: str = "INFO", json_format: bool = False) -> dict:
    """Return logging configuration dictionary."""
    formatter = "json" if json_format else "console"

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "console": {
                "format": "%(asctime)s [%(levelname)s] %(name)s [%(correlation_id)s]: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "json": {
                "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                "fmt": "%(asctime)s %(levelname)s %(name)s %(correlation_id)s %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "filters": {
            "correlation_id": {
                "()": CorrelationIdFilter,
            },
            "sensitive_data": {
                "()": SensitiveDataFilter,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "formatter": formatter,
                "filters": ["correlation_id", "sensitive_data"],
            },
        },
        "root": {
            "level": log_level,
            "handlers": ["console"],
        },
        "loggers": {
            "uvicorn": {"level": "INFO", "handlers": ["console"], "propagate": False},
            "uvicorn.error": {"level": "INFO", "handlers": ["console"], "propagate": False},
            "uvicorn.access": {"level": "INFO", "handlers": ["console"], "propagate": False},
        },
    }


def setup_logging(log_level: str = "INFO", json_format: bool = False) -> None:
    """Initialize logging with the given configuration."""
    config = get_logging_config(log_level, json_format)
    logging.config.dictConfig(config)


def set_correlation_id(correlation_id: str):
    """Set correlation ID in context variable and return token for reset."""
    return correlation_id_var.set(correlation_id)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the standard configuration."""
    return logging.getLogger(name)