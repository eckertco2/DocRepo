# DocRepo changelog

One line per release, newest first: its number, the date it was built, and what it brought. `PROGRESS.md` has each release's details. A release is tagged in git as `v` and its number, from 5.87 on.

| Release | Date | What |
|---|---|---|
| 5.101 | 2026-11-06 | Emails that find their task: each email's Outlook identifiers kept, an email whose conversation is already filed to a task filling the task picker with it, the `email-ids` command for emails captured before, and the troubleshooting report's identifiers and T-mail try-outs. Schema version 23. |
| 5.96 | 2026-11-06 | The usage command: how often each wheel command and each kind of thing in the Activity view was used in the last 7 and 30 days. |
| 5.95 | 2026-11-06 | The browse window in smaller parts, with no change in what it does: its list views, page commands and notes wiring in modules of their own, the long builders in named sections, and a view's own state kept without loading the model again. |
| 5.94 | 2026-11-06 | Where typed text lands: at the end of the notes page, under a heading with its words only when that's the page's last, with the footer saying which. |
| 5.93 | 2026-11-06 | The email path: a dragged email matched to Outlook safely, its place kept so filing later marks it, an email captured before said on its drop, and a 200 MB cap on what a drag hands over. |
| 5.92 | 2026-11-06 | The ** syntax found and loud: a ** list with every name and an example, an Unread line card, a ticked card for a new person, the keys' Syntax tab, and README's table made from DocRepo's own list. |
| 5.91 | 2026-11-06 | Errors you can see and Undo where it was missing: the Problems line, Undo for Done, Discussed and Save, one set of verbs (Discard, Remove, Clear), New task under this one, and a double-click that's Edit task everywhere. |
| 5.90 | 2026-11-06 | Quicker saves and edits: only the pages a change can reach are made, each task's captures, files and status log found from indexes built once, and the browse tool on the shared model. |
| 5.89 | 2026-11-06 | Data integrity: the check command and Settings' Check the data root, capture.md written before a save commits, backups checked before they're kept, drafts in the backup, and a restore tested end to end. |
| 5.88 | 2026-11-06 | Safer upgrades and a quicker test run: migrations split as SQLite reads them, a copy of docs.db before each upgrade, upgrades tested from real old databases, a damaged docs.db said in words, and the fast run with no Qt. |
| 5.87 | 2026-11-06 | A release identity and guard rails: the version in Settings and this changelog, a test for the write and launch rules, File Explorer started from opener.py, and ruff's settings. |
| 5.86 | 2026-11-06 | The task page's clean-up, stage T4: Jump to, the sticky title line and landmarks. |
| 5.85 | 2026-11-05 | The task page's clean-up, stage T3: captions behind a mark in the gutter. |
| 5.84 | 2026-11-05 | The task page's clean-up, stage T2: a short header of widgets. |
| 5.83 | 2026-11-05 | The task page's clean-up, stage T1. |
| 5.82 | 2026-11-05 | No Due that wasn't given: a new meeting's day is its Start, with no Due; meetings left off the due lists whatever their dates; "today" or "tonight" alone in a capture's text no longer a date. |
| 5.81 | 2026-11-05 | A task's priority as its row's left edge. |
| 5.79 | 2026-11-05 | Tagged labels: plant tags found in every capture, email, document and notes page however they're written, a glossary imported from Excel or CSV, a Tagged labels view and each tag's page, chips on captures, documents and tasks, search and the Task view's tag: filter. |
| 5.78 | 2026-11-05 | List rows: one line per row at one height per view. |
| 5.77 | 2026-11-05 | Every capture window fresh, and Drafts. |
| 5.76 | 2026-11-05 | A task's state from its row, with Undo. |
| 5.75 | 2026-11-05 | The `#` list's marks. |
| 5.74 | 2026-11-05 | The `#` and `@` lists search past a space, and an email's own description box, schema version 21. |
| 5.69 | 2026-11-05 | Notes land on the page: typed text alone on a task is no capture. |
| 5.68 | 2026-11-03 | Long notes pages open at once. |
| 5.67 | 2026-11-03 | Links that open in the browser on a click, and the task page's Links group. |
| 5.66 | 2026-11-03 | Links that go in: a dragged link kept exactly, and folders kept. |
| 5.65 | 2026-11-03 | The `#` list: whole rows with their paths, and Right and Left into subtasks. |
| 5.64 | 2026-11-03 | What-ifs on the Timeline page. |
| 5.63 | 2026-11-02 | Apply template: a template put into tasks that already exist. |
| 5.62 | 2026-11-02 | Duration, weekends, involvement, rates and ties typed in a capture. |
| 5.61 | 2026-11-02 | Forms and small things: Edit task without scrolling, and chips in one shape. |
| 5.60 | 2026-11-02 | One meaning per colour: every colour a token. |
| 5.59 | 2026-11-02 | Quieter windows: row actions on hover, level buttons as icons and one accent button. |
| 5.58 | 2026-11-02 | Nothing cut off: the window at half a screen, and words that end in an ellipsis. |
| 5.57 | 2026-11-01 | The look as decided: the Body font, a focus ring, controls at one height and DocRepo's icon. |
| 5.56 | 2026-11-01 | Copilot's folder, `tree-prompt`, `tree-export`, and the handoff with Copilot's prompt file. |
| 5.55 | 2026-11-01 | Edit files on a task tree. |
| 5.54 | 2026-11-01 | Export, and edit files on a template. |
| 5.53 | 2026-11-01 | Tree files: the Import window, the checks and Copy prompt for trees. |
| 5.51 | 2026-11-01 | A template's timing, schema version 20. |
| 5.50 | 2026-10-31 | Ties: a task's Start or Due set from another date, schema version 19. |
| 5.49 | 2026-10-31 | Hours a week, reordering a template's rows, and Duplicate, schema version 18. |
| 5.48 | 2026-11-07 | Plan mode by workdays: a bar with a Duration keeps its workdays while it's dragged, an undated task's name takes its own Duration, and the drop says what changed; the Timeline's hours count each person's Involvement, as Capacity does; and ties on the chart: a selected bar's lines to its ties, and what follows a dragged bar shown where it will go. |
| 5.47 | 2026-10-30 | Involvement, schema version 17. |
| 5.46 | 2026-10-30 | Duration and hours a day, schema version 16. |
| 5.45 | 2026-10-30 | Linked fields and the preview, schema version 15. |
| 5.44 | 2026-10-30 | Task templates, schema version 14. |
| 5.43.1 | 2026-10-31 | The whole wheel shows at once, and Task search's Enter opens the Task view. |
| 5.43 | 2026-10-30 | The Today side panel. |
| 5.42 | 2026-10-30 | The wheels' selection and searches. |
| 5.41 | 2026-10-30 | The navigation wheels. |
| 5.40.1 | 2026-11-02 | A save that Windows refuses for a moment waits and tries again. |
| 5.40 | 2026-11-02 | Timeline and Capacity on one page. |
| 5.39 | 2026-10-30 | A time range typed by hand on the Timeline. |
| 5.38 | 2026-10-30 | Quick input: `**name,` then a sentence fills any field. |
| 5.37 | 2026-10-30 | Notes in the Task view. |
| 5.36 | 2026-10-30 | Small fixes from the voice memos of 2026-10-30. |
| 5.35 | 2026-10-29 | The Task view's Open, its files' text, pins and uses, schema version 13. |
| 5.34 | 2026-10-29 | The Task view: a window for one task, built for finding its documents. |
| 5.33.1 | 2026-10-28 | Add selected Outlook email copies the email whole past Outlook's guard, with a hotkey and the category's colour. |
| 5.33 | 2026-10-28 | Emails from the drag's own copy, read without Outlook, and the task's name as an Outlook category. |
| 5.32 | 2026-10-28 | `#` chooses the task, or splits a note by task. |
| 5.31 | 2026-10-28 | Key dates: dated line items on a task, schema version 12. |
| 5.30 | 2026-10-27 | Planning on the timeline: Plan mode's drags, Focus and Quick edit. |
| 5.29 | 2026-10-27 | The timeline as one chart, with a row per project, Order by and the plant events lane. |
| 5.28 | 2026-10-27 | Copy open in the mods log, and headings that fold in the capture window. |
| 5.27 | 2026-10-27 | Pictures, files and tables on the notes page, and Notes in its frame, schema version 11. |
| 5.26.1 | 2026-10-27 | Each email in a capture its own .msg file, and quoted paths in the content text. |
| 5.26 | 2026-10-27 | Checklists on the notes page, the Checklist summary, and the format bar on the notes. |
| 5.25 | 2026-10-27 | The notes page: each task's notes as one page, edited in place, schema version 10. |
| 5.24 | 2026-10-26 | Find and Fold subtasks on the Priorities board, Group by on the task tree, and the level buttons. |
| 5.23 | 2026-10-26 | The Activity view and Priorities, schema version 9. |
| 5.22 | 2026-10-26 | The visual overhaul, O10: the sidebar redrawn. |
| 5.21 | 2026-10-25 | The visual overhaul, O9: the task page as the task's story. |
| 5.20.1 | 2026-10-25 | pypdf 6.21.2, for the second Frogbot scan's findings. |
| 5.20 | 2026-10-25 | The pinned window's task picker, path box, descriptions and Outlook button, and Outlook's security guard in words. |
| 5.19 | 2026-10-25 | The visual overhaul, O8: the task page's fields in a grid. |
| 5.18 | 2026-10-25 | Plant events in Parse and populate, from the mods log, round 3. |
| 5.17 | 2026-10-25 | The pinned window, OneNote's keys in the content text, and double-click opening Edit. |
| 5.16 | 2026-10-24 | The visual overhaul, O7: the command palette (Ctrl+K). |
| 5.15 | 2026-10-24 | The visual overhaul, O6: Settings as cards. |
| 5.14 | 2026-10-24 | The visual overhaul, O5: the browse window's top bar, sidebar and command bar. |
| 5.13 | 2026-10-24 | The visual overhaul, O4: Edit task, Edit selected, the person and label forms, and the date field. |
| 5.12 | 2026-10-24 | The visual overhaul, O3: the capture window's new layout. |
| 5.11 | 2026-10-24 | The visual overhaul, O2: Show hints, keys in tooltips, and key tips. |
| 5.10 | 2026-10-24 | The visual overhaul, O1: design tokens, the type ramp, the new inputs, icons and the Classic look. |
| 5.9 | 2026-10-23 | Email, group and role for people, reference fields, nested labels and plant events. |
| 5.8 | 2026-10-23 | Items and meeting notes: @, # and ** make tasks, notes, updates and decisions in any capture. |
| 5.7 | 2026-10-23 | Formatted content text, kept as Markdown in capture.md. |
| 5.6 | 2026-10-21 | The capture window and Today: Agenda and Today beside the capture types, quick tasks, and Find in this view. |
| 5.5 | 2026-10-21 | Small fixes: Ctrl+Enter in the forms, an optional file description, editing mods log entries, and double-click. |
| 5.4 | 2026-10-21 | Links as files, email layer 0 and the timeline. |
| 5.3.1 | 2026-10-21 | PowerPoint text without python-pptx, so Pillow goes. |
| 5.3 | 2026-10-21 | Edit task, Edit selected, labels on old tasks, Discard and Today. |
| 5.2 | 2026-10-20 | Quick wins from the mods log, round 1. |
| 5.1 | 2026-10-19 | Fixes from the mods log, round 1. |
| Phase 5 | 2026-10-18 | First everyday version: the Startup shortcut, backups, the Excel import of the project list and the README. |
| Phase 4 | 2026-10-17 | Browse tool: the views, task and capture pages, agendas, capacity, search and Settings. |
| Phase 3 | 2026-10-16 | Capture app: the tray, the hotkey, the capture window, saving captures, text extraction and Outlook emails. |
| Phase 2 | 2026-10-16 | Database and task model: the schema, the task tree, people, logs, the capacity calendar and the generated pages. |
| Phase 1 | 2026-10-09 | Skeleton and safety: the data root, settings, guarded writes, logging, the command line and the network scan. |
