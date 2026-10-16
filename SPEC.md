# DocRepo specification

This file describes what DocRepo does and how it's built. It grows phase by phase (see `PROGRESS.md`): sections for finished phases are complete, and later ones are summaries. The hard rules are in `.github/copilot-instructions.md` and apply to everything here.

## 1. What DocRepo is

A Windows desktop tool for someone who manages many projects at once. Information arrives all day as emails, quick notes and documents, many of them on a shared LAN drive. DocRepo lets its owner capture any of it in seconds and organize it as a tree of tasks, where projects are the top-level tasks.

- **Capture app:** runs in the background with a tray icon. A global hotkey opens a small capture window.
- **Browse tool:** a separate window for the task tree, lists, agendas, capacity, people, labels, documents, search and settings.
- **Capture first.** Every capture is saved at once, with no AI involved. DocRepo never calls an AI. Its Copy prompt button builds a prompt for the owner to paste into an AI chat, and the answer is pasted back as text.

## 2. How it's built and installed

- Developed on the owner's personal computer, in Python 3.12 with PySide6, and published to a public GitHub repo, https://github.com/eckertco2/DocRepo.
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
`init` creates `Captures`, `Tasks`, `Documents`, `Mods`, `Config\prompts` and `System\logs` in the data root, plus `Config\settings.json` and the database, `System\docs.db`. Other folders, such as a task's `Files`, appear only when needed.

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
| `init` | Creates the data root's folders, default settings and database, and starts the log. |
| `try-write PATH` | Writes a small test file at PATH if DocRepo is allowed to, to check the guard. |
| `load-sample [--as-of WHEN]` | Fills a new, empty data root with the made-up sample data (section 6.10). Refuses a database that holds anything. |
| `rebuild [--as-of WHEN]` | Rebuilds the capacity calendar and every generated page from `docs.db`. |
| `report [--as-of WHEN] [--week DATE]` | Prints what DocRepo works out: capacity for 9 weeks, days until due, the lists, labels and parent chains, raw text logs and agendas. |

`--as-of` takes `YYYY-MM-DD` or `"YYYY-MM-DD HH:MM"` and makes the command work as if it were then. It's for testing.

DocRepo's log is `System\logs\docrepo.log` in the data root, rotated at 1 MB with 5 old files kept. It records IDs, file names and actions, never captured content.

## 6. Data model (phase 2, built)

The words used here are defined in `GLOSSARY.md`.

### 6.1 The database
- `System\docs.db`, SQLite, is the source of truth. Folders never encode the task tree: task folders are named by ID only, and nothing moves when a task is renamed or gets another parent.
- `docrepo/db.py` creates the schema and keeps its version in SQLite's `user_version` (now 1). A database from a newer DocRepo, or one that isn't DocRepo's, is refused rather than changed.
- Foreign keys are on. Every change runs inside one transaction, so a save happens completely or not at all.
- The tables:

| Table | Holds |
|---|---|
| `tasks` | Each task's fields (6.3). |
| `task_parents` | Parent links, oldest first. A task can have several parents. |
| `task_people` | Each task's leads and assignees, in order. |
| `task_labels` | Each task's own labels. |
| `people`, `person_aliases` | The people list (6.4). |
| `labels`, `label_keywords` | Labels and the keywords Parse and populate looks for. |
| `status_log` | Field changes (6.6). |
| `captures` | Each capture: when it was saved, its source, capture types, picked task, created task, filing, title, summary. Its content text is in its `capture.md`. |
| `documents`, `capture_documents`, `capture_attachments` | Documents (tracked originals and email attachments), and each capture's files with their Save a copy and Extract information choices. |
| `document_versions` | Changes found in tracked originals, with any pasted summary. |
| `saved_copies` | Copies in a task's `Files` folder, and replaced ones in `_old versions`. |
| `agenda_items` | Agenda items (6.7). |
| `work_calendar` | The capacity calendar (6.8). |
| `id_counters` | The last ID handed out of each kind. |

### 6.2 IDs
- Tasks `T000001`, captures `C000001`, documents `D000001`, people `P001`. Mods log entries are `M0001` (phase 3).
- IDs count up and are never reused, even if a record were removed.

### 6.3 Tasks
- **Fields:** title, state, current status, description, start, due, deadline and its description, reminder, recurrence and repeat until, urgent, meeting, leads and assignees, lead hours and assignee hours, labels, inherit parent labels (on by default), created (the day) and created by (the capture that created it, or "Excel import").
- **States:** Not started, In progress, Parked, Closed. Closed means done or cancelled. Closing records the day it closed; reopening clears it. Open means Not started or In progress.
- **Start** defaults to the day the task was created.
- **Recurrence:** Daily, Weekly, Bi-weekly, Monthly, Quarterly or Yearly. A task with one is a routine task. Repeat until can be set only with a recurrence, and clearing the recurrence clears it. Closing a routine task ends the recurrence.
- **Hours** are per person in the role: a total for a one-time task, per occurrence for a routine one. Every lead gets the full lead hours and every assignee the full assignee hours; someone in both roles gets both.
- **The tree:** a task with no parent is a top-level task (a project). A task can have several parents and shows under each. A link that would put a task under itself is refused. Ancestors are every chain upward, without repeats; a chain runs from a top-level task down to the task.
- **Scopes:** this task, with ancestors, with subtasks (descendants), and family (ancestors and descendants).
- **Labels:** a task's own labels come first, then every parent's labels (their own and inherited), unless the task's inherit switch is off.
- `docrepo/tasks.py` creates and changes tasks. Each change goes into the status log, and the task's capacity calendar rows are rebuilt in the same transaction.

### 6.4 People and labels
- Each person has a name, aliases, hours a week (or not set) and a status, active or retired. Task roles and the calendar store the ID, so renaming someone changes nothing else. One person is me: `me` in `settings.json`.
- Labels have a name (unique, any case), keywords (the name, if none are given) and a status. Renaming a label keeps it on its tasks.
- Retired people and labels are hidden from pickers and lists, never deleted.

### 6.5 Captures and documents
- A capture belongs to the task it created; to the task it picked, unless it only made a subtask there (New task without Update); and to the task it was filed to. A capture with no task and no agenda item is unfiled, and waits in the Unfiled view.
- A capture is listed by an email's subject, or else the first sentence of its content text (without email header lines and file path lines, cut at 100 characters), or else its first file's name. Full stops after abbreviations such as "Dr." and "Oct. 19" don't end a sentence.
- A document belongs to the tasks of the captures it came in with, and to the tasks it has saved copies in. Its document versions join the raw text log of each of those tasks.
- `capture.md`: front matter whose values are JSON (also valid YAML), then the content text, then a "Summary" section if a summary was pasted. The fields, in order: `id`, `saved`, `source` (typed, outlook_email or file_path), `task` (the picked task, else the task it was filed to, else null), `capture_types` (note, new_task, update), `filed`, `edited`, `created_task`, `changes` (field, from, to), `agenda` (subject and target of each item it added), `documents` (id, name, original, description, save_a_copy, extract) and `summary_type`. `filed`, `edited`, `created_task`, `changes` and `agenda` appear only when they apply.
- Phase 2 provides these records and the file format. Saving captures comes in phase 3.

### 6.6 The logs
- **Status log:** each field change, with when, the field, its old and new values as shown, and where it came from (a capture's ID, or "Browse tool", "Capture window", "Agenda view", "Reminders list"). Agenda items add their own entries: "Agenda: None → *target*" when one is added and "Agenda: *target* → Discussed" (or Removed) when it's closed.
- **Raw text log:** the task's captures and its documents' versions, oldest first.
- **Summary log:** pasted summaries from the task's captures and from its documents' versions.
- **Files:** the task's saved copies (and replaced ones), then the documents of its captures: tracked originals and email attachments.

### 6.7 Agenda items
- An agenda item puts a task (its subject), or a note with no task, on the agenda of a target: a meeting, another task or a person. A task can't be on its own agenda.
- It stays open, carrying over, until it's closed by hand as Discussed or Removed. Closing an item never closes its task.
- A target's agenda is its open items. The agenda targets are the open meetings (tasks with Meeting checked), then any other task or person with open items.

### 6.8 Dates, lists and the capacity calendar
- **Windows:** a one-time task works from Start to Due, or to Deadline if there's no Due; with neither, it's unscheduled. A routine task's first window runs from Start to Due, or is just the Start day, and repeats every interval until Repeat until, the horizon (`capacity_horizon_years` from today) or the day it closed. Monthly, quarterly and yearly repeats keep the day of the month, or use the month's last day; 29 February becomes 28 February.
- **Days until due** uses Due, else Deadline. A routine task counts to the end of its next occurrence. Closed tasks have none.
- **Lists** (open tasks only, soonest first): Overdue and next 7 days (not routine tasks), Reminders (a reminder in the next 7 days or past), Waiting on others (assignees, none of them me), Assigned to me, Urgent, and No dates or hours (people, but no hours, or hours but no Due or Deadline on a one-time task).
- **The capacity calendar** (`work_calendar`) has a row per person, day and task. For each window and person, the hours are spread evenly over the window's workdays (`workdays` in settings, Monday to Friday by default); a window with no workdays spreads over its calendar days. Parked tasks and tasks with no hours have no rows, and a closed task has none after its close date. Not started tasks count.
- It's a cache: rebuilt for a task whenever that task is saved, for everything by `rebuild`, and (from phase 3) for all routine tasks at the first start each day, so the horizon rolls forward. It always shows the current plan, past weeks included.
- **Unestimated** tasks have people but no hours; **unscheduled** ones have hours but no dates. Both are open tasks the calendar can't place.

### 6.9 Generated pages
- Every task gets `Tasks\<id>\Task.md`, and the data root `Contents.md`. They're one-way printouts for reading in VS Code's Markdown preview or from a backup; DocRepo never reads them back. Links are relative.
- `Task.md`: the title, a note that the page is generated, and a field table (ID, state, then urgent, meeting and recurrence when set, parents, labels with inherited ones marked, lead and assignees with hours, start, due with days until due, deadline, then reminder and the agendas it's on when set). Then Description, Current status, Subtasks, Agenda (for a target with open items, or an open meeting), Status log (newest first), Summary log, Raw text log and Files.
- `Contents.md`: open tasks as an indented tree, a task with two parents shown under each and marked "also under", then Parked, Closed in the last 30 days, Agendas, Unfiled, People and Labels.
- A page is rewritten only when more than its "Generated from docs.db on" line would change.
- The exact formats are those of the browse tool mockup's examples, kept in `tests/fixtures/examples.md`.

### 6.10 Sample data and tests
- `docrepo/sample/sample-data.json` is the browse tool mockup's made-up sample data, as of Thursday 2026-10-08 07:58. `load-sample` loads it with its IDs, writes its `capture.md` and `extracted.txt` files (not its emails, attachments or saved copies, which are binary), and builds the calendar and pages as of that moment.
- `tests/fixtures/examples.md` and `tests/fixtures/test-vectors.md` are the mockup's expected results for that data. The tests check every generated page, every `capture.md` example, and the report's capacity, days until due, lists, labels and chains, raw text logs and agendas against them, line for line.

## 7. Later phases (summaries)

These are designed in detail in the owner's design notes, and move into this file as each phase is built.

- **Capture app (phase 3):** tray icon, global hotkey, and a capture window with a task picker, the capture types (Note, New task and Update), Parse and populate, Copy prompt, and a **?** button for the mods log. Captures are saved straight to `Captures\YYYY\MM\<id>\`, with text extracted from added files and Outlook emails.
- **Browse tool (phase 4):** the task tree, lists, agendas, capacity, people, labels, documents, search, and Settings for the paths and other settings.
- **First everyday version (phase 5):** Startup shortcut, daily backups, and a one-time import of the project list from Excel.
- **Document tracking (phase 6):** change checks on tracked files, diffs, replaced saved copies, and relinking moved files.
