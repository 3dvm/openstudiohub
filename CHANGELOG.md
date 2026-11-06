# Changelog

All notable changes to OpenStudioHub are documented here.

The project follows Semantic Versioning. Before `1.0.0`, minor and patch
releases may include larger UI or workflow changes.

## [Unreleased]

### Added

- Publish window handles files deleted from disk:
  - missing files are listed separately and are not selected by default;
  - **Restore selected** brings them back with `svn revert`;
  - **Delete from repository** schedules `svn delete --force`, and the deletion
    is committed with the next publish;
  - **Select all missing** marks every reported path at once.
- The publish window shows the task checklist as interactive checkboxes. Each
  tick is saved to the matching Kitsu comment, and only the items checked at
  publish time are added to the commit message.
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
- `openstudio_toolkit` 0.6.2, with self-contained QA rules so it loads from the
  Blender extension sandbox.
- Dedicated render panel and capacity planner:
  - `Render` sidebar entry for TD/PM, with a project selector, shot checkboxes,
    shared per-project settings and a live node log; artists get a read-only
    progress panel;
  - the Hub probes each shot, audits compositing/view layers/output/color,
    joins measured `render_profiles.json` values and calculates GPU-hours,
    nodes, ETA and cost for a target wall time;
  - **Preview selected/all** renders one composite frame at a lower quality,
    locally by default or on a Vast node;
  - final renders can run on Vast.ai on-demand instances or locally with the
    project's isolated Blender; frames use the Blender Studio Tools layout
    `03_render/shots/<sequence>/<shot>.render/`;
  - every Vast instance is destroyed on completion/error/cancel; empty shots
    are skipped, geometry-node shots are flagged and price/node/budget caps are
    enforced ($0.13/h default, Americas preference and bandwidth floor);
  - GPU profiles for RTX 3070 (8 GB), 3080 (10 GB), 4070 (12 GB), 3090/4090
    (24 GB) and A6000 (48 GB); times for a budget profile are scaled from the
    3090 benchmark (marked `~`/estimated) until the GPU is benchmarked directly;
  - **Benchmark selected** measures three frames on one node and updates the
    shared profile;
  - ffmpeg creates the Kitsu review video
    `shared/editorial/footage/pro/<seq>/<shot>/<shot>-render/<shot>-render-v###.mp4`
    and the render-review copy; the panel can upload the video to the matching
    Kitsu `render` task and set a status fetched from the server;
  - new docs: the render backend ADR, the render-farm feature page, the
    capacity guide and the Vast.ai runbook.
- Kitsu-backed shell identity:
  - the top bar shows the active profile name (TD, PM, Editor or Artist)
    instead of a second dropdown arrow;
  - the user avatar is downloaded from Kitsu and falls back to the local user
    icon;
  - the sidebar branding downloads the studio logo from Kitsu and falls back to
    the bundled logo.
- Per-project Blender preferences:
  - Temporary Files points to `<vfs_local>/blender-tmp/`;
  - Undo Steps is set to 256;
  - Save Versions is set to 0 when the project uses VCS;
  - artists can save, reload, restore, import and export `userpref.blend` from
    the Toolkit panel;
  - saved preferences are snapshotted per project and compared on launch;
  - when the loaded session differs (for example Mouse Select or OptiX device),
    Blender warns and offers to restore the saved preferences;
  - the Hub keeps a `session_start.blend` snapshot before each launch;
  - new projects can seed their sandbox from an optional preferences template
    selected in the project creation or configuration dialog.

### Changed

- OpenStudio Toolkit actions are now separate operations: `Audit Scene`,
  `Fix Out-of-Bounds Textures`, `Purge Orphans`, `Lock File` and `Save &
  Commit`. `Lock File` lets an artist acquire the VCS write lock for a
  `.blend` opened outside the Hub.
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

- `Save & Commit` now acquires the SVN lock before saving, so a `needs-lock`
  `.blend` opened without the Hub can be saved instead of failing with
  `Cannot save blend file, path is not writable`. A lock held by another user
  aborts with a clear message, and a failed save reports an actionable error.
- SVN unlock is idempotent. Files already unlocked by another client no longer
  produce `E195013` notifications.
- Lock probes for unversioned or missing paths no longer emit `W155010` audit
  failures or `Info failed` notifications.
- `openstudio_toolkit` activates correctly inside the Blender sandbox.
- Importing, reloading or restoring project preferences no longer crashes
  Blender. The preferences reload now runs from a deferred timer instead of
  inside the operator, because `wm.read_userpref` re-registers add-ons and
  invalidates the running operator.
- The Toolkit panel sections (file status, production context, scene actions
  and project preferences) are collapsible.
- The render scan no longer fails with `name 'bake_particles' is not defined`;
  `RenderService.cheapest_offer()` had a stray `bake_particles` argument.

### Tests

- Full suite: 751 passing tests.

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
