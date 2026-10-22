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
| 5.6 | The capture window and Today from the mods log, round 2: Agenda and Today beside the capture types, what Parse and populate found beside the content text, Expand, quick tasks, one letter per topic, Find in this view | Built 2026-10-21, after the owner approved the mockup. Next: the owner's hand test here, GitHub, and testing on the corporate computer |
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
- Published to the GitHub repo `eckertco2/DocRepo` on 2026-10-09 (phase 1), on 2026-10-16 (the glossary, phases 2 and 3), on 2026-10-18 (phases 4 and 5), on 2026-10-20 (releases 5.1 and 5.2, and the fixes for the first Frogbot findings), and on 2026-10-21 (releases 5.3, 5.3.1, 5.4 and 5.5).
- The route to the corporate computer works (2026-10-09): download, a security scan there, `pip install -r requirements.txt` with every pinned version available, and pytest passing.
