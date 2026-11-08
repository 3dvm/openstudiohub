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
every shot as a collapsible card; the right side shows the selected shot.

- **Shot cards:** each card shows the rendered and approved frame counts
  (`R 120/140 · A 80/140`), frame range, quality, measured time and warning
  summary. The header status is one of:
  `Not ready`, `Check setup`, `Rendering`, `Failed`, `Finished`
  (all frames approved), `In review` (all rendered, not all approved),
  `With renders` (partially rendered) or `Ready`. Hovering the status shows a
  detailed tooltip.
- **Per-shot actions:** **View** toggles play/stop for the shot sequence and the
  active shot keeps an orange outline. **Preview**, **Benchmark**, **Render**,
  **Retry**, **Approve**, **Delete** and a **More** menu with unapprove, video
  creation and folder/.blend actions. **Open .blend** uses the same task
  sandbox as the task cards: it acquires the SVN lock, launches the isolated
  Blender with the Kitsu task environment, and releases the lock when the
  session closes.
- **Selection:** only ready shots can be checked. Shots that are part of the
  active run are locked: their checkbox and render actions are disabled until
  the run finishes.
- **Run controls:** Start, Cancel, **Stop all processes**, preview/review video
  actions and log access sit at the top of the panel, above the preview. Every
  render-starting action asks for confirmation. While a process is active a
  banner is shown and the sensitive controls and shot actions are locked.
- **Render setup audit:** compositing on/off, view layers and whether each one
  is connected to the compositor output, output format/color, camera, fps and
  the output path.
- **Preview lookup:** preview images are remembered per shot in
  `.render_status.json` and `03_render/.previews/index.json`. When a run is
  reopened, the panel also searches the timestamped Vast preview folders, so a
  finished preview stays attached to its shot after a reload.
- **Preview:** one frame of the composite is rendered at 50% / 32 samples in
  PNG by
  default. Preview can run locally (default) or on a Vast node. The preview is
  the quickest way to catch a missing view layer or a broken compositor before
  the full render.
- **Plan and node cards:** approved frames are excluded from the plan; frames
  that are not approved yet count as pending work. The panel shows pending
  frames, GPU-hours, nodes, ETA, cost, confidence and warnings. Before any
  instance is rented, the panel lists the
  candidate offers for the required nodes in a four-column card grid
  (**Refresh candidates** re-queries Vast.ai). Each card then follows its own
  lifecycle: candidate, creating, booting, SSH, installing, staging, rendering,
  syncing, completed, failed or destroyed. Each active card shows its current
  shot, a progress bar, rendered/expected frames, measured seconds per frame and
  an ETA calculated from the real frame times. At the end, the card exposes
  buttons that open its Hub log, summary and raw Blender log directly.
- **Frame ranges:** the sequence player has **In point** / **Out point** and
  **Clear range** controls. **Approve selection** and **Delete selection** act
  on the selected frame range, or on the current frame when no range is set.
- **Final render:** Vast.ai on-demand or local headless, one project at a time.
  The final image format follows Blender's still-image formats (PNG by default,
  plus JPEG, TIFF, OpenEXR and the other Blender image formats) with configurable
  color mode and color depth. Previews are always PNG. GPU profiles: RTX 3070,
  3080, 4070, 3090, 4090 and A6000.
- **Format proxies:** non-PNG final frames also write a PNG proxy in
  `.proxies/`. The in-app sequence player, frame review and preview/review
  videos use those proxies, while delivery frames keep the selected format.
- **Final sequence player:** the panel replays the rendered sequence with a
  timeline that marks approved frames (green), rendered frames awaiting review
  (blue), missing frames (red) and the In/Out selection (orange). Controls below
  the timeline provide play/pause, previous/next frame, loop on/off, In/Out,
  clear range, approve and delete. Missing frames show the Lucide `image-off`
  icon. The current frame can be moved to `.frame_trash/` (render error) or
  approved; approved frames are protected from deletion and future renders.
- **Shot and frame comments:** the player has a local comments panel. Shot
  comments apply to the whole shot; frame comments are attached to the current
  frame and appear as markers on the timeline. They are stored in
  `.render_comments.json` next to the rendered frames.
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
  state of another. The node cards update live from the burst progress events.
- When a run is partial, **Retry missing frames** renders only the frames that
  are absent. Approved frames are skipped.
- Before destroying a node, the Hub copies the remote Blender log and captures
  `nvidia-smi`, memory, disk and `dmesg` diagnostics. This happens on success,
  failure and cancellation, so the cause of a lost node is preserved.
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
