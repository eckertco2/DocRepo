These icons were drawn for DocRepo in the style of Microsoft's Fluent UI System Icons, on a 20 px grid with a 1.4 px
stroke. They are DocRepo's own work, under its licence. Each uses currentColor, which docrepo/ui/icons.py replaces
with the colour for its state. The three files without currentColor (tick-white, arrow-down-grey, filled-marker) are
used by the style sheet as they are. The official Fluent set (MIT) can replace them later: give its files these names.
The task page (release 5.21) draws state-ns, state-ip, state-pk and state-cl beside its subtasks (Not started, In progress,
Parked and Closed; state-cl's tick stays white), and person for the owner in place of initials.
The sidebar (release 5.22) gives each view an icon: sun (Today), unfiled, tasks (the task tree), due, reminders, waiting,
person (Assigned to me), urgent, unplanned, agenda, timeline, capacity, people, labels, file (Documents), discarded and
settings, with chevron-down and chevron-right on the groups' headings (docrepo/ui/nav_pane.py, ICONS).
The Task view (release 5.34) marks each file's type: type-doc (Word and text), type-sheet (Excel and CSV), type-slides
(PowerPoint), type-pdf, type-picture, type-drawing (Visio and CAD), type-mail (emails), type-link and type-other, each
painted in its type's colour from the tokens (type_doc and so on); the type is also in the file's name and the preview.
Templates (release 5.44) adds templates, a small tree in dashed outlines, to the sidebar and to a task's More menu.
The state menu (release 5.76) draws tick, in the accent, after the current state.
The notes page's Jump to (release 5.86) is jump, an arrow down to a line, on the Notes header.
Tagged labels (release 5.79) adds tagged, an equipment tag's plate with its hole and two lines of text, to the sidebar and
to search's results.
The notes page's outline (release 5.113) is outline, a panel with a column at its left and indented lines beside it, on the Notes heading.
The weekly review (release 5.128) is review, a circling arrow around a tick, in the sidebar between Today and Unfiled.
