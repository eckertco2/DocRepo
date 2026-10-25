# DocRepo

Capture work notes, emails and documents in seconds, organize them as a tree of tasks, and keep track of people's capacity. DocRepo is a Windows desktop app written in Python with PySide6. It makes no network connections.

Status: the first everyday version. See `PROGRESS.md`.

## Install on a computer

You need Windows and Python 3.12.

1. Get the code from GitHub. The repo is public, so no sign-in is needed. Download https://github.com/eckertco2/DocRepo/archive/refs/heads/main.zip (the same as **Code → Download ZIP** on the repo's page) and extract it. The files are inside a folder named `DocRepo-main`; rename it to `DocRepo` and keep it on the local drive, outside OneDrive, for example `C:\Users\<you>\DocRepo`. With git, `git clone https://github.com/eckertco2/DocRepo.git` does the same.
2. Open a terminal in that folder and make a virtual environment:
   ```
   py -3.12 -m venv .venv
   ```
3. Install the dependencies:
   ```
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
   pip gets each package from the package index that this computer's pip is set up to use. On the corporate computer, that's the company's JFrog repository. DocRepo itself knows nothing about it.
4. Choose where your data lives (the data root). It must be on the local drive, not in a OneDrive folder. Then create it:
   ```
   .venv\Scripts\python.exe -m docrepo set-data-root "C:\Users\<you>\DocRepoData"
   .venv\Scripts\python.exe -m docrepo init
   ```
   Later, the browse tool's Settings view can change the data root, and the other settings.

## Update

1. Quit DocRepo from its tray icon's menu.
2. With git, run `git pull`. With a ZIP, delete the old `docrepo` and `tests` folders, then unzip the new version over the old folder, keeping `.venv`.
3. If `requirements.txt` changed, run install step 3 again.

Your data root is outside the code folder, so updating never touches your data. If DocRepo's database needs changes for the new version, it makes them itself the next time it starts.

## Start DocRepo

```
.venv\Scripts\pythonw.exe -m docrepo app
```

DocRepo's icon appears in the tray (it may be under the ^ arrow). Press **Ctrl+Shift+Space**, or click the icon, to open the capture window; Esc hides it again. The first time, DocRepo asks for your name, to add you to its people list as "me". Quit it from the tray icon's menu.

To open the browse tool, choose **Open browse tool** in the tray icon's menu, or run:

```
.venv\Scripts\pythonw.exe -m docrepo browse
```

which starts DocRepo first if it isn't running. Closing the browse tool only hides it.

### Start it when you sign in

In the browse tool, open **Settings** and click **Make the Startup shortcut**. DocRepo makes `DocRepo.lnk` in its own folder and opens two File Explorer windows: one with the shortcut selected, and your Startup folder. Drag the shortcut into the Startup folder. DocRepo then starts each time you sign in, with no console window. (DocRepo writes only in its own places, so it leaves this step to you.)

`.venv\Scripts\python.exe -m docrepo make-shortcut` makes the same shortcut from the terminal. To stop DocRepo starting when you sign in, delete `DocRepo.lnk` from your Startup folder (type `shell:startup` in File Explorer's address bar to open it). If you move the DocRepo folder, make the shortcut again and replace the old one; Settings tells you when it points to another folder.

## Everyday use

- **Capture:** press the hotkey, pick a task (or none, to file it later), type or paste, drop files or Outlook emails on the window, and press **Ctrl+Enter**. Check **New task** to make a task, or **Update** to change one. **Alt+P** (Parse and populate) fills the fields from what you typed, says what it understood under the text, and tints the fields it filled until you change them. **Attach** adds files, a link or the email selected in Outlook. **Today** and the agenda picker sit beside the capture types. **Expand** (F11) makes the content text fill the window, for meeting notes. The content text keeps **formatting**, with OneNote's keys: Ctrl+B, Ctrl+I and Ctrl+U, Ctrl+- for strikethrough, Ctrl+Alt+H to highlight, Ctrl+. and Ctrl+/ for lists (or start a line with “- ”, “* ” or “1. ”; Tab indents an item), Ctrl+Up and Ctrl+Down by paragraph, and Alt+Shift+Up and Alt+Shift+Down to move a line. Pasting from OneNote, Word or Outlook keeps it too.
- **Pin:** while you look for files in Outlook or File Explorer, **Pin** (F12, or the pin button beside Expand) shrinks the capture to a small window at the bottom right, on top of the others. Drop files, emails and web links on it, or type in its box; the capture hotkey brings the full window back. A **Pin hotkey** in Settings opens it from anywhere.
- **Items:** in any capture, `@Tom` makes a line a task for Tom (`@L.Tom` his lead, `@__` no one yet), `#Rigging plan` files it to that task, and `**Closed.`, `**u`, `**n`, `**t` or `**Decision.` say what it is; `**event. Spring outage, 3 to 14 Nov` makes a plant event. Type `@` or `#` for a list. A card for each item shows beside the text: untick one to skip it, or change its title or due date.
- **Meeting notes:** Alt+M in the capture window, M on a task, or **Meeting notes** on a meeting's page. Pick the meeting at the top: a regular meeting gets today's meeting under it. **Start from the agenda** puts its open items in the notes as headings to write under; the ones you write under close as Discussed when you save. The draft saves itself every 30 seconds. Alt+N, Alt+T and Alt+U tick Note, New task and Update; Alt+A goes to the agenda picker and Alt+D to Today. With **Show hints** (in **More**), the **i** buttons explain each field; **F1** lists every key. A file's description is optional: left empty, it's the task's name, "Attached document" and the file's name.
- **Browse:** the task tree, the lists (overdue, reminders, waiting on others and so on), agendas, capacity, people, labels and documents. With a task selected, **N** adds a note, **T** a new task under it, **U** an update, **A** puts it on an agenda, **E** edits it and **D** puts it on Today (one letter per topic; F1 lists them). Double-clicking a row opens its edit form (Edit task, or a capture's, person's or label's Edit); the arrow, or Right and Left, open and close its subtasks; **Open folder** on its page shows its folder. **Ctrl+F** narrows the view you're in as you type; the search box at the top (Ctrl+Shift+F) searches everything. The task tree filters by several labels and people at once, and the tree and lists can be sorted by due date, title, state or last update. The views button at the top left (Ctrl+B) hides the views on the left, and each group of views folds.
- **Today:** your list for the day, at the top of the views. Add a task with **D** or the **Today** button on its page, or from the capture window's Today button. The view's box makes a **quick task** from one line ("Call the vendor about seals by Fri" is due Friday), which waits under **Quick tasks** until **Edit** on its row puts it under its real task; switch the box to **Note** for a note, which has **Edit** and **Make it a task**. Items stay until you mark them **Done**, carrying over to the next day ("since Mon"). Done on a task offers to update it too. Below your items, **Due in the next 7 days** lists the tasks due soon that aren't on Today yet, each with **Add to Today**; **Mine only** keeps the ones you lead or are assigned to.
- **Edit a task:** **Edit task…** (E) in its Edit menu shows every field on one page. Each change goes into its status log; use Update in the capture window for a change that comes with a note. In this and the browse tool's other forms, **Ctrl+Enter** saves and closes, and **Esc** closes, asking first if you changed something.
- **Change several tasks:** tick **Select** on the task tree or a list, tick the tasks, then **Edit selected…**. Set only what should change: labels, state, people, dates or a parent. The preview shows each task's changes before you apply them.
- **People, labels and task fields:** a person can have an email address, a group and a role (**Edit…** on their page). DocRepo never sends email: **Copy email** on a person's page, or **Copy** on a task's page, puts addresses on the clipboard for Outlook's To box. The People filter lists the groups first, and ticking one ticks its people. A label can go under a parent label (**Under** in its Edit form), such as Line 1 under Production line; pickers show “Production line › Line 1”, ticking the parent in a filter ticks its sublabels, and the lists, timeline and capacity view can group by it. **Reference fields**, named in Settings, give every task a box for a number from another system, such as a change record's; Parse and populate fills one from the field's name followed by a number. Tick **Plant event** on an outage or turnaround task: the timeline shades it down the whole chart, the capacity view names its weeks, and a line under the dates says when they fall inside it.
- **A new label's tasks:** after you add a label or change its keywords, DocRepo lists the open tasks that mention them; tick the ones to label. **Find matching tasks…** on a label's page does the same.
- **Made by mistake:** **Discard…** (a task's Edit menu, or a capture's page) hides it, with a reason, in the **Discarded** view. Nothing is deleted, and **Bring back** restores it as it was.
- **More hotkeys:** in **Settings**, set a hotkey for the browse tool, for a note, a new task or an update, for Add to agenda, and for a quick task on Today. Each is off until you set it; **Use the suggested keys** fills the empty ones with Ctrl+Shift and the topic's letter. While DocRepo runs, those keys are taken from other programs, such as Outlook's Ctrl+Shift+N.
- **Unfiled captures** wait in the Unfiled view: file each one to a task, or make it a task.
- **Keys and the look:** **Ctrl+K**, in either window, lists every action and view and narrows as you type. Hold **Alt** to see each button's letter key, or **Ctrl** for the Ctrl shortcuts; each button's tooltip names its key too. **Show hints** (More, or Settings) brings back the help text; **Settings → Look** switches to the Classic look, release 5.9's colours and hints.
- **Changes to DocRepo itself:** note them in the mods log, the last button at the top right of the capture window. **Edit** on an open entry puts it back in the box, to add to it rather than start another.

## Import your project list from Excel

Do this once, when you start using DocRepo: each row of your project list becomes a top-level task.

1. In the browse tool, open **Settings** and click **Import projects from Excel…**.
2. **Choose…** the workbook. DocRepo only reads it, never changes it, and no macros run. If it's open in Excel and can't be read, close it or save a copy and import that.
3. Check the sheet and the row the headers are in.
4. For each column, check what it fills. DocRepo proposes this from the headers: the project's name is the **Title**, an owner is the **Lead**, team members are **Assignees**, a category column gives **Labels**, and a column of yes, no or x is **A label (yes or no)**, named in the Label box. Columns you don't map can **Add to the description**, so nothing is lost, or be **left out**.
5. If a column holds each project's state, set it to **State** and check what each value becomes. Otherwise choose the state every task starts in.
6. Read the preview: the tasks, the new people and labels, the values to check (such as a due date that isn't a date) and the rows skipped. Then click **Import**.

Running the import again skips every row whose title is already an imported task, so it never makes doubles. After the import, DocRepo is your project list; you can stop updating the workbook.

## Backups

In **Settings**, choose a **Backup folder** outside the data root and save. DocRepo then backs up every 7 days, at its first start of the day, and when you click **Back up now** (or run `.venv\Scripts\python.exe -m docrepo backup`). A notification says when it's done. You can change how often, and how many database copies to keep (8), in Settings.

In the backup folder:
- `Database\docs-1.db` and so on: copies of DocRepo's database. Each backup overwrites the oldest copy.
- `Files\`: a copy of every file in your data root (captures, emails, saved copies, extracted text, pages, settings and the mods log). New and changed files are copied; nothing is ever removed from it.
- `backup-log.md`: when each backup was made, and which database copy it wrote.

A backup folder on the same drive as the data root doesn't protect you from that drive failing. A folder on another drive, or on a network share you may write to, does.

**To restore:** quit DocRepo. Make a new, empty folder for the data root. Copy everything in the backup's `Files` folder into it, make a `System` folder there, and copy the newest database copy (see `backup-log.md`) into `System` as `docs.db`. Then:

```
.venv\Scripts\python.exe -m docrepo set-data-root "C:\Users\<you>\DocRepoRestored"
.venv\Scripts\python.exe -m docrepo rebuild
```

and start DocRepo.

## Try it with the sample data

DocRepo comes with made-up sample data: a few projects, people, captures and agendas, as of 8 October 2026. Load it into a separate, empty data root, never your real one:

```
.venv\Scripts\python.exe -m docrepo --data-root "C:\Users\<you>\DocRepoSample" init
.venv\Scripts\python.exe -m docrepo --data-root "C:\Users\<you>\DocRepoSample" load-sample
.venv\Scripts\python.exe -m docrepo --data-root "C:\Users\<you>\DocRepoSample" browse
```

Quit any other running copy first, since both would want the hotkey. You can also open the sample data root's `Contents.md` in VS Code and press Ctrl+Shift+V to follow its links, or print what DocRepo works out with `report --as-of 2026-10-08`. Delete the folder when you're done.

## Troubleshooting

- **A troubleshooting report to bring to the personal computer.** In **Settings**, click **Troubleshooting report…** (select an email in Outlook first if the problem is with Outlook). It checks each step of reading the selected email, lists recent drags and pastes in the capture window and recent warnings in the log, and leaves out email text, names and addresses. Read it through, then **Copy report**; it's also saved in `System\diagnostics` in your data root. From a console, `.venv\Scripts\python.exe -m docrepo troubleshoot` makes the same report without the drags and pastes.
- **Adding an Outlook email doesn't work.** The capture window says what Outlook refused, with an error code. Make a troubleshooting report with the email still selected.
- **Nothing seems to happen when DocRepo starts.** `pythonw` has no console, so errors go to the log: the end of `System\logs\docrepo.log` in your data root. Or start it once with `python.exe` instead of `pythonw.exe` to see the message.
- **"DocRepo is already running".** Another copy has the data root open; its tray icon may be under the ^ arrow. If none is running, the lock file named in the message is left from a crash: delete it and start again.
- **The hotkey does nothing.** Another program may use it; DocRepo says so when it starts. Choose another in Settings. **Pause hotkeys** in the tray menu turns them all off for a while.
- **The data root is refused.** It must be a full path on the local drive, outside OneDrive and outside DocRepo's own folder.
- **A backup couldn't be made.** The notification says why: often the backup folder's drive isn't there. The next backup tries again; **Back up now** tries at once.
- **A page in the data root looks out of date.** `Contents.md` and each `Task.md` are rebuilt from the database. **Rebuild pages, calendar and search** in Settings (or the `rebuild` command) rebuilds them all.

## Where things are

- The code is in this folder.
- Your data is in the data root you chose. Its location is recorded in `%LOCALAPPDATA%\DocRepo\location.json`, next to the Startup shortcut DocRepo makes.
- DocRepo writes nowhere else, except the backup folder you choose in its settings.

## Development

See `CLAUDE.md` and `.github/copilot-instructions.md`. Run the tests with `.venv\Scripts\python.exe -m pytest`. `tests\sample_workbook.py` makes a made-up project list for trying the Excel import.
