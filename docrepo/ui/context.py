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
    #: Told which settings the Settings view just changed, so the app can apply them (a new hotkey, say).
    settings_changed: Callable[[list[str]], None] = lambda keys: None
    #: Starts a backup on the app's own thread. Without the app (in tests), the Settings view backs up there and then.
    start_backup: Callable[[], bool] | None = None
    #: The wheels' slots, for the Ctrl+K palettes (release 5.41). Without the app (in tests), there are none.
    wheel_palette: Callable[[], list] = lambda: []
    #: Told when Today may have changed, so the Today side panel draws it again (release 5.43).
    today_changed: Callable[[], None] = lambda: None
    #: The Model last loaded, and the database's state when it was (``model``).
    _model: Model | None = field(default=None, init=False, repr=False)
    _model_at: tuple[int, int] | None = field(default=None, init=False, repr=False)

    def model(self) -> Model:
        """Everything in docs.db, loaded again only once the database has changed (release 5.52): the capture window asks on
        each key pressed, and a load reads every table. All who ask share one Model, so it's read-only. ``total_changes``
        moves with this connection's writes and ``data_version`` with another's. Inside a transaction nothing is kept, since
        what's read there could still be rolled back."""
        if self.conn.in_transaction:
            return Model(self.conn)
        at = (self.conn.total_changes, self.conn.execute("PRAGMA data_version").fetchone()[0])
        if self._model is None or at != self._model_at:
            self._model, self._model_at = Model(self.conn), at
        return self._model

    def parse_people(self, model: Model) -> list[ParsePerson]:
        return [ParsePerson(p.id, p.name, tuple(p.aliases), p.status, p.id == self.settings.me) for p in model.people.values()]

    def parse_labels(self, model: Model) -> list[ParseLabel]:
        return [ParseLabel(label.name, tuple(label.keywords)) for label in model.active_labels()]
