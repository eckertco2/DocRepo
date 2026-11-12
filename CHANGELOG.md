# DocRepo changelog

One line per release, newest first: its number, the date it was built, and what it brought. `PROGRESS.md` has each release's details. A release is tagged in git as `v` and its number, from 5.87 on.

| Release | Date | What |
|---|---|---|
| 5.133 | 2026-11-11 | `**agenda,` in the capture window's content text puts a task on an agenda as you write it: on a task item's line (`- @Mike book the crane **agenda, @Tom and #Business team meeting`), a sub-bullet task, a `#task` line, the New task's own first line, or a plain line under a task, it names a person's agenda, a meeting's, another task's or Today. The line's other words are the item's note (`Ask about the hire rate **agenda, Tom.` puts the task it's under on Tom's agenda, saying why), and with no task at all they go on as a note alone. A task already on that agenda isn't added twice, none goes on its own, and you aren't an agenda: Today is. No schema change. |
| 5.126 | 2026-11-11 | Timing budgets at scale. `load-sample --years 3` adds three years of a lead engineer's made-up work: 1,500 tasks, 15,000 captures with 4,500 emails, 7,500 documents with about 12 KB of text each, 90,000 status-log rows, 450 agenda items, 4,500 tagged labels and 75 people. `python -m docrepo timings` times nine everyday operations on any data root against their budgets (loading, the view counts, a three-word search, the busiest task's page, a save, the task tree, the Timeline, the daily work and `rebuild`), changing nothing and printing counts and times only, kept in `System\diagnostics`. `pytest -m scale` times them on the three years, before each train, never in the default or the fast run: seven of the nine are missed today and marked as expected to fail, with their times. The release-train rule is in CLAUDE.md. No schema change. |
| 5.124 | 2026-11-11 | Decisions across projects: `type:decision` (or `decisions`) in Search everything lists every decision, newest first, as Decisions, with the other filters and a `#task` on top; with no words, all of them. The task page has a Decisions section after Subtasks, open until folded, listing the decisions on the task and the tasks under it, newest first, five then Show all, each with its day, its words, the subtask it's on and the meeting it came from; a click opens its capture. Its Copy puts the decision register on the clipboard as a table (Date, Decision, Task, Where), in rich text and Markdown, and each Task.md has the same table under Decisions. No schema change. |
| 5.122 | 2026-11-11 | Email conversations on the task page: a section after Subtasks, open until folded, listing the conversations of the task and the tasks under it, newest first, each a row with its subject, how many emails, the subtask it's on, who's written and the newest email's first words, with New T-mail at its right; a reply whose subject was changed stays in its conversation. A click opens the conversation's page: every email of it DocRepo holds, oldest first, each with its own words (the quoted emails folded behind Show the quoted emails), its files, and Open in Outlook, Reply all and Open capture; Open in Outlook shows the email itself in Outlook, found by its place there, else opens its saved .msg. No schema change. |
| 5.121 | 2026-11-11 | Search everything takes File search's filters: `type:pdf`, `type:notes`, `type:people`, `from:tom`, `from:attachment`, `after:1 sep`, `since:last week`, `before:oct`, `is:pinned`, `tag:V-110`, `in:reactor` and a bare `.xlsx`, anywhere in what's typed, with `#task` kept at the start of the words. The heading names them, a filter still being typed says what it takes, and one that names nothing lists nothing. Release 5.108's place words ("search excel files …") went. |
| 5.120 | 2026-11-11 | Sub-bullets in the capture window's notes: a task typed as a sub-bullet goes under the task its parent bullet names, and only that one, as it already went under a task its parent bullet makes; and the task made from a sub-bullet has the whole bullet tree as its notes on its page, its parent bullet and the lines around it. A bullet's own sub-bullets were already its task's notes, or its update's. |
| 5.119 | 2026-11-11 | The Today side panel's rows keep their whole line for the title: widened, the state is its icon and the date is short ("8 d", "3 d late", coloured), both on the second line under the title, where Later, Done and Remove show on the pointer. Due in the next 7 days has the short date too. |
| 5.118 | 2026-11-10 | Undo after a move: Move…, Put under…, Also put under… and Remove from under…, on the Edit menu anywhere (and a quick task's Put under… on its row), say what they did with Undo for ten seconds, in Find files' footer too when made there. Undo puts the task back under exactly the parents it had, in the same order and in its old place among each one's subtasks, as one more Parents line in its status log; it says why and changes nothing when the parents have changed since. The moves' words are the mock's: "Rigging plan moved from under Installation to Reactor impeller upgrade.", "… is under Installation too.", "… is a top-level task now.". No schema change. |
| 5.117 | 2026-11-10 | A reminder can repeat: Edit task's Reminder repeats, beside Reminder, takes every week on chosen weekdays, every month on a day or on a workday (the 3rd, the last), or every n days, with Reminder until; each time it comes round the task goes on Today and the reminder moves on to the next time. Schema version 24. |
| 5.116 | 2026-11-10 | A reminder puts its task on Today by itself on its day, marked as a reminder's, and is used up, so Today's Reminders heading goes; Later, on a task's row on Today and on Due in the next 7 days, in the Today view and the side panel, takes it off until Tomorrow, 3 days, 1 week, 2 weeks, 1 month or a day typed in Other…, by setting its Reminder; and Due in the next 7 days leaves out a task whose reminder is still to come. |
| 5.115 | 2026-11-10 | Ticking an item done on Today opens the capture window as an Update on its task, with no question; Done and Remove in the Today side panel say what they did, with Undo, which puts the item back and takes away an untouched Update; Done today's rows have Back on Today; and a file, folder, link or email dropped on a task's row in the Today view opens an Update with it, as the side panel's rows have since 5.106. |
| 5.114 | 2026-11-10 | Files and search results with less on each row, drawn one way everywhere: each type's mark in its colour, the name, one quiet line (where it is, then the words that matched or its description) and one short date at the end. Search everything gains a When column, plural headings with counts and its result count; the Documents view loses Status and Checked for Added; the task page's Files group is a list of rows with Find files after it; Find files and file search drop "from a Note" and marks on task names, and file search opens wider; snippets leave out email headers; the capture window's file rows are two lines; a notes page's file line reads as its name. |
| 5.113 | 2026-11-10 | A calmer task page, and an outline of the notes. Under the title and description, one grid of the task's facts: Status, its dates and its people and labels, each a grey name beside its value, in place of the chips, the fact line and When and who. Every section (Key dates, Agenda, Subtasks, Files, Details, History) is a row of its own with its count and its one command at the right, and everything starts on one left edge. The status card has a bar down its side and says how many changes its log holds. The Notes heading sits over a lighter frame, and beside the notes an outline lists the page's headings and days, marks where you are, goes to one with a click and stays in view as you scroll; its button hides it for every task. 5.109 is a number kept for scoped search's open decision, and 5.110 to 5.112 went unused (the Today reminders are 5.115 to 5.117). |
| 5.108 | 2026-11-10 | Search everything can look in one place. Start with “search” and a place, then the words: “search excel files pump curve”, “search links approval forms”, “search notes V-110”. Or name a task after `#`, which opens the # list in the search box: “search #Reactor impeller upgrade seal” looks in that task and what's under it, and “search links #Reactor impeller upgrade” lists its links. A place or a task with no words lists everything in it, up to 200 of each kind. The places: a file type as File search names them, files, links, folders, notes, emails, captures, tasks, people, labels, tagged labels and saved copies. Anything else typed searches everything, as before. |
| 5.107 | 2026-11-10 | Consultants, from the command line: `consultant-make TASK --name NAME` writes the text of every document on a task and the tasks under it into `Consultants\<name>`, a Word file by heading with its tables as tables, a deck by slide and a PDF by page, with an index that says how well each was read, and the files VS Code needs to offer it as an agent; `consultant-check` checks the map an LLM compiles for it (a catalogue, a vocabulary, topics and an exam) and keeps the pages with no problems; `consultant-status` says what changed since. No schema change. |
| 5.106 | 2026-11-10 | A hotkey, a wheel or a link brings back a minimized browse tool, Find files, file search or capture window, maximized if it was; the Today side panel's inner edge drags to set its width at rest, down to 100 px, kept, with Reset the width at rest on its top line's menu; and a file, folder, link or Outlook email dropped on a task in the panel opens the capture window as an Update on that task with it. |
| 5.105 | 2026-11-10 | New T-mail on a task's page: a new, empty email in Outlook, tagged out of sight so the replies you capture go to that task; Reply all on its arrow (the task's latest email), on Find files' email rows and beside each email on a capture's page, kept the same way. An email already captured counts with its own task, so two from different tasks empty the picker, and a reply whose subject was changed follows the email it answers. The troubleshooting report says whether the saved email has In-Reply-To and References, and stops calling what Outlook doesn't give a failure. |
| 5.104 | 2026-11-08 | A task with a Duration and a Deadline (or key dates) but no Start or Due gets Plan mode's ⋮⋮ grip, as a task with no dates has, so its name can be dragged onto the chart for its own workdays; the drop leaves the Deadline where it is and says when the Due lands past it; the row's tooltip and the line under the chart say it has no Start or Due yet. |
| 5.103 | 2026-11-06 | Every task picker works as the `#` list does: the same rows, search and Right and Left into a task's subtasks, in the capture window's task picker, the browse tool's (Move, Put under, File to task, the Documents filter, templates, ties), the Task view's Ctrl+O, Task search and the Timeline's Focus on, with Recent, None and each place's own extras kept; the agenda picker finds tasks the same way. |
| 5.102 | 2026-11-06 | The review's smaller items: the `dump` command (every table of docs.db as JSON), a save made during a backup waiting for it, one HTML escape, checked names in built SQL, tests for four modules no test imported, six of the seven dead members gone (a test still uses the seventh), a size scale for new code, and the dependency upgrade procedure. |
| 5.101 | 2026-11-06 | Emails that find their task: each email's Outlook identifiers kept, an email whose conversation is already filed to a task filling the task picker with it, the `email-ids` command for emails captured before, and the troubleshooting report's identifiers and T-mail try-outs. Schema version 23. |
| 5.100 | 2026-11-06 | Where dates are edited: Quick edit for dates typed in words, with More options… to Edit task; Duration, ties and key dates under Edit task's More options, which opens by itself when one is set; the capture window's key dates straight inside More fields; and the rule against new date kinds. |
| 5.99 | 2026-11-06 | Two ways to a quick task: Today's box and Ctrl+Shift+D, whose command the wheels' slots run; New task with Today ticked makes an ordinary task on Today; D is Add to Today; Put under… on a quick task's row. |
| 5.98 | 2026-11-06 | Find files: the Task view renamed, opened from the task page's Files group and O, with one Task page button, no task letters and no Notes page tab; one Edit and one Add to menu, on the task page, every task row's right-click menu and Find files' task rows, Edit always its six lines, greyed with a reason where one doesn't apply, and a split button on the task page. |
| 5.97 | 2026-11-06 | The Urgent view retired into the task tree's Urgent only filter, with urgent tasks first in Today's Due in the next 7 days, its old name still leading there; the glossary with Priority and Urgent, and without Set aside. |
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
| 5.80 | 2026-11-06 | Tag patterns: masks in Settings that find plant tags not in the glossary, each put on what mentions it at once and marked new, a Suggested list with Add to glossary, Same as and Not a tag, Never a tag, a tester with Try on everything, and "P-204A/B/C" as each of its tags, from a pattern too. |
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
