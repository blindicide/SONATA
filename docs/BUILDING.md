# Building and distribution

Use Python 3.12 on x86-64. Build each package on its target OS; PyInstaller is not a
cross-compiler. CI uses Windows and Ubuntu 22.04 runners and exercises real local HTTP
downloads, FFmpeg remuxing/audio extraction, duplicate detection, and archive export.

1. Install `.[dev]` in an isolated environment.
2. Run `python scripts/fetch_tools.py` to download exact locked runtime assets.
   Then run `python scripts/collect_licenses.py` to collect installed-runtime notices.
3. Run Ruff and pytest. Enable `SONATA_INTEGRATION=1` for real tool tests.
4. Run `python -m PyInstaller --noconfirm packaging/sonata.spec`.
5. Run `python scripts/package.py` for portable ZIP/TAR.GZ and a Linux DEB.
6. On Windows run `ISCC.exe packaging/installer.iss` with Inno Setup 6 to build the
   English/Russian per-user installer. The GitHub Windows runner supplies the compiler.

The Windows portable marker is excluded from the installer. Removing an installed
application does not delete the user's library, media, or settings. Portable data is kept
beside the executable, so retain `.sonata` when replacing a portable build.

The runtime lock uses immutable dated release URLs where available. BtbN keeps month-end
releases longer than daily releases; the initial lock uses the 2026-10-31 month-end build.
If an upstream asset is removed, normal builds fail rather than substitute unverified tools.
Refresh and review the lock explicitly to move to another release.

## Component sources and notices

Retain `LICENSE`, `THIRD_PARTY.md`, runtime notices and the tool lock in distributed packages.
The FFmpeg build's `-buildconf` identifies enabled third-party libraries, whose licenses
also apply. A release publisher must provide the complete corresponding source and build
materials required for those exact binaries, including enabled libraries. The BtbN source
repository/build scripts alone are not a substitute for all corresponding dependency sources.

CI produces build artifacts for verification. `publish-release.yml` publishes the Overture
release from its verified build, checks package hashes, preserves pinned upstream source
snapshots and the FFmpeg dependency source cache, and archives developer materials
as a separate Actions artifact. The public Release contains only the four application
packages and their SHA256SUMS file. The workflow creates a draft, uploads those five
assets, and publishes only after those steps succeed.
That initial workflow runs on `release/v0.1.0` or by explicit manual dispatch. Application
updates use `publish-update.yml`: a successful push build of `release/v0.1.1` supplies both
platform artifacts. `prepare_application_release.py` checks their hashes and selects exactly
four application packages plus SHA256SUMS; extra files are rejected. Publication happens after
both platforms pass tests and packaging. Published releases are preserved. Runtime dependencies
are unchanged in 0.1.1. Review source and notice requirements again when changing runtime
versions; the Overture manifest is specific to its pinned dependency set.

Qt libraries are kept as separate files for replacement. The Python/Qt dependency versions
are pinned in `pyproject.toml`; runtime tool versions and checksums are in `tools-lock.json`.

Manual validation still required for a release: clean Windows 10/11 and Linux desktop launch;
public YouTube single video/playlist/channel extraction; interruptions on a server supporting
byte ranges; and packaging installation/uninstallation. Automated local tests do not prove
availability of every live website extractor.
