# Architecture

`models.py` validates job configuration and creates format selectors. All subprocess
arguments are lists; media URLs are separated with `--`. User/global yt-dlp configuration
and plugins are disabled for predictable local behavior.

`database.py` stores jobs, settings, media records, and active media reservations in SQLite.
Connections are short-lived. WAL and `BEGIN IMMEDIATE` make media reservation atomic across
workers. A completed media record must have existing files; a failed job does not enter history.
The GUI holds a profile lock to keep a second process from recovering the same active queue.

`engine.py` runs a bounded worker pool with two metadata scanners and up to eight download
workers. Adding a source scans its formats off the GUI thread. The database caches dimensions,
frame rates, and media identity, without signed stream URLs or authentication headers. Each
video selects its highest actual resolution; subsequent edits apply only to that job. Downloads
require explicit Start/Resume, tracked per job. Playlists expand into individually scanned child
jobs; expansion is repeatable after interruption and parent controls include children. Downloads use separate
yt-dlp processes. Structured progress and final-path records update the database. Pause/cancel
terminate the process group/tree, including FFmpeg. Partial files are retained for yt-dlp.

`media.py` provides FFprobe inspection, validated FFmpeg commands, cancellation, and temporary
output handling. Local processing preserves inputs and publishes a separate output only after
successful processing and inspection. MP4 download finalization preserves tags/chapters and
video streams, uses AAC when audio needs conversion, and verifies dimensions/duration before
replacing the new download. `media_window.py` exposes those operations in a modeless window,
including an advanced output-arguments page and generated command preview.

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
