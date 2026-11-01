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

CI produces build artifacts for verification. Public binary release publication is a separate
step: assemble the corresponding-source bundle and verify notices before attaching binaries
to a public release. This repository does not automatically publish GitHub Releases.

Qt libraries are kept as separate files for replacement. The Python/Qt dependency versions
are pinned in `pyproject.toml`; runtime tool versions and checksums are in `tools-lock.json`.

Manual validation still required for a release: clean Windows 10/11 and Linux desktop launch;
public YouTube single video/playlist/channel extraction; interruptions on a server supporting
byte ranges; and packaging installation/uninstallation. Automated local tests do not prove
availability of every live website extractor.
