---
title: Render on Vast.ai
description: Operate the direct Vast.ai render burst from the render panel.
---

# Render on Vast.ai

The render panel rents short-lived Vast.ai instances for the selected shots.
The archived Spanish `VAST_GPU_INSTANCE_GUIDE.md` remains useful as a record of
the original manual session; this page is the operational reference for the
panel.

## Prerequisites

- A Vast.ai account with credit.
- The `vastai` CLI installed and authenticated:

  ```bash
  curl -fsSL https://vast.ai/install.sh | bash
  export PATH="$HOME/.local/bin:$PATH"
  vastai set api-key <API_KEY>
  vastai show user
  ```

  The key is stored in `~/.config/vastai/vast_api_key`. Never put it in the
  repository or in a shared command line.

- An **unencrypted** SSH key registered with Vast. The Hub defaults to
  `~/.ssh/id_ed25519_ppf`; change `ssh_key_path` in `RenderService` if the
  studio uses another key. The private key stays on the workstation.

- `rsync`, `ssh`, and outbound HTTPS/SSH.
- `ffmpeg` on the workstation for review videos.

## Panel workflow

1. Open **Render** in the TD or PM sidebar, or click **🎬 Render…** on a
   project card.
2. Select the shots with checkboxes.
3. Choose the final quality, target duration, GPU, price cap, node cap, budget,
   backend (Vast or local) and preview backend.
4. Click **Recalculate plan**.
5. Optionally click **Preview all selected** (or the per-shot **Preview** action)
   to render one composite frame at the chosen preview quality (local by
   default; Vast is available). Enable **Bake geometry nodes on the node** to
   generate GN caches on the node instead of uploading them.
6. Click **Start render**. The panel asks for confirmation and shows the plan.
7. When frames exist, open **Publish Shot** in the Shot Inspector. Choose the
   Kitsu task, status, editable version, comment and optional thumbnail. Publish
   creates the low-quality review MP4 and uploads it to Kitsu. High-quality
   video is not generated or uploaded.

## What the burst does

For each node:

1. Search on-demand offers for the chosen GPU profile (default: RTX 3090,
   ≥ 24 GB VRAM, ≥ 40 GB disk, CUDA ≥ 12.8, reliability ≥ 0.95), sorted by
   price with US offers preferred.
2. Create a Docker instance with `--ssh --direct` and a label such as
   `osh-render-p0005-<run>-<node>`.
3. Wait until the instance is `running`, then wait for SSH.
4. Install the project's exact Blender version and its runtime libraries
   (about two to four minutes).
5. Report how many files and bytes will be uploaded, then stage only the
   selected shot folders and their linked assets over `rsync`, showing live
   upload progress on the node card. Other shots, storyboards, edit files, the
   shared folder and briefs are not uploaded. A
   **Benchmark all selected** run reuses one node and one upload for every
   selected shot.
   With **Bake geometry nodes on the node** enabled, the geometry-node bake
   caches of the planned shots are excluded and the node bakes them before the
   first frame. The upload drops from the cache size to the production assets.
   The offer search then requires at least 60 GB of host RAM by default (the
   **Min RAM** field can override it), because 16/31 GB hosts are killed while
   rendering heavy baked scenes. The transfer uses `--partial`, retries once
   and scales its timeout with the upload size.
6. Render a contiguous frame chunk with Cycles on GPU (CUDA; OptiX is also
   available). EEVEE is wrapped in `xvfb-run`.
7. Sync the frames to
   `03_render/shots/<sequence>/<shot>.render/`.
8. Destroy the instance, whether the job succeeded, failed or was cancelled.
9. If a node fails, **Relaunch node** on its card searches a fresh offer, keeps
   the planned GPU profile, limits and frame assignment, and renders the frames
   that are still missing.

The measured two-frame node life was 686 s: the setup dominates a small test.
Budget for about ten minutes of node life before the first frame.

## Price, region and bandwidth

The shared settings default to:

| Limit | Default |
|---|---:|
| Maximum price | **$0.13/h** |
| Region | Prefer Americas (US/Canada/Mexico/Brazil) |
| Minimum download | 100 Mbps |
| Minimum upload | 50 Mbps |

The panel shows the offer's location and `inet_down`/`inet_up`. An Americas host
is not automatically faster than a host elsewhere; the offer's bandwidth and the
route to the studio matter. Recent examples: a 4070 in Quebec at $0.126/h with
914/903 Mbps, a 3080 in Washington at $0.109/h with 821/885 Mbps, and a 3070 in
Nevada at $0.082/h with 381/245 Mbps. For a studio in South America, US
East/Miami is often a good default, but a fast host elsewhere can beat a slow US
host.

If no offer fits, the panel reports the exact failed limits, the nearest offers
and the smallest limit change that would match (for example **Lower Min RAM to
31 GB** or **Raise max price to $0.34/h**). It can also search the other GPU
profiles. Every fix is explicit: the Hub does not silently relax a limit or rent
a more expensive node.

When the selected profile has fewer offers than the plan needs, **Fill with
similar GPUs** is available as an opt-in. **Speed priority** accepts the
selected GPU or faster and keeps the ETA conservative. **Budget priority**
accepts the selected GPU or slower; the plan is recalculated with the slowest
selected GPU so the deadline estimate stays honest. Budget mode may use GPUs
with less VRAM only after an extra confirmation, and the plan warns about
out-of-memory risk. If the plan still cannot be filled, the panel offers **Use N
nodes instead** rather than launching fewer nodes silently.

The GPU selector offers RTX 3070, 3080, 4070, 3090, 4090 and A6000.

The instance that was used for the post-reboot test was an RTX 3090 at
$0.208/h in China (468/243 Mbps). It was used only to finish the benchmark and
the two-frame path test, then destroyed.

## Cost reference

Marketplace prices move; these are the reference values from the archived guide
and the recent runs:

| GPU | VRAM | Typical price |
|---|---:|---:|
| RTX 3070 | 8 GB | $0.07–0.09/h |
| RTX 3080 | 10 GB | $0.10–0.12/h |
| RTX 4070 | 12 GB | $0.12–0.15/h |
| RTX 3090 | 24 GB | $0.15–0.25/h |
| RTX 4090 | 24 GB | $0.30–0.60/h |
| RTX A6000 | 48 GB | $0.35–0.55/h |
| H100 | 80 GB | $1.50–3.00/h |

The panel includes the whole node life (boot, install, staging, render, sync)
in the estimate.

## Manual inspection

Read-only commands:

```bash
vastai show user --raw
vastai show instances --raw
vastai search offers \
  'num_gpus=1 rentable=true gpu_name in [RTX_3090] disk_space>=40 cuda_vers>=12.8' \
  -o dph --raw
```

Destroy a leftover burst instance by label prefix:

```bash
vastai show instances --raw
vastai destroy instance <ID> -y
```

The Hub's `VastProvider.destroy_by_label_prefix("osh-render-")` does the same
from the application layer.

## Troubleshooting

| Symptom | Cause | Action |
|---|---|---|
| `The vastai CLI is not installed` | CLI missing from `PATH` | Install it and authenticate. |
| `No ... offer meets all the current limits` | Filters too strict | The panel lists the exact failing limits, the nearest offers and one-click fixes; raise the cap, lower the RAM/network floor, search other GPU profiles or use local. |
| `Balance ... below the estimated cost` | Not enough credit for the plan | Top up or lower the node count/budget. |
| SSH never becomes ready | Key not registered, encrypted, or sshd still starting | Register the `.pub`, use an unencrypted key, wait 15–30 s and retry. |
| Blender exits immediately | Missing runtime library or wrong disk size | Check the node log; the burst installs the standard library set and uses 40 GB. |
| EEVEE fails headless | No display | The burst installs `xvfb` and wraps EEVEE; verify the log. |
| Out of VRAM | Scene heavier than the reference | Use a 48 GB GPU or reduce resolution/samples. |
| A render is slow | Geometry nodes/instancing | Benchmark the shot; the default estimate is deliberately conservative. |
| Particles missing from the frames | Instancer collection not linked into the scene, or the point cache uses a library path | Link the instancer collection into the scene and disable **Use Library Path** before baking the cache or starting the burst. |

## Security

- The Vast API key stays in the CLI configuration; the Hub never receives it.
- The SSH private key stays on the workstation; only the public key is
  registered with Vast.
- The instances are on-demand and labelled; destroy them when a burst is
  cancelled, and verify `vastai show instances --raw` is empty after a failed
  run.
- Do not stage secrets (`.env`, cloud keys) with the production folder.
- Uploads are selective: only the selected shots and their resolved linked
  assets are staged. Files outside the project are reported as external
  dependencies instead of being uploaded silently.

## Related

- [Render capacity](render-capacity.md)
- [Render panel and cloud burst](../features/render-farm.md)
- [ADR-0001: Render backend](../decisions/ADR-0001-render-backend.md)
