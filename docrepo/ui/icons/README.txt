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
