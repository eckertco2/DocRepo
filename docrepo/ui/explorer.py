"""Showing files in File Explorer. Only Explorer is started: DocRepo never opens or runs the file itself."""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def show_in_explorer(path: Path) -> bool:
    """Open File Explorer with ``path`` selected, or on the folder itself. Returns False if nothing there exists."""
    if os.name != "nt":
        return False
    target = Path(path)
    try:
        if target.is_dir():
            subprocess.Popen(["explorer", str(target)])  # noqa: S603, S607 - Explorer only, no shell
            return True
        if target.exists():
            # Explorer reads /select, and the path as one argument. A Windows path can't contain a quote.
            subprocess.Popen(f'explorer /select,"{target}"')  # noqa: S603, S607
            return True
        folder = next((p for p in target.parents if p.is_dir()), None)
        if folder is not None:
            subprocess.Popen(["explorer", str(folder)])  # noqa: S603, S607
    except OSError as e:
        log.warning("couldn't start File Explorer: %s", type(e).__name__)
    return False
