---
title: Render capacity
description: Calculate the GPU nodes needed to finish a render by a deadline.
---

# Render capacity

The capacity calculator turns the selected shots and a target wall-clock
duration into a node count, an ETA and a cost.

## The model

For every ready shot:

```text
T_shot = frames × seconds_per_frame
T_render = Σ T_shot
```

The node count accounts for the full life of an instance, not just the render:

```text
available_per_node = target_seconds - setup_seconds
N = ceil(T_render / (available_per_node × utilization))
wall = setup_seconds + T_render / (N × utilization)
cost = N × wall / 3600 × price_per_hour
```

Defaults:

| Input | Value | Why |
|---|---:|---|
| `setup_seconds` | 600 s (10 min) | Instance boot, Blender install, SSH, staging and result sync. A measured two-frame node life was 686 s. |
| `utilization` | 0.85 | Scheduling gaps, uneven chunks and the last frame of each node. |
| `local_speed_factor` | 8.0 | Local rendering uses one workstation; the plan multiplies the RTX 3090 reference by this factor. |
| `max_price_per_hour` | $0.13 | Default marketplace cap. The panel reports the cheapest offer when nothing fits. |
| `preferred_region` | Americas | Soft preference for US/Canada/Mexico/Brazil; bandwidth is displayed. |

## Measured reference

The reference benchmark used an **RTX 3090 24 GB** in Vast.ai, the project's
Blender 5.2.3 and the `sh010` layout:

| Target | Seconds/frame |
|---|---:|
| 1920×1080, Cycles, 256 samples, OIDN | **38.9 s** (benchmark median; 37–40 s on the render runs) |
| 1920×1080, Cycles, 128 samples, OIDN | **29.5 s** |
| 960×540, Cycles, 128 samples | 27–30 s on the burst hosts |

GPU profiles and their relative speed against the RTX 3090 reference:

| Profile | VRAM | Relative speed |
|---|---:|---:|
| RTX 4090 | 24 GB | 1.55× |
| RTX 3090 | 24 GB | 1.00× |
| RTX A6000 | 48 GB | 1.00× |
| RTX 4070 | 12 GB | 0.80× |
| RTX 3080 | 10 GB | 0.80× |
| RTX 3070 | 8 GB | 0.65× |

The relative speeds are estimates used to scale a 3090 benchmark until the GPU is benchmarked directly. The panel marks those values with `~` and confidence **estimated**.

The 256-sample benchmark was **38.9 / 37.4 / 38.9 s** for frames 101, 148 and
196. The final two-frame test measured **39.4 / 37.9 s** on a second host.

The values live in `<vfs_pipeline>/render_profiles.json` (for `p0005`:
`05_config_estudio/render_profiles.json`). A profile is keyed by blend hash, GPU
profile and quality. If the `.blend` changes, the old value is marked **stale**
and shown as a previous benchmark; the panel's per-shot **Benchmark** button
re-measures three representative frames of the shot's scene range, and
**Benchmark all selected** does the same for every selected shot on a single
node. The dialog lists the exact `.blend`, the frames, the node and the upload
size before renting.

The shot list only contains `.blend` files with a Kitsu shot task, and the scan
result is cached in the project's `vfs_local` folder so the panel opens without
waiting for Blender. Use **Re-scan** when files or task assignments changed.

Geometry-node bakes can be generated on the render nodes instead of uploading
them. The **Bake geometry nodes on the node** checkbox defaults to on when a
selected cache is missing or older than its `.blend`. The plan warns about
missing particle caches; particle systems are not baked remotely. Vast.ai
offers must have at least **60 GB of system RAM** by default when node-side
bakes are enabled; **Min RAM** in the Vast.ai plan overrides it (0 = automatic).
A failed node card offers **Relaunch node**, which finds a new offer with the
same planned configuration and retries its frames.

## Worked example: p0005

The project currently has seven shot files:

- `sh010`: ready, 96 frames, 289k polygons, 11 geometry-node modifiers.
- `sh020`, `sh030`, `sh040`, `sh050`, `sh060`, `070`: empty template scenes
  (4 objects, one 6-polygon mesh). They are skipped.

With the measured 38.9 s/frame on an RTX 3090:

| Frames | Quality | GPU-hours | Nodes for 1 h | Nodes for 2 h | Cost at $0.16/h |
|---:|---|---:|---:|---:|---:|
| 96 (`sh010`) | 1080p / 256 | 1.04 | **2** | **1** | $0.23–0.25 |
| 96 (`sh010`) | 1080p / 256, RTX 4070 (scaled) | 1.30 | **2** | **1** | $0.17–0.20 |
| 96 (`sh010`) | 1080p / 128 | 0.79 | **2** | **1** | $0.17–0.20 |
| 792 (all shots similar) | 1080p / 256 | 8.56 | **13** | **6** | $1.75–2.00 |
| 792 (all shots similar) | 1080p / 128 | 6.49 | **10** | **5** | $1.35–1.49 |

The real `sh010` run used **2 nodes**, finished in **41.5 minutes**, produced
**96 PNG frames (163 MB)** and cost **$0.255**. The two-frame test after the
path change validated `03_render/shots/sq010/sh010.render/` and the composite.

The 792-frame rows are hypothetical until the other shots have content and a
benchmark. Geometry-node shots can be much heavier than the layout reference;
the plan marks them and the confidence drops to **estimated**.

## Output layout

The panel writes the Blender Studio Tools layout:

```text
03_render/shots/<sequence>/<shot>.render/frame_####.png
```

The review video is created in:

```text
04_datos_compartidos/editorial/footage/pro/<sequence>/<shot>/<shot>-render/<shot>-render-v###.mp4
```

and a render-review copy is placed next to the frames.

## Price and network limits

The shared settings default to:

- **maximum price:** $0.13/h;
- **region:** prefer Americas (US/Canada/Mexico/Brazil);
- **minimum bandwidth:** 100 Mbps down / 50 Mbps up.

The panel shows the chosen offer's location and bandwidth. If no offer fits, it
reports the cheapest one seen so the TD can raise the cap explicitly. An
Americas location is not automatically faster: the offer's `inet_down`/`inet_up`
and the route to the studio matter. Recent examples: RTX 3070 from $0.075–0.082/h,
RTX 3080 from $0.108–0.109/h, RTX 4070 from $0.126/h (Canada) or $0.148/h (US).

## Reading the plan

- **measured** — every ready shot has a profile for the chosen quality and GPU.
- **stale** — the profile came from a previous `.blend`; re-benchmark if the
  scene changed.
- **estimated** — at least one ready shot uses the conservative fallback.
- **skipped** — empty or camera-less scenes; they are not rented for.
- **warnings** — not-ready shots, unmeasured shots, geometry nodes, capped
  nodes, cost over budget, an ETA over the deadline, or no offer within the
  price/network limits.

## Benchmarking a shot

1. Select the shot in the panel.
2. Click **Benchmark selected**; it rents one Vast node and renders frames
   `first`, `middle` and `last` at the final quality.
3. The median seconds/frame updates the shared profile for the current blend
   hash.
4. The panel rescans and recalculates the plan.

The benchmark uses the same compositor as the final render, so a broken
compositing setup is visible in the measured frames.

## Related

- [Render panel and cloud burst](../features/render-farm.md)
- [Render on Vast.ai](vast-rendering.md)
- [ADR-0001: Render backend](../decisions/ADR-0001-render-backend.md)
