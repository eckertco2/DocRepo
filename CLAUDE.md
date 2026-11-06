# DocRepo

@.github/copilot-instructions.md

## Working in this repo (Claude Code, personal computer)

- The design is in the parent workspace: `../docs/task-model/brainstorm.md`, plus the browse tool mockup and its exports in `../docs/browse-tool/` (`examples.md` for file formats, `test-vectors.md` for expected results). It moves into `SPEC.md` here phase by phase, so the repo stands on its own on GitHub.
- Use the terms in `GLOSSARY.md`, and not the retired words at its end.
- Build in the phases listed in `PROGRESS.md`, in order. At the end of each phase, stop, summarize, and give the owner numbered steps to test it by hand. Keep `PROGRESS.md` current.
- Prefer the standard library. Write small modules with docstrings and type hints.
- A new list view or form is a module of its own (release 5.95, the whole-app review's F11), taking the browse window, its tree and the model; nothing new goes into `BrowseWindow` or `CaptureWindow` that could be a module. `BrowseWindow`'s list views, page commands and notes wiring are already mixins in `docrepo/ui/lists/`, moved as they were; turning one into a function of (browse, tree, model) is welcome whenever it's touched. A long builder gets a `_build_<section>` method per section, as `SettingsView` and `CaptureWindow._build` have.
- Write automated tests for everything that doesn't need the GUI. Run them with `.venv\Scripts\python.exe -m pytest`.
- The fast run (release 5.88): `.venv\Scripts\python.exe -m pytest -m "not gui"` runs the tests that don't use Qt, in about two minutes, without importing Qt at all; `conftest.py` marks every test in a module that imports `docrepo.ui` or PySide6, or sets `QT_QPA_PLATFORM`, as `gui`. `--lf` reruns only the last run's failures. Each run has its own temporary folder, `.pytest_tmp\run-<process id>`, so two runs can go at once.
- A schema change adds a zipped sample data root at the old version to `tests/fixtures/roots/` (how is in `tests/test_migrations.py`), so the upgrade from it is tested with data in it.
- Lint with ruff (release 5.87): `ruff.toml` selects pycodestyle, pyflakes, bugbear, blind excepts and bandit's checks, so each `# noqa` names a rule that's really checked, with its reason. Ruff is a development tool for this computer only: install it in a venv of its own (`py -3.12 -m venv %TEMP%\ruffenv` then `%TEMP%\ruffenv\Scripts\python.exe -m pip install ruff`), never in `.venv` or `requirements.txt`, and run `%TEMP%\ruffenv\Scripts\ruff.exe check .` here. The tests don't need it. Keep it at no findings.
- Each release sets `__version__` in `docrepo/__init__.py`, adds its line at the top of `CHANGELOG.md` and its row in `PROGRESS.md`, and is tagged when it's committed (`git tag v5.87`). Tags reach GitHub with `git push --tags`, which the owner runs.
- Classic Outlook isn't installed on this computer. Outlook code is tested with fakes here and by hand on the corporate computer.
- Run the app against `dev_data/` only, for example `.venv\Scripts\python.exe -m docrepo --data-root dev_data init`.
- Commit only when the owner asks. Publishing means pushing to the public GitHub repo, so check each change for personal or company details first.
