# B2B Studio Deployment & Provisioning

Deploying a pipeline tool across a studio of 50+ artists can be a logistical nightmare. OpenStudioHub simplifies Day 0 deployment by centralizing the entire studio infrastructure into a single configuration state.

## The Global Configuration
The core of the Hub's behavior is driven by a master `settings.json` file. This file acts as the single source of truth for the studio, defining variables such as:

* Nextcloud/NAS Root Paths.
* Kitsu API URLs.
* The VCS server registry (local Docker and one or more remote VPS).
* Cloud Services and AI Telemetry activation.

The Hub is OS-agnostic: it dynamically detects the host operating system (Windows, Linux, Darwin) to resolve the correct local workspace root automatically.

### Machine-local paths are never shipped

The seed only carries **portable** configuration. The Vault is stored as a relative folder name (`vault_dir`, default `openstudio_vault`) that each machine resolves against its own local workspace root, so artists with a different home folder still find the shared binaries. Absolute paths that only make sense on the authoring machine (a custom vault override and the per-server `ssh_key_path` / `ssh_cert_path` / `known_hosts_path`) are stripped on export and ignored on import; each machine fills its own SSH defaults locally. When a legacy `settings.json` still holds an absolute vault path, the Hub migrates it to the portable form on load (or self-heals to `<workspace>/openstudio_vault` when the stored path is missing on this machine).

## Day 0 Provisioning (The `.seed` File)
To provision multiple workstations without manually configuring paths on each machine, the Hub utilizes a Studio Seed Generator. 

* The system packages and obfuscates the global configuration into a `.seed` file.
* This file is compressed using zlib and base64 for secure and seamless injection into other workstations. 
* On Day 0, a new artist simply clicks "Load Studio Seed" on the login screen, selects the `.seed` file, and their Hub is instantly connected to the studio's specific database, network drives, and VCS backend.

## VCS Servers (Infrastructure panel)
All VCS configuration lives in the **Infrastructure panel**, not in Settings. The studio can register several servers side by side; each project is bound to exactly one of them.

Each server entry has:

* A human-readable **id/name** (the id is derived from the name and is stored in the project blueprint).
* An **adapter** (`svn`, `git-lfs`, `none`) and the **repository URL** (`svn://host`).
* An optional **Vendor Sparse Checkout** flag.
* A **mode**:
  * **`local_docker`** — the bundled developer SVN container (`openstudio_local_svn`).
  * **`remote_ssh`** — a production VPS whose `svnserve` runs inside a Docker container and is only reachable over the tailnet. The Hub creates and deletes **per-project repositories** by running `docker exec` over OpenSSH; it does not manage the daemon itself.

For `remote_ssh` you provide: the SSH host/port/user, the private key (and optional OpenSSH certificate), an optional `known_hosts` file, the **Docker container name** (mandatory), the in-container repository root (svnserve `-r`, e.g. `/var/opt/svn`), and the in-container path to the studio-wide `passwd` file. Leave the passwd path blank to default to `<repo_root>/passwd`.

For HTTPS repository URLs the same entry accepts an optional **TLS CA File**, a **Trust system CA certificates** toggle and an explicit **Allowed cert failures** list. The Hub never trusts arbitrary certificates by default; if a configured CA file is missing, VCS operations fail closed.

**Credentials are per server.** The Session Credentials tab (and the just-in-time prompt before a VCS action) pick the target server from a dropdown and store the VCS username/password and, for remote servers, the SSH key passphrase in RAM for the session only. Nothing is written to disk.

### Troubleshooting remote SSH

All remote server administration (`ssh`, `scp` and the server-side `docker exec` provisioning) writes an always-on diagnostic log to `~/.openstudio/logs/ssh_<host>.log`. Each attempt records:

* the masked command line (host, port, user, key, certificate, known_hosts and container);
* pre-flight facts about the private key (present/missing, encrypted or not, permission warnings);
* whether a passphrase was available;
* the full `ssh` stderr and exit code.

The passphrase is never written to the log; only whether one was present. To capture OpenSSH's own negotiation trace (which key was offered, whether the server accepted it, agent/certificate details), tick **Verbose (ssh -v)** next to **Test SSH** in the Infrastructure panel before running the test.

A `Permission denied (publickey)` message means the server rejected the offered key: the public key is not in the target account's `authorized_keys`, the SSH user/host is wrong, the key file is not readable, or the key is encrypted and no passphrase was supplied. The log and the `-v` trace show exactly which key was offered so you can fix the server-side account instead of guessing. If the key is encrypted and no passphrase is available, the Hub falls back to `BatchMode=yes`, so OpenSSH cannot decrypt the key and public-key authentication fails.

New projects pick their server in the creation dialog; the binding is recorded as `vcs_server_id` in the project's `project_init.json`, so a studio can run some projects on the local sandbox and others on a VPS at the same time.

Each new repository also receives `svn:auto-props` for `*.blend = svn:needs-lock=yes`, inheritable ignore rules for caches and backups, and a `pre-commit` hook that rejects `.blend` files without the lock property. Existing repositories can be refreshed from the project card with **Apply VCS Lock Policy…** (TD only).

Each repository created on the remote server gets a `conf/svnserve.conf` that points at the global passwd by **absolute path**, e.g.:

```
[general]
anon-access = none
auth-access = write
password-db = /var/opt/svn/passwd
realm = OpenStudio
```

The global passwd file is never modified by the Hub; provision it once on the server (bind-mounted into the container next to the repositories).

TD users can inspect repository locks with **Manage VCS Locks…**, and review the redacted VCS audit trail from the **VCS Audit** panel or `~/.openstudio/state/vcs_audit.jsonl`.

### Migrating an Existing Project
Migration is **per project**, works **between any two servers**, and preserves history. From a project card (TD role), choose **Migrate VCS to Remote** and pick the target server:

1. The Hub verifies the target repository is present and empty.
2. It streams a `svnadmin dump` from the project's current server into a `svnadmin load` on the target (the repository UUID is preserved).
3. The existing working copy is repointed with `svn relocate`, so uncommitted local changes are kept.
4. The per-project `vcs_server_id` and `vcs_base_url` are recorded in `project_init.json`.
5. You are then asked whether to delete the old repository or leave it orphaned.

## Kitsu Server (remote or local)

Set the Kitsu API URL in `settings.json` under `kitsu_production.api_url`, for example `https://kitsu.studio.com/api`. The embedded Kitsu view is built for **remote servers over HTTPS**:

* The Hub strips `/api` to obtain the web root and loads Kitsu inside the dashboard content area (sidebar/top bar stay visible).
* The current login is reused: the Hub sets the Kitsu JWT access/refresh cookies on a dedicated off-the-record `QWebEngineProfile` and adds an `Authorization: Bearer` fallback for `/api/` requests. No reverse-proxy change is required.
* Token and cookie data stay in RAM; the profile is destroyed with the session. Logout clears the embedded cookies.
* Task links are built from the task's entity type, so sequences open under `/sequences`, shots under `/shots`, and so on.
* Navigation to other domains opens in the system browser.

If the embedded view shows the Kitsu login page, the Hub session token has expired: log in inside the embedded view or log out and back into the Hub.
