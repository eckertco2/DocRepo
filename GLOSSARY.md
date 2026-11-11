# DocRepo glossary

These are the words DocRepo's code, docs and AI assistants use, and what each one means. Use them in code, comments, tests and docs. The retired words at the end shouldn't appear in new text.

## 1. Captures

- **Capture window**: the hotkey window where everything enters DocRepo. The browse tool's Add note, Update and New task buttons open it with a task already picked.
- **Capture**: one saved use of the capture window: its input plus the record of its outputs, with an ID such as C000187. It names both the act and the saved record; closing the window without saving leaves no capture.
- **Capture type**: what a capture is for, chosen in the window: Note, New task or Update. One capture can be several types at once. Meeting notes (release 5.8) isn't a type: it's the window's way of taking a meeting's notes, which are a note on the meeting.
- **Note**: reference information linked to a task without changing its status, typed by hand or in files. It becomes part of the task's raw text log.
- **New task**: a capture type that creates a task. The task is a subtask when a parent task is picked, and a top-level task when none is.
- **Update**: a capture with the Update box checked, also called a status update. It changes the task's state or another field, or adds an entry to its status log.
- **Capture input**: everything the owner provides: the content text, files, emails, and their selections (capture type, task, field values, per-file options).
- **Capture metadata**: what DocRepo records on its own: the ID, the time saved, the source and email headers.
- **Capture output**: everything a capture creates or changes: a new task, changes to a task, a link to a task, documents, saved copies and summary entries. One capture can have several outputs.
- **Content text**: the text typed or pasted into the capture window's main box, kept with the capture once it's saved.
- **Formatted content text**: content text with bold, italic, underline, strikethrough, highlights or lists (release 5.7). Its capture.md keeps it as Markdown; everything that reads its words reads it without the marks.
- **Operator**: `@`, `@L.`, `@__`, `#` or `**` in the content text, saying what a line makes (release 5.8): a person, a lead, no one yet, a task it belongs to, or its kind.
- **Parameter**: a field of a task that a `**name,` line fills from one sentence in the content text (release 5.38): `**due, 5 Nov.`
- **Item**: a line of the content text (with the list items under it) that an operator makes into a task, a note, an update or a decision. Saving keeps each as a small capture of its own, linked to the capture it came from (its notes).
- **Heading**: a line that's only `#` tasks. It covers the lines under it, until the next heading.
- **Split**: what Save does with a note that names several `#` tasks and has no task picked (release 5.32): a capture per task, each with its part of the text and the files added while the cursor was in it, and an unfiled one for the rest. One `#` task fills the task picker instead.
- **Meeting notes**: the capture window taking a meeting's notes (Alt+M): expanded, with the meeting's name and its agenda beside the text. The notes are kept on the meeting, and their items made when they're saved.
- **Unfiled capture**: a capture with no task linked yet.
- **Filing**: linking an unfiled capture to a task later. The capture's folder doesn't move.
- **Unfiled**: the browse tool's view of unfiled captures, newest first, and the matching section of `Contents.md`.
- **Parse and populate**: the window's rule-based filling of fields from the content text, with no LLM. It's the only feature called "parse".
- **Navigation wheel**, or wheel: a small ring of actions on a hotkey, picked with the arrow keys (release 5.41). Each is in `Config\wheels.jsonc`.
- **Slot**: one place on a wheel, under a direction from N round to NW, naming a command. A **held** slot keeps the place for later and does nothing.

## 2. Tasks

- **Task**: the unit of work and the scaffold everything else hangs on: a place in the tree, fields, and the captures linked to it. A New task capture or the Excel import creates it; Update captures and browse-tool edits change it.
- **Top-level task**: a task with no parent.
- **Project**: an informal name for a top-level task. There's no separate project object.
- **Parent task**: any task with subtasks. A task can have more than one parent.
- **Subtask**: a task under a parent task.
- **Task tree**: all tasks arranged by their parent links, as the browse tool and the task picker show them.
- **State**: Not started, In progress, Parked or Closed. Closed means done or cancelled.
- **Current status**: a short paragraph saying where the task stands now.
- **Status log**: the dated list of changes to a task's state, current status and other fields.
- **Raw text log**: the corpus of all reference information entered for a task, including the text of its status updates and the content text of all captures associated with that task. Since release 5.25 the browse tool lists it on the task page's **Captures** tab, and the notes page is where its words are read.
- **Notes page**: a task's notes as one page (release 5.25), read, written and edited in place on its task page. Each capture saved on the task adds its block to it; the owner adds, rewords and reorganises it freely. It lives in the database, and Task.md prints it under Notes.
- **Caption**: the small grey line that starts a capture's block on a notes page, with its date, time and what it is ("Thu 8 Oct 2026 · 10:42 am · Note"). It links to the capture; removing it unties the text under it from the capture. A block with no words of its own beyond its files has none (release 5.83): its file lines are its block. Since release 5.85 a caption with a line under it is tucked away: the page shows its **mark** (an icon for its kind) in the gutter beside that line, with the caption's words in the mark's tooltip, and a click on the mark opens the capture; Backspace at the line's start takes the caption off. The caption is still a line of the page in docs.db and Task.md.
- **Landmark**: a short line on the task page's scroll bar where a heading of the notes page sits in the scroll (release 5.86): the owner's headings in the accent, the day dividers in grey, with the heading's words in its tooltip. **Jump to** (the Notes header's button, the sticky title line or Ctrl+G) lists the same headings and days, with Top of the page and Latest, which goes to the end of the notes.
- **Outline**: the column at the left of a task's notes (release 5.113) listing the notes page's headings and days, with the one you're in marked; a click goes there. Its button on the Notes heading shows or hides it for every task.
- **Facts grid**: the task page's facts under its title (release 5.113): Status, its dates and its people and labels, each a grey name beside its value. It took the place of the chips, the fact line and the When and who group.
- **Task line**: a line on a notes page that's one link to a task made from those notes (release 5.83): "Task: Rigging plan · Mike Ortiz · due Wed 14 Oct", in the item's place, with the item's text kept in its capture and on the task's own page.
- **Checklist line**: a line with a box on a notes page or in a capture's content text (release 5.26), ticked with a click. It's kept as `- [ ]` or `- [x]`.
- **Checklist summary**: every checklist line on a task's notes page, shown again at the top of its notes and in Edit task; each row is the line itself, so a change in either place changes both.
- **Picture** and **attachment** (on a notes page): a list item that shows one of the task's files, as the picture itself or as a link to the file (release 5.27), with its description as the list item under it. Saving the page keeps that description as the file's.
- **Made on the page**: said of a capture made by pasting a picture or dropping a file on a notes page (release 5.27). It has no caption: its picture or attachment is its block.
- **Day heading**: a heading on a notes page that reads as a date. New captures go under the heading for their day, and so does a note's text under none of its own headings (since release 5.69 on every task; before it, with day headings on for the task).
- **Task description**: the short "what it is" of a task. A task made from a capture takes the first line of its content text; the whole text goes on its notes page (release 5.25).
- **Label**: a category on a task, such as Safety. A task can have several, and subtasks can inherit them.
- **Parent label**: a label with labels under it (its **sublabels**), such as Production line over Line 1 and Line 2. It's a heading: tasks get its sublabels, not it. Labels nest one level only.
- **Priority**: a task's bucket on the Priorities board (Critical, High, Medium or Parking lot) and its place in it, shown as its row's left edge (releases 5.23 and 5.81).
- **Urgent**: a tick on a task. The task tree's **Urgent only** filter lists the urgent tasks, and Today's Due in the next 7 days puts them first; since release 5.97 there's no Urgent view. It isn't a priority bucket.
- **Plant event**: a task with Plant event ticked, such as an outage or a turnaround, which the timeline shades from its Start to its Due so other work can be seen against it.
- **Reference field**: a field every task has for a number from another system, such as a change record's. Its name is set in Settings.
- **Tagged label**: a plant's tag, such as V-110 or FIC-2210, found in the text of every capture, email, document, notes page and task (release 5.79). It isn't a label: a label is a category the owner gives a task, and a tagged label is found in the words. It's found however its parts are joined (V-110, V110, V 110), and by its aliases. Captures, documents and tasks show theirs in a **Tagged labels** row.
- **Glossary** (of tagged labels): the list of tagged labels, each with its description and aliases, imported from Excel or CSV in the Tagged labels view, or added by hand. Each is known by its **key**, its letters and digits in capitals.
- **Alias** (of a tagged label): another name it's found by: one with a digit and no space (D-10) is matched like a label, and any other (feed drum) as whole words.
- **Tag pattern**: a name and a **mask** such as `XX[X]-####` for a plant's tagging convention, kept in Settings, which finds tags that aren't in the glossary yet (release 5.80). In a mask `X` is a capital letter, `#` a digit, `*` either, `[ ]` optional and `' '` itself; DocRepo makes it a regular expression of its own.
- **Suggested** (tagged label): a new tagged label a tag pattern found that isn't in the glossary, put on what mentions it at once and marked **new**, waiting in the Tagged labels view's Suggested list for **Add to glossary**, **Same as…** (an alias of another label) or **Not a tag** (release 5.80).
- **Never a tag**: the list in Settings of whole tags (ABC123) and starts with `*` (API*) that no tag pattern makes a tagged label. It applies to patterns only: a glossary label is always found (release 5.80).
- **Tester** (of tag patterns): Settings' **Try it** box, which marks what the glossary and the patterns find in pasted text as it's typed, and **Try on everything**, which runs the patterns over everything DocRepo holds before they're saved (release 5.80).
- **Mentioned**: said of an item whose text has a tagged label, and of the label. **Mentioned only** narrows the Tagged labels view to those.
- **Routine task**: a task with Recurrence set. Its occurrences aren't checked off one by one, and closing the task ends the recurrence.
- **Meeting**: any task with Meeting checked, one-off or routine.
- **Agenda item**: a temporary link that puts a task, or a note with no task, on the agenda of a meeting, another task or a person. It's added with the capture window's Add to agenda option and stays open until it's closed by hand.
- **Agenda target**: the meeting, task or person whose agenda an item is on.
- **Agenda**: the open agenda items of one agenda target.
- **Today**: the built-in agenda target that is the owner's to-do list for the day. Its items carry over until they're marked Done.
- **Quick task**: a task made from one line and put on Today, two ways (release 5.99): Today's box (the view's and the side panel's), and Ctrl+Shift+D, whose command the wheels' slots run. Make it a task turns a note on Today into one. It's an ordinary task. A New task with Today ticked in the capture window isn't one: it's an ordinary new task on Today. D on a row is **Add to Today**, which puts the task on Today as it is.
- **Quick tasks**: the built-in top-level task that quick tasks wait under until **Put under…** on the row's menu (release 5.99), or Edit task, puts them under their real task. DocRepo makes it the first time it's needed.
- **Today side panel**: the Today view as a floating strip beside the other windows (release 5.43). It has the same items as the Today view, not a list of its own.
- **Discard**: hiding a task or capture made by mistake, with a reason. Nothing is deleted, and Bring back restores it. It's how DocRepo "deletes" anything. Since release 5.91 it's the one word for getting rid of a record: a task, a capture or a draft.
- **Remove**: taking a link away (release 5.91): a person from a task, a file from a capture, an item from an agenda or Today, a task from under a parent, a row from a template, a task from a what-if's plan, or a row or column from a table on a notes page. What it linked stays. In a what-if, **Add back** undoes it.
- **Clear**: emptying a field, or the content text (release 5.91).
- **New task under this one**: the task page's and the Activity view's name for a new task made under the task you're on (release 5.91), in place of "New subtask".
- **Scope**: which tasks a view or prompt draws on: this task, with ancestors, with subtasks, or family. Family is all ancestors plus all descendants.
- **Event**: a dated happening, such as an audit or a turnaround, entered as a task's Deadline. "Event" means nothing else, except in "plant event".

- **Template**: a small tree of tasks without dates, kept apart from tasks, that Make tasks copies into the task tree (release 5.44). Its name is its top row's title.
- **Template row**: one task in a template.
- **Make tasks**: copying a template, or a row and what's under it, into the task tree. The copies are ordinary tasks.
- **Starting notes**: what a template row copies onto each new task's notes page, once. The page is the task's own from then on.
- **Linked field**: a field on a task that follows its template row until it's changed on the task.
- **Detach**: ending all of a task's links to its template, keeping its values.
- **Duration**: a task's length in days, kept when its dates move once it's typed (release 5.46).
- **Runs through weekends**: a tick saying a task's days are every day, not only workdays.
- **Quick edit**: the small window for one task from the Timeline (Q), where its dates are typed in words, read as you type, with its people and hours (release 5.30). Since release 5.100 the rest of what shapes its dates, its Duration, Runs through weekends, ties and key dates, has one form, Edit task's **More options**, which Quick edit's More options… opens. No new date kind comes without a decision that retires one.
- **Hours a day**: a role's hours stated as a rate (**h a day**), whose total (**h in all**) is the rate times the task's days. The total is what the lists, the timeline and Capacity read.
- **Hours a week**: the same with **h a week**, whose total is the rate times the weeks in the task's days, part weeks included. A week is the workdays in Settings, or 7 days with Runs through weekends.
- **Tie**: a task's Start or Due set from another date: a number of workdays or weeks, before or after another task's start or end, or a key date's. When the source moves, the date moves and keeps its gap. Changing the date by hand keeps the tie, with a new gap.
- **Source** (of a tie): the task or key date a tie counts from.
- **Gap** (of a tie): the number of workdays or weeks between a tied date and its source.
- **Anchor**: the one row in a template that other rows tie to by default, whose date is typed at Make tasks. A template has one at most.
- **Apply template**: putting a template into tasks that already exist. Each keeps all it has and becomes the top of a tree, with the template's subtasks under it. **Make tasks** makes new tasks instead.
- **Timing window**: where a template's anchor and every row's ties are set, with a chart that redraws as you type.
- **Involvement**: the percentage of a role's hours that land on one person on one task. 100% by default, and not a split.
- **Preview** (of a template change): the window saying which tasks or trees a change to a template would reach, each with a tick, before it's made. An unticked task keeps its value and stops following.
- **Changes** (of a template): the list on a template's page of what was changed and what it did to its tasks.
- **Tree** (of a template): the tasks one Make tasks made, or one Save as template linked.
- **Tree file**: a JSON file describing a small tree of tasks, which Import makes into a template and Export writes.
- **Edit file**: a JSON file listing changes to a template or a task tree, matched by ID and reviewed before they're made.
- **Tree prompt**: the instructions, format and names Copy prompt gives an LLM to write a tree file.
- **Copilot's folder**: the folder, named in Settings, where Copilot leaves files for DocRepo to read.

## 3. People and hours

- **People list**: everyone DocRepo knows, each with an ID such as P001, aliases and available hours per week.
- **Lead**: a person driving a task. A task can have several.
- **Assignee**: a person doing a task's work. A task can have several.
- **Participants**: a task's leads and assignees together.
- **Group**: the team a person is in, such as Maintenance. One each, at most; filters and the capacity view can use it.
- **Role**: what a person does, such as Planner, shown after their name.
- **Me**: the person marked as DocRepo's owner. "I" and "me" in a capture mean them.
- **Lead hours, Assignee hours**: estimated hours for each person in that role: a total for a one-time task, per occurrence for a routine one.
- **Capacity calendar**: hours per person, workday and task, built from task fields. It's a cache that can be rebuilt at any time.
- **What-if**: a named change to the plan, made on the Timeline page, that changes no task until it's applied (release 5.64). Its things done are removing a task from the plan, moving a bar or a whole parent, and moving a key date. **Remove** in a what-if (Take off until release 5.91) means Parked once it's applied, and **Add back** undoes it. The **real plan** is the tasks as they are.

## 4. Files and documents

- **Original**: a file where it already lives, on a local drive or the LAN. DocRepo only reads it.
- **Document**: DocRepo's record of an original, with an ID such as D000042, a file description and extracted text.
- **Extracted text**: the plain text DocRepo pulls out of a file when a capture adds it, kept in `Documents/<id>/extracted.txt` for search and for the differences in document versions. Pulling it out isn't Extract, which is the later processing for the knowledge base.
- **File description**: the description written for each file added to a capture. It tells people, and later agents, what the file holds without opening it.
- **Saved copy**: a copy of a file in a task's `Files` folder, made only when Save a copy is checked.
- **Attachment**: a file inside an Outlook email, saved with that email's capture.
- **Email layer 0**: the first pass over an Outlook email added to a capture. It gives each of the email's attachments, the links in its body and the pictures in its body a row of its own, each kept or left out with Keep, and records what it kept and left out in the capture. Later layers, such as summaries and tasks from emails, build on it.
- **The drag's own copy**: the full copy of an email (its `.msg`) that Outlook puts on a drag, which DocRepo's own drop target takes and saves as it is, read without Outlook (release 5.33). An attachment dragged from an email, or a file in a zip folder, comes the same way, as a file with no path on disk.
- **Conversation**: an Outlook email with its replies and forwards, known by the GUID in their conversation index, the same in each whatever its subject (release 5.101). A conversation follows the task it was last filed to, so an email of it added to a capture fills the task picker, "from conversation". A thread (5) holds one or more conversations.
- **T-mail**: an email DocRepo opens in Outlook from a task for the owner to write and send (release 5.105): a new one from **New T-mail** on the task page, or a **Reply all** to a captured email. It's tagged with its conversation, unseen, and kept with its task, so the replies it gets fill the capture window's task picker with that task. DocRepo never sends one.
- **Outlook category**: the task's name DocRepo adds to an Outlook email it files on that task, with Mark filed emails in Outlook on in Settings (release 5.33), so Outlook's own search finds it. It isn't a label.
- **Link**: a web or SharePoint address kept as a document, with a file description, in place of a file. Its original is the address. DocRepo never opens or fetches it, so it has no extracted text; Copy link puts it on the clipboard.
- **Pinned file**: a file pinned on a task in its Find files (release 5.35): one of the task's key documents, first on its Overview and listed in its Task.md. Pins are per task.
- **Document version**: DocRepo's record that a tracked original has changed, with the difference. It isn't a capture; it becomes part of the raw text log of the tasks linked to that document.

## 5. Summaries and processing

- **Summary**: an LLM's answer that the owner pastes back into a capture or task. It's added to the task's summary log.
- **Summary type**: a prompt file in `Config/prompts` that says what to send to the LLM and what to ask.
- **Copy prompt**: the button that builds a summary type's prompt and copies it to the clipboard.
- **Extract**: processing captured text and files into chunks for the knowledge base, at a later stage. The per-file Extract information checkbox asks for it.
- **Knowledge base**: the future store of chunks that agents search.
- **Chunk**: one piece of text in the knowledge base, with its metadata and embedding.
- **Embedding**: the vector made from a chunk, used to find related text by meaning.
- **Thread**: an email conversation. Its chunks are grouped by thread, so an agent can pull the whole conversation.
- **AI layer**: whatever does processing and answers questions over the data root. It sits beside DocRepo, as Copilot skills and scripts that work on the data root; DocRepo itself runs no model.
- **Agent**: an LLM working through a task with tools, such as Copilot in agent mode.
- **Skill**: a packaged set of instructions an agent follows, such as the planned email processing skill.

## 6. The system and the work

- **Work assistant**: the whole system: DocRepo plus the future AI layer.
- **DocRepo**: the Windows app: the capture window, the browse tool and the data root they write to.
- **Browse tool**: DocRepo's main window for viewing and editing tasks, captures, lists and settings.
- **Data root**: the folder holding all of DocRepo's data, with `docs.db` as the source of truth.
- **Dump**: every table of `docs.db` written as JSON, a file each, in `System\export\<date>` (the `dump` command, release 5.102), for reading the database outside DocRepo. It's a copy made for reading; DocRepo never reads one back.
- **Consultant**: an agent over the documents of one task and the tasks under it (release 5.107), made by `consultant-make` as a folder in `Consultants` in the data root, for asking questions of those documents in VS Code. Its **corpus** is the documents' text, a file a document and a section a heading, slide or page, each with a reference such as `D000123#s4`. Its **map** is the one part an LLM writes: a catalogue, a vocabulary, a topic index and an exam, checked by DocRepo before it's kept. Its **trainer** is the agent that compiles the map.
- **Build phase**: a numbered step in building DocRepo, phases 1 to 6 in `PROGRESS.md`.
- **Mods log**: DocRepo's own list of changes the owner wants made to it.
- **IDs**: T task, C capture, D document, P person, M mod.
- **Look**: how DocRepo's windows are drawn: the new look (from release 5.10), or the **Classic look**, release 5.9's colours, fonts and hints on the same layouts. Chosen in Settings.
- **Show hints**: the setting that shows the help text, the **i** buttons and the key badges in every window. Off by default.
- **Key tips**: the labels that show each control's key while Alt (letter keys) or Ctrl (Ctrl shortcuts) is held.
- **Find files**: a window of its own for one task (releases 5.34 and 5.35, as the Task view; renamed in release 5.98), opened from the Files group on the task page, or with O: its status at a glance, an outline of its subtasks, and a search that finds its files, emails, notes and updates as you type, with a preview, built for finding and opening its documents. Its one command is Task page: the task page is a task's home.
- **Edit** and **Add to** (a task's menus): Edit is Edit task… with the task's place in the tree and Discard…; Add to is Today, the open meetings and anyone else. Each is made from one list (release 5.98), the same on the task page, every task row's right-click menu and Find files' task rows.
- **Command palette**: the box Ctrl+K opens, listing every action and view, narrowed as you type.
- **Pinned window**: the capture window shrunk to a small window at the bottom right (Pin, F12), for dropping files, emails and links on. It's the same capture.

## 7. Retired words

- **Capture event**: say capture. It covers both the act and its record.
- **Content type**: say capture type.
- **New subtask**: as an option name, say New task. It's a subtask when it has a parent. On a task's own page and menus, say New task under this one (release 5.91).
- **Delete**, **Take off**, **Take out** and **Put back** (in the windows, release 5.91): say Discard for a record, Remove for a link and Clear for a field. Bring back stays as Discard's opposite, and Add back as Remove's in a what-if. A what-if itself is still deleted, as it holds no record of the owner's: nothing changed until it was applied.
- **File a copy**: say Save a copy, so "filing" only means linking an unfiled capture.
- **Task view**: say Find files (release 5.98). Its Notes page tab went with the name: the notes are on the task page.
- **Set aside**: retired with release 5.77, when the capture window opens fresh each time and a capture closed before it's saved goes to Drafts.
- **Project notes**: say Note.
- **Tag**: on its own, only a plant's tag (a tagged label, release 5.79), as in tag pattern. Never a capture's type, which is its capture type, or a task's category, which is a label.
- **option**: the field in `capture.md` becomes `capture_types`, a list, since one capture can be several types.
- **Inbox**: for the browse tool's view and the `Contents.md` section, say Unfiled.
- **Inbox capture**: say unfiled capture.
- **Raw notes**: say raw text log.
- **Content**: for the capture window's text, say content text.
