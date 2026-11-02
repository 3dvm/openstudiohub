# System Requirements

To successfully install, deploy, and run the OpenStudioHub ecosystem in your studio, ensure your infrastructure meets the following prerequisites.

## 1. Operating System Requirements
OpenStudioHub is built to be cross-platform, but certain environments have specific demands:
* **Linux:** **Ubuntu 24.04 or higher** is strictly required to run the compiled binary smoothly.
* **Windows:** Windows 10 or Windows 11 (64-bit) for standard artists and pipeline execution.
* **macOS:** macOS 12+ (Compatible with both Apple Silicon and Intel architectures).

## 2. Server & Backend Infrastructure
* **SVN Server:** A Subversion (SVN) 1.14+ server is mandatory for version control, binary asset locking, and sparse checkout (vendor jailing). The Hub supports Docker-based SVN containers for local deployments or dedicated remote servers.
  * **Multiple servers** can be registered in the Infrastructure panel; each project is bound to one server. A common setup is a local Docker sandbox for development plus one or more production VPS.
  * **Remote (production) servers** run `svnserve` inside a **Docker container** (e.g. `estudio_svn`) on a VPS that is only reachable over the tailnet (e.g. Headscale/Tailscale). Project repositories are created/deleted with `docker exec` over OpenSSH; the Hub assumes `svnserve` is already running and that the SSH user can run `docker` without a sudo password.
  * Configure the container name, the in-container repository root (svnserve `-r`, e.g. `/var/opt/svn`) and the in-container path of the global `passwd` file. When the passwd path is left blank the Hub derives `<repo_root>/passwd`, and each new repository's `svnserve.conf` references it by absolute path.
  * Server administration needs `svn`, `svnadmin`, `svnmucc`, `ssh` and `scp` on the PATH or inside the administration container. The SSH passphrase (when the key is encrypted) is kept in RAM for the session only.
  * Every workstation needs **SVN client 1.14+**. The Hub verifies it at startup and before VCS actions, and the Initial Configuration wizard runs when the machine is not ready.
  * HTTPS repositories can pin a CA file and explicit certificate-failure policies from the Infrastructure panel. `svn://` repositories are unaffected.
  * VCS operations and repository administration are recorded in `<state_dir>/vcs_audit.jsonl` with secrets redacted; TD users can inspect them from the **VCS Audit** panel.
* **Kitsu / Zou Server:** A fully operational Kitsu instance (production tracker) accessible via HTTP/HTTPS API. The Hub requires an admin account to seed initial templates and establish API bindings.

## 3. Network & Storage
* **NAS / Shared Storage:** A centralized Network Attached Storage (NAS) accessible by all artists and TDs.
* **File Manager:** A working, correctly configured file manager environment. The system relies heavily on creating Virtual File Systems (VFS), symbolic links (`vfs_shared`), and isolated sandboxes (`vfs_local`). Your file manager and NAS file system must support these operations (e.g., NTFS, ext4, APFS).

## 4. Software Dependencies
* **Blender:** Target versions supported as defined in your studio's Vault manifest (e.g., 3.6 LTS, 4.2 LTS, 5.1+). The Hub handles Blender binary deployment automatically via the Vault.
* **Git & Git LFS (Optional):** If future pipeline extensions require Git-based repositories instead of SVN, both Git and Git LFS must be installed in the system PATH.

## 5. Render farm / cloud burst
The direct Vast.ai burst needs the following on the workstation that starts the
render:

* **Vast.ai account and credit.** Top up before a production run; the render
  panel shows the current balance. The default price cap is $0.13/h; raise it
  explicitly when the plan reports that no offer fits.
* **`vastai` CLI** installed and authenticated. The API key is stored by the CLI
  in `~/.config/vastai/vast_api_key`; never commit it.
* **Unencrypted SSH key registered with Vast.** The Hub defaults to
  `~/.ssh/id_ed25519_ppf`; use `ssh_key_path` in `RenderService` to point at
  another key. The private key stays on the workstation.
* **`rsync`, `ssh` and outbound HTTPS/SSH.** The burst installs Blender inside
  each instance and stages the production folder over SSH. The panel prefers
  US offers with at least 100 Mbps down / 50 Mbps up by default.
* **GPU class.** RTX 3070 (8 GB), 3080 (10 GB), 4070 (12 GB), 3090/4090
  (24 GB) and A6000 (48 GB) are supported. The 3070/3080/4070 are the budget
  profiles; use 24/48 GB for heavy geometry-node or high-resolution scenes.
* **Disk.** 40 GB per instance (Blender, project staging and frames).
* **Output storage.** `03_render/` grows with every frame; a 1080p PNG is
  roughly 1.7 MB in the `sh010` reference. Plan NAS capacity accordingly.
* **`ffmpeg`.** Required for the review video and the Blender render-review
  copy. The panel reports a clear error if it is missing.
* **Kitsu permissions.** The user who uploads the review video must be able to
  add a preview/comment and change the task status on the matching `render`
  task.
* **Output paths.** Frames go to
  `03_render/shots/<sequence>/<shot>.render/`; the review video goes to
  `04_datos_compartidos/editorial/footage/pro/<sequence>/<shot>/<shot>-render/`.
* **A benchmark for heavy shots.** Geometry-node shots (many instances) are
  flagged and should be measured before a deadline run. The panel has a
  **Benchmark selected** action that measures three frames on one Vast node.

Flamenco is not required for the direct burst. A future persistent Flamenco
farm will additionally need a synchronous shared filesystem; on Vast.ai that
means VMs with Tailscale + NFS, not Docker instances.
