# DocRepo progress

DocRepo is being rebuilt on the owner's personal computer, starting 2026-10-08. The first version's phases 0 to 2, built on the corporate computer, are replaced.

## Phases

| Phase | What | Status |
|---|---|---|
| 1 | Skeleton and safety: the data root's location, settings, guarded writes, logging, the command line, and the network-module scan | Built; waiting for the owner's test |
| 2 | Database and task model: schema, IDs, the task tree, labels, people, logs, recurrence, days until due, the capacity calendar, and the generated pages, checked against the mockup's test vectors and examples | Not started |
| 3 | Capture app: tray, hotkey, the capture window (task picker, New subtask, Update task, Parse and populate, Copy prompt, mods log), saving captures, text extraction, Outlook emails and LAN paths | Not started |
| 4 | Browse tool: the views, task and capture pages, agendas, capacity, people, labels, documents, search, and Settings | Not started |
| 5 | First everyday version: Startup shortcut, backups, the one-time Excel import of the project list, and the README | Not started |
| 6 | Document tracking: change checks, diffs, replaced filed copies, and relinking moved files | Not started |

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

## Unfinished / notes

- `SPEC.md` covers phase 1 in full; later phases are summaries until they're built. The detailed design is in the parent workspace's `docs/task-model/brainstorm.md`.
- Published to the GitHub repo `eckertco2/DocRepo` on 2026-10-09 (phase 1). Next: the owner installs it on the corporate computer to test the route, including pip installing from JFrog.
