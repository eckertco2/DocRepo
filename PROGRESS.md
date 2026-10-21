# DocRepo progress

DocRepo is being rebuilt on the owner's personal computer, starting 2026-10-08. The first version's phases 0 to 2, built on the corporate computer, are replaced.

## Phases

| Phase | What | Status |
|---|---|---|
| 1 | Skeleton and safety: the data root's location, settings, guarded writes, logging, the command line, and the network-module scan | Done. Tested on the corporate computer (2026-10-09): pip install, pytest and the command checks |
| 2 | Database and task model: schema, IDs, the task tree, labels, people, logs, recurrence, days until due, the capacity calendar, and the generated pages, checked against the mockup's test vectors and examples | Built and hand-tested by the owner 2026-10-16; on GitHub 2026-10-16. Tested on the corporate computer by 2026-10-20 |
| 3 | Capture app: tray, hotkey, the capture window (task picker, the Note, New task and Update capture types, Parse and populate, Copy prompt, mods log), saving captures, text extraction, Outlook emails and LAN paths | Built and hand-tested by the owner 2026-10-16 (3a); on GitHub 2026-10-16. Tested on the corporate computer, with 3b (Outlook), by 2026-10-20 |
| 4 | Browse tool: the views, task and capture pages, agendas, capacity, people, labels, documents, search, and Settings | Built 2026-10-17; hand-tested by the owner 2026-10-18; on GitHub 2026-10-18. Tested on the corporate computer by 2026-10-20 |
| 5 | First everyday version: Startup shortcut, backups, the one-time Excel import of the project list, and the README | Built 2026-10-18; hand-tested by the owner 2026-10-18; on GitHub 2026-10-18. Tested on the corporate computer by 2026-10-20 |
| 5.1 | Fixes from the mods log, round 1: Outlook emails, the troubleshooting report, Parse and populate, pasted lists | Built 2026-10-19; hand-tested by the owner 2026-10-20; on GitHub 2026-10-20. Tested on the corporate computer 2026-10-20 |
| 5.2 | Quick wins from the mods log, round 1: the deadline in Due's place, hiding the views, more hotkeys, filtering by several people and labels, sorting | Built 2026-10-20; hand-tested by the owner 2026-10-20; on GitHub 2026-10-20. Tested on the corporate computer 2026-10-20 |
| 5.3 | Editing and daily use from the mods log, round 1: Edit task, Edit selected, labels on old tasks, Discard, Today | Built 2026-10-21. Next: the owner's hand test here, then GitHub and the corporate computer |
| 6 | Document tracking: change checks, diffs, replaced saved copies, and relinking moved files | Not started |

## Decisions

- Python 3.12.6, the same version as on the corporate computer.
- Packages: the seven approved in the first version's Phase 0, at the same versions, pinned in `requirements.txt` with their dependencies. extract-msg isn't used; `.msg` files are read through Outlook.
- Default hotkey: Ctrl+Shift+Space.
- No paths in the code. The data root's location is kept in `%LOCALAPPDATA%\DocRepo\location.json`; everything else is in `<data root>\Config\settings.json` and is edited in the browse tool's Settings view.
- Publish to GitHub after phase 1, to test the route to the corporate computer early.
- The GitHub repo is public (2026-10-09), so the corporate computer can download it without signing in to GitHub. Nothing personal or company-related may go into it.

## Code layout (phase 1)

- `docrepo/safe_fs.py`: the only module that writes, copies, moves or creates folders. See SPEC section 4.
- `docrepo/config.py`: the data root's location (`location.json`), `Settings` (`Config\settings.json`), the OneDrive and code-folder checks, `make_safe_fs` and `init_data_root`.
- `docrepo/log_setup.py`: the rotating log in `System\logs`.
- `docrepo/cli.py`: the commands `where`, `set-data-root`, `init` and `try-write`.
- `tests/`: the guard (including `..`, junctions and symlinks), the network-module scan, settings and the command line. 53 pass; the symlink test is skipped because this Windows account can't create symlinks, the same as on the corporate computer.

## Code layout (phase 2)

- `docrepo/db.py`: `docs.db`, its schema and version, transactions, and IDs. See SPEC section 6.1.
- `docrepo/dates.py`, `docrepo/schedule.py`: dates as stored and shown; windows, next occurrences and days until due.
- `docrepo/model.py`: a read-only snapshot of the database and the rules that read it (the tree, scopes, inherited labels, raw text logs, summaries, files, the status log, agendas, unfiled captures).
- `docrepo/tasks.py`, `docrepo/people.py`, `docrepo/agenda.py`, `docrepo/captures.py`: the writes. Task changes go into the status log and rebuild the task's calendar rows in the same transaction. `captures.py` also writes `capture.md`.
- `docrepo/capacity.py`: the capacity calendar (`work_calendar`), unestimated and unscheduled tasks. `docrepo/lists.py`: the six lists.
- `docrepo/pages.py`: `Task.md` and `Contents.md`. `docrepo/text.py`: sentences and capture titles. `docrepo/report.py`: the `report` command's text.
- `docrepo/sample.py` and `docrepo/sample/sample-data.json`: the made-up sample data and `load-sample`.
- `tests/`: 65 new tests. `tests/fixtures/` holds the mockup's `examples.md` and `test-vectors.md`; every generated page, the `capture.md` examples and the report's tables match them line for line.

## Decisions (phase 2)

- The sample data's labels are Line 1, Line 2 and Strategic Plan, so nothing from real work is in the public repo.
- Agenda entries in a status log are worked out from `agenda_items`, not stored twice.
- A capture's content text stays in its `capture.md`; the database keeps its title.
- A generated page is rewritten only when more than its "Generated on" line changes.
- `report` writes UTF-8 when its output goes to a file.

## Code layout (phase 3)

- `docrepo/parse.py`: Parse and populate, ported from the mockup's `parse.js`. `tests/test_parse_vectors.py` runs all of `test-vectors.md`'s captures and date phrases.
- `docrepo/save.py`: saving a capture (the draft, the checks, one transaction, then the files). `docrepo/extract.py`: text from files, file checksums, mapped drives as network paths.
- `docrepo/prompts.py`: summary types and Copy prompt. `docrepo/mods.py`: the mods log.
- `docrepo/hotkey.py`: RegisterHotKey through ctypes. `docrepo/outlook.py`: Outlook through COM (phase 3b).
- `docrepo/app.py`: the tray, single copy, hotkey, reminders, daily work and the first-start question. `docrepo/ui/`: the capture window, task picker, chip pickers, mods log panel, help texts (generated from the mockup's `HELP`) and style.
- `docrepo/db.py`: schema version 2, brought up from version 1 when a database is opened.
- `tests/`: 288 new tests, 242 of them Parse and populate's vectors. The capture window and the app are tested offscreen (`QT_QPA_PLATFORM=offscreen`), so no window appears.

## Decisions (phase 3)

- Saving runs on the window's own thread, because Outlook's COM objects belong to it. The window shows a busy cursor; a big file on the LAN can take a moment.
- Only one copy of the app runs per data root, through a lock file in `System`. A second copy finds the first's window and asks it, with a registered Windows message, to show itself. (Qt's local sockets are in QtNetwork, which the network rule bans.)
- An email's attachments are saved only with the capture, so Copy prompt can't include their text before then: DocRepo has nowhere else it may write them.
- Until the browse tool exists, clicking a reminder opens the capture window on that task with Update checked.
- The label, people and agenda pickers show their suggestions in a list under the box, not a floating popup, so typing never loses focus.
- The capture window uses Segoe UI, which every Windows 10 and 11 computer has.

## Code layout (phase 4)

- `docrepo/views.py`: what the middle pane lists (the task tree, the lists and Documents in tree form, unfiled captures, agendas, the capacity grid), the date cells and the view counts.
- `docrepo/stories.py`: the status log and raw text log as stories, ported from the mockup's `storyOf` and `noteItem`.
- `docrepo/detail.py`: the task, capture, document, person and label pages as HTML, and the capacity view's details. Its links (`task:`, `tab:`, `chap:` and so on) are handled by the window; none leaves DocRepo.
- `docrepo/search.py`: the search index (`search_text`, schema version 3) and searching. `docrepo/edits.py`: the browse tool's changes (filing, fixing a capture, clearing a reminder, closing an agenda item, task edits and moves).
- `docrepo/ui/browse_window.py`: the window. `docrepo/ui/tree_view.py`: the list with HTML cells and the group colours. `docrepo/ui/settings_view.py`, `docrepo/ui/dialogs.py`, `docrepo/ui/explorer.py` (File Explorer only).
- Also changed: `save.py` (Make it a task, the search index, what Save did for the browse tool), `capture_window.py` (opening with an agenda target or from an unfiled capture), `tasks.py` (Description in the status log, `move_parent`), `prompts.py` (content text, `raw_text_all` and `file_text` for a task), `captures.py` (reading content text back from capture.md), `app.py` (Open browse tool, reminders open the Reminders list, the hotkey from Settings), `cli.py` (`browse`; `rebuild` rebuilds the search index too).
- `tests/`: 119 new tests (526 pass in all). `tests/fixtures/stories.json` is the mockup's `exportStories`: every sample task's story and raw text log, checked entry for entry. The views are checked against the mockup's rows. The window is tested offscreen.

## Decisions (phase 4)

- The browse tool runs inside the app, sharing its database connection and capture window, so the two never disagree. `browse` starts the app if it isn't running.
- The detail pane is a QTextBrowser showing HTML built by `docrepo/detail.py`, so the pages are tested as text without Qt. Captured text is always escaped, never shown as markup.
- Moving a task in the tree is done from the task page's Edit menu (Move from under, Also put under, Take out from under), with the task picker, not by dragging.
- The browse tool never opens or runs a document: Show in File Explorer only starts File Explorer, in line with the rule against launching attachments. Open original, Check now and Relink wait for phase 6.
- Search finds items holding every word typed, anywhere in their text, as the mockup's search does with one phrase. Captures' and documents' text is copied into `search_text` in docs.db; tasks, people and labels are searched in their own tables.
- Make it a task files the unfiled capture to the new task instead of making a second capture. The capture keeps its own content text; the new task's description is what was in the window.
- Copy prompt for a task sends the latest raw text log entry's content text (not just its title), and `raw_text_all` and `file_text` now work for a task too.
- A status log value with line breaks stays on one line in `Task.md`.
- DocRepo's windows stay light even when Windows is in dark mode (found in the owner's first hand test, 2026-10-17). Qt follows Windows' dark mode and drew its controls dark under DocRepo's light colours, which hid text in both windows. A dark look could come later; it would need dark versions of every colour.

## Code layout (phase 5)

- `docrepo/backup.py`: backups (database copies in rotating slots, the files mirror, `backup-log.md`). The app runs them on their own thread and notifies when done; the `backup` command and Settings' Back up now run one at once.
- `docrepo/safe_fs.py`: replace roots. `replace_file` and `replace` overwrite only there; `make_safe_fs` makes the backup folder the only one, never inside the data root.
- `docrepo/startup.py`: the Startup shortcut, made through Windows' shell (pywin32), and its status. The `make-shortcut` command.
- `docrepo/excel_import.py`: reading the workbook (openpyxl, read-only), proposing the mapping, the preview and the import. `docrepo/ui/import_dialog.py`: the form.
- `docrepo/ui/settings_view.py`: the backup fields, Back up now, the Startup shortcut and the import button. `docrepo/config.py`: `backup_every_days` and `backup_keep`.
- `tests/`: 30 new tests (557 pass in all, 1 skipped). `tests/sample_workbook.py` makes a made-up project list for the import tests, and for trying the import by hand.

## Decisions (phase 5)

Settled with the owner on 2026-10-18 (brainstorm round 27).
- **The Startup shortcut:** DocRepo makes `DocRepo.lnk` in `%LOCALAPPDATA%\DocRepo\` and opens that folder and the Startup folder, and the owner drags it across. The hard rules gain `.lnk` in that one folder; DocRepo only reads the Startup folder.
- **The Excel import** is a form in the browse tool, with a dropdown per column and a preview, and stays a one-time import. Rows already imported (by title) are skipped if it's run again.
- **Backups are weekly** (`backup_every_days`, 7), with 8 copies of docs.db (`backup_keep`), both changeable in Settings. The files are mirrored; nothing is removed from the backup.
- The backup folder is the only place DocRepo overwrites files, through the new replace roots; copies into the data root still never overwrite.
- The owner's project list has names, descriptions, status text, dates, people and label columns, but no state column, so imported tasks start In progress unless the form says otherwise. A status text isn't read as a state (as round 13 decided for Parse and populate).
- Retired people in the workbook are left off, as Parse and populate does. The workbook's name, not its path, is kept with the last import.
- Restoring a backup is done by hand, following the README and `backup-log.md`.
- Found in the phase 5 hand test: a file dragged from File Explorer was taken for an Outlook email, so no file row appeared. Explorer's drags carry Outlook's virtual-file format (FileGroupDescriptorW) as well as the files. Now files in a drop come first, only Outlook's own formats (RenPrivate…) mean an email, a drop is always taken as a copy, and a folder or a file only another program holds (such as one in a zip folder) is refused with a message. This was in phase 3, so on the corporate computer, test dropping files with this version rather than an older one.

## Release 5.1: the mods log, round 1

The owner's first mods log from the corporate computer (M0001 to M0024, 2026-10-19) is planned in the parent workspace's `docs/mods/round-1-plan.md`. This release is its stage 1, the bug fixes: M0004, M0006, M0007, M0013 and M0022.

- `docrepo/outlook.py` (M0004): Outlook is found with `GetActiveObject`, then joined with `Dispatch` when Outlook's main window is open (never started). Each field is read on its own (`read_field`), so a field Outlook's security guard refuses is left out and named (`EmailItem.refused`). Every error becomes an `OutlookError` with its step and its COM code in words (`describe`, `HRESULTS`), and is kept in `PROBLEMS`.
- `docrepo/ui/capture_window.py`: `_read_emails` shows every failure in the window, including errors outlook.py didn't expect, which used to escape the button and, under pythonw, show nowhere. `note_drag` notes each drag's formats for the report. Pasting goes through `docrepo/paste.py` (M0022).
- `docrepo/diagnose.py`: the troubleshooting report (SPEC 9.4), the Outlook check, and `install_excepthook`, which the app sets so an error nothing caught is logged and told. `cli.py`: `outlook-check`, also called `troubleshoot`. `settings_view.py`: Troubleshooting report… and its window.
- `docrepo/parse.py` (M0006, M0007, M0013): ported from the mockup's `parse.js`, where the changes were made first. `tests/fixtures/test-vectors.md` gains a "Mods log round 1" section of 16 captures and 5 date phrases, and eight existing Update rows now show their first sentence as Current status. The regenerated file's checksum equals the mockup's own `exportChecksum("test-vectors.md")`, so both versions of Parse and populate agree on every vector.
- `tests/`: `test_outlook.py` (fake COM objects), `test_diagnose.py`, `test_paste.py`, and new capture window tests.

## Decisions (release 5.1)

- Decision 2 of the round 1 plan, taken as recommended: several known people named with no phrase become assignees only when they make a list of names on their own, or follow "each:" or "per assignee:". A list needs one known name, or "assignee" or "each" in the sentence before it, so a list of capitalized words ("Valves, Pumps and Motors.") adds no one. Teams' initials (HR, QA and so on) aren't names.
- With New task and Update both checked, Update still takes only a quick update's state and status: the first sentence is the new task's description.
- "Tom is lead-certified" isn't a lead phrase, and names not on the people list don't become new leads from "is lead": only from "Lead: …" as before.
- The troubleshooting report doesn't try Outlook's SaveAs, so it leaves no copy of an email behind. Saving a capture still uses it, and its errors are listed in the notification and the log as before.
- The mockup's artifact wasn't republished for this release; `browse-mockup.html` is rebuilt locally.

## Release 5.2: quick wins from the mods log, round 1

Stage 2 of the round 1 plan: M0003, M0012, M0002, M0010, M0020, M0018 and the first part of M0015.

- `docrepo/detail.py`, `docrepo/views.py` (M0003): with no Due, the task page shows the deadline in Due's place, marked "(deadline)", and a row's date is marked "deadline" (`DueCell.deadline`). Days until due, the lists and the capacity calendar already used the deadline.
- `docrepo/ui/browse_window.py` (M0012): **≡ Views** and Ctrl+B hide the views pane, kept in `app_state` as `browse_views_hidden`.
- `docrepo/hotkey.py`, `docrepo/app.py`, `docrepo/config.py` (M0002, M0010, M0020): `HOTKEYS` lists six hotkeys, five of them new settings, empty by default. The app registers each one that's set and runs its action (`hotkey_actions`); Pause hotkeys pauses them all. `CaptureWindow.open_with_hotkey` opens the window for a capture type, through the task picker when Update or Add to agenda has no task. In the browse tool, G puts the selected task on an agenda. Settings has a box for each, checked as the first is, and no two may share keys.
- `docrepo/views.py`, `docrepo/ui/widgets.py` (M0018): `TreeFilter` takes several labels and people (`labels`, `people`), matching any of each. `CheckMenuButton` is the filter button: a menu of tick boxes that stays open while you tick and redraws the list when it closes.
- `docrepo/views.py` (M0015, first part): `SORTS` and `sort_tree`, on the task tree and each list, sorting the tasks under each parent; `last_updated` for Last updated.
- The mockup's `files.js` and `examples.md` show the new settings; the regenerated file's checksum equals `exportChecksum("examples.md")`.
- `tests/`: new tests in `test_views.py`, `test_detail.py`, `test_browse_window.py` and `test_capture_window.py`.

## Decisions (release 5.2)

- Decision 1 of the round 1 plan, as the owner chose (option a): the deadline is shown in Due's place, not copied into Due, so moving the deadline later still moves the shown date.
- The views pane's choice is kept in docs.db, so it holds across restarts; a sort lasts until DocRepo quits.
- With the views hidden, the list's own title says which view it is; **≡ Views** or Ctrl+B brings them back.
- The hotkeys for Update and Add to agenda use the task already picked in the capture window's draft; only with none do they open the task picker. Picking None there leaves a note (on an agenda, for Add to agenda).
- Sorting by label waits for the timeline view (stage 4), where grouping by label fits.

## Release 5.3: editing and daily use, from the mods log, round 1

Stage 3 of the round 1 plan: M0008, M0011, M0009, M0014, M0016 (with M0020) and M0021.

- `docrepo/ui/task_forms.py`, `docrepo/edits.py` (M0008, M0011): `TaskEditDialog`, **Edit task…** and E, saved by `edits.edit_task`. It replaces the Title and description and Labels dialogs. `people.find_or_add` adds someone new for it and for saving a capture.
- `docrepo/bulk.py` (M0009, M0014): `BulkEdit`, `run` (one transaction, a savepoint per task) and `preview` (the same, rolled back); `label_matches` and `keyword_pattern`. `tasks.set_parents` puts a task under exactly the given parents as one change. `docrepo/ui/task_forms.py`: `BulkEditDialog` and `LabelMatchDialog`. `docrepo/ui/tree_view.py`: tick boxes on rows (`add_tick`, `ticked`), drawn before the row's HTML.
- `docrepo/db.py` (schema version 4), `model.py`, `schedule.py`, `views.py`, `search.py`, `capacity.py`, `pages.py`, `detail.py`, `stories.py`, `edits.py` (M0021): discarded tasks and captures, hidden everywhere but the Discarded view; `is_open` and `due_of` leave a discarded task out, and `Model.live_captures` a discarded capture.
- `docrepo/agenda.py`, `model.py`, `views.py`, `pages.py`, `detail.py`, `stories.py`, `edits.py`, `save.py`, `report.py`, the browse and capture windows (M0016): Today, the agenda target `today`, closed as Done. Version 4 makes `agenda_items` again to allow Done.
- `docrepo/ui/widgets.py`: `label_options` and `people_options`, shared by the capture window and the forms.
- The mockup gained the Today view (`today.js`) for review first, and was republished with it.
- `tests/`: `test_bulk.py`, `test_discard.py`, `test_today.py`, and new tests in `test_edits.py`, `test_browse_window.py`, `test_capture_window.py` and `test_db.py` (633 pass in all, 1 skipped).

## Decisions (release 5.3)

- Decisions 3 and 4 of the round 1 plan, as the owner chose: unfinished Today items stay on the next day; Discard for tasks and captures is the way to delete, and nothing is deleted.
- Discard is a pair of columns, not a state, so a task keeps its state and comes back as it was. A task with live subtasks, or open items on its own agenda, can't be discarded; one whose parents are all discarded can't come back first.
- A discarded capture's `capture.md` isn't changed, since the hard rules allow editing it only to file it or to fix a mistake. Discarding is recorded in docs.db.
- Edit selected adds only people already on the list; Edit task can add someone new. Removing a label removes a task's own label, not an inherited one.
- The matching tasks list opens after a label is saved in the browse tool, not after the capture window creates one, so saving a capture never opens another window.
- In the Today view, Done and Remove are links at the end of each row, as Discussed and Remove are in the Agendas view, rather than the mockup's round button.
- Today isn't one of the Agendas view's targets (`Model.agenda_targets`), but its picker offers Today first, which opens the Today view.

## The first Frogbot findings (2026-10-20)

The corporate computer's Frogbot scan of phase 5 found four things.

- `requirements.txt`: Pillow 12.3.0 had CVE-2026-96639 (critical) and CVE-2026-96640 (high), both fixed in Pillow 13.0.0, now pinned. DocRepo doesn't use Pillow itself; python-pptx needs it, and works with 13.0.0.
- `pyproject.toml` is gone, and its pytest settings are in `pytest.ini`. Two GPL-3.0 findings named a component `docrepo` (in `pyproject.toml` and `docrepo/log_setup.py`). That was DocRepo itself: JFrog's pip scan runs `pip install .` first, and the `[project]` table named "docrepo" matched an unrelated GPL-3.0 package of that name on PyPI. DocRepo isn't installed as a package, so nothing used the table. Now `pip install .` fails, and the scan falls back to `requirements.txt`.

## Unfinished / notes

- On the corporate computer, phases 2 to 5 and releases 5.1 and 5.2 all passed their tests by 2026-10-20, Outlook included.

- Phase 5 passed the owner's hand test on this computer on 2026-10-18, after the fix for files dropped from File Explorer, and went to GitHub the same day.

- Phase 4 passed the owner's hand test on this computer on 2026-10-18, after the fix that keeps the windows light in Windows' dark mode, and went to GitHub the same day. The hand test covered what the automated tests can't: the window with the real Windows style, File Explorer opening, the tray menu and reminder clicks, and the Settings view.

- Phases 2 and 3 passed the owner's hand tests on this computer and went to GitHub together on 2026-10-16 (brainstorm round 12).

- `SPEC.md` covers phases 1 to 5 in full; later phases are summaries until they're built. The detailed design is in the parent workspace's `docs/task-model/brainstorm.md`.
- Published to the GitHub repo `eckertco2/DocRepo` on 2026-10-09 (phase 1), on 2026-10-16 (the glossary, phases 2 and 3), on 2026-10-18 (phases 4 and 5), and on 2026-10-20 (releases 5.1 and 5.2, and the fixes for the first Frogbot findings).
- The route to the corporate computer works (2026-10-09): download, a security scan there, `pip install -r requirements.txt` with every pinned version available, and pytest passing.
