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
| 5.3 | Editing and daily use from the mods log, round 1: Edit task, Edit selected, labels on old tasks, Discard, Today | Built 2026-10-21; on GitHub 2026-10-21, before the owner's hand test. Next: the hand test here, and testing on the corporate computer |
| 5.3.1 | PowerPoint text without python-pptx, so Pillow (flagged by the company's license policy) goes | Built 2026-10-21; on GitHub 2026-10-21. Next: the corporate computer, with release 5.3 |
| 5.4 | Big features from the mods log, round 1: links as files, email layer 0 and the timeline | Built 2026-10-21, after the owner approved the mockups; on GitHub 2026-10-21, before the owner's hand test. Next: the hand test here, and testing on the corporate computer |
| 5.5 | Small fixes from the mods log, round 2: Ctrl+Enter in the forms, an optional file description, editing mods log entries, double-click, and what's due this week on Today | Built 2026-10-21; on GitHub 2026-10-21; hand-tested by the owner 2026-10-21. Next: testing on the corporate computer |
| 5.6 | The capture window and Today from the mods log, round 2: Agenda and Today beside the capture types, what Parse and populate found beside the content text, Expand, quick tasks, one letter per topic, Find in this view | Built 2026-10-21, after the owner approved the mockup; on GitHub 2026-10-21, before the owner's hand test. Next: the hand test here, and testing on the corporate computer |
| 5.7 | Formatted content text from the mods log, round 2: bold, italic, underline, strikethrough, highlights and lists in the content text, kept as Markdown in capture.md | Built 2026-10-23; on GitHub 2026-10-23, before the owner's hand test. Next: the hand test here, and testing on the corporate computer |
| 5.8 | Items and meeting notes from the mods log, round 2: @, # and ** make tasks, notes, updates and decisions in any capture, and Meeting notes takes a meeting's notes with its agenda | Built 2026-10-23, after the owner approved the mockup; on GitHub 2026-10-23, before the owner's hand test. Next: the hand test here, and testing on the corporate computer |
| 5.9 | People, labels and task fields from the mods log, round 2: email, group and role for people, reference fields named in Settings, nested labels, and plant events | Built 2026-10-23, with decisions 19 to 22 as the owner took them; on GitHub 2026-10-23, before the owner's hand test. Next: the hand test here, and testing on the corporate computer |
| 5.10 | The visual overhaul, O1: design tokens, Fusion, the type ramp, the new inputs and buttons, the Fluent-style icons and the Classic look | Built 2026-10-24, with the others of the overhaul; on GitHub 2026-10-25, before the owner's hand test. Next: the hand test here, and testing on the corporate computer |
| 5.11 | The visual overhaul, O2: Show hints, keys in tooltips, and the Alt and Ctrl key tips | Built 2026-10-24, with the others of the overhaul; on GitHub 2026-10-25, before the owner's hand test. Next: the hand test here, and testing on the corporate computer |
| 5.12 | The visual overhaul, O3: the capture window's new layout | Built 2026-10-24, with the others of the overhaul; on GitHub 2026-10-25, before the owner's hand test. Next: the hand test here, and testing on the corporate computer |
| 5.13 | The visual overhaul, O4: Edit task, Edit selected and the person and label forms, and the date field | Built 2026-10-24, with the others of the overhaul; on GitHub 2026-10-25, before the owner's hand test. Next: the hand test here, and testing on the corporate computer |
| 5.14 | The visual overhaul, O5: the browse window's top bar, sidebar, command bar, empty detail pane, capacity colours and timeline legend | Built 2026-10-24, with the others of the overhaul; on GitHub 2026-10-25, before the owner's hand test. Next: the hand test here, and testing on the corporate computer |
| 5.15 | The visual overhaul, O6: Settings as cards, with Look and Show hints | Built 2026-10-24, with the others of the overhaul; on GitHub 2026-10-25, before the owner's hand test. Next: the hand test here, and testing on the corporate computer |
| 5.16 | The visual overhaul, O7: the command palette (Ctrl+K) | Built 2026-10-24, with the others of the overhaul; on GitHub 2026-10-25, before the owner's hand test. Next: the hand test here, and testing on the corporate computer |
| 5.17 | The capture window and double-click, from the mods log, round 3: the pinned window, OneNote's keys and 20 px indents in the content text, and double-click opening Edit | Built 2026-10-25, with decisions 53 to 60; on GitHub 2026-10-25, before the owner's hand test. Next: the hand test here, and testing on the corporate computer |
| 5.18 | Plant events in Parse and populate, from the mods log, round 3 | Built 2026-10-25, with decisions 53 to 60; on GitHub 2026-10-25, before the owner's hand test. Next: the hand test here, and testing on the corporate computer |
| 5.19 | The visual overhaul, O8: the task page's fields in a grid, from the mods log, round 3 | Built 2026-10-25, with decisions 53 to 60; on GitHub 2026-10-25, before the owner's hand test. Next: the hand test here, and testing on the corporate computer |
| 5.20 | The pinned window's task picker, capture types, path or link box, descriptions and Outlook button, and Outlook's security guard in words, from the mods log, round 3 (M0062 to M0064) | Built 2026-10-25, with decisions 61 to 63; on GitHub 2026-10-25, before the owner's hand test. Next: the hand test here, and testing on the corporate computer |
| 5.20.1 | pypdf 6.21.2, for the second Frogbot scan's findings | Built 2026-10-25; on GitHub 2026-10-25. Next: the corporate computer, with `release-5-20-1-frogbot-fix.md` |
| 5.21 | The visual overhaul, O9: the task page as the task's story (decisions 64 to 69) | Built 2026-10-25 and hand-tested by the owner; on GitHub 2026-10-26. Next: testing on the corporate computer |
| 5.22 | The visual overhaul, O10: the sidebar redrawn, with an icon per view, small folding headings and counts only where they ask for something (decisions 79 to 84) | Built 2026-10-26, from the approved mock; on GitHub 2026-10-26, before the owner's hand test. Next: the hand test here, and testing on the corporate computer |
| 5.23 | Review and planning, from the mods log, round 2 (stage 8): the Activity view and Priorities (decisions 23 and 70 to 78), schema version 9 | Built 2026-10-26, from the approved mock; hand-tested by the owner and on GitHub 2026-10-26. Next: testing on the corporate computer |
| 5.24 | The owner's comments on 5.23: Find and Fold subtasks on the Priorities board, Group by on the task tree, and Collapse a level and Expand a level on every view whose rows nest | Built 2026-10-26; hand-tested by the owner and on GitHub 2026-10-26. Next: testing on the corporate computer |
| 5.25 | The notes page: each task's notes as one page, edited in place on its task page, with captures adding their blocks (the notes page plan's decisions 95 to 120), schema version 10 | Built 2026-10-27, without a mock, after the Qt sample; hand-tested by the owner and on GitHub 2026-10-27. Next: testing on the corporate computer |
| 5.26 | Checklists on the notes page and the Checklist summary (the notes page plan's decisions 85 to 91 as redone, and 121 to 123), and the format bar on the notes | Built 2026-10-27; hand-tested by the owner and on GitHub 2026-10-27. Next: testing on the corporate computer |
| 5.26.1 | Fixes: each email in a capture its own .msg file and attachments with unique names (two emails had both gone to email.msg, losing the first), and a file path with Copy as path's quotes, or one DocRepo can't find, in the content text | Built 2026-10-27; on GitHub 2026-10-27, before the owner's hand test. Next: the hand test here, then testing on the corporate computer with `release-5-26-1-test.md` |
| 5.27 | Pictures, files and tables on the notes page (the notes page plan's decisions 124 to 129, with the hard rules' change in 127), and Notes in its frame (decision 130), schema version 11 | Built 2026-10-27; hand-tested by the owner and on GitHub 2026-10-27. Next: testing on the corporate computer with `release-5-27-test.md` |
| 6 | Document tracking: change checks, diffs, replaced saved copies, and relinking moved files | Not started |

## Decisions

- Python 3.12.6, the same version as on the corporate computer.
- Packages: the seven approved in the first version's Phase 0, at the same versions, pinned in `requirements.txt` with their dependencies. extract-msg isn't used; `.msg` files are read through Outlook. RapidFuzz (MIT, no dependencies) joined with release 5.16, the owner having approved reputable packages for the overhaul, to be checked by the corporate JFrog scan; without it, the command palette uses the standard library.
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

## Release 5.3.1: PowerPoint text without python-pptx (2026-10-21)

The corporate computer's JFrog scan flagged Pillow 13.0.0 under the company's copyleft license policy as GPL-2.0. Pillow's own license is MIT-CMU, but its license file carries the full GPL-2.0 text for the FreeType library it bundles, which is offered under the FreeType License or GPL-2.0. DocRepo never used Pillow: python-pptx required it, and loaded it on import.

- `docrepo/extract.py`: `.pptx` files are read with the standard library (`zipfile`, `xml.etree.ElementTree`): the slides in `presentation.xml`'s order, each shape's text (inside groups too), tables row by row, and each notes page's body placeholder. A part with a DTD, or bigger than `MAX_PART_BYTES` (64 MB) unpacked, is refused, so a file built to trick the reader gets the status "error".
- The text is python-pptx's, compared on made-up decks, with two changes: text inside grouped shapes is read (python-pptx's top-level shapes missed it), and a line break inside a paragraph is a new line rather than a vertical tab.
- `requirements.txt`: python-pptx, Pillow and XlsxWriter (python-pptx's other dependency) are gone. lxml and typing_extensions stay for python-docx.
- `tests/test_extract.py`: the test deck is written by hand, as the test PDF is, and a deck with a DTD and an oversized part are refused (634 pass in all, 1 skipped, with the three packages uninstalled).

## Release 5.4: big features from the mods log, round 1

Stage 4 of the round 1 plan: links as files (M0001), email layer 0 (M0005, M0024) and the timeline view (M0019, with M0015's sorting by label). Email layer 0 and the timeline were mocked first and approved (decisions 9 to 13, as recommended). The meetings capture type (M0023) and Task an agent (M0017) are design work for later.

### Links as files

- `docrepo/links.py` (M0001): `is_link`, `link_name` and `NO_TEXT`. A link on a line of its own, or from **Add link…**, is a file row and then a document whose original is the address, with no text, no saved copy and no Extract information.
- `docrepo/save.py`: a link is matched to its document exactly, gets `text_status` none, is never read or copied, and doesn't make a capture file_path. `docrepo/text.py` (`is_file_line`, `plain_text`) and `docrepo/parse.py` (`prep_text`) leave link lines out, as they do file path lines; the mockup's `model.js` and `parse.js` do the same, and every export is unchanged.
- `docrepo/model.py`: the Files kind Link. `docrepo/pages.py`: a link's line in `Task.md`, as code. `docrepo/detail.py`: Copy link in the Files tab, and a link's page.
- `docrepo/edits.py` (`source_of`) and `docrepo/ui/explorer.py`: File Explorer is never handed a link, which it would open in the browser.
- `docrepo/ui/capture_window.py`: link rows, **Add link…**, and link lines in the content text. `docrepo/ui/browse_window.py`: **Copy link** on a link's page and from `copylink:`, double-click copies a link, and the Documents view marks links.
- `GLOSSARY.md`: Link. `docrepo/ui/help_text.py`: the files and content notes, from the mockup's `HELP`.
- `tests/test_links.py`: 8 tests.

### Email layer 0

- `docrepo/layer0.py`: `find` (an email's parts: attachments, the body's links, the body's pictures, and what it left out), `read_body` (Python's `html.parser`), `unwrap` (Safe Links), `line` (the layer 0 line) and `size_text`.
- `docrepo/outlook.py`: the HTML body (`HTMLBody`, read field by field like the rest), and every attached file with its size, content ID (`PR_ATTACH_CONTENT_ID`) and hidden flag. Hidden attachments are no longer dropped here; layer 0 decides.
- `docrepo/save.py`: `Attachment` gains `size`, `content_id` and `hidden`; `EmailItem` gains `html`; `FileRow` gains `part`, `of` and `keep`, and `described`; `email_rows` and `email_layer0_line`. An email's own row makes no document; each kept part does. `email.msg` is now saved for every email, including one with no attachments, which before was skipped.
- `docrepo/db.py` (schema version 5): `captures.email_layer_0`. `docrepo/captures.py`, `docrepo/model.py`: the field, and `email_layer_0` in `capture.md`. `docrepo/detail.py`: the capture page's Email layer 0 row.
- `docrepo/ui/capture_window.py`: the email's row with its layer 0 line, a row per part with Keep, indented under it.
- `docrepo/diagnose.py`: the troubleshooting report counts attachments with a content ID, and what layer 0 would find in the body.
- `tests/test_layer0.py`: 4 tests; `tests/test_outlook.py` and `tests/test_save.py` updated.

### Timeline

- `docrepo/timeline.py`: `build` (groups and rows for a range, grouping and filters), `Timeline` (its scale: months and week labels), `default_start`, `step` and `tooltip`. Ported from the mockup's `timeline.js`.
- `docrepo/ui/timeline_view.py`: `TimelineChart` (painted with QPainter: names, bars, hatching, diamonds, dots, Today, tooltips, clicks) and `TimelineView` (its controls, the card, the legend, the undated tasks). `docrepo/views.py`: the Timeline view under Plan. `docrepo/ui/browse_window.py`: the view in the middle and right panes, opening a task or an Update from it.
- `docrepo/ui/widgets.py`: `CheckMenuButton` makes room for its text, which the menu's arrow had clipped.
- `tests/test_timeline.py`: 4 tests (651 pass in all, 1 skipped).

## Decisions (release 5.4)

- Decision 5 of the round 1 plan, as the owner chose: a link is only ever copied. DocRepo has no Open link anywhere, and its pages show addresses as text.
- Only http and https lines are links; anything else on a line stays text.
- A link's name is the file its address names, else its host, so SharePoint's long sharing links still read as "Pump datasheet.docx".
- A capture whose only files are links is typed: its source names how it came in, and a link is pasted text.
- Decisions 9 to 13 of the round 1 plan, as recommended: an email's parts have their own rows and descriptions, the email's row none, and an unticked part stays only inside `email.msg`; pictures are kept in the attachments folder, with Save a copy but no Extract information, and those under 10 KB start unticked; the layer 0 line goes in `capture.md` and on the capture page, not the content text; the timeline's first click shows a card, the second opens the task; nine weeks or six months, grouped by top-level task, label or person.
- Decision 10 said hidden pictures are signatures. Outlook hides most pictures in the body, so layer 0 uses the body instead: a picture is an attachment the body shows by its content ID, and a hidden attachment the body doesn't show is left out. Small pictures, logos and signatures among them, start unticked. The corporate test checks this on real emails.
- The timeline opens a task in the task tree (its second click, a double-click or Open task), as other views that aren't lists of tasks do; the Timeline view is one click away on the left.
- Email layer 0 comes before phase 6 (document tracking), as running stage 4 decided (the plan's decision 6).

## Release 5.5: small fixes from the mods log, round 2

The owner's second mods log copy (M0025 to M0052, 2026-10-21) is planned in the parent workspace's `docs/mods/round-2-plan.md`. This release is its stage 5: M0035, M0041, M0047, M0043 (its first part) and M0050. Its item 24 (M0027, signature pictures) waits for release 5.4's corporate test.

- `docrepo/ui/widgets.py` (M0035): `FormDialog`, the base of the browse tool's forms: Ctrl+Enter (`SAVE_KEYS`) calls the form's `save`, and `reject` asks first (`ask_discard`) when `changed`, by `snapshot` against `mark_clean`. `docrepo/ui/task_forms.py` (Edit task, Edit selected, a label's matching tasks) and `docrepo/ui/dialogs.py` (a person, a label) build on it, each with a line saying so by its buttons. `docrepo/ui/browse_window.py`: Ctrl+Enter and Esc in a capture's Edit, which asks before dropping a change.
- `docrepo/save.py` (M0041): `default_description`. Saving no longer asks for descriptions; an empty one gets the default, naming the new task or the picked task (`holder_title`). `docrepo/ui/capture_window.py`: each description box's placeholder shows its default (`_default_desc`), following the task, the capture types and Title. The `file:` focus for a missing description is gone.
- `docrepo/mods.py`, `docrepo/ui/mods_panel.py` (M0047): `edit_entry` and `ModEntry.edited`; a heading ends "· edited YYYY-MM-DD". The panel's Edit, Save M00nn and Cancel edit; in the capture window, Esc on the panel stops an edit before going back.
- `docrepo/ui/browse_window.py` (M0043): `double_click`.
- `docrepo/views.py`, `docrepo/ui/browse_window.py` (M0050): `due_this_week`, `_today_due_rows`, `set_today_mine` and `TODAY_MINE_KEY`.
- `docrepo/ui/help_text.py`: the files note, from the mockup's `HELP`. The mockup's `capture.js` (the default description and its placeholder) and `today.js` (Due in the next 7 days) show the same; `browse-mockup.html` was rebuilt locally, not republished. Its exports are unchanged.
- `README.md`: everyday use.
- `tests/`: new tests in `test_save.py`, `test_capture_window.py`, `test_prompts_mods.py`, `test_views.py` and `test_browse_window.py`; `test_layer0.py` no longer expects a missing description to stop a save (658 pass in all, 1 skipped).

## Decisions (release 5.5)

- Decisions 14 and 15 of the round 2 plan, and item 22's double-click, as the owner chose (2026-10-21): an empty description becomes "*task* – Attached document – *file name*" ("Attached link", "Attached picture"), or the file name with no task; Today's Due in the next 7 days shows everyone's tasks, with a Mine only switch kept in docs.db; double-clicking a task opens or closes its subtasks.
- A file already tracked still starts with its description in the box. Only an empty box gets the default, which becomes the document's description.
- Saved copies were already named from the file's own name, so the default descriptions don't lengthen them.
- An edited mods log entry keeps its ID and time, and its heading keeps only the day of the latest edit. Only open entries can be edited, since the panel lists only those.
- A form asks before closing only when something changed. Edit selected counts as changed when anything is set, and the matching tasks when any is ticked.
- With nothing on Today, "Nothing on Today" comes before Due in the next 7 days.

## Release 5.6: the capture window and Today, from the mods log, round 2

Stage 6 of the round 2 plan: M0037, M0042, M0046 and M0048's phase 1 (the capture window), M0039 and M0040 (quick tasks), and M0036 and M0026 (keys and Find). It was mocked in the browse tool mockup first, and the owner approved the mock (decisions 32 to 36, as recommended).

- `docrepo/ui/capture_window.py` (M0037, M0042, M0046, M0048): 940 px wide. The capture types' line wraps (`FlowLayout`) and holds Agenda: the **Today** button (`today_on`, `set_today`) and the agenda picker, which no longer offers Today. Title, the content text and Parse and populate sit left of the found list (`main_layout`, under it below `NARROW`), which shows a placeholder until Parse and populate runs, and Clear. Expand (`toggle_expand`, F11) hides `lower` (the files, Copy prompt, the summary and the New task and Update fields) behind a line saying so, and fills the screen. Alt+N, Alt+T, Alt+U, Alt+A and Alt+D (`_alt_type`, `_alt_agenda`, `_alt_today`), and F1. The draft's agenda is `_targets()`; `_quick()` marks a quick task. `open_with_hotkey("today")`.
- `docrepo/quick.py` (M0039): the built-in Quick tasks, `parent_id`, `ensure_parent` and `is_parent`. `docrepo/save.py`: `CaptureDraft.quick`; a new task with no task picked that goes on Today goes under Quick tasks; `quick_task_draft`, `add_quick_task` and `note_to_task`; Save's message names the parent of a quick task.
- `docrepo/agenda.py` (M0040): `set_note` and `make_task`. `docrepo/edits.py`: `edit_today_note`, and `edit_task`'s `parents` (`tasks.set_parents`). `docrepo/ui/task_forms.py`: Edit task's Parents field (`put_under`, `remove_parent`), with the task picker from the browse tool.
- `docrepo/ui/browse_window.py` (M0036, M0026, M0039, M0040): the letters N, T, U, A, D and E; **Keys** and F1 (`docrepo/ui/keymap.py`, `KeyMapDialog`); Find in this view (`open_find`, `close_find`, `_apply_find`; `views.find_text`; `tree_view.DIM_ROLE` fades a parent kept for context); Ctrl+Shift+F to the search box. Today's box has a Task and Note switch (`today_kind`, `add_today_item`, `add_today_task`); its items have Edit and Note, or Edit and Make it a task (`edit_today_note`, `make_today_task`; `ask_text` is replaceable in tests).
- `docrepo/timeline.py`: Quick tasks itself isn't named among the undated tasks.
- `docrepo/hotkey.py`, `docrepo/config.py`, `docrepo/app.py`, `docrepo/ui/settings_view.py` (M0036, M0039): `today_hotkey`; `hotkey.SUGGESTED` and Settings' Use the suggested keys.
- `docrepo/ui/style.py`: the Today button, the divider, and the found list before it has found anything. `docrepo/ui/widgets.py`: `set_filled` sets other style properties too.
- `docrepo/ui/help_text.py`: the types, agenda, content and parse notes, from the mockup's `HELP`. The mockup's `files.js` and `examples.md` gain `today_hotkey`; the regenerated file's checksum equals `exportChecksum("examples.md")`.
- `GLOSSARY.md`: Quick task, Quick tasks. `README.md`: everyday use.
- `tests/`: `test_quick.py`, and new tests in `test_capture_window.py` and `test_browse_window.py` (671 pass in all, 1 skipped). The capture window's test fixture now hides its window before deleting it: a window left showing took focus in a later test and read a closed database.

## Decisions (release 5.6)

- Decisions 16 to 18 of the round 2 plan, as the owner chose: a quick task is a real task under the built-in Quick tasks; one letter per topic, which moves the browse tool's N, A, G and T to T, N, A and D; Ctrl+Shift and the letter for the global hotkeys (the owner's choice over Ctrl+Alt, knowing Outlook uses some of them); Ctrl+F finds in this view and Ctrl+Shift+F searches everything.
- Decisions 32 to 36, from the approved mock, as recommended: the 940 px window with Agenda on the capture types' line and the found list beside the content text; Expand on F11 and a button; Today's box makes a quick task unless switched to Note, and Quick tasks itself stays off the timeline; Find matches a task's ID, title, description, current status, labels and people, and isn't on the timeline or capacity; the direct hotkeys stay off until set, with the suggested keys a click away.
- Quick tasks is known by its creator, "DocRepo", rather than a stored ID, so it survives a rename; a discarded one is replaced the next time a quick task needs it.
- A quick task from Today's box is a capture of its one line, as from the capture window, so its story begins with the capture and the line is its description. Make it a task saves that capture, then moves the note's item to the new task, keeping when it was added.
- Only known people are kept from a quick task's line: a one-liner doesn't add people.
- The capture types' line wraps instead of scrolling; Expand's button says Expand and Back, since Segoe UI has no arrow glyphs for it.

## Release 5.7: formatted content text, from the mods log, round 2

Stage 10's item 36 of the round 2 plan (M0045, round 1's item 17): the first half of stage 10. The second half, release 5.8 (items made by `@`, `#` and `**` in any capture, and meeting mode), is mocked for the owner's review before it's built.

- `docrepo/markup.py` (new): the format (SPEC 6.5). `escape`, `escape_inline` and `escape_line_start` write plain text as markup that reads as the same text; `from_list_lines` turns release 5.1's "- item" lines into real list items; `marks_text` writes a line from its segments, changing only the marks that change, so stars never run together into other marks; `to_plain`, `is_formatted`, `inline_html`, `to_html` (paragraphs and nested lists), `to_line_html` (lines, for the raw text log), `clip` (by lines) and `without_title_line`.
- `docrepo/ui/rich_edit.py` (new): `RichEdit`, a QTextEdit with the formatting keys and lists (Tab, Shift+Tab, Enter on an empty item, Backspace at an item's start, "- " and "1. " to start one); its keys are taken before any shortcut (`ShortcutOverride`), so they work in the browse tool too. `value()` gives (markup, True) when anything is formatted, else (plain text, False); `plain()`, `set_value`, `remove_line`, `clear` (which drops the formatting the cursor was in). Pasted HTML is read through a QTextDocument (`document_markup`), keeping only the marks and lists, with Word's and Outlook's `mso-list` paragraphs read by `paste.html_to_text` (`paste.has_mso_list`). `FormatBar`: B, I, U, S, Highlight (with Yellow, Green, Pink and No highlight), bullets and numbers, checked to show where the cursor is.
- `docrepo/db.py`: schema version 6, `captures.formatted`. `docrepo/model.py`: `Capture.formatted`. `docrepo/captures.py`: `add_capture(formatted=)`, `content_format: "markdown"` in capture.md, and `plain(c, content)` for a capture's words.
- `docrepo/save.py`: `CaptureDraft.formatted` and `words()`. capture.md keeps the markup, with an email's text escaped; the checks, the title, a new task's title and description, Parse and populate's title and an agenda note read the words.
- `docrepo/edits.py`: `edit_capture(formatted=)` sets or clears `formatted`, and the title comes from the words. `docrepo/search.py`: a capture is indexed by its words.
- `docrepo/stories.py`: `RawItem.formatted`; `words_of`; a formatted capture's body keeps its markup, without its file lines, and without its first line when that's its title. `docrepo/detail.py`: the raw text log shows it with `markup.to_line_html` and folds it by lines; the capture page with `markup.to_html`.
- `docrepo/ui/capture_window.py`: `ContentEdit` is a `RichEdit` (dropping files and emails as before), with the `FormatBar` above it. The draft takes `value()`; Parse and populate reads `plain()`, and Copy prompt sends the markup, as the browse tool's does; removing a pasted path line keeps the rest's formatting; Make it a task shows the capture's formatting. `docrepo/ui/browse_window.py`: the capture page's Edit uses a `RichEdit` and `FormatBar`. `docrepo/ui/style.py`: `FORMAT_BAR_STYLE`, in both windows.
- `docrepo/ui/help_text.py`: the content note, from the mockup's `HELP`. The mockup's exports are unchanged.
- `tests/`: `test_markup.py` and `test_formatted.py`, and new or changed tests in `test_capture_window.py`, `test_browse_window.py` and `test_db.py` (702 pass in all, 1 skipped).

## Decisions (release 5.7)

- Decision 41 of the round 2 plan: bold, italic, underline, strikethrough, three highlight colours and lists; no text colours or sizes. Decision 43: release 5.7 first, then 5.8 mocked before it's built.
- Formatted content text is kept as Markdown in capture.md, which stays readable in any editor and is what Copilot reads best; HTML would have needed cleaning and isn't readable. Underline and highlights have no Markdown of their own, so they're the HTML tags most Markdown readers know (`<u>`, `<mark>`).
- Only a capture with formatting is kept as markup, and says so (`content_format`, `formatted`). Plain captures, and every capture before release 5.7, stay plain text, so nothing old is read as markup and nothing needs converting.
- Everything that reads content text for its words reads it without the marks, so a star never reaches a title, search or Parse and populate. A list item keeps its "- " or number there, as pasted lists have since release 5.1.
- A backslash escapes only the characters that would otherwise mean something; before anything else it's a backslash, so a path such as `C:\Docs\a.pdf` reads the same in capture.md as on screen.
- A highlight pasted in another colour becomes the nearest of the three, and a near-white background none.

## Release 5.8: items and meeting notes, from the mods log, round 2

Stage 10's item 35 of the round 2 plan (M0048 phase 2, M0049, M0052, with M0023), the second half of stage 10. It was mocked in the browse tool mockup first, and the owner approved the mock (decisions 37 to 40, 42 and 44 to 52).

- `docrepo/items.py` (new): the operators (`scan`): `@` people by name or alias (a new name otherwise), `@L.`, `@__`, `#` tasks by title or ID, and the `**` types, kept as `@[Name](P003)` and `#[Title](T000012)` in capture.md (`store`, `unstore`, `refs_of`; `Names` prefers the IDs a capture had or the window picked). `clean` gives a line without its operators, `read` the lines, blocks, headings and items, with where each goes and the cards' changes; `self_fields`, `line_kinds`, `parse_text`, `discussed`, `typing`, `options` and `words`. `docrepo/markup.py`: `replace_spans`, which puts the IDs into a formatted capture's markup, keeping its marks.
- `docrepo/db.py`: schema version 7, `captures.from_notes`, `item` and `meeting`. `docrepo/model.py`: those on `Capture`. `docrepo/captures.py`: `add_capture(from_notes=, item=, meeting=)`, capture.md's `meeting`, `items`, `from_notes` and `item`, and `plain` shows names, not IDs.
- `docrepo/save.py`: `CaptureDraft.meeting`, `meeting_name`, `agenda_ticks`, `item_overrides`, `refs` and `lines()`; `meeting_case`, `meeting_name`, `item_names`; Save makes the meeting, the capture and then each item (`_save_items`), closes the discussed agenda items, writes each capture.md with IDs (a person the save added too), and says what it made. A new task's own first line fills its people and parents, and gives its title without the operators; a capture's title reads its words without operators.
- `docrepo/edits.py`: `edit_capture` takes the text as shown and keeps each `@` and `#` with its ID again, the capture's own IDs first; meeting notes and items keep their titles.
- `docrepo/stories.py`, `docrepo/detail.py`: the raw text log's Decision and "from the notes of", an item's block only when it's more than its line, meeting notes in full; the capture page's What Save did names the meeting, the items and the agenda items discussed, and shows names, not IDs.
- `docrepo/ui/items_panel.py` (new): `OperatorHighlighter` (colours that are never saved), `ItemCards` and `ItemCard`, `AgendaPanel`, `RefPopup` and `where_text`.
- `docrepo/ui/capture_window.py`: the items read again 250 ms after you stop typing (`read_items`), the cards (their changes in `item_ov`), the `@` and `#` list (`_ref_list`, `_pick_ref`; `ContentEdit.list_keys`), Parse and populate reading only the lines that aren't items, Meeting notes (`toggle_meeting`, Alt+M; the meeting row, `_fill_meet_name`, the agenda panel, `start_from_agenda`, `agenda_ticks`), and the draft that keeps itself (`keep_draft`, `restore_draft`, `forget_draft`, `clear`; `System\capture-draft.json`). `docrepo/ui/browse_window.py`: Meeting notes on an open meeting's page and in the Agendas view, M on the selected task, and Edit showing names. `docrepo/ui/keymap.py`: M. `docrepo/ui/style.py`: the cards, the panels and the list. `docrepo/ui/help_text.py`: the items, meeting notes and agenda panel notes, from the mockup's `HELP`.
- `tests/`: `test_items.py`, `test_meeting.py` and `test_meeting_window.py`, and `test_db.py` (731 pass in all, 1 skipped).

## Decisions (release 5.8)

- Decisions 37 to 40 and 42 of the round 2 plan (the operators everywhere, `**` rather than one star, the rules, no lead without `@L.`, Quick tasks for a task with nowhere else to go, the three meeting cases, titles and descriptions, cards that can be changed), and 44 to 52 as mocked: every `@` makes a task; a heading lasts until the next heading; plain lines under a heading are one note; a task item under a task item is its subtask; people come only from the operators; several `#` tasks mean a capture on each; titles drop operators at a line's ends; meeting notes are named after their meeting and Start from the agenda puts notes on their own first; the draft keeps itself in the data root.
- Names are matched by name or alias, the longest first, and a picked or kept ID comes ahead of the lists, so two tasks with the same title, or a renamed person, stay right. A name that isn't on the people list is a new person only when the capture is saved.
- An item's capture keeps its block as written, so its raw text log entry reads as the notes did; a one-line item shows only its title there, which already says it.
- The colours in the content text come from a syntax highlighter, so they're never part of the text's formatting and never saved.
- The draft goes in the data root (`System\capture-draft.json`), one of the three places DocRepo writes; saving or Clear empties it rather than deleting it.

## Release 5.9: people, labels and task fields, from the mods log, round 2

Stage 7 of the round 2 plan (items 28 to 31: M0031, M0033, M0038, M0034, M0051, M0028), with decisions 19 to 22. It wasn't mocked first: the owner took the decisions from the plan.

- `docrepo/db.py`: schema version 8: `email`, `person_group` and `role` on people, `parent` on labels, `plant_event` on tasks, and `task_references`. `docrepo/model.py`: `Person.email`, `group` and `role`; `Label.parent`; `Task.plant_event` and `references`; `groups`, `group_people`, `label`, `parent_label`, `sublabels`, `is_parent_label`, `label_path` and `plant_events`.
- `docrepo/people.py`: `add_person` and `update_person` take email (checked as an address), group and role; `add_label` and `update_label` take the parent label, one level only. `docrepo/tasks.py`: `create_task(plant_event=, references=)`, and `update_task` logs Plant event and each reference field by its name. `docrepo/bulk.py`: Edit selected sets Plant event. `docrepo/config.py`: `reference_fields`.
- `docrepo/parse.py`: Parse and populate reads each reference field (`parse_capture(refs=)`), from the mockup's `parse.js`; `tests/fixtures/test-vectors.md` gains a Reference fields section, read with two made-up field names. `docrepo/items.py`: `**event.` makes a task with Plant event ticked, its end date its Due (as the mockup's `items.js`).
- `docrepo/timeline.py`: Group by group and by a parent label (`group_choices`), the plant events in view (`Timeline.events`, `bands`), and the line that names a plant event a date falls in (`during`, `during_text`). `docrepo/ui/timeline_view.py`: the bands, their tooltip and the legend.
- `docrepo/pages.py`, `docrepo/detail.py`, `docrepo/search.py`: Plant event and the reference fields in `Task.md`, on the task page and in search; a person's email, group and role; a label's parent, and a parent label's sublabels and their tasks.
- `docrepo/ui/browse_window.py`: the People view's Group and Role columns, Copy email and Copy (emails and reference fields), the Labels view as a tree, the lists' Group by a parent label, capacity's Group by group and plant event weeks, and the forms' new fields. `docrepo/ui/widgets.py`: `CheckMenuButton` sets (a group's people, a parent label's sublabels), `label_filter` and `people_filter`, and label pickers with paths. `docrepo/ui/dialogs.py`: the person form's Email, Group and Role, and the label form's Under. `docrepo/ui/settings_view.py`: Reference fields. `docrepo/ui/task_forms.py`: Edit task's Plant event, reference field boxes and plant event line; Edit selected's Plant event. `docrepo/ui/capture_window.py`: New task's Plant event, Update's under More fields, a box for each reference field under More fields (`_sync_refs`), and the plant event line under the dates. `docrepo/ui/help_text.py`: the Plant event and reference field notes, from the mockup's `HELP`.
- `docrepo/sample/sample-data.json`: made-up email addresses (`example.com`), groups and roles for the sample people.
- `tests/`: release 5.9's tests in `test_people_agenda.py`, `test_tasks.py`, `test_timeline.py`, `test_capture_window.py`, `test_items.py`, `test_detail.py`, `test_pages.py`, `test_search.py`, `test_bulk.py`, `test_browse_window.py` and `test_parse_vectors.py` (753 pass in all, 1 skipped).

## Decisions (release 5.9)

- Decisions 19 to 22 of the round 2 plan: one group per person; reference fields named in Settings, so the public code names no company system; labels nest one level; a Plant event tick box and the `**event.` operator, with no reading of event words.
- A `**event.` item's end date is its Due: its own name ("Spring outage") is an event word, so Parse and populate reads the date as a Deadline, which for a plant event is the end of it.
- A reference field's value is any text; Parse and populate reads only a number after its name. Search finds a value, or the name and value.
- DocRepo never sends email: it keeps addresses and copies them, joined by "; " for Outlook's To box.
- A plant event's band and the line under the dates use the same windows as the capacity calendar, so a routine plant event counts each time it comes round.

## Releases 5.10 to 5.16: the visual overhaul (2026-10-24)

The overhaul's stages O1 to O7, built together at the owner's request, from the plan, decisions 1 to 18 and the assessment of release 5.9's windows in the parent workspace (`docs/ui-design/`). O3 (the capture window) was mocked and approved; O4 and O5 were built from the assessment without mocks of their own.

- **O1, 5.10:** `docrepo/ui/tokens.py`: every colour (light now, dark reserved), the type ramp, sizes and spacing, and from them the palette, the style sheet (`qss`) and the pages' HTML styles (`CSS`). `docrepo/ui/style.py`: `apply_look` (Fusion, the palette, the font, and the style sheet once on the application), `style_sheet` and `page_css`, and the Classic look (release 5.9's `CLASSIC_STYLE`). `docrepo/ui/icons/` and `docrepo/ui/icons.py`: the icons. `docrepo/config.py`: `look` and `show_hints`. `docrepo/ui/tree_view.py`: the top-level task's colour as an edge on its own row, the accent edge on the selected row, 28 px rows and a 16 px indent.
- **O2, 5.11:** `docrepo/ui/look.py`: `LOOK`, `Help` and `KeyBadge` (shown only with Show hints, or in the Classic look), `set_hints`, `tip`, `with_key` and `KeyTips`, with one application-wide watcher for every window. The **i** buttons (`InfoButton`) are gated the same way, and field labels' own hints too. Help text in the capture window, the forms, the items and agenda panels, the browse tool's view notes, Capacity and the Timeline became `Help`.
- **O3, 5.12:** `docrepo/ui/capture_window.py`: the new `_build` and `_build_footer` (row 1 of capture types as toggles, Today, Agenda and three icon buttons; the task picker with State beside it; the outlined editor; Parse, Attach and the Understood line; the items' column only when there's something in it; the footer with More and Save), Clear with Undo (`_draft_data`, `_apply_draft`, `_undo_clear`), the window fitting its content (`_fit`), sentence-case group headings, and item cards striped by their top-level task (`docrepo/ui/items_panel.py`: `task_colour`). `docrepo/ui/rich_edit.py`: the format bar's icons and tooltips.
- **O4, 5.13:** `docrepo/ui/widgets.py`: `DateField` (words when you're not in it, the calendar button inside, 176 px; `parse_day`), `section`, `dialog_buttons` and `fit_dialog`. `docrepo/ui/task_forms.py`: Edit task in sections, Edit selected and the label's matching tasks on the same rules. `docrepo/ui/dialogs.py`: the person and label forms with labels above their fields.
- **O5, 5.14:** `docrepo/ui/browse_window.py`: the top bar, the sidebar's folding groups (`_render_nav_new`, `_nav_clicked`, `browse_nav_folded`), the command bar (`_action` with icons and keys; More), the detail pane hidden while nothing is picked, Capacity's colours on one line, and Show hints from More. `docrepo/ui/timeline_view.py`: the legend under the controls.
- **O6, 5.15:** `docrepo/ui/settings_view.py`: the settings cards (`_card`, `_row`), with Look and Show hints.
- **O7, 5.16:** `docrepo/ui/palette.py`: `Command`, `rank` (RapidFuzz, else difflib) and `CommandPalette`; `palette_commands` and `open_palette` in both windows, on Ctrl+K and in More. `docrepo/ui/keymap.py`: Ctrl+K and the held Alt and Ctrl keys.
- **The mockup and its exports:** `settings.json`'s example gains `look` and `show_hints`; the browse tool mockup's capture window shows the overhaul beside release 5.9's.
- `tests/`: `test_look.py` (the tokens' contrast, the style sheet, Show hints, the date field, the palette, key tips, and the new look's capture window, browse tool and Settings); the capture, meeting, browse and config tests follow the new labels (762 pass in all, 1 skipped).

## Decisions (releases 5.10 to 5.16)

- The owner's decisions 1 to 18 (`docs/ui-design/decisions.md` in the parent workspace), with three changes on the way:
  - **Icons:** drawn for DocRepo in the style of Fluent UI System Icons, as in the approved mock, rather than downloaded. The official set (MIT) can replace them by giving its files the same names.
  - **The Classic look** restores release 5.9's colours, fonts, hints and key badges, on the new layouts: keeping both layouts would double every window's code, and every view is converted at once.
  - **The command palette** uses RapidFuzz, with the owner's approval of reputable packages for the overhaul, and falls back to the standard library.
- The style sheet is set once on the application: per-window sheets made each window and dialog parse it again.
- The key tips need no key of their own: one watcher on the application hands Alt and Ctrl to the window that has the keyboard, and lets every other event through.
- The capture window fits its content from 380 px to 88% of the screen, keeping its top where it is; Edit task fits up to 85% and scrolls only on a short screen.
- Help that guards against a mistake stays in view: the mods log's note to leave out names and work details, and the import's note that the workbook is only read.
- Without RapidFuzz, the palette matches a word whose letters come in order ("edt" finds Edit), so the tests pass either way.
- Left for later: the formatting buttons only on hover, filter chips and Display options in each view's header, row actions on hover, a marker tooltip for auto-filled fields, Capacity's 80% and 100% as settings, and grey for a person who is away (DocRepo doesn't record time away yet).

## Releases 5.17 to 5.19: the third mods log (2026-10-25)

From the third copy of the mods log (M0053 to M0060), planned in the parent workspace's `docs/mods/round-3-plan.md` (items 39 to 43, decisions 53 to 60), and built straight away without mocks, at the owner's request. M0057 (Copy prompt) was only logged, and M0060 (people from emails) waits for the email reader's refinement, as the owner asked.

- **5.17, the pinned window (M0053, M0054):** `docrepo/ui/pin_window.py`: `PinWindow` (the top line with the task's name and the open and close buttons, a `ContentEdit` on the capture window's own document, the drop zone, the problem line, moving it by its top line) and `DropZone`, `what_was_added`. `docrepo/ui/capture_window.py`: the Pin icon and F12, `pin`, `unpin`, `toggle_pin`, `hide_pinned`, `_close_pin`; `show_capture` and a save bring a pinned capture back; `_fail` shows a drop's problem on the pinned window, and a save's in the full window; `read_drop` and `note_drag` take web links where the window asks for them (`links`), and `ContentEdit.take_links`. `docrepo/app.py`: the main hotkey unpins, and `pin_hotkey`. `docrepo/hotkey.py` and `docrepo/config.py`: `pin_hotkey`, off until set, with no suggested key. `docrepo/ui/icons/pin.svg`. Styles for `#pinWindow` and `#dropZone` in both looks.
- **5.17, the content text (M0055):** `docrepo/ui/rich_edit.py`: `INDENT` (20 px), `KEYS`, OneNote's keys beside release 5.7's, `to_paragraph` (Ctrl+Up and Ctrl+Down), `move_lines` and `_unit` (Alt+Shift+Up and Alt+Shift+Down, through the markup, as one undo step), and `FormatBar.show_on_use`. `docrepo/ui/keymap.py`: F12 and the content text's keys. `docrepo/ui/help_text.py`: the content text's help.
- **5.17, double-click (M0056):** `BrowseWindow.double_click` opens Edit task, a capture's Edit, a note on Today's Edit, or a person's or label's Edit…; documents as before.
- **5.18, plant events (M0059):** `docrepo/parse.py` (from the mockup's `parse.js`): `PLANT_EVENT`, `NOT_PLANT_EVENT`, `as_plant_event`, the `plant_event` field (New task and Update) and a "Plant event:" lead-in. `docrepo/items.py`: `SelfFields.plant_event`, and a task item that says "plant event". `docrepo/save.py`: the new task's own `**event`. The capture window ticks Plant event as a filled field and opens More fields.
- **5.19, the task page (M0058):** `docrepo/detail.py`: `facts_grid` and `text_block`; the task page's short fields in a grid of three, people first, then the long text.
- **The mockup and its exports:** `parse.js`, `items.js` and `export.js` (a Plant events section of the test vectors, 6 captures), and `settings.json`'s `pin_hotkey`; `test-vectors.md` and `examples.md` match the mockup's exports by checksum.
- `tests/`: `test_pin_window.py`; the content text's keys and line moves (`test_markup.py`); double-click (`test_browse_window.py`); plant events (`test_items.py`, `test_capture_window.py`, the vectors); `test_config.py`'s field list and the suggested hotkeys (777 pass in all, 1 skipped).

## Decisions (releases 5.17 to 5.19)

- Decisions 53 to 60 (the parent workspace's `docs/mods/round-3-plan.md`): 53, 55, 56 and 57 as recommended; 54, 58 and 59 as proposed, without mocks (decision 60).
- The pinned window shares the capture window's text document, so there's one capture, never two to keep in step; its box has no `@` and `#` lists.
- A web link dropped on the content text box is still typed in, as before; on the rest of the window, or the pinned window, it's added as a link.
- Ctrl+Shift+N isn't the content text's clear-formatting key, as OneNote's is: it's the suggested note hotkey, which Windows hands to DocRepo first.
- Alt+Shift+Up and Down move a line with the list items under it, as DocRepo reads a block, by rewriting the text through its markup in one edit, so one Ctrl+Z puts it back.
- The formatting buttons keep their room while hidden, so the text and the rows below never jump when the cursor leaves the box.
- "Plant event" and "major event" count only in the singular, and not before planning, prep, preparation, meeting, review or readiness, so "major events planning meeting" isn't one; the event words alone still don't (decision 22).
- The task page's people take a row of their own; the dates and the rest share rows, so a lone field doesn't leave a row nearly empty.

## Release 5.20: the pinned window, again (2026-10-25)

From M0062 to M0064 (the parent workspace's `docs/mods/round-3-plan.md`, items 45 to 48, decisions 61 to 63).

- `docrepo/ui/pin_window.py`, rebuilt at the same 320 × 236 px: the task picker on the top line (`task_button`, opening `CaptureWindow._open_picker` under it), the capture types (`type_boxes`), the content text, the landing row (`DropZone`, now a frame round `path`, a box for a typed or pasted path or link, and `outlook_button`), one description at a time (`desc`, with ‹ and ›; `describable`, `_step`, `_described`), and one line for what's been added, or two for a problem, cut with "…" and all of it in the tooltip (`status`, `message`, `two_lines`). `typed_path` takes File Explorer's quotes off. The whole window takes drops and lights the landing row.
- `docrepo/ui/capture_window.py`: `_open_picker(anchor)`, and a task picked from the pinned window puts the cursor back in its box. A capture type refused while pinned (Update with no task) says so there.
- `docrepo/outlook.py`: `refused_note` says what Outlook held back in words (text, sender, recipients), why, and the ways round it today; `FIELD_WORDS`.
- `docrepo/diagnose.py`: `antivirus_status` (Windows Security Center, through WMI, read-only) and `antivirus_text`, in the report's programmatic access section; the Click-to-Run registry place for the Trust Center's setting.
- `docrepo/ui/icons/chevron-left.svg`; styles for the pinned window's task button, small toggles and boxes, in both looks.
- `tests/`: the pinned window's types, typed paths and links, descriptions, picker and Outlook button (`test_pin_window.py`); the refusal's words (`test_outlook.py`, `test_capture_window.py`); the antivirus line (`test_diagnose.py`) (780 pass in all, 1 skipped). The real app was driven on `dev_data` too, by a script that clicks and types: every row of the corporate test's section 3 but Outlook's.

## Decisions (release 5.20)

- Decisions 61 to 63: no default change (the Pin hotkey opens it pinned already); Outlook's guard is diagnosed now and read past later, with the email reader's refinement; the rows as built, at the same size.
- One description shows at a time, the newest first, so the window needn't grow with the files; the full window still has every row.
- A typed path that isn't there, or is a folder, stays in the box with the problem underneath, so it can be fixed.
- The report reads Security Center's antivirus product state by its documented bytes (on: 0x10 or 0x11 in the middle byte; up to date: 0 in the low byte), and names only the products.

## Release 5.21: the task page as a story (2026-10-25)

The visual overhaul's O9, designed, mocked and decided in the parent workspace (`docs/ui-design/task-page.md`, decisions 64 to 69, all as recommended). The owner found O8's grid still crowded and hard to follow; the page now reads top to bottom as the task's story (SPEC 8.4).

- `docrepo/detail.py`: `task_page(task_id, state, width)` rebuilt from `page_head`, `status_block` (with `status_since`), `when_rows`, `who_rows` (with `avatar`), `agenda_section`, `subtask_section` (with `mark`), `details` and `history` (with `files_in`); one column, When and Who side by side from `SIDE_BY_SIDE` (540 px), and a rail from `WIDE_PAGE` (760 px), no wider than `PAGE_MAX`. `PageState` gains `details`, `desc` and `closed`. `story_tab` loses its order and chapters line, and its headings and months are in sentence case. `TABS` drops Subtasks; `SCOPE_NAMES` names the scopes. `link`, `task_link` and `capture_link` take `quiet` ("tl" or "tq"), for titles that read as text. O8's `facts_grid`, `text_block` and `tab_bar` are gone.
- `docrepo/dates.py`: `days_words` ("in 22 days", "3 days overdue") and `ago` ("yesterday", "5 weeks ago").
- `docrepo/ui/page_view.py`: `PageView`, the detail pane, draws `avatar:`, `mark:` and `progress:` pictures (`picture`) and says when its width crosses a layout's (`layout_changed`, `layout_of`).
- `docrepo/ui/browse_window.py`: the page view; `render_detail` passes its width, and a crossing draws it again (`_page_width_changed`). `on_link` learns `fold:`, `menu:` (`_page_menu`: the scope, with Open all and Close all chapters, and the order), `new:`, `update:`, `copyref:` and `folder:`. `_task_actions`: Note, Update, Meeting notes, Add to (Today, or On Today ✓, then the agendas), Edit, and More at the row's end (New subtask, Open agenda, Copy, Copy prompt, Open folder), the same in both looks.
- `docrepo/ui/widgets.py`: `FlowLayout` keeps a widget with the `flowEnd` property at its line's right end.
- `docrepo/ui/icons.py`: `tinted`. `docrepo/ui/icons/`: `person.svg` and `state-ns`, `state-ip`, `state-pk` and `state-cl`.
- `docrepo/ui/tokens.py` and `detail.CSS`: the page's classes (`sec`, `dt`, `rel`, `over`, `stat`, `sk`, `desc`, `lbli`, `rule`, `tl`, `tq`) in both looks; `QPushButton#iconOnly` for More.
- `tests/`: the page's order, what it leaves out, the folds, the wide page and the dates in words (`test_detail.py`); the bar, its menus, the links and the redraw across 760 px, and the pictures (`test_browse_window.py`) (785 pass in all, 1 skipped). The new and Classic looks were drawn from the code over the sample data and checked by eye at the usual pane width and wide.

## Decisions (release 5.21)

- Decisions 64 to 69, as recommended: the story's order with Details folded; empty fields hidden but Due ("No due date"), with a deadline in Due's place when there's no Due (M0003); Subtasks as a section, closed ones behind Show closed; the description in about two lines with More; Note, Update, Add to, Edit and More; two columns from 760 px.
- **Changed on the way:**
  - The path has no colour dot: the tree's colours follow its filters, so the page couldn't match them.
  - The progress bar is a small one beside the count, not a line across the section, so the page needn't be drawn again for every width.
  - Details' folded line shows the reference fields too, beside the ID, so a change record's number is never a click away.
  - Titles that are links (the path, subtasks, agenda items, raw text log entries) read as text; Qt's rich text can't underline them on hover, so the pointer and the click say they're links.
  - The tab strip's tabs are a table of their own: the selected tab's underline made a full-width table a pixel too wide, with a scroll bar.
- The page's scope names are plainer: With parent tasks and Whole family, for With ancestors and Family.

## Release 5.22: the sidebar (2026-10-26)

The visual overhaul's O10, designed and mocked in the parent workspace (`docs/ui-design/sidebar.md`, decisions 79 to 84, all as mocked; for 83, Discarded and Settings both at the foot). The owner found release 5.16's sidebar, drawn with the task tree's control, didn't follow the playbook. It's built ahead of round 2's stage 8, whose Activity and Priorities views go under Plan in it.

- `docrepo/ui/nav_pane.py` (new): `NavPane`, the new look's sidebar, in place of the `RowTree`. `ViewRow` and `Heading` are buttons painted from the tokens (the icon, the name elided with a tooltip, the count, the backplate and pill, and the focus ring); `show_state(counts, current, folded)` sets the open view, the counts and the folded groups, keeping the open view in sight under a folded heading. It says `picked(view)` and `folded(section, closed)`. Tab has one stop in it (the open view's row, or the row last moved to), and its event filter moves between rows with the arrows, Home and End, opens or folds with Enter, and folds with Left and Right. `ICONS`, `FOOT` (discarded, settings) and `WIDTH` (248).
- `docrepo/views.py`: `ASKS`, the views whose counts the new look's sidebar shows (today, unfiled and each list).
- `docrepo/ui/browse_window.py`: the `NavPane` in the new look, the `RowTree` kept for the Classic look; `_render_nav_new` calls `show_state`, and `_nav_folded` keeps the folded groups in docs.db (`browse_nav_folded`, as before); `_nav_clicked` is gone. The sidebar starts at `WIDTH` once the window has its size, rather than a share of it. `_set_head` takes a `total`, shown after the title in the new look (Task tree, People, Labels and Documents), and sets the title's text format, so a search for text such as `<b>` shows as typed.
- `docrepo/ui/tokens.py`: `QWidget#navPane`, `#navBody` and `QFrame#navFoot` (its hairline), for `QTreeWidget#nav`.
- `docrepo/ui/icons/`: `unfiled`, `tasks`, `due`, `reminders`, `waiting`, `urgent`, `unplanned`, `timeline`, `capacity`, `labels` and `discarded`, from the mock's drawings; the README lists each view's icon.
- `tests/test_nav_pane.py` (new): the rows, their order and the foot; counts only for `ASKS`, and the totals in the headers; a click opening and marking a view, and none marked while searching; folding kept in docs.db and the open view kept in sight; the keys; the ellipsis; the Classic look's tree. `test_browse_window.py` and `test_look.py` follow the new pane. (792 pass in all, 1 skipped.) The new look was drawn on `dev_data/` with Windows' own fonts and checked by eye: no name cut short at 248 px, a folded group with the open list in sight, and the focus ring.

## Decisions (release 5.22)

- Decisions 79 to 84, as mocked: an icon per view and small semibold headings with a chevron, drawn by a widget of their own; a folded group keeps the open view in sight; counts only for Today, Unfiled and the lists; the inset backplate with a short accent pill and a semibold name; Discarded and Settings pinned at the foot; the order as it was (Activity and Priorities join Plan in 5.23).
- **Changed on the way:**
  - **Width:** 248 px to start with, not 228. The mock's text was 13 px; DocRepo's is 14 px, and "Overdue and next 7 days" in semibold with its count needs 227 px of row, plus room for the scroll bar on a short window.
  - **The rows are painted, not styled:** a style sheet can't put the count at the right or draw the short pill, so `nav_pane.py` paints each row from the tokens, and the style sheet only colours the pane and the foot's hairline.
  - **No button group:** the pane marks the open view itself, so that no row is marked while searching, and a click on the open view keeps it marked.
  - **The totals that left the sidebar** are beside their views' titles ("14 open", "7 active"), as `sidebar.md` said they'd be.
  - **The tooltip** shows only when a name is cut short. The headings' tooltips say Fold or Unfold.

## Release 5.27: pictures, files and tables on the notes page, and Notes in its frame (2026-10-27)

The notes page plan's last part (decisions 124 to 129, asked for by the owner on 2026-10-26: "paste pictures, tables, etc into the notes corpus", a picture filed as any other file, with the sub-bullet under it as its description), and decision 130 (2026-10-27): more distinction between Notes and the rest of the task page, from the UI playbook. Schema version 11. No new package. Decision 127 changes the hard rules: DocRepo may now write PNG files of pictures the owner pastes, in the data root.

- `docrepo/safe_fs.py`: `write_picture`, `.png` only, atomic, never over a file. `.github/copilot-instructions.md`: the writes rule names it.
- `docrepo/db.py`: schema version 11, `page_made` on captures. `docrepo/model.py`, `docrepo/captures.py`: `Capture.page_made`. `docrepo/layer0.py`: `Part.pasted`. `docrepo/save.py`: `CaptureDraft.page_made` (its block is the page's line, so saving adds none), and a pasted picture's made-up description says "Pasted picture".
- `docrepo/notes_page.py`: the page's pictures and attachments (`item_line`, a list item that's one picture of, or link to, a document, its description the item under it) and tables (`cells_of`, `row_line`, `separator_line`, `is_separator`); a capture's picture comes onto the page as a picture with its description, not an email's; `descriptions`, `document_ids`, `made_up` and `on_page` (a capture made on the page is on it while its picture or attachment is); `task_md` prints pictures, links and tables; `words` reads cells.
- `docrepo/edits.py`: `add_page_picture` (a PNG in the task's `Files` folder, kept as a capture made on the page), `add_page_file` (a dropped file, tracked where it is, its text read), and `sync_descriptions` when the page is saved (the item under a picture or attachment is its document's description; empty, the made-up one). `docrepo/pages.py`: Task.md's pictures and links to their files. `docrepo/detail.py`: the Captures tab's On the notes page knows captures made on the page.
- `docrepo/ui/rich_edit.py`: `png_bytes`, and a picture pasted with no text goes to `image_pasted` where a box `takes_pictures` (else it's dropped, as before). `docrepo/ui/capture_window.py`: a picture pasted in the content text is a file row, saved as a PNG in the capture's `attachments` folder (decision 129).
- `docrepo/ui/notes_edit.py`: pictures shown from their files (`picture_path`, `loadResource`), at their own size up to 560 px; `insert_item`; typing on a picture goes to its description, Backspace or Delete takes it and its description off; dropped files (`files_dropped`); tables (`insert_table`, the page's rows read into a table and back, Tab, Shift+Tab and Enter, the right-click menu for rows and columns, tables pasted from Excel, Word, Outlook or a web page; a cell's room is its lines' margins, so a table in a folded section folds away, its leftover borders covered, and the fold's pill counts its rows as lines). `docrepo/ui/browse_window.py`: the picture and the dropped files become captures and go in at the caret.
- `docrepo/ui/task_pane.py`: the frame (decision 130): Notes, the format bar (now always shown), the **Table** button (`icons/table.svg`, new) and ⋯ in a tinted header band, then the Checklist summary and the page, in one frame whose bottom edge turns to the accent while the page has the caret. `docrepo/ui/tokens.py`: the frame's looks. `docrepo/ui/style.py`: `NOTES_STYLE`, the Classic look's frame, page and summary, now in the browse window's style sheet as well, so the Classic look shows 5.25's and 5.26's styles there too (they had been only in the capture window's).
- Two fixes found on the way: whole lines copied on the page and pasted kept every line's form but the first's (a heading came back as bold text, a list item as text), and moving lines on a page with a table did nothing without a word; it now says so.
- Tests: `tests/test_pictures_tables.py` (new); `tests/test_notes_edit.py`, the first copied line; `tests/test_db.py`, version 11. 880 pass in all, 1 skipped. The task page with a picture, an attachment and a table was drawn over the sample data root with Windows' own fonts, in both looks, and checked by eye.

## Decisions (release 5.27)

- Decisions 124 to 129 as recommended, 127 by the owner's explicit yes, and 130 as recommended.
- **Changed on the way, for the owner's hand test:**
  - **An email's pictures stay file lines.** Most are signatures and logos; a picture dropped or pasted in the capture window comes onto the page as a picture.
  - **The capture window doesn't show a pasted picture in its text.** It's a file row, like a dropped file; the notes page shows it.
  - **A file dropped on the page is tracked where it is**, as in the capture window, not copied: Save a copy still copies it.
  - **Discarding a capture made on the page leaves its picture or attachment there.** It has no caption to find its block by; Backspace takes it off.
  - **Lines don't move (Alt+Shift+Up and Down) on a page with a table** yet; it says so. Cut and paste still move lines.
  - **A table under a folded heading folds with its section.**
  - **The format bar is always shown** in the frame's header band, which gives it a place of its own.
  - **The table's grid is Qt's own**, each cell with its border, so rows and columns added later have one too.

## Release 5.26.1: each email its own .msg file, and quoted paths (2026-10-27)

Two fixes. The first is for a bug found while planning the knowledge base (`docs/knowledge-base/plan.md` in the parent workspace, its decision 12). Two emails added to one capture were both saved as `email.msg`, and same-named attachments across them (such as each email's `image001.png`) to one file in `attachments\`. Outlook's SaveAs and SaveAsFile replace a file without asking, so only the last of each was kept, against the rule that saved emails are never lost. Both emails' text was always in capture.md; what was lost was the first `.msg` file and any overwritten attachment, and an overwritten attachment's document pointed at the other email's file. Captures saved before this release can't get them back from DocRepo; the emails themselves are still in Outlook. No schema change and no new package.

- `docrepo/save.py`: `msg_name` names each email's file by its place among the capture's emails, `email.msg`, then `email 2.msg` and so on. `attachment_name` cleans an attachment's name of characters Windows forbids and makes it unique within the capture, in any case (`image001 (2).png`); the attachment's document takes that name, so `edits.source_of`, Task.md's link and Save a copy find its file by it, as before.
- `docrepo/ui/capture_window.py`: an email's row says which file it will be ("Saved as email 2.msg in the capture's folder."), and the rows after a removed email move up.
- `tests/test_save.py`: two emails with same-named attachments keep two `.msg` files and two attachments, each document with its own file and extracted text, and a saved copy of the second; the names' rules. `tests/test_capture_window.py`: each email row names its file, and moves up when the first is removed.

The second is for a file path the owner couldn't add on the corporate computer, a mapped drive's path with spaces in its folder names (2026-10-27). A path line in the content text was matched only without quotes, but File Explorer's Copy as path puts quotes round every path it copies; and a path line that didn't lead to a file (a typo, or no-break spaces from a path copied out of an email or a chat) stayed as text without a word, so it looked as if DocRepo refused it.

- `docrepo/text.py`: `typed_path`, moved from `docrepo/ui/pin_window.py` (whose path box already took quotes off), and `is_path_line` reads through it, so a quoted path line is left out of titles, descriptions and Parse and populate like any other.
- `docrepo/ui/capture_window.py`: `_sync_paths` takes the quotes off; `existing_file` also tries the path with its no-break spaces as spaces; a path line that isn't a file is noted once and said in the window's message line (`_tell_missing_paths`) once the cursor leaves it, so a path being typed isn't reported half-way.
- `tests/test_capture_window.py`: a quoted path with spaces adds its file and its row goes with its line; no-break spaces find the file; a missing path is said once, after the cursor leaves. `tests/test_text.py`: quoted path lines.
- 867 pass in all, 1 skipped. The email fix can only be tried by hand where Outlook runs, so here it rests on the tests' fake Outlook; `release-5-26-1-test.md` in the parent workspace tries it with two drafts.

Asked for at the same time and left for its own release: headings in the capture window. A capture's text has no heading form, and its lines are escaped on the notes page so they never become the page's headings, which mark the sections later captures go under; how a capture's heading should behave there needs deciding first.

## Release 5.26: checklists and the Checklist summary (2026-10-27)

The notes page plan's checklists (decisions 85 to 91 as the page redid them, and 121 to 123), asked for by the owner, with the format bar on the notes, which 5.25 left out. No schema change and no new package.

- `docrepo/markup.py`: checklist lines, `- [ ] ` and `- [x] ` (`CHECK`, `check_of`, `TICKED_GREY`), in `to_html` (Qt's list item with a box, a ticked one grey) and `to_line_html` (☐ and ☑). `docrepo/items.py`: a checklist line's `@` names stay names, so it never makes a task item (87). `docrepo/save.py`: `first_line` skips checklist lines.
- `docrepo/ui/rich_edit.py`: checklists in the content text box, so the capture window has them too: Ctrl+1, the format bar's **Checklist** button (`icons/checklist.svg`, new), `[] ` or `[ ] ` at a line's start, a click on a box ticks it, a ticked line's words grey, Enter after a ticked line starts an unticked one, and the new look's tick box painted over Qt's; `block_markup` writes the boxes.
- `docrepo/notes_page.py`: `checklist` and `CheckLine`, and Task.md's Checklist summary at the top of Notes, open lines first. `docrepo/ui/notes_edit.py`: checklist lines on the page (not on headings, captions or file lines), and `checklist_blocks`, `set_line_from`, `remove_line`, `add_check_item` and `go_to_block` for the summary.
- `docrepo/ui/checklist_summary.py` (new): `ChecklistSummary`, its rows bound to the page's lines (`Row`, `LineEdit`): ticking, rewording and removing in either place change the one line; done lines behind Show N done; Add item; Go to; folding, kept for each task. `docrepo/ui/task_pane.py`: the summary under Notes, and the format bar beside it. `docrepo/ui/task_forms.py` and `browse_window.py`: Edit task's Checklist section, the same summary bound to the same page, so a tick there saves and Cancel leaves it. `docrepo/ui/tokens.py` and `style.py`: the summary's looks.
- `tests/test_checklists.py` (new). 860 pass in all, 1 skipped. The task page's summary and checklist lines, Edit task's Checklist and the capture window's checklist were drawn with Windows' own fonts and checked by eye.

## Decisions (release 5.26)

- Decisions 85 to 91 as the notes page redid them, and 121 to 123, as recommended.
- **Changed on the way, for the owner's hand test:**
  - **Add item takes words.** Format them on the page or in the row afterwards.
  - **A row's Enter finishes the row**; it never adds a line. New lines come from Add item or the page.
  - **Ctrl+1 again takes a line out of the list**, back to a line of text, as decision 86 says, not to a bullet.
  - **A heading, caption or file line** never becomes a checklist line.


## Release 5.25: the notes page (2026-10-27)

The notes page plan (`docs/mods/notes-page-plan.md` in the parent workspace, decisions 95 to 120, and 117: Qt's own text box), asked for by the owner on 2026-10-26 and built without a mock, as the owner chose, using what the Qt sample found. The checklist summary (5.26) and pictures, files and tables (5.27) follow.

- `docrepo/db.py`: schema version 10, `task_pages`, `task_page_versions` (the page at each day's end, when the owner last edited it, and whether they did), tasks' `day_headings`, and `search_text` made again with pages. `docrepo/model.py`: `Model.pages`, `Model.page_edits`, `Task.day_headings` and `uses_day_headings`.
- `docrepo/notes_page.py` (new): the page's lines (headings, captions, file lines, markup), a capture's block and caption, where a block goes (`add_block`, with day headings in date order), taking one off (`remove_block`, `edited_blocks`), `merge` for two writers, `task_md`, `words`, and docs.db (`get`, `put` with the day's version, `versions`, `add_capture`, `remove_capture`, `build`, `build_all`, `needs_build`).
- `docrepo/save.py`: a saved capture's block, and each item's, go on their tasks' pages; a new task's description is its text's first line (`first_line`), Make it a task's the window's whole text. `docrepo/edits.py`: `add_to_pages`, `save_page`, `add_again`, filing, discarding (with `off_edited_pages`) and bringing back; `edit_task`'s `day_headings`; `edit_capture` now fixes the title and summary only, leaving capture.md as it arrived. `docrepo/app.py`: `build_pages`, the first pages after a backup, once. `docrepo/sample.py`: the sample builds its pages.
- `docrepo/pages.py`: Task.md's Notes and Captures, and `write_task_page`. `docrepo/detail.py`: the task page in two parts ("top", "bottom"), and the Captures tab (On the notes page, Not on the notes page, Add it again). `docrepo/search.py`: pages indexed and found under Notes. `docrepo/activity.py`: Notes edited.
- `docrepo/ui/notes_edit.py` (new): `NotesEdit`, the page's editor (folding, captions, headings, Alt+Shift+D, moving lines, copy and paste, saving). `docrepo/ui/task_pane.py` (new): `TaskPane`, the task page in one scroll, with the Notes menu. `docrepo/ui/browse_window.py`: the pane in the detail stack, saving, folds kept, merging arrivals, the Captures tab's links, Page history, discarding asking about an edited block, and the capture edit form (title, summary, its text read-only, Go to it on the page). `docrepo/ui/rich_edit.py`: `block_markup`. `docrepo/ui/tokens.py` and `style.py`: the pane is one white page.
- `.github/copilot-instructions.md`: capture.md is written once and then only ever filed. `GLOSSARY.md`: notes page, caption, day heading.
- Tests: `tests/test_notes_page.py` and `tests/test_notes_edit.py` (new); the Task.md examples in `tests/fixtures/examples.md` now have Notes and Captures, written from DocRepo (the mockup's own exports don't have notes pages yet); the capture edit, task page and description tests follow the decisions. 851 pass in all, 1 skipped. The task page was drawn over a sample data root with Windows' own fonts and checked by eye.

## Decisions (release 5.25)

- Decisions 95 to 120 as the plan records them, with 119's default off (a meeting's on).
- **Changed on the way, for the owner's hand test:**
  - **Day headings for new captures** are set in the task page's **Notes** menu (⋯ beside Notes), not in Edit task.
  - **Folded headings are kept in docs.db** (`app_state`), not in `%LOCALAPPDATA%\DocRepo\` as the plan said: the hard rules keep only `location.json` and the Startup shortcut there.
  - **Make it a task** keeps the window's whole text as the new task's description: the page gets the capture's own text, so the window's would otherwise be kept nowhere.
  - **Typing on the page** isn't on the Captures tab or in the status log; it's a Notes edited line in Activity.
  - **Find (Ctrl+F) and Find in this view** don't search the page yet; search (the top bar) does. A heading's own bold or italic isn't kept.
  - **Ctrl+Z just after a capture arrives** can't undo it: the page is shown again, and undo starts afresh. Unsaved typing is merged with it instead.


## Release 5.24: the owner's comments on 5.23 (2026-10-26)

After the 5.23 hand test the owner asked for four things: Find (Ctrl+F) on the Priorities board, as elsewhere; a way to fold the board down to the parent tasks; the task tree clustered by the groups picked; and Collapse a level and Expand a level on every browse view. The owner chose a Fold subtasks switch and a Group by list over the alternatives.

- `docrepo/priorities.py`: `BoardFilter.fold`, `open_subtasks`, `folded` (a subtask with no open subtasks of its own; a task under Quick tasks counts as top-level) and `folded_under`.
- `docrepo/ui/priorities_view.py`: the Fold subtasks switch, with each parent's card saying how many subtasks are folded and how they're ranked ("3 subtasks folded (2 Critical)"); the board's Find box (`open_find`, `close_find`, Esc), matching the task's ID, title, description, status, labels, people and path; the focus stays in the box while the board redraws.
- `docrepo/views.py`: `TreeFilter.only`, `TREE_GROUPS`, `TreeSection` and `tree_sections`: a section per group, person, label or parent label's sublabel, each a task tree of its tasks with their parents dimmed; with People or Labels ticked, only what's ticked gets one, and a last section holds the tasks in none.
- `docrepo/ui/browse_window.py`: Ctrl+F opens the board's box, and Find works on Activity too; the task tree's Group by (`_tree_group_box`, `_set_tree_group`, which opens the branches down to each section's tasks), drawn as a heading per section with its tree under it; Collapse a level and Expand a level on Today, the lists, Agendas, Activity, Documents and Labels (`NESTING_VIEWS`, `_level_buttons`, `_tree_level`, `_sync_level_buttons`), as the task tree's work, with each view's hand-folded rows kept while DocRepo runs (`shut`, `_apply_shut`, `_row_id`); Today's and Agendas' headings hold their items, so they fold.
- `tests/test_grouping.py` (new): the sections, only what's ticked getting one, the tree's Group by, and the level buttons on the other views, with folds kept. `tests/test_priorities.py`: Fold subtasks, and Find and Fold on the board. `tests/test_browse_window.py`: Today's Done today holding its item. (819 pass in all, 1 skipped.) Checked by eye over a sample data root: the board folded and found, the tree grouped by group, and Agendas' headings folding.

## Decisions (release 5.24)

- The owner's: Fold subtasks as one switch on the board, and a Group by list on the task tree (each section in tree shape; only what's ticked gets a section).
- **Judgement calls, for the owner's hand test:**
  - **The level buttons** are on every view whose rows nest. Unfiled, People, Discarded and Search are always flat, so they have none; the board has Fold subtasks instead; the timeline, capacity and Settings have no rows to fold.
  - **Today's and Agendas' headings** now hold their items, indented under them, so they fold.
  - **Find works on Activity too**, as the other list views have it.
  - **A folded parent's card** says how its folded subtasks are ranked, so a Critical subtask isn't lost from sight.
  - **Choosing a Group by** opens the branches down to each section's tasks; Collapse a level folds them as usual.

## Release 5.23: Activity and Priorities (2026-10-26)

Round 2's stage 8 (`docs/mods/round-2-plan.md` in the parent workspace, items 32 and 33), mocked and approved with decisions 23 (four buckets, ordered within each) and 70 to 78 as mocked. Both views are under Plan in the sidebar, after Agendas.

- `docrepo/db.py`: schema version 9, `priority` (critical, high, medium or parking, checked) and `priority_rank` on tasks. `docrepo/model.py`: `Task.priority`, `Task.priority_rank`, and `PRIORITY_NAMES`.
- `docrepo/priorities.py` (new): the buckets (`BUCKETS`, `COLUMNS`, `BY_DIGIT`), what's on the board (`on_board`, `BoardFilter`, `shown`), each bucket's order and Not ranked's sort (`bucket_ids`, `not_ranked`), the board's `columns`, `place` (into a bucket before a task or at its end, numbering it again, and a Priority status log entry when the bucket changes) and `nudge` (one place among the cards shown, not logged), and `sort_key` for Sort by priority.
- `docrepo/activity.py` (new): `window`, `Activity.lines` (captures, status log changes made outside a capture, document versions and agenda items, each a `Line` under its task), `passes` (People, Labels, What), `groups` (by top-level task, person, group or label, with `Heading`s in tree order and Not filed yet last), `plant_events`, `markdown`, and `agenda_items` (one item per ticked task, its ticked lines joined as the note).
- `docrepo/edits.py`: `set_priority` (a move on the board), `add_activity_to_agenda` (skipping a task already open on that agenda), and `edit_task`'s `priority`. `docrepo/bulk.py`: `BulkEdit.priority`. `docrepo/tasks.py`: `record`, for status log entries made outside `update_task`.
- `docrepo/views.py`: the Activity and Priorities views, Sort by priority, `TreeFilter.priorities`, and `markers` with Critical (rows only show that bucket). `docrepo/stories.py`: the Priority sentences. `docrepo/pages.py`: `Task.md`'s Priority row. `docrepo/detail.py`: the task page's priority chip, for every bucket, and the chips' classes.
- `docrepo/ui/priorities_view.py` (new): `PrioritiesView`, with `Column` (a drop target, with a line where a card lands) and `Card` (dragged with `QDrag`); the filters, the selected card's strip with the buckets as buttons, and the keys (an event filter on each card, so the columns' scroll areas don't take the arrows).
- `docrepo/ui/browse_window.py`: the board in the middle pane (the detail pane hidden, as for the timeline) and its `move_priority` and `nudge_priority`; the Activity view (`_activity_view`, `_activity_controls`, `_activity_group`): its rows in the list pane, a line opening its page and staying the selected row (`select(keep_row=True)`, `_row_to_select`), Select's ticks and bar, `add_activity_to_agenda` and `copy_activity`; the task tree's Priority filter. `docrepo/ui/task_forms.py`: Priority in Edit task and Edit selected. `docrepo/ui/nav_pane.py` and `docrepo/ui/icons/`: `activity.svg` and `priorities.svg`. `docrepo/ui/tokens.py`: the board's styles and the priority chips; the Classic look has its own. `docrepo/ui/keymap.py`: the board's keys.
- `tests/test_priorities.py` and `tests/test_activity.py` (new); `test_db.py` and `test_nav_pane.py` follow (813 pass in all, 1 skipped). Both views were drawn over a sample data root with Windows' own fonts and checked by eye: Activity this week, with Select and its bar; the board with eight tasks ranked and the selected card above it; the tree with the Critical chip beside Urgent and the Priority filter; the task page's chip.

## Decisions (release 5.23)

- Decisions 23 and 70 to 78, as mocked: four buckets, Critical, High, Medium and Parking lot, ordered within each; Activity's lines, where each goes, Add to agenda, and its place in the list pane; the board's tasks and filters, Not ranked sorted for you, the status log on a move to another bucket only, Critical on rows and every bucket on the page, the board and Edit task, Urgent a flag of its own (77), and Parking lot not Parked.
- **Also built, from the plan (item 33) but not mocked:** Sort by priority on the task tree and the lists, the task tree's Priority filter (the lists have no filters), and Edit selected's Priority.
- **Changed on the way:**
  - **The Critical chip is solid red,** white on the critical colour: Qt's rich text can't draw the mock's outlined chip, and a tint would look like Urgent's.
  - **`Task.md` has a Priority row** when a task is ranked, after State; the mock's `Task.md` has none, and its examples (with no ranked task) don't change.
  - **A card dropped on Not ranked** leaves its bucket: Not ranked has no order, so no line shows there.
  - **Activity's agenda list** is the open meetings (with their next dates), Today, then the people, without the owner.
  - **Activity's header** says how much happened and when ("20 things happened, Mon 5 Oct to today"), with the kinds counted in the first row.

## The first Frogbot findings (2026-10-20)

The corporate computer's Frogbot scan of phase 5 found four things.

- `requirements.txt`: Pillow 12.3.0 had CVE-2026-96639 (critical) and CVE-2026-96640 (high), both fixed in Pillow 13.0.0, now pinned. DocRepo doesn't use Pillow itself; python-pptx needs it, and works with 13.0.0.
- `pyproject.toml` is gone, and its pytest settings are in `pytest.ini`. Two GPL-3.0 findings named a component `docrepo` (in `pyproject.toml` and `docrepo/log_setup.py`). That was DocRepo itself: JFrog's pip scan runs `pip install .` first, and the `[project]` table named "docrepo" matched an unrelated GPL-3.0 package of that name on PyPI. DocRepo isn't installed as a package, so nothing used the table. Now `pip install .` fails, and the scan falls back to `requirements.txt`.

## The second Frogbot findings (2026-10-25), release 5.20.1

The corporate scan listed 23 open findings, every one located in `DocRepo-main/requirements.txt`:

- **Pillow 12.3.0** (20: CVE-2026-112393, -112398, -112403 and -112900 critical; CVE-2026-96637, -96642, -96643, -96644, -96778, -112390, -112392, -112397, -112399, -112400, -112404, -112405, -112895, -112896, -112897 and -112902 high). Pillow 12.3.0 was phase 5's pin, before the first findings; Pillow left DocRepo altogether in release 5.3.1. So `DocRepo-main/` is a copy of phase 5 left inside the corporate repo, the first zip's folder, which the import guide says not to keep. Removing it there closes these; nothing in DocRepo changes.
- **pypdf 6.19.0** (3: CVE-2026-115572, -115580 and -115585, high). The current `requirements.txt` pins it too, so the scan most likely reported each finding once, at the first copy it met. None of the three had a public record to name its fixed version, so pypdf goes to 6.21.2, the newest, whose releases since 6.19.0 carry six security fixes (6.20.0 to 6.21.2: limits on stream and xref work, cycles in trees, repeated file loads, and image data opened only with the matching Pillow plugin). It needs nothing new on Python 3.12, and every test passes on it (780, 1 skipped).

## Unfinished / notes

- On the corporate computer, phases 2 to 5 and releases 5.1 and 5.2 all passed their tests by 2026-10-20, Outlook included.

- Phase 5 passed the owner's hand test on this computer on 2026-10-18, after the fix for files dropped from File Explorer, and went to GitHub the same day.

- Phase 4 passed the owner's hand test on this computer on 2026-10-18, after the fix that keeps the windows light in Windows' dark mode, and went to GitHub the same day. The hand test covered what the automated tests can't: the window with the real Windows style, File Explorer opening, the tray menu and reminder clicks, and the Settings view.

- Phases 2 and 3 passed the owner's hand tests on this computer and went to GitHub together on 2026-10-16 (brainstorm round 12).

- `SPEC.md` covers phases 1 to 5 in full; later phases are summaries until they're built. The detailed design is in the parent workspace's `docs/task-model/brainstorm.md`.
- Published to the GitHub repo `eckertco2/DocRepo` on 2026-10-09 (phase 1), on 2026-10-16 (the glossary, phases 2 and 3), on 2026-10-18 (phases 4 and 5), on 2026-10-20 (releases 5.1 and 5.2, and the fixes for the first Frogbot findings), on 2026-10-21 (releases 5.3, 5.3.1, 5.4, 5.5 and 5.6), and on 2026-10-23 (releases 5.7, 5.8 and 5.9).
- The route to the corporate computer works (2026-10-09): download, a security scan there, `pip install -r requirements.txt` with every pinned version available, and pytest passing.
