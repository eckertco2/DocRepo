# DocRepo progress

DocRepo is being rebuilt on the owner's personal computer, starting 2026-10-08. The first version's phases 0 to 2, built on the corporate computer, are replaced.

## Phases

| Phase | What | Status |
|---|---|---|
| 1 | Skeleton and safety: the data root's location, settings, guarded writes, logging, the command line, and the network-module scan | Done. Tested on the corporate computer (2026-10-09): pip install, pytest and the command checks |
| 2 | Database and task model: schema, IDs, the task tree, labels, people, logs, recurrence, days until due, the capacity calendar, and the generated pages, checked against the mockup's test vectors and examples | Built 2026-10-16; every test passes here. Waiting for the owner's hand test, then goes to the corporate computer with phase 3 |
| 3 | Capture app: tray, hotkey, the capture window (task picker, the Note, New task and Update capture types, Parse and populate, Copy prompt, mods log), saving captures, text extraction, Outlook emails and LAN paths | Not started |
| 4 | Browse tool: the views, task and capture pages, agendas, capacity, people, labels, documents, search, and Settings | Not started |
| 5 | First everyday version: Startup shortcut, backups, the one-time Excel import of the project list, and the README | Not started |
| 6 | Document tracking: change checks, diffs, replaced saved copies, and relinking moved files | Not started |

## Decisions

- Python 3.12.6, the same version as on the corporate computer.
- Packages: the seven approved in the first version's Phase 0, at the same versions, pinned in `requirements.txt` with their dependencies. extract-msg isn't used; `.msg` files are read through Outlook.
- Default hotkey: Ctrl+Shift+Space.
- No paths in the code. The data root's location is kept in `%LOCALAPPDATA%\DocRepo\location.json`; everything else is in `<data root>\Config\settings.json` and is edited in the browse tool's Settings view.
- Publish to GitHub after phase 1, to test the route to the corporate computer early.
- The GitHub repo is public (2026-10-09), so the corporate computer can download it without signing in to GitHub. Nothing personal or company-related may go into it.

## Code layout (phase 1)

- `docrepo/safe_fs.py`: the only module that writes, copies, moves or creates folders. See SPEC section 4.
- `docrepo/config.py`: the data root's location (`location.json`), `Settings` (`Config\settings.json`), the OneDrive and code-folder checks, `make_safe_fs` and `init_data_root`.
- `docrepo/log_setup.py`: the rotating log in `System\logs`.
- `docrepo/cli.py`: the commands `where`, `set-data-root`, `init` and `try-write`.
- `tests/`: the guard (including `..`, junctions and symlinks), the network-module scan, settings and the command line. 53 pass; the symlink test is skipped because this Windows account can't create symlinks, the same as on the corporate computer.

## Code layout (phase 2)

- `docrepo/db.py`: `docs.db`, its schema and version, transactions, and IDs. See SPEC section 6.1.
- `docrepo/dates.py`, `docrepo/schedule.py`: dates as stored and shown; windows, next occurrences and days until due.
- `docrepo/model.py`: a read-only snapshot of the database and the rules that read it (the tree, scopes, inherited labels, raw text logs, summaries, files, the status log, agendas, unfiled captures).
- `docrepo/tasks.py`, `docrepo/people.py`, `docrepo/agenda.py`, `docrepo/captures.py`: the writes. Task changes go into the status log and rebuild the task's calendar rows in the same transaction. `captures.py` also writes `capture.md`.
- `docrepo/capacity.py`: the capacity calendar (`work_calendar`), unestimated and unscheduled tasks. `docrepo/lists.py`: the six lists.
- `docrepo/pages.py`: `Task.md` and `Contents.md`. `docrepo/text.py`: sentences and capture titles. `docrepo/report.py`: the `report` command's text.
- `docrepo/sample.py` and `docrepo/sample/sample-data.json`: the made-up sample data and `load-sample`.
- `tests/`: 65 new tests. `tests/fixtures/` holds the mockup's `examples.md` and `test-vectors.md`; every generated page, the `capture.md` examples and the report's tables match them line for line.

## Decisions (phase 2)

- The sample data's labels are Line 1, Line 2 and Strategic Plan, so nothing from real work is in the public repo.
- Agenda entries in a status log are worked out from `agenda_items`, not stored twice.
- A capture's content text stays in its `capture.md`; the database keeps its title.
- A generated page is rewritten only when more than its "Generated on" line changes.
- `report` writes UTF-8 when its output goes to a file.

## Unfinished / notes

- Phase 2 isn't on GitHub yet. Phases 2 and 3 go up together (brainstorm round 12).
- The daily rebuild of routine tasks' calendar rows, and of the pages, runs when the capture app starts each day; that's phase 3. Until then, `rebuild` does it.

- `SPEC.md` covers phase 1 in full; later phases are summaries until they're built. The detailed design is in the parent workspace's `docs/task-model/brainstorm.md`.
- Published to the GitHub repo `eckertco2/DocRepo` on 2026-10-09 (phase 1).
- The route to the corporate computer works (2026-10-09): download, a security scan there, `pip install -r requirements.txt` with every pinned version available, and pytest passing.
