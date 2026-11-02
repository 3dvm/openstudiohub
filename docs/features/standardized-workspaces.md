# Standardized Workspaces & Sandboxing

*"It works on my machine"* is a phrase that should never be heard in a professional pipeline. Mismatched software versions, outdated add-ons, and customized user preferences cause catastrophic render failures and broken files.

OpenStudioHub enforces a strict **Golden Path** through zero-configuration Sandboxing.

## The Isolated Vault

### 1. Pristine Blender Deployment
The Hub acts as an autonomous package manager. It asynchronously scrapes and downloads the exact, studio-approved Blender executable directly from `download.blender.org`. The software is extracted into an isolated local vault (e.g., `local`), completely ignoring any pre-existing Blender installations on the artist's machine.

### 2. Environment Variable Injection
To guarantee that the entire team uses the exact same tools without conflicts, the Hub launches Blender using injected environment variables like `BLENDER_USER_RESOURCES`. This forces the software to read configurations and add-ons strictly from the controlled Hub ecosystem.

### 3. Dynamic Tooling & Add-on Sync
Before the software even launches, the Hub performs a silent sync. 

* It pulls the studio tools declared by the project from the central NAS.
* It forces physical studio preferences (like injecting the `OPENSTUDIO_PROJECT_ROOT` path into the add-on settings), instantly reverting any manual, unauthorized modifications made by the user.
* Features are context-aware: tools and actions can be hidden or enabled by task type and role. Current rendering is TD/Manager-triggered from the project card; Flamenco-based artist submission is on the roadmap.

### 4. Manifest-Driven Add-on Versions

The Vault manifest is the source of truth for add-on versions and Blender
compatibility:

* each Blender version has its own add-on list;
* the Hub only installs the version declared for the project's exact Blender
  version;
* the archive's `blender_manifest.toml` must match that version and declare a
  compatible `blender_version_min`;
* if the declared archive is missing or incompatible, the update fails with an
explicit message instead of silently installing another version.

Local installs are version-aware. Existing add-ons are replaced when the
manifest declares a newer compatible version, or when a repackaged archive with
the same version has different content. The installed copy records the source
archive hash so later integrity checks can detect drift.

When an add-on update is available, project integrity marks the workspace as
needing an update. Use **Update Workspace** on the project card to refresh the
add-ons together with the rest of the workspace.

To repackage the locally maintained OpenStudio Toolkit after changing its
source, open the software manifest editor, select the target Blender version
and click **Package OpenStudio Toolkit**. It reads the version from
`addons/openstudio_toolkit/blender_manifest.toml`, writes the matching zip to
the vault and updates that Blender version's manifest entry. Then run
**Update Workspace** on the affected projects.

## Per-project Blender preferences

Each project sandbox has its own `userpref.blend` under
`<vfs_local>/blender_data/config/`. The artist controls it locally; it is not a
TD/PM setting.

The Hub applies these project policies at every launch:

* **File Paths → Temporary Files** points to
  `<vfs_local>/blender-tmp/`;
* **Undo Steps** is set to `256`;
* **Save Versions** is set to `0` when the project has VCS enabled.

The OpenStudio Toolkit panel adds a separate **Project Preferences** section:

* **Save Preferences** applies the project policy, writes `userpref.blend` and
  records a signed-off snapshot of the values (Mouse Select, OptiX device,
  keyconfig, temp directory, undo steps and save versions);
* **Reload Preferences** reloads the project sandbox preferences into the
  current session;
* **Restore Saved Preferences** restores the last saved snapshot;
* **Import Preferences…** replaces the project preferences from an exported
  `userpref.blend` and then reapplies the project policy;
* **Export Preferences…** saves a copy of the project's current preferences.

After startup, if the loaded session differs from the saved snapshot, Blender
shows a dialog with the differing values and offers **OK to restore** or
**Cancel to keep the current session**. The Hub also keeps a
`blender_prefs/session_start.blend` snapshot before each launch.

Import/export and restore are artist actions. A project can start from a
studio-provided preference template selected in the project creation or
configuration dialog, but after that the local artist remains in control. The
template is only used when the sandbox does not have a `userpref.blend` yet.
