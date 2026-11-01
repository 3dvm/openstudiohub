# Automated QA & Auto-Fixing (Gatekeeper)

In a fast-paced production environment, sending a file back and forth between artists and supervisors due to technical errors—like an unapplied scale or a missing texture—is a massive waste of time and money. 

OpenStudioHub solves this natively through its **Gatekeeper** engine.

## What is the Gatekeeper?
The Gatekeeper is a strict, automated Quality Assurance (QA) protocol that runs
inside Blender. Its actions are intentionally separate:

* **Audit Scene** — scans dependencies, transforms and naming, then opens the
  repair dialog when it finds issues.
* **Fix Out-of-Bounds Textures** — copies external textures into the project
  and makes the paths relative.
* **Purge Orphans** — removes unused data blocks and excludes `__TEMP__`.
* **Save & Commit** — saves the file and commits it only when the project uses
  version control.

Auditing never saves, commits or purges on its own. Playblast publishing is
left to Blender Kitsu.

For prop asset tasks, the Hub sets the scene frame range to `1–2` so a
playblast does not render hundreds of identical frames. Shots and other
entities keep their original range.

## Key Features

### 1. Out-of-Bounds Dependency Resolution
A classic mistake: an artist links a texture or an HDRI from their personal `Downloads` folder instead of the project's network drive (NAS).

* **Detection:** The Gatekeeper scans all external dependency paths in Blender.
* **Auto-Fix (The Concierge):** If a file resides outside the `OPENSTUDIO_PROJECT_ROOT`, it triggers an interactive pop-up. The artist classifies the file, and the Hub automatically copies the asset to the correct shared folder and makes the paths relative. No more "pink meshes".

### 2. Geometry Sanity & Scale Auto-Fix
Delivering an asset with unapplied rotations or incorrect scales will break rigs and downstream simulations.

* **Detection:** Scans all published objects for Scale anomalies (anything != 1.0, 1.0, 1.0) and unapplied rotations.
* **Auto-Fix:** Automatically applies transformations (`bpy.ops.object.transform_apply`) and enforces the studio's strict naming conventions (e.g., `{asset_name}-{suffix}`).

### 3. Orphan Purging
To keep files lightweight and repository sizes small, **Purge Orphans** removes
unused data blocks and excludes temporary collections such as `__TEMP__`. It is
a separate action and can be run before auditing or saving.
