# DocRepo specification

This file describes what DocRepo does and how it's built. It grows phase by phase (see `PROGRESS.md`): sections for finished phases are complete, and later ones are summaries. The hard rules are in `.github/copilot-instructions.md` and apply to everything here.

## 1. What DocRepo is

A Windows desktop tool for someone who manages many projects at once. Information arrives all day as emails, quick notes and documents, many of them on a shared LAN drive. DocRepo lets its owner capture any of it in seconds and organize it as a tree of tasks, where projects are the top-level tasks.

- **Capture app:** runs in the background with a tray icon. A global hotkey opens a small capture window.
- **Browse tool:** a separate window for the task tree, lists, agendas, capacity, people, labels, documents, search and settings.
- **Capture first.** Every capture is saved at once, with no AI involved. DocRepo never calls an AI. Its Copy prompt button builds a prompt for the owner to paste into an AI chat, and the answer is pasted back as text.

## 2. How it's built and installed

- Developed on the owner's personal computer, in Python 3.12 with PySide6, and published to a private GitHub repo.
- On the corporate computer, the owner downloads the repo, makes a `.venv` and runs `pip install -r requirements.txt`. That computer's pip settings fetch the packages from the company's package repository. DocRepo's code never refers to it.
- No packaging into an .exe. DocRepo runs as `python -m docrepo` from its folder.
- `README.md` has the steps for installing and updating.

## 3. Data root and settings (phase 1, built)

### Where the data root is
DocRepo keeps all its data in one folder, the **data root**, on the local drive. It must not be inside a OneDrive folder, and for real use it must be outside DocRepo's code folder, so updates never touch it.

DocRepo picks the data root from, in order:
1. `--data-root PATH` on the command line (for development and tests);
2. the `DOCREPO_DATA_ROOT` environment variable;
3. `%LOCALAPPDATA%\DocRepo\location.json`, which holds `{"data_root": "<path>"}` and is written by `set-data-root` (later, by the Settings view).

### Folders
`init` creates `Captures`, `Tasks`, `Documents`, `Mods`, `Config\prompts` and `System\logs` in the data root, plus `Config\settings.json`. Other folders, such as a task's `Files`, appear only when needed.

### settings.json

| Field | Meaning | Default |
|---|---|---|
| `schema_version` | Format version of this file | 1 |
| `me` | The owner's person ID, such as `P001` | none |
| `hotkey` | The capture window's hotkey | Ctrl+Shift+Space |
| `backup_dir` | The backup folder | none |
| `doc_check_minutes` | How often tracked documents are checked for changes | 60 |
| `extracted_text_cap_chars` | Most text kept per extracted file | 200000 |
| `prompt_warn_chars` | Copy prompt warns above this length | 60000 |
| `capacity_horizon_years` | How far ahead routine tasks fill the capacity calendar | 5 |
| `workdays` | Days the capacity calendar spreads hours over | Mon to Fri |

A missing file gives the defaults. An unreadable file stops DocRepo with an error; it's never overwritten silently. Unknown fields are ignored with a warning in the log.

## 4. Guarded writes (phase 1, built)

`docrepo/safe_fs.py` is the only code that writes, copies or moves files, or creates folders.

- **Allowed places:** the data root, the backup folder (if set) and `%LOCALAPPDATA%\DocRepo\`.
- **Checks on every path:** it must be a full path with a drive or a `\\server\share`. Device paths (`\\?\`, `\\.\`), alternate data streams, names ending in a dot or space, characters Windows forbids and reserved device names (CON, NUL, COM1 and so on) are refused. The path is then resolved through `..`, symlinks and junctions, and must land inside an allowed place.
- **Writing:** `write_text` writes only `.md`, `.json`, `.txt` and `.log` files, as UTF-8, atomically (a temporary file in the same folder replaces the target).
- **Copying:** `copy_file` copies a file the owner asked to keep. It only reads the source, and never overwrites.
- **Moving:** `move` moves only from one allowed place to another, and never overwrites.
- **No delete function.** Every refusal is logged.
- Code that writes on its own (SQLite, the log, Outlook's SaveAs) gets its path from `checked_path` first.

## 5. Command line (phase 1, built)

`python -m docrepo [--data-root PATH] COMMAND`

| Command | What it does |
|---|---|
| `where` | Shows the data root, what chose it, and whether it's set up. |
| `set-data-root PATH` | Records the data root in `location.json`, after checking it isn't in OneDrive or the code folder. |
| `init` | Creates the data root's folders and default settings, and starts the log. |
| `try-write PATH` | Writes a small test file at PATH if DocRepo is allowed to, to check the guard. |

DocRepo's log is `System\logs\docrepo.log` in the data root, rotated at 1 MB with 5 old files kept. It records IDs, file names and actions, never captured content.

## 6. Later phases (summaries)

These are designed in detail in the owner's design notes, and move into this file as each phase is built.

- **Data model (phase 2):** SQLite (`System\docs.db`) is the source of truth. Tasks form a tree in which a task may have more than one parent. Tasks have states (Not started, In progress, Parked, Closed), dates (start, reminder, due, deadline, recurrence), leads and assignees with hours, labels (inherited from parents), and logs (raw notes, summaries, status changes). A capacity calendar spreads each person's hours over workdays. Each task gets a generated `Tasks\<id>\Task.md`, and the data root a generated `Contents.md`.
- **Capture app (phase 3):** tray icon, global hotkey, and a capture window with a task picker, New subtask and Update task, Parse and populate, Copy prompt, and a **?** button for the mods log. Captures are saved straight to `Captures\YYYY\MM\<id>\`, with text extracted from attached files and Outlook emails.
- **Browse tool (phase 4):** the task tree, lists, agendas, capacity, people, labels, documents, search, and Settings for the paths and other settings.
- **First everyday version (phase 5):** Startup shortcut, daily backups, and a one-time import of the project list from Excel.
- **Document tracking (phase 6):** change checks on tracked files, diffs, replaced filed copies, and relinking moved files.
