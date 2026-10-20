"""The troubleshooting report: what DocRepo can tell about itself, Outlook and its recent problems.

The owner carries the report to the personal computer, where DocRepo is fixed,
so it holds versions, steps, counts and error codes, never captured content:
no email text, subjects, names or addresses. Paths are shortened (the data root,
the user's folder, server names) and email addresses are taken out. The
report is made by ``outlook-check`` on the command line and by Troubleshooting
report in the browse tool's Settings, and saved in ``System\\diagnostics``.
"""
from __future__ import annotations

import ctypes
import importlib.metadata
import logging
import os
import platform
import re
import struct
import sys
import traceback
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import TracebackType

from docrepo import __version__, outlook
from docrepo.safe_fs import SafeFS

log = logging.getLogger(__name__)

REPORT_DIR = Path("System") / "diagnostics"
LOG_DAYS = 7
LOG_LINES = 60
TRACEBACK_LINES = 15

#: Outlook's item classes (OlObjectClass), for the report's "kind of item".
ITEM_CLASSES = {43: "email", 26: "appointment", 53: "meeting request", 54: "meeting cancellation", 56: "meeting response",
                48: "task", 40: "contact", 46: "report (such as a delivery report)", 45: "post", 69: "distribution list"}

#: Outlook's programmatic access settings, read from the registry (read-only), and what their values mean.
SECURITY_VALUES = ("ObjectModelGuard", "PromptOOMAddressBookAccess", "PromptOOMAddressInformationAccess", "PromptOOMSaveAs",
                   "PromptOOMSend", "PromptOOMFormulaAccess", "PromptOOMMeetingTaskRequestResponse", "AdminSecurityMode",
                   "CheckAdminSettings")
GUARD_MEANING = {0: "warn when antivirus is off or out of date", 1: "always warn", 2: "never warn"}
PROMPT_MEANING = {0: "always refuse", 1: "ask", 2: "always allow", 3: "ask when antivirus is off or out of date"}


@dataclass(frozen=True)
class DragNote:
    """A drag onto the capture window, or a paste into its content text: the formats it carried (their names only)
    and what DocRepo took it as."""

    at: str
    stage: str  # "enter", "drop" or "paste"
    formats: tuple[str, ...]
    urls: int
    local_files: int
    taken_as: str  # files, outlook, virtual, or "" when DocRepo left it to the text box


#: This session's drags onto the capture window and pastes into it, newest last.
DRAGS: deque[DragNote] = deque(maxlen=12)
#: This session's uncaught errors, newest last: (when, what).
UNCAUGHT: deque[tuple[str, str]] = deque(maxlen=10)


def note_drag(stage: str, formats: Sequence[str], urls: int, local_files: int, taken_as: str) -> None:
    DRAGS.append(DragNote(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), stage, tuple(formats), urls, local_files, taken_as))
    log.info("drag %s: %d formats, %d urls (%d local), taken as %s", stage, len(formats), urls, local_files, taken_as or "text")


def short_format(name: str) -> str:
    """A drag format's name: Qt names the Windows-only ones application/x-qt-windows-mime;value="…"."""
    m = re.fullmatch(r'application/x-qt-windows-mime;value="(.+)"', name)
    return f"{m.group(1)} (Windows)" if m else name


# ---- uncaught errors ----
def install_excepthook(notify: Callable[[str, str], None]) -> None:
    """Log errors nothing caught (under pythonw they'd vanish), keep them for the report, and say so once per kind."""
    told: set[str] = set()

    def hook(kind: type[BaseException], error: BaseException, tb: TracebackType | None) -> None:
        if issubclass(kind, KeyboardInterrupt):
            sys.__excepthook__(kind, error, tb)
            return
        log.error("uncaught %s", kind.__name__, exc_info=(kind, error, tb))
        where = traceback.extract_tb(tb)[-1] if tb else None
        UNCAUGHT.append((datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                         kind.__name__ + (f" in {Path(where.filename).name}, line {where.lineno} ({where.name})" if where else "")))
        if kind.__name__ not in told:
            told.add(kind.__name__)
            try:
                notify("DocRepo hit a problem", f"Something failed ({kind.__name__}). It's in DocRepo's log, and Settings → "
                                                "Troubleshooting report collects the details.")
            except Exception:  # noqa: BLE001 - the hook itself must never fail
                pass

    sys.excepthook = hook


# ---- what the report shows ----
def _version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def _is_admin() -> str:
    if os.name != "nt":
        return "not Windows"
    try:
        return "yes" if ctypes.windll.shell32.IsUserAnAdmin() else "no"
    except OSError:
        return "unknown"


def computer() -> list[tuple[str, str]]:
    exe = Path(sys.executable).name.lower()
    return [
        ("DocRepo", __version__),
        ("Python", f"{platform.python_version()}, {struct.calcsize('P') * 8}-bit, run with {exe}"),
        ("Windows", f"{platform.release()} (build {platform.version()})" if os.name == "nt" else platform.platform()),
        ("PySide6", _version("PySide6")),
        ("pywin32", _version("pywin32")),
        ("Running as administrator", "yes (so Windows blocks drags from Outlook and File Explorer into DocRepo)" if (admin := _is_admin()) == "yes" else admin),
        ("Outlook's main window", "open" if outlook.outlook_window_open() else "not found"),
    ]


@dataclass(frozen=True)
class Step:
    name: str
    ok: bool
    result: str


def _length(value: object) -> str:
    return f"{len(value)} characters" if isinstance(value, str) else "empty" if value is None else type(value).__name__


def outlook_check() -> tuple[list[Step], str]:
    """Each step DocRepo takes to read the selected email, and how it went. Also returns Outlook's version ("" if it
    wasn't reached). Values are described by their length or count only."""
    steps: list[Step] = []
    try:
        import win32com.client
    except ImportError as e:
        return [Step("Load pywin32", False, outlook.describe(e))], ""
    steps.append(Step("Load pywin32", True, f"pywin32 {_version('pywin32')}"))
    window = outlook.outlook_window_open()
    steps.append(Step("Find Outlook's main window", window, "found" if window else "not found: is classic Outlook open?"))
    app = None
    try:
        app = win32com.client.GetActiveObject("Outlook.Application")
        steps.append(Step("Find Outlook (GetActiveObject)", True, "ok"))
    except Exception as e:  # noqa: BLE001 - COM raises its own errors
        steps.append(Step("Find Outlook (GetActiveObject)", False, outlook.describe(e)))
        if window:
            try:
                app = win32com.client.Dispatch("Outlook.Application")
                steps.append(Step("Join Outlook (Dispatch)", True, "ok"))
            except Exception as e2:  # noqa: BLE001
                steps.append(Step("Join Outlook (Dispatch)", False, outlook.describe(e2)))
    if app is None:
        return steps, ""
    version = ""
    try:
        version = str(app.Version)
        steps.append(Step("Outlook's version", True, version))
    except Exception as e:  # noqa: BLE001
        steps.append(Step("Outlook's version", False, outlook.describe(e)))
    try:
        explorer = app.ActiveExplorer()
    except Exception as e:  # noqa: BLE001
        steps.append(Step("Outlook's main window (ActiveExplorer)", False, outlook.describe(e)))
        return steps, version
    if explorer is None:
        steps.append(Step("Outlook's main window (ActiveExplorer)", False, "none open"))
        return steps, version
    steps.append(Step("Outlook's main window (ActiveExplorer)", True, "ok"))
    try:
        selection = explorer.Selection
        count = selection.Count
        steps.append(Step("Outlook's selection", count > 0, f"{count} item(s) selected" if count else "nothing selected: select an email and run this again"))
        items = [selection.Item(n) for n in range(1, min(count, 3) + 1)]
    except Exception as e:  # noqa: BLE001
        steps.append(Step("Outlook's selection", False, outlook.describe(e)))
        return steps, version
    mail = None
    for n, item in enumerate(items, 1):
        try:
            cls = item.Class
            steps.append(Step(f"Selected item {n}: its kind", True, f"{cls} ({ITEM_CLASSES.get(cls, 'another kind')})"))
            if cls == outlook.OL_MAIL and mail is None:
                mail = item
        except Exception as e:  # noqa: BLE001
            steps.append(Step(f"Selected item {n}: its kind", False, outlook.describe(e)))
    if mail is None:
        return steps, version
    for name in ("Subject", "SenderName", "To", "SentOn", "ReceivedTime", "Body", "HTMLBody"):
        try:
            value = getattr(mail, name)
            steps.append(Step(f"Read the email's {name}", True, "ok" if name in ("SentOn", "ReceivedTime") else f"ok, {_length(value)}"))
        except Exception as e:  # noqa: BLE001
            steps.append(Step(f"Read the email's {name}", False, outlook.describe(e)))
    try:
        found = mail.Attachments
        files = hidden = other = 0
        for n in range(1, found.Count + 1):
            a = found.Item(n)
            if a.Type != outlook.OL_BY_VALUE:
                other += 1
            elif outlook.is_hidden(a):
                hidden += 1
            else:
                files += 1
        steps.append(Step("Read the email's attachments", True, f"{found.Count}: {files} files, {hidden} hidden (signature pictures), {other} other"))
    except Exception as e:  # noqa: BLE001
        steps.append(Step("Read the email's attachments", False, outlook.describe(e)))
    try:
        has_save = callable(getattr(mail, "SaveAs", None))
        steps.append(Step("SaveAs is there (used on Save)", has_save, "yes, not tried here, so no file is left behind" if has_save else "no"))
    except Exception as e:  # noqa: BLE001
        steps.append(Step("SaveAs is there (used on Save)", False, outlook.describe(e)))
    return steps, version


def security_settings(version: str) -> list[tuple[str, str]]:
    """Outlook's programmatic access settings from the registry, read-only. Only the values that are set are listed."""
    if os.name != "nt":
        return []
    import winreg

    major = ".".join(version.split(".")[:2]) if version else "16.0"
    out = []
    keys = [(rf"Software\Policies\Microsoft\Office\{major}\Outlook\Security", "policy"), (rf"Software\Microsoft\Office\{major}\Outlook\Security", "setting")]
    for hive_name, hive in (("HKCU", winreg.HKEY_CURRENT_USER), ("HKLM", winreg.HKEY_LOCAL_MACHINE)):
        for path, kind in keys:
            try:
                with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as key:
                    for name in SECURITY_VALUES:
                        try:
                            value, vtype = winreg.QueryValueEx(key, name)
                        except OSError:
                            continue
                        if vtype != winreg.REG_DWORD:
                            continue
                        meaning = GUARD_MEANING.get(value, "") if name == "ObjectModelGuard" else PROMPT_MEANING.get(value, "") if name.startswith("PromptOOM") else ""
                        out.append((f"{hive_name} {kind}: {name}", f"{value}" + (f" ({meaning})" if meaning else "")))
            except OSError:
                continue
    return out


def log_problems(data_root: Path, now: datetime, days: int = LOG_DAYS, limit: int = LOG_LINES) -> list[str]:
    """Warnings and errors from DocRepo's log in the last ``days``, with the start of each error's traceback, oldest first.
    The log is only read."""
    folder = data_root / "System" / "logs"
    files = sorted(folder.glob("docrepo.log*"), key=lambda p: p.stat().st_mtime) if folder.is_dir() else []
    since = now - timedelta(days=days)
    stamp = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ (\w+)\s")
    out: list[str] = []
    keep = False
    tb_lines = 0
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            m = stamp.match(line)
            if m:
                try:
                    when = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    keep = False
                    continue
                keep = when >= since and m.group(2) in ("WARNING", "ERROR", "CRITICAL")
                tb_lines = 0
                if keep:
                    out.append(line)
            elif keep and tb_lines < TRACEBACK_LINES:
                out.append(line)
                tb_lines += 1
    return out[-limit:]


def scrub(text: str, data_root: Path | None) -> str:
    """Shorten paths and take out what names a person or a computer: the data root, the user's folder, the user and
    computer names, servers and shares, and email addresses."""
    swaps = []
    if data_root is not None:
        swaps.append((str(data_root), "<data root>"))
    home = os.path.expanduser("~")
    if home and home != "~":
        swaps.append((home, "%USERPROFILE%"))
    for var, label in (("USERNAME", "<user>"), ("COMPUTERNAME", "<computer>"), ("USERDOMAIN", "<domain>")):
        value = os.environ.get(var, "")
        if len(value) >= 3:
            swaps.append((value, label))
    for old, new in swaps:
        text = re.sub(re.escape(old), new.replace("\\", "\\\\"), text, flags=re.IGNORECASE)
    text = re.sub(r"\\\\[\w.$-]+\\[\w.$ -]+", r"\\\\<server>\\<share>", text)
    return re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "<email address>", text)


def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def build_report(data_root: Path | None, now: datetime, drags: Sequence[DragNote] | None,
                 check_outlook: Callable[[], tuple[list[Step], str]] | None = None) -> str:
    """The report as Markdown. ``drags`` is None from the command line, where there's no capture window."""
    check_outlook = check_outlook or outlook_check
    lines = ["# DocRepo troubleshooting report", "",
             f"Made {now:%Y-%m-%d %H:%M}. To bring it to the personal computer, copy it (Copy report) or take the file from "
             "System\\diagnostics in the data root. It holds versions, steps, counts and error codes, not email text, names or "
             "addresses, and paths are shortened. Read it through before you send it on.", "",
             "## Computer", "", "| What | Value |", "|---|---|"]
    lines += [f"| {a} | {_cell(b)} |" for a, b in computer()]
    lines += ["", "## Outlook check", "",
              "Each step DocRepo takes to read the email selected in Outlook. Select an email in Outlook before making the report. "
              "If Outlook asks whether to allow access, answer as you would when adding an email.", "",
              "| Step | Result |", "|---|---|"]
    try:
        steps, version = check_outlook()
    except Exception as e:  # noqa: BLE001 - the report must still be made
        steps, version = [Step("The check itself", False, outlook.describe(e))], ""
    lines += [f"| {s.name} | {'ok' if s.ok else 'FAILED'}: {_cell(s.result)} |" for s in steps]
    settings = security_settings(version)
    lines += ["", "## Outlook's programmatic access settings", ""]
    lines += (["| Where | Value |", "|---|---|", *[f"| {a} | {_cell(b)} |" for a, b in settings]] if settings
              else ["None set in the registry, so Outlook's defaults apply (warn when antivirus is off or out of date)."])
    lines += ["", "## Drags and pastes in the capture window", ""]
    if drags is None:
        lines.append("Not available from the command line. Use Troubleshooting report in the browse tool's Settings, after dragging an "
                     "email onto the capture window or pasting into it.")
    elif not drags:
        lines.append("None yet since DocRepo started. Drag an email from Outlook onto the capture window, or paste into it, then make "
                     "the report again. If a drag never shows here, Windows didn't let it reach DocRepo.")
    else:
        lines += ["| When | Stage | Taken as | URLs (local files) | Formats |", "|---|---|---|---|---|"]
        lines += [f"| {d.at} | {d.stage} | {d.taken_as or 'text, or nothing'} | {d.urls} ({d.local_files}) | {_cell(', '.join(short_format(f) for f in d.formats)) or 'none'} |"
                  for d in drags]
    lines += ["", "## Outlook problems since DocRepo started", ""]
    lines += ([f"- {p.at} · {p.step}: {p.detail}" for p in outlook.PROBLEMS] if outlook.PROBLEMS
              else ["None." if drags is not None else "Not available from the command line (they're kept by the running app)."])
    if UNCAUGHT:
        lines += ["", "## Errors nothing caught since DocRepo started", "", *[f"- {at} · {what}" for at, what in UNCAUGHT]]
    lines += ["", f"## DocRepo's log: warnings and errors in the last {LOG_DAYS} days", ""]
    found = log_problems(data_root, now) if data_root is not None else []
    lines += (["```", *found, "```"] if found else ["None."])
    return scrub("\n".join(lines) + "\n", data_root)


def save_report(fs: SafeFS, data_root: Path, text: str, now: datetime) -> Path:
    """Save the report as System\\diagnostics\\troubleshooting YYYY-MM-DD HHMM.md, never over an earlier one."""
    folder = data_root / REPORT_DIR
    name = f"troubleshooting {now:%Y-%m-%d %H%M}"
    path, n = folder / f"{name}.md", 2
    while path.exists():
        path, n = folder / f"{name} ({n}).md", n + 1
    return fs.write_text(path, text)
