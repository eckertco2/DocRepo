"""Showing files in File Explorer, for the windows. The launch itself is ``opener.show_in_explorer`` (release 5.87):
only ``opener.py`` starts another program."""
from __future__ import annotations

from docrepo.opener import open_folder, show_in_explorer

__all__ = ["open_folder", "show_in_explorer"]
