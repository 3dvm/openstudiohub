# Automated QA & Auto-Fixing (Gatekeeper)

In a fast-paced production environment, sending a file back and forth between artists and supervisors due to technical errors—like an unapplied scale or a missing texture—is a massive waste of time and money. 

OpenStudioHub solves this natively through its **Gatekeeper** engine.

## What is the Gatekeeper?
The Gatekeeper is a strict, automated Quality Assurance (QA) protocol that runs silently in the background. Before an artist is allowed to push or publish their work to the server, the Gatekeeper audits the scene to ensure it complies with the studio's technical standards.

Instead of just warning the user, **it actively attempts to fix the issues for them.**

## Key Features

### 1. Out-of-Bounds Dependency Resolution
A classic mistake: an artist links a texture or an HDRI from their personal `Downloads` folder instead of the project's network drive (NAS).

* **Detection:** The Gatekeeper scans all external dependency paths in Blender.
* **Auto-Fix (The Concierge):** If a file resides outside the `OPENSTUDIO_PROJECT_ROOT`, it triggers an interactive pop-up. The artist classifies the file, and the Hub automatically copies the asset to the correct shared folder and makes the paths relative. No more "pink meshes".

### 2. Geometry Sanity & Scale Auto-Fix
Delivering an asset with unapplied rotations or incorrect scales will break rigs and downstream simulations.

* **Detection:** Scans all published objects for Scale anomalies (anything != 1.0, 1.0, 1.0) and unapplied rotations.
* **Auto-Fix:** Automatically applies transformations (`bpy.ops.object.transform_apply`) and enforces the studio's strict naming conventions (e.g., `{asset_name}-{suffix}`).

### 3. Silent Orphan Purging
To keep files lightweight and repository sizes small, the system runs a transparent purge of unused data blocks (orphan data) and explicitly excludes temporary collections (like `__TEMP__`) from the final publish.
