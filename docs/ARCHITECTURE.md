# Architecture

`models.py` validates job configuration and creates format selectors. All subprocess
arguments are lists; media URLs are separated with `--`. User/global yt-dlp configuration
and plugins are disabled for predictable local behavior.

`database.py` stores jobs, settings, media records, and active media reservations in SQLite.
Connections are short-lived. WAL and `BEGIN IMMEDIATE` make media reservation atomic across
workers. A completed media record must have existing files; a failed job does not enter history.
The GUI holds a profile lock to keep a second process from recovering the same active queue.

`engine.py` runs a bounded worker pool. Each source is resolved off the GUI thread. Playlists
expand into child jobs; expansion is repeatable after interruption. Downloads use separate
yt-dlp processes. Structured progress and final-path records update the database. Pause/cancel
terminate the process group/tree, including FFmpeg. Partial files are retained for yt-dlp.

`archive.py` exports explicit registered files. It rejects symlinks, missing paths, and files
outside their recorded collection root. An adjacent temporary archive is atomically renamed
only after success. A manifest includes source records and per-file SHA-256 values.

`updates.py` fetches the official stable yt-dlp release only on explicit request. It verifies
the release's SHA-256 list, checks the executable's reported version, and atomically installs
it in the writable profile. Reset removes that override. The bundled tool remains available.

`window.py` and `preferences.py` use Qt Widgets, standard menus/toolbars, sortable tables,
and translated strings. Worker messages cross into the GUI via Qt signals. SQLite state
refreshes on a 600 ms timer. No browser, web renderer, server, account service, or analytics
SDK is embedded in the interface.

`AppPaths` separates immutable packaged assets from writable profile data. `portable.txt`,
`--portable`, and `--data-dir` provide explicit profile choices. The application never needs
to modify its installation directory in installed mode.
