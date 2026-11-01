SONATA 0.1.0 — Overture: runtime source snapshots

The application packages are built from application commit:
8181345f78359c56e2aa86deace76311484d892d
Verified Windows/Linux build: https://github.com/blindicide/SONATA/actions/runs/41316533412

Source-Qt-6.8.3.tar.xz is the complete upstream Qt source distribution, including
its bundled third-party sources and notices. Source-PySide-Shiboken-6.8.3.tar.gz
contains the Python bindings and Shiboken sources. Python versions match the
Windows (3.12.10) and Linux (3.12.15) CI runtimes. Qt shared libraries remain
separate files in SONATA and can be replaced with ABI-compatible versions.

FFmpeg source revision: 4811625b5f4e5aed528aed9225d0ca868a8e6e96
Build recipe revision: 5031c6f1082414e53688d39e521849905071070d
Build targets: win64 gpl and linux64 gpl
Upstream release: autobuild-2026-10-31-12-59

The FFmpeg dependency source cache from the same upstream build is preserved
as numbered parts to stay below GitHub's per-asset size limit. Reassemble in
numeric order before opening it. On Linux:

  cat Source-FFmpeg-dependencies.tar.gz.part-* > ffmpeg-dependency-sources.tar.gz
  tar -xzf ffmpeg-dependency-sources.tar.gz

The resulting .cache/downloads directory contains the pinned upstream component
source archives, including vendored sources where supplied by the upstream
download recipes. The original build scripts identify each component and its
build instructions. SOURCE-MANIFEST.json records the cache provenance and hash.
Build tooling may retrieve additional unmodified toolchain/registry packages as
specified by those upstream build recipes and lockfiles.

yt-dlp-THIRD-PARTY-LICENSES.txt is extracted from the exact bundled yt-dlp binary.
Its original upstream source-availability statement and component notices are
preserved. The included Mutagen source version is read from that binary.

Sources are unmodified upstream snapshots except SONATA's own application code
and packaging scripts. Each component retains its own license. SHA256SUMS covers
the application packages, source archives, split parts and provenance files.

These source archives are for development and inspection. They are not needed
to install or run SONATA. See the repository's docs/BUILDING.md for application
build instructions and THIRD_PARTY.md for component licensing references.
