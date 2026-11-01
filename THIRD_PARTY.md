# Third-party components

SONATA application code is GPL-3.0-or-later. The distribution contains separately
licensed components. Their licenses continue to apply; this file does not relicense them.

| Component | Purpose | License / upstream |
|---|---|---|
| Python | Embedded runtime in frozen builds; tar/gzip/SQLite support | [PSF license](https://docs.python.org/3/license.html) |
| PySide6 / Qt 6 | Native desktop widgets | [LGPLv3 / GPLv3 / commercial](https://doc.qt.io/qtforpython-6/licenses.html) |
| yt-dlp | Media extraction and transfer | [Unlicense, with bundled dependency notices](https://github.com/yt-dlp/yt-dlp/blob/master/THIRD_PARTY_LICENSES.txt) |
| Deno | Local JavaScript execution for YouTube extraction | [MIT and dependency notices](https://github.com/denoland/deno/blob/main/LICENSE.md) |
| FFmpeg / FFprobe | Merge, remux, audio conversion, metadata | [GPLv3 builds by BtbN](https://github.com/BtbN/FFmpeg-Builds) |
| PyInstaller bootloader | Application launcher | [GPL with distribution exception](https://pyinstaller.org/en/stable/license.html) |

`tools-lock.json` records each bundled tool's release, exact source URL and SHA-256.
Builds copy upstream license files from runtime archives into `vendor/licenses`.
FFmpeg build scripts and source retrieval instructions are at the exact upstream
release linked by the lock. SONATA release automation also preserves FFmpeg's
source archive alongside binary packages, when supplied by the upstream release.

Qt libraries are distributed as separate files in the application directory.
Users may replace those libraries with ABI-compatible versions. Qt source and
build instructions: https://code.qt.io/cgit/pyside/pyside-setup.git/ and
https://code.qt.io/cgit/qt/qtbase.git/ (match the bundled version).

Binary release maintainers must retain all bundled notices and provide the
corresponding source required by component licenses. See `docs/BUILDING.md`.
