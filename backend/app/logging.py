"""Local, bounded diagnostics shared by the desktop and command-line hosts."""

import json
import logging
import re
import threading
import time
import traceback
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pydantic import ValidationError

_CREDENTIAL = re.compile(
    r"(?i)(\b(?:api[_-]?key|apikey|key|token|access_token|password|authorization)"
    r"[\"']?\s*[:=]\s*[\"']?)(?:Bearer\s+)?[^\s&\"',}\]]+"
)
_VALIDATION_INPUT = re.compile(r"(input_value=).*?(, input_type=[\w.]+\])", re.DOTALL)
_VWORLD_KEY = re.compile(
    r"(https?://api\.vworld\.kr/req/wmts/1\.0\.0/)[^/\s\"']+", re.I
)


class _DiagnosticFormatter(logging.Formatter):
    converter = time.gmtime

    def formatException(self, exc_info):  # noqa: N802 - stdlib override
        error = exc_info[1]
        if isinstance(error, ValidationError):
            # Pydantic's default traceback includes rejected input values.
            details = error.errors(
                include_input=False, include_context=False, include_url=False
            )
            return "".join(traceback.format_tb(exc_info[2])) + json.dumps(details)
        return super().formatException(exc_info)

    def format(self, record):
        # Other handlers may already have cached a traceback containing inputs.
        previous = record.exc_text
        record.exc_text = None
        try:
            content = _VALIDATION_INPUT.sub(r"\1[redacted]\2", super().format(record))
            content = _VWORLD_KEY.sub(r"\1[redacted]", content)
            return _CREDENTIAL.sub(r"\1[redacted]", content)
        finally:
            record.exc_text = previous


@contextmanager
def application_logging(directory: Path, component: str):
    """Append UTF-8 UTC logs; release the file and restore host hooks on exit."""
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        directory / "uarc.log",
        maxBytes=5 * 1024**2,
        backupCount=3,
        encoding="utf-8",
        errors="backslashreplace",
    )
    handler.setFormatter(
        _DiagnosticFormatter(
            "%(asctime)s.%(msecs)03dZ %(levelname)s pid=%(process)d "
            "thread=%(threadName)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root = logging.getLogger()
    previous_level = root.level
    previous_hook = threading.excepthook

    def thread_error(args):
        logging.getLogger(__name__).error(
            "Unhandled thread exception thread=%s",
            args.thread.name if args.thread else "unknown",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        previous_hook(args)

    root.addHandler(handler)
    root.setLevel(min(previous_level, logging.INFO))
    threading.excepthook = thread_error
    logger = logging.getLogger(__name__)
    try:
        logger.info("Application started component=%s", component)
        yield
    except Exception:
        logger.exception("Application failed component=%s", component)
        raise
    finally:
        logger.info("Application stopped component=%s", component)
        threading.excepthook = previous_hook
        root.removeHandler(handler)
        handler.close()
        root.setLevel(previous_level)
