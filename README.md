# DocRepo

Capture work notes, emails and documents in seconds, organize them as a tree of tasks, and keep track of people's capacity. DocRepo is a Windows desktop app written in Python with PySide6. It makes no network connections.

Status: being rebuilt. See `PROGRESS.md`.

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
   Once the browse tool exists, this moves into its Settings view.

## Update

1. With git, run `git pull`. With a ZIP, delete the old `docrepo` and `tests` folders, then unzip the new version over the old folder, keeping `.venv`.
2. If `requirements.txt` changed, run install step 3 again.

Your data root is outside the code folder, so updating never touches your data.

## Where things are

- The code is in this folder.
- Your data is in the data root you chose. Its location is recorded in `%LOCALAPPDATA%\DocRepo\location.json`.
- DocRepo writes nowhere else, except the backup folder you choose in its settings.

## Development

See `CLAUDE.md` and `.github/copilot-instructions.md`. Run the tests with `.venv\Scripts\python.exe -m pytest`.
