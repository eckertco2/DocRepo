"""The glossary lookup (release 5.172, the design workspace's ``docs/mods/glossaries-plan.md``, decisions 807 to 809): a
popup modelled on Recent captures (``recent_captures``), reached from the Browse wheel's NE (``glossary.lookup``), a hotkey
of its own and the palette (decision 808), for finding a row of a glossary while writing somewhere else.

It opens on the list of glossaries, the last used first (``Settings.glossary_recent``); with only one, straight on its
rows. Typing narrows the list by name, and Enter or Tab opens one. Then the rows narrow as words are typed: a row matches
when every word is somewhere in it, in any column, case and accents aside, and a word with a digit in it matches a tag
however it's written ("p204a" finds P-204A). At most 50 are listed (``glossaries.lookup``, which orders them), each on one
line with its columns, the tag column first and in bold, and, when its tag is on the tag list, how many places mention it
("in 14 places", counted only for the rows listed).

- **Enter** (or a click) copies the row's tag, its first cell when the glossary has no tag column, and closes: the
  keyboard goes back to the window you were in, to paste it there.
- **Ctrl+C** copies the whole row, its cells tab-separated, and closes the same way (with text selected in the box, it
  copies that, as a box does).
- **Ctrl+Enter** opens the browse tool on the tag's tagged label page, which lists every mention.
- **Backspace** in an empty box goes back to the list of glossaries; **Esc** closes.

It changes nothing: it reads the glossaries' two tables, and the tag list from the Model the app already holds, for the
counts and the pages. Its one write is ``glossary_recent`` in settings.json, which glossary was used last.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QLineEdit,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from docrepo import glossaries, items, tagged
from docrepo.glossaries import Found, Glossary
from docrepo.ui import tokens
from docrepo.ui.style import style_sheet
from docrepo.ui.task_list import OPTION_ROLE, Row, TaskList, Words

if TYPE_CHECKING:
    from docrepo.app import CaptureApp

log = logging.getLogger(__name__)

#: The popup's list: as wide as its widest row, between these; this many rows in view before it scrolls.
LIST_MIN_W, LIST_MAX_W, ROWS = 520, 860, 12
WIDTH = LIST_MIN_W + 8
#: The line under the box: what the keys do, in each of its two lists.
HINT_LIST = "Enter or Tab opens a glossary"
HINT_ROWS = "Enter copies the tag · Ctrl+C the row · Ctrl+Enter the tag's page · Backspace: the glossaries"
#: The same, for a glossary with no tag column: Enter copies a row's first cell, and there's no tag's page to open.
HINT_NO_TAGS = "Enter copies the first column · Ctrl+C the row · Backspace: the glossaries"
NONE_YET = "No glossaries yet: import one in the browse tool's Glossaries view."
#: A row's ref in the list of glossaries, and in a glossary's rows.
_G, _R = "g:", "r:"


class LookupDelegate(QStyledItemDelegate):
    """A row as a line of parts: a glossary's name and, in grey, its rows and its tag column; or a glossary row's cells, the
    tag first in bold, the others separated by grey dots, and at its right end, in grey, how many places mention it. What
    doesn't fit is cut at the right edge."""

    PAD, GAP = 8, 12
    DOT = "  ·  "

    def __init__(self, popup: LookupList) -> None:
        super().__init__(popup)
        self.popup = popup
        self.font = tokens.ui_font(tokens.BODY)
        self.bold = QFont(self.font)
        self.bold.setBold(True)
        self.small = tokens.ui_font(tokens.CAPTION)

    def row_height(self) -> int:
        return max(30, QFontMetrics(self.font).height() + 10)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt's name
        return QSize(1, self.row_height())

    def _metrics(self, kind: str) -> QFontMetrics:
        return QFontMetrics(self.bold if kind == "bold" else self.small if kind == "grey" else self.font)

    def natural_width(self, o: Row, head: bool) -> int:
        """The row's width with nothing cut (``TaskList._fit`` asks)."""
        if isinstance(o, Words):
            return 2 * self.PAD + QFontMetrics(self.small).horizontalAdvance(o.label)
        parts, right = self.popup.parts(o)
        w = 2 * self.PAD + sum(self._metrics(k).horizontalAdvance(t) for t, k in parts)
        return w + (self.GAP + QFontMetrics(self.small).horizontalAdvance(right) if right else 0)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index) -> None:
        o: Row = index.data(OPTION_ROLE)
        rect = option.rect
        fn = QFontMetrics(self.font)
        base = int(rect.top() + (rect.height() + fn.ascent() - fn.descent()) / 2)
        left, right = rect.left() + self.PAD, rect.left() + rect.width() - self.PAD
        grey = QColor(tokens.colour("text2"))
        if isinstance(o, Words):
            p.save()
            p.setFont(self.small)
            p.setPen(grey)
            p.drawText(QPoint(left, base), QFontMetrics(self.small).elidedText(o.label, Qt.TextElideMode.ElideRight, max(0, right - left)))
            p.restore()
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, p, opt.widget)  # the row's back and selection
        parts, at_right = self.popup.parts(o)
        p.save()
        if at_right:
            fs = QFontMetrics(self.small)
            p.setFont(self.small)
            p.setPen(grey)
            p.drawText(QPoint(right - fs.horizontalAdvance(at_right), base), at_right)
            right -= fs.horizontalAdvance(at_right) + self.GAP
        text = QColor(tokens.colour("text"))
        for t, kind in parts:
            room = right - left
            if room <= 0:
                break
            fm = self._metrics(kind)
            shown = t if fm.horizontalAdvance(t) <= room else fm.elidedText(t, Qt.TextElideMode.ElideRight, room)
            p.setFont(self.bold if kind == "bold" else self.small if kind == "grey" else self.font)
            p.setPen(grey if kind in ("grey", "dot") else text)
            p.drawText(QPoint(left, base), shown)
            left += fm.horizontalAdvance(shown)
        p.restore()


class LookupList(TaskList):
    """The `#` list's rows and keys (``task_list.TaskList``), drawn as glossaries or as a glossary's rows."""

    def __init__(self, parent: GlossaryPopup) -> None:
        super().__init__(parent)
        self.popup = parent
        self.delegate = LookupDelegate(self)
        self.setItemDelegate(self.delegate)
        self.min_width, self.max_width, self.max_rows = LIST_MIN_W, LIST_MAX_W, ROWS

    def parts(self, o: Row) -> tuple[list[tuple[str, str]], str]:
        return self.popup.parts(o)


class GlossaryPopup(QFrame):
    """The popup: a line naming the glossary and its count, a box to type in, a line saying what the keys do, and the list.
    ``done(opened)`` is called as it closes after a pick: True when it opened the browse tool."""

    def __init__(self, parent: QWidget | None, app: CaptureApp, done) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("taskPicker")  # the task picker's frame and list, so they look alike
        self.app = app
        self.done = done
        self._at = QPoint()
        #: The glossaries, the last used first; the one open (None while its list shows).
        self.listed: list[Glossary] = []
        self.glossary: Glossary | None = None
        #: The rows listed, by their ref; each one's tagged label, when its tag is on the tag list, and its count of places.
        self.found: dict[str, Found] = {}
        self.labels: dict[str, tagged.Label] = {}
        self.places: dict[str, int] = {}
        self._hits: tuple[int, dict[int, int]] | None = None  # the Model's id, and its tasks' mentions (glossaries.task_hits)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.title = QLabel("", objectName="hint")
        self.title.setContentsMargins(4, 0, 4, 0)
        layout.addWidget(self.title)
        self.search = QLineEdit()
        self.search.setAccessibleName("Glossary lookup")
        self.search.textChanged.connect(self.refill)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)
        self.note = QLabel(HINT_LIST, objectName="hint")
        self.note.setContentsMargins(4, 0, 4, 0)
        layout.addWidget(self.note)
        self.list = LookupList(self)
        self.list.setObjectName("taskPickerList")
        self.list.picked.connect(self._picked)
        self.list.refitted.connect(self._place)
        layout.addWidget(self.list)

    # ---- opening ----
    def popup(self, at: QPoint) -> None:
        """Open with its top left at ``at``, kept on the screen: on the list of glossaries, or on the one there is."""
        self._at = QPoint(at)
        self._hits = None  # counted again for each opening, as the tag list may have changed
        ctx = self.app.ctx
        self.listed = glossaries.by_recent(glossaries.summaries(ctx.conn), ctx.settings.glossary_recent)
        if len(self.listed) == 1:
            self.open_glossary(self.listed[0], remember=False)
        else:
            self.back_to_list()
        self.show()
        self._place()
        self.raise_()
        self.search.setFocus()

    def _place(self) -> None:
        if not self.isVisible():
            return
        self.adjustSize()
        screen = QGuiApplication.screenAt(self._at) or self.screen() or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = max(area.left(), min(self._at.x(), area.left() + area.width() - self.width()))
        y = max(area.top(), min(self._at.y(), area.top() + area.height() - self.height()))
        self.move(x, y)

    def _clear_box(self, placeholder: str) -> None:
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.search.setPlaceholderText(placeholder)

    def back_to_list(self) -> None:
        """The list of glossaries, the box empty."""
        self.glossary = None
        self._clear_box("Which glossary? Type to narrow them")
        self.note.setText(HINT_LIST)
        self.refill()

    def open_glossary(self, g: Glossary, remember: bool = True) -> None:
        """A glossary's rows, the box empty; kept as the last used (decision 807)."""
        self.glossary = g
        self._clear_box(f"Search {g.name}: every word, any column")
        self.note.setText(HINT_ROWS if g.tag_column is not None else HINT_NO_TAGS)
        if remember:
            st = self.app.ctx.settings
            if st.glossary_recent[:1] != [str(g.id)]:
                st.glossary_recent = glossaries.remember(st.glossary_recent, g.id)
                try:
                    st.save(self.app.ctx.fs, self.app.ctx.data_root)
                except OSError as e:
                    log.warning("glossary lookup: settings not saved (%s)", type(e).__name__)
        self.refill()

    # ---- what it lists ----
    def refill(self) -> None:
        typed = self.search.text().strip()
        if self.glossary is None:
            self._list_glossaries(typed)
        else:
            self._list_rows(self.glossary, typed)

    def _list_glossaries(self, typed: str) -> None:
        self.title.setText("Glossary lookup")
        words = glossaries.words_of(typed)
        shown = [g for g in self.listed if all(w in glossaries.fold(g.name) for w in words)]
        options: list[Row] = [items.Option(g.name, g.name, f"{g.rows:,} rows", ref=f"{_G}{g.id}") for g in shown]
        empty = NONE_YET if not self.listed else f"No glossary's name has “{typed}”."
        self.list.show_rows(options or [Words(empty, heading=False)])

    def _list_rows(self, g: Glossary, typed: str) -> None:
        conn = self.app.ctx.conn
        found, total = glossaries.lookup(conn, g, typed)
        self.found = {f"{_R}{f.pos}": f for f in found}
        self._count(g)
        of = f"{len(found)} of {total:,}" if total > len(found) else f"{total:,}"
        self.title.setText(f"{g.name} · {of} row{'s' * (total != 1)}" if typed else f"{g.name} · {g.rows:,} rows")
        options: list[Row] = []
        for ref, f in self.found.items():
            words = " · ".join(t for t, _bold in glossaries.shown_cells(g, f.cells))
            options.append(items.Option(glossaries.tag_of(g, f.cells), words, ref=ref))
        empty = f"No row of {g.name} has every word of “{typed}”." if typed else f"{g.name} has no rows."
        self.list.show_rows(options or [Words(empty, heading=False)])

    def _count(self, g: Glossary) -> None:
        """Each listed row's tagged label and its count of places (decision 807), for the rows listed only."""
        self.labels, self.places = {}, {}
        if g.tag_column is None or not self.found:
            return
        m = self.app.ctx.model()
        for ref, f in self.found.items():
            key = tagged.key_of(glossaries.tag_of(g, f.cells))
            lb = m.tagged.by_key.get(key) if key else None
            if lb is not None:
                self.labels[ref] = lb
        if not self.labels:
            return
        if self._hits is None or self._hits[0] != id(m):
            self._hits = (id(m), glossaries.task_hits(m))
        for ref, lb in self.labels.items():
            self.places[ref] = glossaries.places_of(m, lb, self._hits[1])

    def parts(self, o: Row) -> tuple[list[tuple[str, str]], str]:
        """A row's parts, each (text, kind: "bold", "text", "dot" or "grey"), and its grey words at the right end."""
        ref = getattr(o, "ref", None) or ""
        if ref.startswith(_G):
            g = next((x for x in self.listed if f"{_G}{x.id}" == ref), None)
            if g is None:
                return [(o.label, "text")], ""
            tag = f" · tags in {g.tag_name}" if g.tag_name else ""
            return [(g.name, "text"), ("   ", "dot"), (f"{len(g.columns)} columns{tag}", "grey")], f"{g.rows:,} rows"
        f = self.found.get(ref)
        if f is None or self.glossary is None:
            return [(o.label, "text")], ""
        out: list[tuple[str, str]] = []
        for n, (t, bold) in enumerate(glossaries.shown_cells(self.glossary, f.cells)):
            if n:
                out.append((LookupDelegate.DOT, "dot"))
            out.append((t, "bold" if bold else "text"))
        n = self.places.get(ref)
        return out, (f"in {n} place{'s' * (n != 1)}" if n is not None else "")

    # ---- keys and picks ----
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt's name
        """The box keeps the keyboard. Up and Down move in the list; Enter and Tab open a glossary, then Enter copies a row's
        tag, Ctrl+Enter opens its page and Ctrl+C copies the row; Backspace in an empty box goes back; Esc closes."""
        if watched is self.search and event.type() == QEvent.Type.KeyPress:
            key, mods = event.key(), event.modifiers()
            ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
            if key == Qt.Key.Key_Escape:
                self.close()
                return True
            if key == Qt.Key.Key_Backspace and not self.search.text() and self.glossary is not None and len(self.listed) > 1:
                self.back_to_list()
                return True
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                return self.list.handle_key(key)
            if self.glossary is None:
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
                    return self.list.handle_key(key)
            else:
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    o = self.list.current()
                    if o is not None:
                        (self.open_page if ctrl else self.copy_tag)(o)
                    return True
                if key == Qt.Key.Key_Tab:
                    return True  # the box keeps the keyboard
                if ctrl and key == Qt.Key.Key_C and not self.search.hasSelectedText():
                    o = self.list.current()
                    if o is not None:
                        self.copy_row(o)
                    return True
        return super().eventFilter(watched, event)

    def _picked(self, o: Row) -> None:
        ref = getattr(o, "ref", None) or ""
        if ref.startswith(_G):
            g = next((x for x in self.listed if f"{_G}{x.id}" == ref), None)
            if g is not None:
                self.open_glossary(g)
        elif ref.startswith(_R):
            self.copy_tag(o)

    def copy_tag(self, o: Row) -> None:
        """Enter: the row's tag on the clipboard, and closed (decision 807)."""
        f = self.found.get(getattr(o, "ref", None) or "")
        if f is None or self.glossary is None:
            return
        QGuiApplication.clipboard().setText(glossaries.tag_of(self.glossary, f.cells))
        self._close_after(False)

    def copy_row(self, o: Row) -> None:
        """Ctrl+C: the whole row, tab-separated, on the clipboard, and closed."""
        f = self.found.get(getattr(o, "ref", None) or "")
        if f is None:
            return
        QGuiApplication.clipboard().setText(glossaries.row_text(f.cells))
        self._close_after(False)

    def open_page(self, o: Row) -> None:
        """Ctrl+Enter: the tag's tagged label page in the browse tool; a tag not on the tag list says so and stays."""
        ref = getattr(o, "ref", None) or ""
        lb = self.labels.get(ref)
        if lb is None:
            f = self.found.get(ref)
            tag = glossaries.tag_of(self.glossary, f.cells) if f is not None and self.glossary is not None else ""
            self.note.setText(f"{tag} isn't on the tag list, so it has no page." if tag else "This row has no tag, so it has no page.")
            return
        self._close_after(True)
        browse = self.app.browse
        browse.view = "tagged"
        browse.select("tagged", lb.key, update_list=True)
        self.app.show_browse()

    def _close_after(self, opened: bool) -> None:
        self.done(opened)
        self.close()


class GlossaryLookup(QWidget):
    """The host window, and the popup that opens from it, as Recent captures has them: a popup opened from no window can't
    take the keyboard."""

    def __init__(self, app: CaptureApp) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.app = app
        self.setFixedSize(1, 1)
        self.setObjectName("capture")
        self.setStyleSheet(style_sheet())
        self.popup = GlossaryPopup(self, app, self._done)
        self.popup.installEventFilter(self)
        self._opened = False

    def open_it(self, screen) -> None:
        """At the centre of ``screen``, a sixth of the way down, as Recent captures opens."""
        self._opened = False
        area = screen.availableGeometry()
        at = QPoint(area.x() + (area.width() - WIDTH) // 2, area.y() + area.height() // 6)
        self.move(at)
        self.show()
        self.raise_()
        self.activateWindow()
        self.popup.popup(at)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt's name
        if watched is self.popup and event.type() == QEvent.Type.Hide:
            QTimer.singleShot(0, self._hidden)
        return super().eventFilter(watched, event)

    def _hidden(self) -> None:
        """Just after the popup closes: unless it opened the browse tool, the keyboard goes back to the window you were in,
        where a copied tag is pasted."""
        if not self._opened:
            self.app.wheels.give_back()
        self.hide()

    def _done(self, opened: bool) -> None:
        self._opened = opened
