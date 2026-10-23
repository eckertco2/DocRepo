# DocRepo glossary

These are the words DocRepo's code, docs and AI assistants use, and what each one means. Use them in code, comments, tests and docs. The retired words at the end shouldn't appear in new text.

## 1. Captures

- **Capture window**: the hotkey window where everything enters DocRepo. The browse tool's Add note, Update and New task buttons open it with a task already picked.
- **Capture**: one saved use of the capture window: its input plus the record of its outputs, with an ID such as C000187. It names both the act and the saved record; closing the window without saving leaves no capture.
- **Capture type**: what a capture is for, chosen in the window: Note, New task or Update. One capture can be several types at once, and Meeting notes is a later type.
- **Note**: reference information linked to a task without changing its status, typed by hand or in files. It becomes part of the task's raw text log.
- **New task**: a capture type that creates a task. The task is a subtask when a parent task is picked, and a top-level task when none is.
- **Update**: a capture with the Update box checked, also called a status update. It changes the task's state or another field, or adds an entry to its status log.
- **Capture input**: everything the owner provides: the content text, files, emails, and their selections (capture type, task, field values, per-file options).
- **Capture metadata**: what DocRepo records on its own: the ID, the time saved, the source and email headers.
- **Capture output**: everything a capture creates or changes: a new task, changes to a task, a link to a task, documents, saved copies and summary entries. One capture can have several outputs.
- **Content text**: the text typed or pasted into the capture window's main box, kept with the capture once it's saved.
- **Formatted content text**: content text with bold, italic, underline, strikethrough, highlights or lists (release 5.7). Its capture.md keeps it as Markdown; everything that reads its words reads it without the marks.
- **Unfiled capture**: a capture with no task linked yet.
- **Filing**: linking an unfiled capture to a task later. The capture's folder doesn't move.
- **Unfiled**: the browse tool's view of unfiled captures, newest first, and the matching section of `Contents.md`.
- **Parse and populate**: the window's rule-based filling of fields from the content text, with no LLM. It's the only feature called "parse".

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
- **Raw text log**: the corpus of all reference information entered for a task, including the text of its status updates and the content text of all captures associated with that task.
- **Task description**: the content text of the capture that created the task. There's no separate Description box.
- **Label**: a category on a task, such as Safety. A task can have several, and subtasks can inherit them.
- **Routine task**: a task with Recurrence set. Its occurrences aren't checked off one by one, and closing the task ends the recurrence.
- **Meeting**: any task with Meeting checked, one-off or routine.
- **Agenda item**: a temporary link that puts a task, or a note with no task, on the agenda of a meeting, another task or a person. It's added with the capture window's Add to agenda option and stays open until it's closed by hand.
- **Agenda target**: the meeting, task or person whose agenda an item is on.
- **Agenda**: the open agenda items of one agenda target.
- **Today**: the built-in agenda target that is the owner's to-do list for the day. Its items carry over until they're marked Done.
- **Quick task**: a task made from one line and put on Today, from Today's box, the Today hotkey, or a new task with no task picked that goes on Today. It's an ordinary task.
- **Quick tasks**: the built-in top-level task that quick tasks wait under until Edit task puts them under their real task. DocRepo makes it the first time it's needed.
- **Discard**: hiding a task or capture made by mistake, with a reason. Nothing is deleted, and Bring back restores it. It's how DocRepo "deletes" anything.
- **Scope**: which tasks a view or prompt draws on: this task, with ancestors, with subtasks, or family. Family is all ancestors plus all descendants.
- **Event**: a dated happening, such as an audit or a turnaround, entered as a task's Deadline. "Event" means nothing else.

## 3. People and hours

- **People list**: everyone DocRepo knows, each with an ID such as P001, aliases and available hours per week.
- **Lead**: a person driving a task. A task can have several.
- **Assignee**: a person doing a task's work. A task can have several.
- **Participants**: a task's leads and assignees together.
- **Me**: the person marked as DocRepo's owner. "I" and "me" in a capture mean them.
- **Lead hours, Assignee hours**: estimated hours for each person in that role: a total for a one-time task, per occurrence for a routine one.
- **Capacity calendar**: hours per person, workday and task, built from task fields. It's a cache that can be rebuilt at any time.

## 4. Files and documents

- **Original**: a file where it already lives, on a local drive or the LAN. DocRepo only reads it.
- **Document**: DocRepo's record of an original, with an ID such as D000042, a file description and extracted text.
- **Extracted text**: the plain text DocRepo pulls out of a file when a capture adds it, kept in `Documents/<id>/extracted.txt` for search and for the differences in document versions. Pulling it out isn't Extract, which is the later processing for the knowledge base.
- **File description**: the description written for each file added to a capture. It tells people, and later agents, what the file holds without opening it.
- **Saved copy**: a copy of a file in a task's `Files` folder, made only when Save a copy is checked.
- **Attachment**: a file inside an Outlook email, saved with that email's capture.
- **Email layer 0**: the first pass over an Outlook email added to a capture. It gives each of the email's attachments, the links in its body and the pictures in its body a row of its own, each kept or left out with Keep, and records what it kept and left out in the capture. Later layers, such as summaries and tasks from emails, build on it.
- **Link**: a web or SharePoint address kept as a document, with a file description, in place of a file. Its original is the address. DocRepo never opens or fetches it, so it has no extracted text; Copy link puts it on the clipboard.
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
- **Build phase**: a numbered step in building DocRepo, phases 1 to 6 in `PROGRESS.md`.
- **Mods log**: DocRepo's own list of changes the owner wants made to it.
- **IDs**: T task, C capture, D document, P person, M mod.

## 7. Retired words

- **Capture event**: say capture. It covers both the act and its record.
- **Content type**: say capture type.
- **New subtask**: as an option name, say New task. It's a subtask when it has a parent.
- **File a copy**: say Save a copy, so "filing" only means linking an unfiled capture.
- **Project notes**: say Note.
- **Tag**: captures have a type, and tasks have labels.
- **option**: the field in `capture.md` becomes `capture_types`, a list, since one capture can be several types.
- **Inbox**: for the browse tool's view and the `Contents.md` section, say Unfiled.
- **Inbox capture**: say unfiled capture.
- **Raw notes**: say raw text log.
- **Content**: for the capture window's text, say content text.
