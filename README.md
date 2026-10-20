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

- **Capture:** press the hotkey, pick a task (or none, to file it later), type or paste, drop files or Outlook emails on the window, and press **Ctrl+Enter**. Check **New task** to make a task, or **Update** to change one. **Alt+P** (Parse and populate) fills the fields from what you typed. The **i** buttons explain each field.
- **Browse:** the task tree, the lists (overdue, reminders, waiting on others and so on), agendas, capacity, people, labels and documents. With a task selected, **A** adds a note, **N** a new task under it, **U** an update and **G** puts it on an agenda. Search is at the top (Ctrl+F). The task tree filters by several labels and people at once, and the tree and lists can be sorted by due date, title, state or last update. **≡ Views** (Ctrl+B) hides the views on the left.
- **More hotkeys:** in **Settings**, set a hotkey for the browse tool, for a note, a new task or an update, and for Add to agenda. Each is off until you set it.
- **Unfiled captures** wait in the Unfiled view: file each one to a task, or make it a task.
- **Changes to DocRepo itself:** note them in the mods log, the **?** button in the capture window.

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
