"""DocRepo's own log, in <data root>\\System\\logs\\docrepo.log.

The logging module writes the file itself, so its path is checked by SafeFS
before the handler opens it. Rotation renames files only within that folder.
Log lines hold IDs, file names and actions, never captured content.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from docrepo.safe_fs import SafeFS

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_HANDLER_NAME = "docrepo-file"


def setup_logging(fs: SafeFS, data_root: Path, level: int = logging.INFO) -> Path:
    """Send DocRepo's log records to the data root's log file. Safe to call more than once."""
    log_dir = fs.makedirs(data_root / "System" / "logs")
    log_path = fs.checked_path(log_dir / "docrepo.log")
    root = logging.getLogger()
    for handler in [h for h in root.handlers if h.get_name() == _HANDLER_NAME]:
        root.removeHandler(handler)
        handler.close()
    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(handler)
    root.setLevel(level)
    return log_path
