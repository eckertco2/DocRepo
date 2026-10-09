# DocRepo

@.github/copilot-instructions.md

## Working in this repo (Claude Code, personal computer)

- The design is in the parent workspace: `../docs/task-model/brainstorm.md`, plus the browse tool mockup and its exports in `../docs/browse-tool/` (`examples.md` for file formats, `test-vectors.md` for expected results). It moves into `SPEC.md` here phase by phase, so the repo stands on its own on GitHub.
- Build in the phases listed in `PROGRESS.md`, in order. At the end of each phase, stop, summarize, and give the owner numbered steps to test it by hand. Keep `PROGRESS.md` current.
- Prefer the standard library. Write small modules with docstrings and type hints.
- Write automated tests for everything that doesn't need the GUI. Run them with `.venv\Scripts\python.exe -m pytest`.
- Classic Outlook isn't installed on this computer. Outlook code is tested with fakes here and by hand on the corporate computer.
- Run the app against `dev_data/` only, for example `.venv\Scripts\python.exe -m docrepo --data-root dev_data init`.
- Commit only when the owner asks. Publishing means pushing to the public GitHub repo, so check each change for personal or company details first.
