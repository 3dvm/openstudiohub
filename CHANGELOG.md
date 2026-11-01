# Changelog

All notable changes to OpenStudioHub are documented here.

The project follows Semantic Versioning. Before `1.0.0`, minor and patch
releases may include larger UI or workflow changes.

## [Unreleased]

### Added

- Incremental access profiles with view switching:
  - `TD` can use the TD, PM and Artist dashboards;
  - `PM` can use the PM and Artist dashboards;
  - a PM with the `lead` position (the Editor) uses the Artist dashboard and
    is labelled `Editor` in the top bar;
  - `Artist`, `Vendor` and `Lead` use the Artist dashboard only;
  - `Supervisor`, `Client` and `Guest` are denied access for now.
- Top-bar profile selector showing the active profile and allowing permitted
  users to switch dashboards.
- Project configuration changes are mirrored into `project_config.json` and
  mark the workspace as requiring an update; the project card and config dialog
  expose the update action.
- Shared task-file resolver that handles linked paths, case differences,
  versioned masters and naming drift. Missing task files are reported on the
  card and block the launch.
- Spawned `.blend` files are registered in Subversion as soon as the wizard
  finishes: `svn add`, `svn:needs-lock`, and one `first spawn` commit per batch.
- `Register Spawned Files to VCS…` backfill action for projects created before
  automatic registration.
- Version-aware add-on deployment:
  - the vault manifest is authoritative per Blender version;
  - installed add-ons are refreshed when the manifest declares a compatible
    newer version or different archive content;
  - updates fail explicitly when the declared archive is missing or
    incompatible;
  - project integrity marks the workspace as needing an update.
- `openstudio_toolkit` 0.6.0, with self-contained QA rules so it loads from the
  Blender extension sandbox.
- Per-project Blender preferences:
  - Temporary Files points to `<vfs_local>/blender-tmp/`;
  - Undo Steps is set to 256;
  - Save Versions is set to 0 when the project uses VCS;
  - artists can save, import and export `userpref.blend` from the Toolkit panel.

### Changed

- OpenStudio Toolkit actions are now separate operations: `Audit Scene`,
  `Fix Out-of-Bounds Textures`, `Purge Orphans` and `Save & Commit`.
- The software manifest editor exposes **Package OpenStudio Toolkit** so the
  local toolkit can be repackaged for the selected Blender version without
  fetching remote Studio Tools.
- Removed the Toolkit's own Kitsu playblast hook; Blender Kitsu remains the
  owner of playblast publishing.
- Prop asset tasks use a two-frame timeline (`1–2`); shots and other entities
  keep their original frame range.
- The add-on manifest parser no longer mistakes `schema_version` for the
  add-on version.

### Fixed

- SVN unlock is idempotent. Files already unlocked by another client no longer
  produce `E195013` notifications.
- Lock probes for unversioned or missing paths no longer emit `W155010` audit
  failures or `Info failed` notifications.
- `openstudio_toolkit` activates correctly inside the Blender sandbox.

### Tests

- Full suite: 686 passing tests.

## [0.7.5] - 2026-10-25

### Added

- Production-grade Subversion client workflow:
  - startup verification of the Studio Seed, projects folder and SVN client;
  - Initial Configuration wizard with Seed, SVN client and projects folder
    steps;
  - SVN 1.14 minimum version gate;
  - deterministic setup for first-time machines.
- Typed SVN command runner with timeouts, cancellation, UTF-8 decoding, process
  cleanup and structured `E...`/`W...` error classification.
- TLS controls for HTTPS repositories:
  - pinned CA file;
  - optional system CA trust;
  - explicit certificate-failure allow-list;
  - fail-closed behavior for missing CA files.
- Structured working-copy status with content, property and tree conflict
  detection.
- Conflict resolution (`mine-full`, `theirs-full`, `working`) from the publish
  window.
- `svn:needs-lock` policy for `.blend` files:
  - repository `svn:auto-props`;
  - pre-commit hook that rejects `.blend` files without the lock property;
  - cache/backup path rejection;
  - TD action to refresh the policy on existing repositories.
- Lock recovery and administration:
  - stale same-user lock detection;
  - Release my lock action;
  - TD break-lock action;
  - TD repository lock manager backed by `svnadmin lslocks` and `svnadmin
    rmlocks`.
- VCS update cleanup:
  - conflict/obstruction reporting;
  - Move aside with timestamped backups under `.openstudio_aside`;
  - local ignores applied through `svn --config-option`;
  - Retry update action.
- File history, diff and revision export:
  - `svn log` history viewer;
  - revision diff and working-copy diff;
  - safe export of historical revisions without overwriting the workspace.
- VCS audit trail:
  - JSON Lines log with operation, project, server, user, paths, result,
    revision and duration;
  - secret redaction and automatic rotation;
  - TD-only VCS Audit viewer with filters and failure-only mode.
- In-app notification center:
  - top-bar bell with unread badge;
  - VCS failure notifications derived from the audit trail;
  - per-user read state and baseline;
  - TD-only administrative notifications;
  - copy any notification to the clipboard with its SVN error code, project,
    paths and message;
  - dismiss notifications individually or clear the whole visible list;
  - dismissed notifications are kept in a hidden per-user archive and never
    reappear in the visible list.

### Changed

- Unified the Qt interface around the global QSS theme:
  - semantic surfaces, typography, cards, tables, lists, menus, checkboxes,
    progress bars and scrollbars;
  - shared spacing scale;
  - QSS-driven status states;
  - responsive VCS dialogs with size grips.
- Moved Settings to the bottom of the sidebar, with a smaller icon and a
  separator.
- Fixed the top-bar background in internal dashboards by using the canonical
  `TopBar` object name.
- Publish now keeps untracked files unchecked by default; they are only added
  when explicitly selected.
- Publish commit messages include completed task checklist items automatically.
- Locks are released after a successful publish. If a session ends with no
  changes, the lock is released; if there are pending changes, the lock stays
  until they are published.

### Fixed

- Stale same-user locks reported as `W160035` or `E200009` are recognized and
  can be released from the task card.
- Out-of-date commits are classified as `SvnOutOfDateError` instead of a raw
  process failure.
- Property-only and tree conflicts are surfaced instead of appearing as clean
  files.
- Conflict resolution no longer requires resetting the entire working copy.
- Update obstructions can be moved aside without deleting user data.
- The notification and audit logs never include passwords or passphrases.

### Security

- VCS passwords travel over stdin with `--password-from-stdin`.
- Authentication caching is disabled per command.
- The blanket `--trust-server-cert` option was removed.
- Audit messages and commands are redacted before they are written to disk.

### Tests

- Added real `svnadmin`/`svnserve` integration tests for checkout, commit, log,
  diff, conflicts, out-of-date commits and the needs-lock workflow.
- Added CI workflow with Subversion installed and Qt running offscreen.
- Added theme consistency checks and notification service/view tests.
- Full suite: 644 passing tests.

## [0.7.0] - 2026-06-25

- Domain-Driven Design and MVVM refactoring.
- Extracted application services and domain aggregates.
- Centralized VCS, vault, path and add-on rules.
- Stability fixes for project audit and repair workflows.

## [0.6.5] - 2026-05-30

- Watchtower production visualization integration.
- Sandboxed workspace and context injection foundations.
- SVN integration for production assets and tasks.
