---
title: Render panel and cloud burst
description: Select shots, preview the composite, render locally or on Vast.ai, and publish the review video.
---

# Render panel and cloud burst

The render workflow lives in a dedicated **Render** panel, not in a modal
dialog. TD and PM profiles open it from the sidebar or from the project card
(**🎬 Render…**). Artists get a read-only **Render** panel with the current
progress, preview and review video.

## The panel

The project selector at the top chooses the production. The left side lists
every shot with a checkbox; the right side shows the selected shot.

- **Shot selection:** only ready shots can be checked. Empty template scenes are
  listed as not ready and are never rented for.
- **Render setup audit:** compositing on/off, view layers and whether each one
  is connected to the compositor output, output format/color, camera, fps and
  the output path.
- **Preview:** one frame of the composite is rendered at 50% / 32 samples by
  default. Preview can run locally (default) or on a Vast node. The preview is
  the quickest way to catch a missing view layer or a broken compositor before
  the full render.
- **Plan:** selected frames, GPU-hours, nodes, ETA, cost, confidence and
  warnings. The plan is recalculated from the shared settings.
- **Final render:** Vast.ai on-demand or local headless, one project at a time. GPU profiles: RTX 3070, 3080, 4070, 3090, 4090 and A6000.
- **Final sequence player:** the panel replays the rendered PNG sequence with
  play/pause, scrubbing and frame stepping. The current frame can be moved to
  `.frame_trash/` (render error) or approved; approved frames are protected from
  deletion and from future renders.
- **Preview video:** a fast, half-resolution MP4 for quick review. It is
  created separately from the per-shot review videos.
- **Review video:** ffmpeg creates the Kitsu review MP4 and the
  Blender-Studio-style render-review copy.
- **Kitsu:** the panel can upload the review video and set the task status. The
  status list is fetched from the Kitsu server.

Settings are stored in the project's pipeline folder:

```text
<project>/05_config_estudio/render_settings.json
```

That file is shared by every workstation. It keeps the final quality, preview
quality, selected shots, target duration, GPU profile, price/network limits,
backend, preview backend and video options.

## Render setup audit

The Hub never writes render settings back to the `.blend`. The audit reads the
scene and the final/preview quality is applied to the headless render in memory.

The panel reports:

- `Compositing: on/off` and the compositor name.
- `View layers: 2/2 connected (BG, dev)`; a disconnected layer is a warning.
- `Output: PNG RGB 8-bit · Standard`.
- `Camera`, `fps` and frame range.
- `Files: composite only` or the File Output nodes.

The current `sh010` layout has two view layers (`BG`, `dev`) connected through
Alpha Over/Glare to the Group Output. The panel shows that both are connected
and that only the composite is written. If a scene has no compositor, the panel
warns before rendering; the preview shows what the render would actually look
like.

## Blender Studio Tools paths

Frames are written in the same layout that Blender Studio Tools expects:

```text
<project>/
└── 03_render/
    └── shots/
        └── <sequence>/
            └── <shot>.render/
                ├── frame_0101.png
                ├── frame_0102.png
                └── ...
```

The render-review video is also written next to the frames as
`<shot>-<first>-<last>.mp4`, so Blender Kitsu's render review can find it.
The quick preview video lives under `.previews/` and is generated on demand,
independently from the review videos.

Approved frames are recorded in `.frame_state.json` next to the frames. The
player can move a bad frame to `.frame_trash/`; a new render fills only the
missing frames.

The review copy goes to the Kitsu footage folder:

```text
<project>/
└── 04_datos_compartidos/editorial/footage/pro/<sequence>/<shot>/<shot>-render/
    ├── <shot>-render-v001.mp4
    └── metadata.json
```

The version auto-increments. The task type defaults to `render` and can be
changed in the panel.

## Rendering

- **Vast.ai:** the Hub rents the on-demand instances, installs the project's
  exact Blender, stages the production folder, renders contiguous frame chunks
  and syncs the frames back. Every instance is destroyed in a `finally` block.
  Each node is audited independently, so a failure on one node never hides the
  state of another.
- When a run is partial, **Retry missing frames** renders only the frames that
  are absent. Approved frames are skipped.
- Each run writes a local audit trail:
  `~/.openstudio/state/render_runs.jsonl` plus per-node logs under
  `~/.openstudio/state/render_runs/<run_id>/`:
  `node-<n>.log` (Hub timeline), `node-<n>.json` (result) and
  `node-<n>-blender-<shot>.log` (raw Blender output). Local runs write the same
  files with the `local-<shot>` node id. The panel has **Open run logs**.
- **Local:** the project's isolated Blender runs headlessly on the workstation
  and writes the same path. This is useful for simple shots or when there is
  enough time. The plan shows an estimated local slowdown factor
  (`local_speed_factor`, default 8× the RTX 3090 reference).

The default price cap is **$0.13/h**, with a preference for Americas offers
(US/Canada/Mexico/Brazil) and a minimum bandwidth (100 Mbps down / 50 Mbps up by
default). The panel shows the offer's location and bandwidth. If no offer fits,
it reports the cheapest seen so the TD can raise the cap explicitly. Budget
profiles (3070/3080/4070) use a benchmark scaled from the 3090 reference until
they are benchmarked directly.

## Scene requirements

The Hub audits view layers, compositing and output, but it does not audit
particle caches. Two Blender-side conditions still need to be true:

- **Instancer collections must be in the scene.** A particle system whose
  `render_type` is `Collection` can show particles in the viewport while the
  Cycles render drops them if the instancer collection (for example `shell` or
  `grains_good`) is only linked from an external asset and is not linked into
  the scene collection. Link the collection into the scene; the particles then
  render in both preview and final.
- **The point cache must resolve for the renderer.** When the particle cache
  is library-linked, the point cache stores an absolute library path. For a
  local or headless render, disable **Use Library Path** on the particle cache
  and bake it against the `.blend`, otherwise the renderer cannot find the
  cache even though the bake is present.

A preview that shows the machine but no particles, while the 3D viewport shows
them, is the usual signature of the first condition. The same scene can render
correctly in the open Blender session and fail in the Hub's headless process if
its cache depends on the library path.

## Review video and Kitsu

`ffmpeg` is required. The default review encode is H.264, CRF 18, `yuv420p`,
`+faststart`.

After the render, the panel can:

1. Upload the review video to the matching Kitsu task (entity name + task type
   `render`).
2. Set the task status from the statuses linked to the project.
3. Add a comment (for example, “Render review: sh010”).
4. Use the video as the task thumbnail.

The review folder receives a `metadata.json` entry so Blender Kitsu's render
review recognizes the video.

## Artist progress

Artists see a read-only **Render** panel. It polls the shared status file:

```text
<project>/03_render/.render_status.json
```

and shows the status, frames done/expected, active nodes, cost, latest preview
and review video. No node is rented and no Blender process starts from the
artist session.

## Flamenco later

Flamenco remains the target for a persistent local farm and for studios with
shared storage. The capacity calculator and the panel are provider-agnostic; a
future Flamenco provider can reuse them. On Vast.ai, Flamenco workers require
VMs with Tailscale + NFS, not Docker instances. See
[ADR-0001](../decisions/ADR-0001-render-backend.md).

## Related

- [Render capacity](../admin-guide/render-capacity.md)
- [Render on Vast.ai](../admin-guide/vast-rendering.md)
- [ADR-0001: Render backend](../decisions/ADR-0001-render-backend.md)
