# DocRepo specification

This file describes what DocRepo does and how it's built. It grows phase by phase (see `PROGRESS.md`): sections for finished phases are complete, and later ones are summaries. The hard rules are in `.github/copilot-instructions.md` and apply to everything here.

## 1. What DocRepo is

A Windows desktop tool for someone who manages many projects at once. Information arrives all day as emails, quick notes and documents, many of them on a shared LAN drive. DocRepo lets its owner capture any of it in seconds and organize it as a tree of tasks, where projects are the top-level tasks.

- **Capture app:** runs in the background with a tray icon. A global hotkey opens a small capture window.
- **Browse tool:** a separate window for the task tree, lists, agendas, capacity, people, labels, documents, search and settings (section 8).
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
3. `%LOCALAPPDATA%\DocRepo\location.json`, which holds `{"data_root": "<path>"}` and is written by `set-data-root` or the browse tool's Settings view (8.9).

### Folders
`init` creates `Captures`, `Tasks`, `Documents`, `Mods`, `Config\prompts` and `System\logs` in the data root, plus `Config\settings.json` and the database, `System\docs.db`. Other folders, such as a task's `Files`, appear only when needed.

### settings.json

| Field | Meaning | Default |
|---|---|---|
| `schema_version` | Format version of this file | 1 |
| `me` | The owner's person ID, such as `P001` | none |
| `hotkey` | The capture window's hotkey | Ctrl+Shift+Space |
| `browse_hotkey`, `note_hotkey`, `new_task_hotkey`, `update_hotkey`, `agenda_hotkey` | More hotkeys (7.1): the browse tool, each capture type, and Add to agenda | empty, so off |
| `backup_dir` | The backup folder | none |
| `backup_every_days` | How often a backup is made, in days (9.1) | 7 |
| `backup_keep` | How many copies of docs.db the backup folder keeps | 8 |
| `doc_check_minutes` | How often tracked documents are checked for changes | 60 |
| `reminder_time` | When each day's reminders are shown | 08:00 |
| `extracted_text_cap_chars` | Most text kept per extracted file | 200000 |
| `prompt_warn_chars` | Copy prompt warns above this length | 60000 |
| `capacity_horizon_years` | How far ahead routine tasks fill the capacity calendar | 5 |
| `workdays` | Days the capacity calendar spreads hours over | Mon to Fri |
| `event_words` | Words Parse and populate reads as events, for deadlines | turnaround, shutdown, audit, inspection, outage, walkthrough |

A missing file gives the defaults. An unreadable file stops DocRepo with an error; it's never overwritten silently. Unknown fields are ignored with a warning in the log.

## 4. Guarded writes (phase 1, built)

`docrepo/safe_fs.py` is the only code that writes, copies or moves files, or creates folders.

- **Allowed places:** the data root, the backup folder (if set) and `%LOCALAPPDATA%\DocRepo\`.
- **Checks on every path:** it must be a full path with a drive or a `\\server\share`. Device paths (`\\?\`, `\\.\`), alternate data streams, names ending in a dot or space, characters Windows forbids and reserved device names (CON, NUL, COM1 and so on) are refused. The path is then resolved through `..`, symlinks and junctions, and must land inside an allowed place.
- **Writing:** `write_text` writes only `.md`, `.json`, `.txt` and `.log` files, as UTF-8, atomically (a temporary file in the same folder replaces the target).
- **Copying:** `copy_file` copies a file the owner asked to keep. It only reads the source, and never overwrites.
- **Moving:** `move` moves only from one allowed place to another, and never overwrites.
- **Replacing:** `replace_file` (copy over) and `replace` (move over) work only inside a SafeFS's replace roots. `make_safe_fs` makes the backup folder the only one, and none when the backup folder is inside the data root or holds it, so a backup can bring its copies up to date (9.1) while nothing in the data root is ever overwritten by a copy.
- **The Startup shortcut:** `DocRepo.lnk` in `%LOCALAPPDATA%\DocRepo\` is written by Windows' shell, to a path `checked_path` allows (9.2).
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
| `rebuild [--as-of WHEN]` | Rebuilds the capacity calendar and every generated page from `docs.db`, and the search index from the capture and document files. |
| `report [--as-of WHEN] [--week DATE]` | Prints what DocRepo works out: capacity for 9 weeks, days until due, the lists, labels and parent chains, raw text logs and agendas. |
| `app` | Starts the capture app (section 7). Use `pythonw` instead of `python` for no console window. |
| `browse` | Opens the browse tool (section 8), starting the app first if it isn't running. |
| `backup` | Makes a backup now (9.1). |
| `make-shortcut` | Makes `DocRepo.lnk`, the Startup shortcut, in `%LOCALAPPDATA%\DocRepo\`, and says where to move it (9.2). |
| `set-hotkey KEYS` | Sets the capture window's hotkey, such as `"Ctrl+Alt+Space"`. It needs Ctrl, Alt or Win. Takes effect when the app next starts. The browse tool's Settings view does the same, at once. |
| `outlook-check` (or `troubleshoot`) | Makes the troubleshooting report (9.4), without the capture window's drags and pastes, prints it and saves it in `System\diagnostics`. |

`--as-of` takes `YYYY-MM-DD` or `"YYYY-MM-DD HH:MM"` and makes the command work as if it were then. It's for testing.

DocRepo's log is `System\logs\docrepo.log` in the data root, rotated at 1 MB with 5 old files kept. It records IDs, file names and actions, never captured content. The app logs any error nothing caught, with its traceback, and says so once in a notification (under `pythonw` it would otherwise vanish).

## 6. Data model (phase 2, built)

The words used here are defined in `GLOSSARY.md`.

### 6.1 The database
- `System\docs.db`, SQLite, is the source of truth. Folders never encode the task tree: task folders are named by ID only, and nothing moves when a task is renamed or gets another parent.
- `docrepo/db.py` creates the schema and keeps its version in SQLite's `user_version` (now 5). An older DocRepo database is brought up to date when it's opened (version 2, phase 3: each document's text status, size, modified time and checksum, plus `app_state` and `reminders_shown`; version 3, phase 4: the search index, `search_text`; version 4, release 5.3: `discarded` and `discard_reason` on tasks and captures, and `agenda_items` made again, keeping its rows, so an item can close as Done; version 5, release 5.4: `email_layer_0` on captures). A database from a newer DocRepo, or one that isn't DocRepo's, is refused rather than changed.
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
| `search_text` | The search index: each capture's and document's text (8.8). A cache, rebuilt by `rebuild`. |

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
- **Discarded** (release 5.3, M0021): a task made by mistake can be discarded, with a reason. It keeps its state and everything else, but it's hidden from the task tree, the lists, the counts, the pickers, search, the capacity calendar and `Contents.md`, and kept in the browse tool's Discarded view. Bringing it back clears `discarded` and `discard_reason`. Both go into the status log as "Discarded" (the reason, or None when it's brought back). Nothing is deleted.
- `docrepo/tasks.py` creates and changes tasks. Each change goes into the status log, and the task's capacity calendar rows are rebuilt in the same transaction.

### 6.4 People and labels
- Each person has a name, aliases, hours a week (or not set) and a status, active or retired. Task roles and the calendar store the ID, so renaming someone changes nothing else. One person is me: `me` in `settings.json`.
- Labels have a name (unique, any case), keywords (the name, if none are given) and a status. Renaming a label keeps it on its tasks.
- Retired people and labels are hidden from pickers and lists, never deleted.

### 6.5 Captures and documents
- A capture belongs to the task it created; to the task it picked, unless it only made a subtask there (New task without Update); and to the task it was filed to. A capture with no task and no agenda item is unfiled, and waits in the Unfiled view.
- A capture is listed by an email's subject, or else the first sentence of its content text (without email header lines and file path lines, cut at 100 characters), or else its first file's name. Full stops after abbreviations such as "Dr." and "Oct. 19" don't end a sentence.
- A document belongs to the tasks of the captures it came in with, and to the tasks it has saved copies in. Its document versions join the raw text log of each of those tasks.
- **A link** (release 5.4, M0001; `docrepo/links.py`) is a document whose original is a web or SharePoint address (http or https, no spaces), matched exactly rather than in any case. DocRepo keeps only the address: it never fetches a link, so a link has no extracted text (`text_status` none) and no saved copy, and it never opens one; Copy link puts it on the clipboard (round 1 plan, decision 5). It's listed by the file its address names (SharePoint's `file=`, else the path's last part, such as "Pump spec.docx"), else by its host. A capture whose only files are links is typed, not file_path.
- `capture.md`: front matter whose values are JSON (also valid YAML), then the content text, then a "Summary" section if a summary was pasted. The fields, in order: `id`, `saved`, `source` (typed, outlook_email or file_path), `task` (the picked task, else the task it was filed to, else null), `capture_types` (note, new_task, update), `filed`, `edited`, `created_task`, `changes` (field, from, to), `agenda` (subject and target of each item it added), `documents` (id, name, original, description, save_a_copy, extract), `email_layer_0` (release 5.4: what email layer 0 kept from an email and what it left out, 7.5) and `summary_type`. `filed`, `edited`, `created_task`, `changes`, `agenda` and `email_layer_0` appear only when they apply.
- **A discarded capture** (release 5.3, M0021) leaves its tasks' raw text logs, summaries and files, the Unfiled view and search, and is kept in the Discarded view. Its folder and `capture.md` aren't touched, and changes it made to tasks stay in their status logs. A document that came in only with discarded captures leaves the Documents view too.
- Phase 2 provides these records and the file format. Saving captures comes in phase 3.

### 6.6 The logs
- **Status log:** each field change, with when, the field, its old and new values as shown, and where it came from (a capture's ID, or "Browse tool", "Capture window", "Agenda view", "Reminders list", "Today"). In `Task.md` each entry stays on one line, so a value with line breaks, such as an edited description, is shown with spaces. Agenda items add their own entries: "Agenda: None → *target*" when one is added and "Agenda: *target* → Discussed" (or Removed) when it's closed.
- **Raw text log:** the task's captures and its documents' versions, oldest first.
- **Summary log:** pasted summaries from the task's captures and from its documents' versions.
- **Files:** the task's saved copies (and replaced ones), then the documents of its captures: tracked originals, links and email attachments. `Task.md` shows a link's address as code (`` - Link: name · `address` · D000042 ``), not as a link to follow.

### 6.7 Agenda items
- An agenda item puts a task (its subject), or a note with no task, on the agenda of a target: a meeting, another task or a person. A task can't be on its own agenda.
- It stays open, carrying over, until it's closed by hand as Discussed or Removed. Closing an item never closes its task.
- A target's agenda is its open items. The agenda targets are the open meetings (tasks with Meeting checked), then any other task or person with open items.
- **Today** (release 5.3, M0016) is a built-in target, stored as `today`: the owner's list for the day. Its items carry over until they're closed as Done (or Removed); other targets' items close as Discussed or Removed. A task is on Today at most once. The status log says "Added to Today.", "Done for today." and "Taken off Today.", and `Contents.md` lists Today first under Agendas, with "since" and the day an item carried over from. Today isn't one of the agenda targets above: it has a view of its own.

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

## 7. Capture app (phase 3, built)

### 7.1 Running it
- `pythonw -m docrepo app` (no console window) or `python -m docrepo app`. It runs in the background with a tray icon. Only one copy runs per data root (a lock file, `System\capture-app.lock`); starting it again shows the running copy's capture window.
- **Tray menu:** New capture, Open browse tool, Mods log, Pause hotkeys (or Resume hotkeys), Quit. Clicking the icon opens the capture window.
- **Hotkey:** `hotkey` in settings, Ctrl+Shift+Space by default, registered with Windows' own `RegisterHotKey` through ctypes. Nothing watches the keyboard. If another program has the hotkey, a notification says so and suggests `set-hotkey`; the tray icon still opens the window.
- **More hotkeys** (release 5.2, from the mods log's M0002, M0010 and M0020), each off until set in Settings: `browse_hotkey` opens the browse tool; `note_hotkey` and `new_task_hotkey` open the capture window with that capture type checked; `update_hotkey` checks Update on the draft's task, or, with no task picked, opens the task picker first and checks Update when a task is picked; `agenda_hotkey` does the same and puts the cursor in Add to agenda; `today_hotkey` (release 5.6, M0039) opens it on New task with Today on and the cursor in Title, for a quick task (7.4). Settings' **Use the suggested keys** (release 5.6, M0036) fills each empty box with Ctrl+Shift and the topic's letter (`hotkey.SUGGESTED`: B, N, T, U, A and D), the owner's choice; while DocRepo runs, a global hotkey is taken from every other program, such as Outlook's Ctrl+Shift+N. They're registered like the first, and a taken one is named in one notification. **Pause hotkeys** in the tray menu pauses them all. `docrepo/hotkey.py` lists them (`HOTKEYS`); each one's Windows ID is its place there.
- **First start:** DocRepo asks for the owner's name and adds them to the people list as me (`me` in settings), so "I" and "me" in a capture mean them.
- **Daily work:** at the first start each day, and after midnight while it runs, it rebuilds the capacity calendar (so routine tasks roll forward) and the generated pages. The day is kept in `app_state`.
- **Reminders:** a Windows notification from the tray icon for each open task whose reminder is today or past and hasn't been shown (`reminders_shown`), at start-up and from `reminder_time` each day. More than three become one notification. Clicking a reminder opens the browse tool's Reminders list, on that task when there's one.
- Saves, reminders and errors are logged by ID only.

### 7.2 The capture window
- Made once at start-up and shown or hidden, so it opens at once: stays on top, centred near the top of the screen with the mouse pointer, and puts the cursor in the content text (in Title when New task is checked).
- **Top to bottom** (release 5.6, M0037, M0042): the task picker; the capture types Note, New task and Update, with **Agenda** beside them: **Today** as a button, then the agenda picker (the line wraps when the window is narrow); a line saying what Save will do; then Title (New task only), the content text and Parse and populate (Alt+P) on the left, with the list of what it found on the right, always in view (under the content text below 700 px wide); the files; the summary type and Copy prompt; the Summary (after Copy prompt, or Add a summary); the New task fields; the Update fields. A **?** button opens the mods log over the window. The window is 940 px wide, or the screen's width less 32 px.
- **Expand** (release 5.6, M0046, M0048 phase 1): the button by Parse and populate, or F11, makes the window fill most of the screen and the content text most of the window. The files, Copy prompt and the summary, and the New task and Update fields fold away (a line says which), and come back on F11 again. What's in them is kept and saved as before.
- Each field has an **i** button that shows what it's for and its shortcuts (`docrepo/ui/help_text.py`).
- **Capture types:** several can be checked. Note is checked by default; checking New task or Update unchecks it unless it was checked by hand, and with nothing checked it comes back. Update needs a picked task.
- **Keys:** Ctrl+Enter saves (on the mods log panel, saves the entry). Esc hides the window and keeps the draft (on the mods log panel, stops an edit, then goes back). Alt+P runs Parse and populate. One letter per topic (release 5.6, M0036): Alt+N, Alt+T and Alt+U tick or untick Note, New task and Update; Alt+A goes to the agenda picker; Alt+D puts it on Today or takes it off; F11 expands; F1 lists every key (`docrepo/ui/keymap.py`).
- **Task picker:** cascading menus of the open tasks, with a search box, Recent (the last 5 tasks captures were saved to) and None at the top. Hovering a task shows its subtasks; clicking it, or Enter, picks it even when it has subtasks. Typing switches to a flat list of matching tasks (title or ID) with their paths, which also finds parked tasks. A task with two parents shows under both.
- **Pickers for labels, people and agendas:** typing filters the list, and people also match their aliases. With nothing matching, the labels and people pickers offer "Create label …" or "Add … to people"; those are made when the capture is saved. The agenda picker lists open meetings first, then people, and finds any open task as you type; Today has its own button (release 5.6). Both work with New task, with Update, or with no task picked; otherwise they're greyed out and say why.
- **New task fields:** Labels (with Inherit parent labels, the inherited ones listed), Lead, Assignees, Due, Deadline, Deadline description, Urgent, Meeting; under More fields, State, Start (today by default), Reminder, Recurrence, Repeat until (only with a recurrence), Lead hours and Assignee hours.
- **Update fields:** State, Current status, Due, Deadline and its description, prefilled from the task; under More fields, Lead, Assignees, the hours, Start, Reminder, Recurrence, Repeat until, Urgent and Meeting. Only fields that differ from the task are changed, and a line lists them.
- **Pasting:** a list keeps its bullets. OneNote puts its bullets only in the clipboard's HTML, so when the HTML holds a list (HTML list items, or Word's and Outlook's `mso-list` paragraphs), it's pasted as plain text with each item a `- item` line (numbered items keep their numbers), indented two spaces a level. Bullet characters starting plain-text lines (`•`, `·`, `▪` and so on) become `- `. `docrepo/paste.py`.
- **Files:** files dropped on the window or added with Add files…, a file path on a line of its own in the content text (deleting the line removes it), and Outlook emails (7.5). Each gets a row: its description, Save a copy and Extract information. A description is optional (release 5.5, M0041): one left empty becomes "*task* – Attached document – *file name*" when Save runs, "Attached link" for a link and "Attached picture" for an email's picture, where the task is the new task, else the picked task; with no task it's the file name. The box shows that in grey beforehand (`save.default_description`). Saved copies are named from the file's own name, never its description. With several, "Use the first file's description and choices for every file". A path on a mapped drive is recorded as its network path (`\\server\share\…`). A file that's already tracked reuses its document and starts with its description.
- **Links** (release 5.4, M0001): a web or SharePoint link on a line of its own in the content text, or one added with **Add link…** (which offers the clipboard's link), gets a row too, marked Link, with its description ("What's at this link?") and no Save a copy or Extract information (6.5). A link typed by hand gets its row without the cursor leaving the content text. Link lines, like file path lines, are left out of a new task's description, a capture's title and what Parse and populate reads, so a date in an address is never read as a date.
- **Email layer 0** (release 5.4, M0005, M0024; `docrepo/layer0.py`): an Outlook email's row has no description of its own. Under it, each of the email's attachments, the links in its body and the pictures in its body gets a row of its own, with **Keep**, a description and its choices: an attachment has Save a copy and Extract information, a picture Save a copy, a link neither. An unticked row is left out: it needs no description, and isn't saved as a document (an attachment stays inside `email.msg`). The email's row shows the layer 0 line, such as "2 attachments, 2 links and 1 picture kept. Left out: 1 email address, 1 repeated link and 1 unticked row.", which goes into the capture's `capture.md` and its page. "Use the first file's description" works across every described row. Removing the email removes its rows.

### 7.3 Parse and populate
- `docrepo/parse.py`, ported from the mockup's `parse.js`: fixed rules with `re` and `datetime`, no LLM. It reads the content text (and any email's text) and fills the fields of the checked capture types. With New task and Update both checked, it fills the new task's fields, and for Update only a quick update's state and status. With a task picked, nothing checked and a quick update ("Closed. …"), it checks Update itself.
- **What it fills:** the title (New task), Due and Deadline from date phrases read with the words around them, the deadline description, Reminder, Start, Recurrence, Urgent, labels from their keywords, leads and assignees (known people by name or alias, new names from unmistakable phrases), lead and assignee hours, a quick update's State and Current status, and otherwise an update's first sentence as its Current status.
- **Mods log round 1 (2026-10-19)** added: an update's first sentence as Current status (not with New task checked too, when the first sentence is the new task's description); a sentence or line that's only a list of names ("Priya, Tom, Mike and Tyler."), or the list after "each:" or "per assignee:", as assignees, when one name in it is known or the sentence before mentions assignees or "each", its new names becoming new people; "is lead", "is the lead", "will be the lead" and "as lead" as lead phrases; half years and quarters with the year joined on ("2H2027", "Q42026"); and "1H" or "2H" before a year, or after "due" or "by", read as a half year rather than hours. The rules in full are in the owner's design notes; `tests/fixtures/test-vectors.md` lists the results for about 150 captures and 100 date phrases, and the tests check every one.
- It uses the people list (me from settings), the active labels and `event_words` from settings.
- It never overwrites a field typed in, and says so in its list. Fields it fills stay highlighted until edited. Lists (labels, people) only gain items. More fields opens when it fills one of them. Nothing is saved until Save.

### 7.4 Saving a capture
- `docrepo/save.py`. What it needs: a new task needs a title or some content text; Update needs a picked task and a change, an agenda or some text; a Note needs some text, a file or an email; a note put on an agenda with no task needs content text. Otherwise it says what's missing and changes nothing. A file's description left empty gets its default (7.2).
- **A quick task** (release 5.6, M0039): a new task with no task picked that goes on Today goes under the built-in top-level task **Quick tasks** (`docrepo/quick.py`), which is made, In progress and created by "DocRepo", the first time it's needed; DocRepo knows it by that creator, so renaming it changes nothing, and if it's discarded the next quick task makes a new one. The task picker's button then says "None: a quick task, under Quick tasks", and Save's line and message say so. `save.quick_task_draft` makes one from a line (Today's box, Make it a task): Parse and populate reads it as a new task (title, dates, recurrence, hours, labels), and keeps only people already on the list.
- One database transaction holds everything: new people and labels; the new task (its description is the content text without email header and file path lines; with no title, the title Parse and populate would give, else the first sentence); the update, whose changes go into the status log under the capture's ID; the capture's record; its documents (an email's kept attachments and pictures become documents held by the capture, and its kept links link documents); saved copies (Save a copy goes into the new task's or the picked task's `Files` folder now, or into the task an unfiled capture is filed to later); and agenda items (the new task, the updated task, or the content text as a note).
- A capture is kept only when it has content text, a file or a summary. An update with only field changes keeps no capture, and its changes are logged as "Capture window".
- **Then the files:** the capture's folder `Captures\YYYY\MM\<id>\` with `capture.md`; an email's `email.msg` and `attachments\`; each document's text in `Documents\<id>\extracted.txt`, with its size, modified time and SHA-256 in docs.db for the document checks of phase 6; the saved copies, named `YYYY-MM-DD <name>`, cleaned of characters Windows forbids, at most 100 characters and made unique; and the generated pages. A file that fails never undoes the capture: it's listed in the notification and logged.
- After saving, a notification says what Save did, such as "Saved C000026. Created T000020, Book the alignment contractor, under Installation. On the agenda of Business team meeting."

### 7.5 Files, text and Outlook emails
- `docrepo/extract.py` reads text, opening files read-only: `.txt`, `.md`, `.csv`, `.log`, `.json` (UTF-8, UTF-16 with a BOM, or Windows-1252), `.pdf` (pypdf), `.docx` (python-docx: paragraphs and tables), `.pptx` (read with the standard library since release 5.3.1, as a zip of XML parts: each slide's text in the deck's order, shapes inside groups too, tables row by row, and the speaker notes; a part with a DTD, or bigger than 64 MB unpacked, is refused), `.xlsx`/`.xlsm` (openpyxl, read-only: sheet names and cell values), `.eml`. Anything else is recorded with no text. Each document notes how it went (`text_status`: ok, partial when cut at `extracted_text_cap_chars`, none, or error) and how many characters it kept.
- **Outlook (phase 3b, tested on the corporate computer):** `docrepo/outlook.py`, through classic Outlook's COM interface (pywin32). DocRepo finds the running Outlook with `GetActiveObject`, and, since Office registers itself late, joins it with `Dispatch` when that fails but Outlook's main window is open; it never starts Outlook. Each field is read on its own, so one Outlook refuses (its security guard can refuse the sender, recipients or body) is left out and the window names it, and every failure shows in the window with its COM error code in words. Each problem is logged and kept for the troubleshooting report (9.4). An email dragged from Outlook isn't a file, so a drop that comes from Outlook, or **Add selected Outlook email**, reads the emails selected in Outlook: subject, sender, recipients, time, plain-text and HTML bodies and attachments, each with its size, content ID and hidden flag (embedded items, such as an attached email, are left out).
- **Email layer 0** (release 5.4) sorts an email's parts. A picture is an attachment the HTML body shows (an image whose address is `cid:` and the attachment's content ID). Outlook hides most of those from the list of attachments, so hidden doesn't mean a signature: a hidden attachment the body doesn't show is left out, as before release 5.4, and a picture under 10 KB starts unticked as a probable logo or signature picture. Every other attachment is an attachment. The links are the body's `<a href>` addresses, in order: email addresses (`mailto:`) are left out, an address wrapped in Outlook's Safe Links (`…safelinks.protection.outlook.com/?url=…`) is turned back into the real one, anything that isn't http or https (a phone number, a place in the email) is left out, and a repeat is dropped. The body is read with Python's own HTML parser, as data: nothing in it is run, opened or fetched. A `.msg` file dropped from File Explorer is opened through Outlook. The email's text joins the content text, and saving writes `email.msg` (Outlook's SaveAs) and its attachments into the capture's folder. DocRepo never sends, moves or changes an email.

### 7.6 Copy prompt and summary types
- Summary types are Markdown files in `Config\prompts`: front matter with `name`, `fields` and `scope`, then the instructions. `init` and the app write four defaults when they're missing (General summary, Email extraction and summary, Report high-level summary and topic overview, Ancestor context); edited ones are never replaced. A file whose front matter isn't right is skipped and logged.
- `fields` can be `raw_text_latest`, `raw_text_all`, `file_text`, `summary_log`, `status_log`, `events`, `file_list`, `title`, `description` and `current_status`; `scope` is self, ancestors, descendants or family.
- Copy prompt builds the prompt (a preamble saying the blocks are data, not instructions; the type's instructions; then each block of data with its label), copies it to the clipboard and shows its length, with a warning above `prompt_warn_chars`. In the capture window, the blocks are this capture's text, its files' text and the picked task's records within the scope. An email's attachments are saved only with the capture, so their text isn't in a prompt before then. The Summary box then opens; saving puts the summary in the summary log of the capture's task.

### 7.7 The mods log
- `Mods\mods-log.md`, a plain Markdown file kept out of docs.db so it works when something else is broken and can leave the computer on its own. Entries M0001, M0002 and so on, oldest first: a heading with the ID, date and time, area and open or "done" with the day, then "edited" with the day for an entry that was edited (release 5.5), then the note.
- The panel over the capture window (the **?** button, or Mods log in the tray menu): a text box, an Area (General, Capture window, Task picker, Parse and populate, Copy prompt, Browse tool, Capacity, Documents), Save, Copy log (the whole log as Markdown, to the clipboard) and the open entries, newest first, each with Edit and Mark done. A line reminds the owner to leave out names and work details.
- **Edit** (release 5.5, M0047; `mods.edit_entry`) puts an open entry's note and area back in the box, and Save becomes Save M00nn: it replaces the note and area, keeps the ID and time, and adds "edited" with the day to the heading, so a copy of the log shows the entry changed. Saving it unchanged changes nothing. Esc or Cancel edit leaves it as it was.

## 8. Browse tool (phase 4, built)

### 8.1 Running it
- It's part of the app: **Open browse tool** in the tray menu, or `pythonw -m docrepo browse`, which starts the app first if it isn't running and otherwise asks the running copy (with a registered Windows message, `DocRepo.ShowBrowse`) to show it. Closing the window only hides it; the app keeps running in the tray.
- `docrepo/ui/browse_window.py` is the window. What it shows is worked out in modules with no Qt in them, so they're tested as text: `docrepo/views.py` (the rows of the middle pane), `docrepo/stories.py` (the status log and raw text log as stories), `docrepo/detail.py` (the pages, as HTML) and `docrepo/search.py`. Its changes are in `docrepo/edits.py`. All are ported from the browse tool mockup.
- It shares the capture app's database connection and capture window, so both always show the same data. After the capture window saves, the browse tool shows what Save did: the new task, the updated task (Status log tab), the agenda it went on, the task it was added to, or the unfiled capture. The task just saved shows in the task tree whatever the filters, until something else is selected.

### 8.2 The window
- **Top:** **≡ Views**, search, New capture, New task (T) and Update (U) for the selected task, and **Keys** (F1). While browsing (not typing in a box), one letter per topic (release 5.6, M0036; before it, A, N, G and T): N adds a note to the selected task, T a new task under it, U an update and A puts it on an agenda (an update with the cursor in the agenda picker), through the capture window; E opens Edit task, and D puts the task on Today. F1 lists every key (`KeyMapDialog`). Ctrl+F finds in this view and Ctrl+Shift+F goes to the search box (8.8); F5 reads docs.db again. **≡ Views** or Ctrl+B hides the views on the left, leaving more room for the list and the page; the choice is kept in docs.db's `app_state` (`browse_views_hidden`).
- **Left:** the views, with their counts. **Middle:** the view's list. **Right:** the selected item's page, with its buttons above it. Capacity and Settings use the middle and right together.
- **Lists** show tasks in tree form: each matching task under its parents, which show dimmed for context. Each top-level task's group has a colour band (blue, teal, amber, violet in turn), lighter for each level down. A task's row has its title, its markers (Urgent, the recurrence, "2 parents"), its state and its days until due (red when late, amber within two days), marked "deadline" when the task has no Due and the date is its deadline. Titles wrap. Double-clicking a task opens or closes its subtasks (release 5.5, M0043; it used to show the task's folder, which Open folder still does); double-clicking another row shows it in File Explorer, or copies a link.
- A line at the bottom says what the last action did, or why it couldn't.
- Both windows stay light when Windows is in dark mode: the app asks Qt for the light colour scheme and a light palette as it starts, since its colours are the mockup's light ones (`use_light_theme` in `docrepo/ui/style.py`).

### 8.3 Views

| View | Shows |
|---|---|
| Today | Release 5.3 (M0016). Today's open items: Carried over (each with "since Mon", or the date when older than a week), then those added today, then Done today. A box adds a quick task (release 5.6, M0039: `save.add_quick_task`, under Quick tasks, 7.4), or a note with its **Task** and **Note** switch. A task's item has **Edit** (Edit task, whose Parents files a quick task) and **Note** (a Note capture on it); a note's item has **Edit** (its text, `edits.edit_today_note`) and **Make it a task** (`save.note_to_task`: a quick task from its text takes its place, keeping when it was added) (release 5.6, M0040). Each item has Done and Remove; Done on a task then asks "Update the task too?", where Update… and Close the task… open an Update capture starting "Done today: " or "Closed. ", and No closes the question. Below them, **Due in the next 7 days** (release 5.5, M0050; `views.due_this_week`): the tasks of the Overdue and next 7 days list that aren't on Today, soonest first, each with Add to Today. **Mine only** keeps those I lead or am assigned to, and is kept in docs.db's `app_state` (`today_due_mine`). |
| Unfiled | Unfiled captures, newest first, with their source and when they were saved. |
| Task tree | Top-level tasks and their subtasks. Show parked, Show closed and Show routine (on by default), the Labels and People filters (non-matching parents dimmed), Sort, Collapse a level and Expand a level. Each filter is a button whose menu has a tick box for each active label or person, staying open while you tick; a task matches with any of the ticked labels and any of the ticked people (as lead or assignee), and the list is drawn again when the menu closes. Opening a parked, closed or routine task from elsewhere turns its filter on. |
| Overdue and next 7 days, Reminders, Waiting on others, Assigned to me, Urgent, No dates or hours | The lists of section 6.8. Reminders shows the reminder date instead of days until due ("1 d ago" once passed) and a Clear button on each row, which clears the reminder and logs it as "Reminders list". Waiting on others names the assignees. Each list has Sort too. |
| Agendas | Pick an agenda target (open meetings first, then any task or person with open items). Its open items, grouped under the top-level task their subject belongs to, with notes last under "Other topics"; each has Discussed and Remove. Then "Closed recently". Copy as Markdown copies the agenda. Discussed closes the item and opens an Update capture on its task, starting "Discussed at *target*: ", so the outcome goes into its status log; Esc skips it. |
| Timeline | Release 5.4 (M0019, with M0015's sorting by label; `docrepo/timeline.py`, `docrepo/ui/timeline_view.py`). Open tasks over nine weeks from the Monday before this week, or six months, using the middle and right panes together. A bar runs from Start to Due (or the Deadline with no Due), hatched while Not started and red at its end when late; a deadline is a diamond (red once passed); a routine task is a dot per occurrence, or a short bar when one spans days; Today is a line. Group by top-level task (the tree's shape, undated parents dimmed, the tree's colours), label (inherited ones too) or person, soonest first. Labels and People filters as the task tree's, Show routine, Earlier and Later (four weeks, or 13 over six months) and This week. Parked, closed and discarded tasks are left out; open tasks with no dates are named under the chart, each opening its task, except the built-in Quick tasks (release 5.6). Clicking a row shows its path, dates and people in a card above the chart, with Open task and Update; clicking it again or double-clicking opens it in the task tree. Hovering shows its dates and people. |
| Capacity | Hours per active person and week, nine weeks from this one, from `work_calendar`, with each person's share of their hours a week (under 80%, 80 to 100%, over 100%). Earlier, This week and Later move by nine weeks. Clicking a cell lists its tasks. Unestimated and unscheduled tasks are listed below. |
| People | Name, aliases, hours a week and open tasks; Show retired; Add person. |
| Labels | Name, keywords and open tasks; Show retired; Add label. |
| Documents | Each task that holds documents, under its parents, with its documents (name and file description) first under it; documents not filed yet last. A Task filter (the task picker) with Include subtasks. |
| Discarded | Release 5.3 (M0021). Discarded tasks and captures, the latest first, with why. Each opens its page, which has Bring back. |
| Settings | Section 8.9. |

**Select** (release 5.3, M0009), on the task tree and each list, puts a tick box on each task row (not the dimmed parents), with Select all shown (the rows you can see, not those under a collapsed task), Clear and **Edit selected (n)…** (8.7). Ticks are cleared when the view changes.

**Sort** (release 5.2, M0015), on the task tree and each list: the view's own order (tree order, or soonest first), Due date, Title, State (In progress, Not started, Parked, Closed) or Last updated (the latest status log entry or capture, newest first). It sorts the tasks under each parent, so the tree keeps its shape; Due date sorts a task by the soonest Due (else Deadline) among it and the subtasks shown under it, with undated tasks last. The top-level tasks' colour bands follow the new order. Each view keeps its own sort until DocRepo quits (`views.sort_tree`).

### 8.4 The task page
- The path (one line per parent chain), the title, the state, markers, Meeting, labels (inherited ones in italics; each opens its label) and the ID.
- Fields: description, current status, lead and assignees with hours (per occurrence for a routine task), start ("date entered" when it's the created day), due and deadline with days until due (with no Due, the deadline shows in Due's place, marked "(deadline)"; nothing changes in docs.db), reminder ("1 d ago" once passed), recurrence with its next occurrence, the agendas it's on, when it closed, and what created it. An agenda target lists its open items, with Open agenda.
- **Buttons:** Add note (N), Update (U), New task (T), Add to Today (D; On Today when it's there, which opens the Today view), Open agenda (an open meeting, or a task with open items), Add to agenda (A: Today, which adds it at once, then the open meetings, those with open items first, then "Someone else or another task…", each opening an Update capture with that target under Add to agenda), Edit, the summary type and Copy prompt, and Open folder.
- **Edit:** Edit task… (E, release 5.3, M0008 and M0011: section 8.7), Move from under *parent*…, Put under a task… (a top-level task), Also put under…, Take out from under *parent* (with several parents), Make it a top-level task (with one) and Discard… (8.7). Each change goes into the status log as "Browse tool". A move that would put a task under itself is refused.
- **A discarded task's page** says when it was discarded and why, and has only Bring back and Open folder.
- **Tabs:** Raw text log, Summaries, Status log, Files, Subtasks. A scope (this task, with ancestors, with subtasks, family) applies to all but Subtasks; it's With subtasks each time a task is opened.
- **Status log and Raw text log** read as stories (`docrepo/stories.py`), oldest first (an Order switch gives newest first), grouped by day with a heading for each month. The status log opens with how the task began (created under its parents, made from an unfiled capture, or imported, with its description and what it started with), tells each update in words (a state change as a chip such as "Work started" or "Closed", then sentences such as "Due date moved to Fri 23 Oct."), and shows its direct subtasks and, for an agenda target, its agenda items as one-line milestones. The raw text log shows each capture as a journal entry (what it is, such as "Update · Due date moved to Fri 23 Oct." or "Email from …", its title and its text; a summary with the original behind Show the email) and each document version. Long entries fold after 360 characters, with Show all. With subtasks or ancestors in the scope, each one's story is a chapter, closed until opened, with its state, latest status or number of entries, its latest date and Open; Open all chapters and Close all.
- **Summaries, Files and Subtasks** are one row per entry. An entry from another task in the scope names that task, which opens it. A file's name shows it in File Explorer; a link's name opens its page, and **Copy link** next to it copies the address.
- **Copy prompt** works as in the capture window (7.6), on the task's records within the summary type's scope: the latest raw text log entry's content text (or every entry's, for `raw_text_all`), each document's extracted text for `file_text`, and the rest as before.

### 8.5 The capture page
- Saved, source, capture types, what Save did (the task it created, updated or added to, where it was filed, and each agenda item, with how and when it was closed), when it was filed, its field changes, an email's layer 0 line, its files with their descriptions and choices, its summary, when it was edited and how many earlier versions are kept, then the content text, read from its capture.md.
- **Edit** fixes the content text and the summary. Saving first copies the previous capture.md to the capture's `_old versions\capture YYYY-MM-DD HHMM.md` (made unique), then updates docs.db (`edited`, the title, the summary), rewrites capture.md with `edited` in its front matter, the search index and the pages. A capture with no files can't be left without content text. A capture.md that can't be read can't be edited.
- **Show in File Explorer** shows its capture.md.
- **Discard…** (release 5.3, M0021) asks why and discards it (6.5). A discarded capture's page says so, and has only Bring back and Show in File Explorer.
- **An unfiled capture** also has a task picker, **File to task** and **Make it a task**. Filing sets the capture's task in docs.db and its capture.md (with `filed`); the folder doesn't move; the saved copies its files asked for are made in the task's `Files` folder now. Make it a task opens the capture window with New task checked, the capture's content text and a title from it; saving creates the task (its creator is the capture, so its story says "Made into a task from an unfiled capture") and files the capture to it. No new capture is made, and the capture's own content text stays as it was, even if it was changed in the window for the new task's description.

### 8.6 Documents, people and labels
- **A document's page:** its file description, ID, original (or the capture holding it as an email attachment), status, how its text was pulled out, when it was last checked, its document versions, its tasks and its saved copies. Show in File Explorer shows the original; Show extracted text shows its extracted.txt. DocRepo never opens or runs the file itself: it only starts File Explorer. Checking for changes, relinking and editing descriptions come in phase 6.
- **A link's page** (release 5.4): its file description, ID, the address, "No text" and its tasks, with only **Copy link**. In the Documents view a link is marked Link, and double-clicking it copies it. File Explorer is never handed a link (`edits.source_of` gives none, and `show_in_explorer` takes only a full path), since it would open it in the browser.
- **A person's page:** aliases, hours a week, status, hours scheduled this week and next, the open tasks they lead and are assigned, and their agenda. Edit… (name, aliases, hours a week) and Retire or Make active. The owner (me) can't be retired.
- **A label's page:** keywords, status and its tasks, inherited ones marked. Edit… (name and keywords; renaming keeps it on its tasks), Find matching tasks… (8.7) and Retire or Make active.
- People and label changes rewrite the generated pages, since they show names.

### 8.7 Changes made in the browse tool
- **The forms** (Edit task, Edit selected, a label's matching tasks, a person, a label, and a capture's Edit; release 5.5, M0035): Ctrl+Enter saves and closes, as in the capture window (Edit selected and the matching tasks apply), unless the form can't be saved, when it says why. Esc, Cancel or the window's close button closes it, asking first when something was changed (`widgets.FormDialog`).
- Every change runs in one transaction, then rewrites the generated pages; a file that can't be written is reported and logged, and never undoes the change. Task changes go into the status log as "Browse tool" ("Reminders list" for Clear, "Agenda view" for closing an agenda item).
- The status log's sentences for the browse tool's own fields: "Renamed “…”.", "Description edited.", "Label Safety added.", "No longer inherits its parents' labels.", "Discarded: *reason*." and "Brought back.".
- **Edit task** (release 5.3, M0008, M0011; `docrepo/ui/task_forms.py`, `edits.edit_task`): every field on one page: title, description, state, current status, labels (a new one is created) and Inherit parent labels, lead and assignees (someone new is added to the people list), lead and assignee hours, start, due, deadline and its description, reminder, recurrence and Repeat until, urgent and meeting, and (release 5.6, M0040) **Parents**: each parent with ×, and **Put under a task…**, the task picker. Putting a quick task under a task takes it out of Quick tasks; any other task gains the parent. The parents change as one Parents entry in the status log (`tasks.set_parents`). Only fields that differ change. A Start left at the day the task was created stays unset. An Update capture stays the way to make a change that comes with a note.
- **Edit selected** (release 5.3, M0009; `docrepo/bulk.py`, `edits.bulk_edit`): on the ticked tasks, only what's set changes: labels added and removed (their own labels; a new one is created), the state, leads and assignees added or put in place of those there (people on the list only), Due, Deadline and Reminder set or cleared, and a parent (Move there, out from under their parents; or Also put there). One transaction; each task gets its own status log entries. The preview is the same change made and rolled back, so it's what Apply does, task by task. A task it can't be made on, such as one that would end up under itself, is left as it was, and the preview and the message say why.
- **A label's matching tasks** (release 5.3, M0014; `bulk.label_matches`): the open tasks whose title, description or current status holds one of the label's keywords (as Parse and populate finds them: a whole word, with -s, -es, -ing or -ed), and that don't have the label yet, own or inherited. Each shows where a keyword was found, and none starts ticked. Apply adds the label to the ticked ones through Edit selected. The list opens after a label is added or its keywords change, when anything matches, and from Find matching tasks….
- **Discard** (release 5.3, M0021; `edits.discard_task`, `edits.discard_capture`): asks why ("Made by mistake" unless something else is typed). A task with subtasks that aren't discarded, or with open items on its own agenda, has to lose them first; it comes off the agendas it's on, as Removed. A task whose parents are all discarded comes back only after one of them. Changes and Bring back go into the status log as "Browse tool".
- **Today** (release 5.3, M0016; `edits.add_to_today`, `edits.close_today_item`): added and closed from the browse tool as "Browse tool" and "Today"; from the capture window, Today is a button beside the capture types (release 5.6), and with no task picked the content text goes on as a note, or with New task checked makes a quick task.

### 8.8 Search
- **Find in this view** (release 5.6, M0026): Ctrl+F opens a box above the list. As you type, the view keeps the rows that hold every word, each with its parents, faded, for context; closed branches open while it finds, and a line counts the matches. A task is found by its ID, title, description, current status, labels (inherited ones too) and people (`views.find_text`); any other row by its text. Esc clears it, and so does moving to another view. It works on Today, the task tree, the lists, Unfiled, Agendas, People, Labels, Documents and Discarded; the timeline and capacity have their own filters.
- Typing two letters or more in the search box (Ctrl+Shift+F) lists what holds every word typed, in any case: tasks (ID, title, description, current status, deadline description), captures (ID, title, summary, content text), documents (ID, name, file description, original's path, extracted text), saved copies (by name), people (name and aliases) and labels (name and keywords), grouped in that order, at most 40 of each. Captures and documents show the text around the first word found. Esc clears it.
- Captures' and documents' text is copied into `search_text` in docs.db when a capture is saved, edited or filed. `rebuild`, the Settings view's Rebuild button, and the app's start (when the index is missing items, as after updating to phase 4) rebuild it from the files.

### 8.9 Settings
- The data root in use. **Change data root…** picks a folder, checks it isn't in OneDrive or the code folder, sets it up if it's new and records it in `location.json`; DocRepo uses it from its next start, and nothing in the current data root moves. When DocRepo was started with `--data-root` or `DOCREPO_DATA_ROOT`, the page says the recorded one isn't in use.
- **Rebuild pages, calendar and search** does what `rebuild` does.
- Whether DocRepo starts when the owner signs in, with **Make the Startup shortcut** (9.2), and **Import projects from Excel…** (9.3).
- Under the fields, when the last backup was made and when the next is due, with **Back up now** (9.1).
- The fields of `settings.json` (3): me (from the active people), the hotkey (checked as `set-hotkey` checks it, and registered again at once), the more hotkeys (each empty to leave it off, checked the same way, and no two the same; Use the suggested keys fills the empty ones, release 5.6), the backup folder (a full path outside the data root; it joins the places DocRepo may write at once), how often to back up and how many database copies to keep, the reminder time, the workdays, the capacity horizon, the event words, the extracted text cap, Copy prompt's warning length and how often documents are checked. Save settings writes only what changed; a change to the workdays or the horizon rebuilds the capacity calendar and the pages. Undo changes shows what's saved again.

## 9. First everyday version (phase 5, built)

### 9.1 Backups
- `docrepo/backup.py`. A backup runs every `backup_every_days` (7 by default) at the app's first start of the day, on its own thread so the windows stay quick, and when the owner asks: **Back up now** in Settings, or the `backup` command. A notification says what it did. The time of the last backup is kept in `app_state`.
- It needs a backup folder (Settings), outside the data root; with none, no backups are made. In the backup folder:
  - `Database\docs-1.db` to `docs-<backup_keep>.db` (8 by default): copies of docs.db made with SQLite's backup API, so they're whole even while DocRepo writes. Each backup fills an empty slot, or overwrites the oldest copy.
  - `Files\`: the data root's files as they are there, except the `System` folder (docs.db is copied whole instead; the lock and the logs stay). New and changed files (by size and modified time) are copied over; nothing is ever removed from it.
  - `backup-log.md`: one line per backup (when, which database copy, how many files were copied), and how to restore.
- A backup writes through a SafeFS that allows only the backup folder. It's the one place DocRepo replaces files: `replace_file` and `replace` work only in a SafeFS's replace roots, which `make_safe_fs` sets to the backup folder, and never when that folder is inside the data root (section 4).
- A file that can't be copied is listed in the notification and the log, and the backup goes on. A missing backup drive stops the backup with a message.
- **Restoring** (by hand, in the README and the log): quit DocRepo, copy `Files` into a new empty folder, copy the newest database copy into its `System` folder as `docs.db`, then `set-data-root` and `rebuild`.

### 9.2 Starting when the owner signs in
- `docrepo/startup.py`. DocRepo may write only in its three places, and the Startup folder isn't one of them, so **Make the Startup shortcut** in Settings (or the `make-shortcut` command) makes `DocRepo.lnk` in `%LOCALAPPDATA%\DocRepo\`, then opens that folder (with the shortcut selected) and the owner's Startup folder in File Explorer, for the owner to drag it across.
- The shortcut runs this copy's `pythonw.exe -m docrepo app` from DocRepo's folder, so no console window opens, and names no data root (DocRepo finds it in `location.json`). Windows' shell (`WScript.Shell`, through pywin32) writes it, to a path the guard checks first. No admin rights, services, scheduled tasks or registry changes.
- Settings says whether DocRepo starts when the owner signs in, by reading the Startup folder: not yet, yes, or a shortcut that starts DocRepo from another folder (made before DocRepo moved), to make again.

### 9.3 Importing the project list from Excel
- `docrepo/excel_import.py` and the form `docrepo/ui/import_dialog.py`, from **Import projects from Excel…** in Settings. A one-time import: each row of the owner's project list becomes a top-level task, created by "Excel import", so its story begins "Imported from the Excel tracker" with its current status. After it, DocRepo is the master list.
- The workbook (`.xlsx` or `.xlsm`) is opened with openpyxl in read-only mode with cached values, so formulas and macros never run, and it's never changed. A workbook open in Excel can't always be read; the form says to close it or import a copy.
- **The form:** the workbook and sheet (a sheet named like "projects" is picked first), the header row (the first row with two or more text cells, so title rows above it are skipped), and the state tasks start in without a State column (In progress). Then each column, with a few example values and a dropdown for what it fills: Title, Description, Add to the description ("Header: value" lines, so nothing is lost), Current status, State, Start, Due, Deadline, Deadline description, Lead, Assignees, Labels, A label (yes or no), Urgent, Lead hours, Assignee hours, or Leave out. The proposal comes from the header's words (Owner and Project lead are Lead, Team is Assignees, Category is Labels, Due date is Due and so on, with Title last so "Project lead" isn't the title), and a column holding only yes, no, x or blank is one label, named by its header (changeable). A State column's values each get the state they become, proposed from their words (complete is Closed, on hold is Parked). Only one column can fill each single field, and one must fill Title.
- **The preview** lists the tasks Import will make (row, title, state, due, lead, assignees, labels), the new people and labels, what to check, and the rows skipped. Nothing is written until **Import**.
- **Values:** dates from date cells, Excel day numbers, or text read as Parse and populate reads date phrases ("Q1 2027", "10/30/2026"); text that isn't a date goes into the description, and the preview says so. Names in Lead and Assignees (split at commas, semicolons, slashes, "&" and "and") match the people list by name or alias; a retired person is left off, as Parse and populate does; the rest become new people. Label names that don't exist become new labels. Urgent reads yes, x, high, urgent, critical or P1.
- Rows with no title are left out. A row whose title is already an Excel-imported task's is skipped, so importing again makes no doubles; the form shows the last import (when, how many, the workbook's name).
- **Import** runs in one transaction (the new people, labels and tasks, each task's capacity calendar rows), then writes the pages. The log records counts only.

### 9.4 The troubleshooting report
- `docrepo/diagnose.py`, from **Troubleshooting report…** in Settings, or the `outlook-check` (`troubleshoot`) command. Added in mods log round 1, since Outlook can only be tested on the corporate computer. The owner carries the report to the personal computer, so it holds versions, steps, counts and error codes, never captured content.
- **What it holds:** DocRepo's, Python's, Windows', PySide6's and pywin32's versions, whether DocRepo runs as administrator (Windows then blocks drags into it) and whether Outlook's main window is open; the Outlook check, each step of reading the email selected in Outlook (finding Outlook, its version, its main window, the selection, each item's kind, each of the email's fields by its length only, the attachments by count (with how many are hidden and how many have a content ID), what email layer 0 would find in the body (links, email addresses, Safe Links and pictures, by count), and whether SaveAs is there, which isn't tried so no file is left behind); Outlook's programmatic access settings, read-only from the registry; this session's drags onto the capture window and pastes into it, by their formats' names and what DocRepo took them as; this session's Outlook problems and uncaught errors; and the log's warnings and errors from the last 7 days, with the start of each traceback.
- **Shortened:** the data root, the user's folder, the user, computer and domain names, servers and shares, and email addresses are replaced, such as `<data root>` and `\\<server>\<share>`.
- It's saved as `System\diagnostics\troubleshooting YYYY-MM-DD HHMM.md`, never over an earlier one, and shown in a window with Copy report and Show in File Explorer.

## 10. Later phases (summaries)

These are designed in detail in the owner's design notes, and move into this file as each phase is built.

- **Document tracking (phase 6):** change checks on tracked files, diffs, replaced saved copies, relinking moved files, and editing file descriptions. Links (6.5) are never checked: DocRepo can't fetch them.
