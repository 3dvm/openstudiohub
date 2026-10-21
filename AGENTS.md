# AGENTS.md — OpenStudioHub

## Language

- All user-facing strings, UI labels, dialogs, error messages and tooltips must be in **English**.
- All code comments, docstrings, log messages and commit messages must be in **English**.
- Existing Spanish text should be translated opportunistically when a file is touched. New code must never introduce Spanish UI text or Spanish comments.

## Code conventions

- Keep the MVVM boundaries: views never call infrastructure directly; ViewModels orchestrate application services.
- Keep new VCS work behind the adapters in `src/infrastructure/vcs/`; do not duplicate subprocess logic in UI code.
- Add or update tests for every behavioural change. Prefer pytest and the existing `qapp` fixture for Qt code.

## VCS

- The supported client is the `svn` CLI, minimum version 1.14.
- Never put passwords in command-line arguments or logs.
- The Hub must verify the VCS configuration at startup and launch the initial setup wizard when it is incomplete.
- `*.blend` files must carry `svn:needs-lock`; server-side hooks enforce it.

## Verification

- Run the full suite before finishing: `.venv/bin/python -m pytest -q`.
- Prefer focused tests first while iterating, then the full suite.
