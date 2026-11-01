# Contributing

Use an isolated Python 3.12 environment and follow `docs/BUILDING.md`.
Run Ruff and pytest before submitting changes. A meaningful engine change should include
a regression test; changes involving real tools should also run the local integration test.

Keep the GUI compact and conventional. Prefer Qt Widgets, real menus and table rows.
Every new user-facing label should have an English and Russian translation.
Network operations must be explicit user actions and must run off the GUI thread.
Never add analytics, cloud dependencies, arbitrary shell execution, or silent tool downloads.

For a bug report, include SONATA/tool versions, operating system, reproduction steps,
and a redacted error. Do not publish private media URLs, authentication cookies or tokens.
