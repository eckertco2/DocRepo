"""What the windows share: the data root, its settings, the database and a way to show notifications."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from docrepo.config import Settings
from docrepo.model import Model
from docrepo.parse import ParseLabel, ParsePerson
from docrepo.safe_fs import SafeFS


@dataclass
class AppContext:
    conn: sqlite3.Connection
    data_root: Path
    fs: SafeFS
    settings: Settings
    #: Shows a notification from the tray icon: (title, text).
    notify: Callable[[str, str], None] = lambda title, text: None
    now: Callable[[], datetime] = field(default=datetime.now)

    def model(self) -> Model:
        return Model(self.conn)

    def parse_people(self, model: Model) -> list[ParsePerson]:
        return [ParsePerson(p.id, p.name, tuple(p.aliases), p.status, p.id == self.settings.me) for p in model.people.values()]

    def parse_labels(self, model: Model) -> list[ParseLabel]:
        return [ParseLabel(label.name, tuple(label.keywords)) for label in model.active_labels()]
