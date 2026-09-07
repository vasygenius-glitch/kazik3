"""Mask common secrets in formatted logs, including exception tracebacks."""
import logging
import re

_PATTERNS = (
    re.compile(r"\b(?:gh[pousr]_|github_pat_|hf_)[A-Za-z0-9_]{16,}"),
    re.compile(r"\b\d{6,15}:[A-Za-z0-9_-]{30,}"),
)
_USERINFO = re.compile(r"(?i)(\b(?:https?|rediss?|mongodb(?:\+srv)?|postgres(?:ql)?)://)[^/\s@]+@")


def redact_secrets(text: str) -> str:
    text = _USERINFO.sub(r"\1[REDACTED]@", text)
    for pattern in _PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


class RedactingFormatter(logging.Formatter):
    def __init__(self, wrapped=None):
        super().__init__()
        self.wrapped = wrapped or logging.Formatter()

    def format(self, record):
        return redact_secrets(self.wrapped.format(record))


def install_secret_redaction():
    loggers = [logging.getLogger()] + [value for value in logging.Logger.manager.loggerDict.values()
                                      if isinstance(value, logging.Logger)]
    for logger in loggers:
        for handler in logger.handlers:
            if not isinstance(handler.formatter, RedactingFormatter):
                handler.setFormatter(RedactingFormatter(handler.formatter))
