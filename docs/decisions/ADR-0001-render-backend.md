---
title: ADR-0001 Render backend
description: Direct Vast.ai burst first, Flamenco later.
---

# ADR-0001: Render backend for OpenStudioHub

- **Status:** Accepted
- **Date:** 2026-11-01
- **Supersedes:** the render-farm assumptions in
  `old_unorganized_docs_no_git_upload/PAYLOAD_Full_roadmap-*-FROZEN.md` (v0.7.5 /
  v0.8.6) and `PAYLOAD_SDD-v4.5-FROZEN.md` §1.14 and §2.14.
- **Related:** [Render capacity](../admin-guide/render-capacity.md),
  [Render on Vast.ai](../admin-guide/vast-rendering.md),
  [Render farm](../features/render-farm.md).

## Context

The Hub needs a way to render a project, or a single shot, inside a user-defined
wall-clock window (for example one or two hours). The first real case is
`p0005-indent-machine`.

The archived design assumed a persistent Flamenco Manager with cloud workers
(AWS/RunPod in the old documents, Vast.ai in the newer operational guide),
joined to the studio NAS through a Tailscale mesh and NFS mounts. That design is
still a good long-term target for a permanent farm, but it has a hard
constraint:

- Flamenco requires a **synchronous shared filesystem mounted at the same path**
  on the Manager and every Worker. It explicitly does not support Syncthing,
  Dropbox, Google Drive or other asynchronous sync services.
- Shaman only optimises **input** ingestion; it still needs the shared
  filesystem for the file store and the job checkouts.
- Vast.ai Docker instances document only environment variables, hostname and
  ports as Docker options. Tailscale with TUN, NFS or FUSE mounts are not a
  supported assumption there.
- Vast.ai **VMs** are full Linux machines with systemd, but they are scarcer,
  slower to boot and need a separate validation.

Vast.ai also offers **Cloud Copy**, but it is a copy operation, not a mount; it
does not satisfy Flamenco's shared-storage requirement.

At the same time, a direct headless Blender burst on Vast.ai is proven: the
archived `VAST_GPU_INSTANCE_GUIDE.md` documents the full lifecycle, and a real
benchmark of `sh010` on an RTX 3090 (1080p, 256 samples) measured
**38.9 s/frame** (median; 37–40 s across hosts). The whole shot rendered on two
on-demand instances in **41.5 minutes for $0.255**. The later two-frame path
 test measured 39.4 / 37.9 s on a second host.

## Decision

1. **Ship the direct Vast.ai burst first.** The Hub rents on-demand GPU
   instances, installs the project's Blender version, stages the production
   folder over SSH, renders contiguous frame chunks, syncs the frames to the
   Blender Studio Tools layout
   `03_render/shots/<sequence>/<shot>.render/`, and destroys every instance in
   a `finally` block.
2. **Make the capacity plan a first-class feature.** The Hub probes each shot,
   joins the result with measured profiles, and calculates the node count for a
   target duration. The plan includes GPU-hours, ETA, cost, confidence and
   warnings.
3. **Keep Flamenco for later.** Flamenco remains the target for a persistent
   local farm and for studios that already have shared storage. A future
   `FlamencoProvider` can reuse the same capacity plan and UI.
4. **Use Vast.ai VMs, not Docker instances, if Flamenco workers are provisioned
   on Vast.** This avoids the TUN/FUSE limitation and allows Tailscale + NFS.
5. **Use a dedicated render panel, not a dialog.** TD and PM profiles get a
   `Render` sidebar entry with a project selector, shot checkboxes, the render
   setup audit, preview, plan and live progress. A project card action opens
   the panel with that project selected. Artists get a read-only progress
   panel fed by the shared `03_render/.render_status.json`.
6. **Apply the final and preview configurations at render time.** The Hub does
   not rewrite the artist's `.blend`; the headless render applies the selected
   resolution, samples, engine and compositing in memory. The scene audit still
   warns about missing compositing or disconnected view layers.
7. **Preview the composite before the full render.** The panel renders one
   representative frame at a lower quality, locally by default or on Vast on
   demand. The preview is how missing view layers or a broken compositor are
   caught before spending on the full render.
8. **Keep the local backend.** The same selected shots can be rendered with the
   project's isolated Blender on the workstation when the project is simple or
   the deadline allows it. The plan uses an explicit local speed factor.
9. **Create the review video and publish it to Kitsu.** ffmpeg writes the
   Blender Studio review path
   `shared/editorial/footage/pro/<seq>/<shot>/<shot>-render/<shot>-render-v###.mp4`,
   plus a render-review copy next to the frames. The panel can upload it to the
   matching Kitsu task and set the status from the statuses linked to the
   project.
10. **Guard the marketplace.** The default cap is $0.13/h, with a soft Americas
    preference, a 100/50 Mbps floor and GPU profiles for the RTX 3070, 3080,
    4070, 3090, 4090 and A6000. If no offer fits, the panel reports the cheapest
    seen and does not rent silently.

## Alternatives considered

| Alternative | Why not now |
|---|---|
| Flamenco Manager + Vast Docker workers | Flamenco needs shared storage; Vast Docker does not safely expose TUN/FUSE. A custom job type with `rsync`/`rclone` pre/post steps is possible but complex and untested by Flamenco. |
| Flamenco Manager + Vast VM workers | Viable, but VMs are scarcer and slower to boot, and the studio must expose a NAS over the WAN. This is the recommended phase 2. |
| Flamenco all-in-one on one Vast instance | Adds a manager/worker lifecycle to a single ephemeral machine without providing a real farm. Useful only as a validation spike. |
| OpenCue / CGRU / Deadline | OpenCue is heavy, Deadline is proprietary, and none integrates with the Blender/Flamenco stack the Hub already documents. |
| Vast Cloud Copy as shared storage | It is a copy operation, not a synchronous mount; Flamenco would break. |

## Consequences

- **Positive:** the user gets a working "render this project in 1–2 hours"
  flow now, with explicit cost and ETA; no VPN, NFS or Manager to operate.
- **Positive:** the preview and setup audit catch missing compositing/view
  layers before the full render.
- **Positive:** the local backend covers simple projects and avoids cloud cost.
- **Positive:** the review video and Kitsu upload close the loop for review.
- **Positive:** artists can follow progress without renting nodes or opening
  Blender.
- **Positive:** the capacity model is provider-agnostic; Flamenco can reuse it.
- **Negative:** there is no persistent queue or automatic retry across shots.
  Each burst is a new plan; a missing frame must be re-rendered.
- **Negative:** every new heavy shot needs a benchmark. Geometry-node shots
  (seeds in the drum) are marked as "benchmark required" because a default
  estimate may be far too low.
- **Negative:** the project's production folder is staged per node. Large
  projects will need a smarter dependency set or object-storage staging.
- **Operational:** Vast API keys stay in the CLI configuration; the SSH key must
  be unencrypted and registered with Vast; the Hub never writes either secret.
- **Operational:** the output lives in `03_render/shots/...`, outside SVN, as
  decided in the archived VFS plan; the review video lives in the Kitsu footage
  folder.
- **Operational:** the default marketplace cap is $0.13/h; the panel shows the
  cheapest offer when the cap is too low. An Americas location is preferred but
  is not a guarantee of faster transfer; the offer bandwidth is displayed.

## References

- Vast.ai instances: <https://docs.vast.ai/guides/instances/overview.md>
- Vast.ai Docker environment and limitations:
  <https://docs.vast.ai/guides/instances/docker-environment.md>
- Vast.ai VMs: <https://docs.vast.ai/guides/instances/virtual-machines.md>
- Vast.ai Cloud Copy: <https://docs.vast.ai/guides/instances/storage/cloud-sync.md>
- Flamenco shared storage:
  <https://flamenco.blender.org/usage/shared-storage/>
- Flamenco Shaman: <https://flamenco.blender.org/usage/shared-storage/shaman/>
