# B2B Studio Deployment & Provisioning

Deploying a pipeline tool across a studio of 50+ artists can be a logistical nightmare. OpenStudioHub simplifies Day 0 deployment by centralizing the entire studio infrastructure into a single configuration state.

## The Global Configuration
The core of the Hub's behavior is driven by a master `settings.json` file. This file acts as the single source of truth for the studio, defining variables such as:

* Nextcloud/NAS Root Paths.
* Kitsu API URLs.
* VCS Engine topology (SVN vs. Git).
* Cloud Services and AI Telemetry activation.

The Hub is OS-agnostic: it dynamically detects the host operating system (Windows, Linux, Darwin) to resolve the correct local workspace root automatically.

## Day 0 Provisioning (The `.seed` File)
To provision multiple workstations without manually configuring paths on each machine, the Hub utilizes a Studio Seed Generator. 

* The system packages and obfuscates the global configuration into a `.seed` file.
* This file is compressed using zlib and base64 for secure and seamless injection into other workstations. 
* On Day 0, a new artist simply clicks "Load Studio Seed" on the login screen, selects the `.seed` file, and their Hub is instantly connected to the studio's specific database, network drives, and VCS backend.

## Remote VCS Server (VPS over the Tailnet)
The Infrastructure panel configures how the Hub administers project repositories. Two modes are available:

* **`local_docker`** — the bundled developer SVN container (`openstudio_local_svn`).
* **`remote_ssh`** — a production VPS whose `svnserve` runs inside a Docker container and is only reachable over the tailnet. The Hub creates and deletes **per-project repositories** by running `docker exec` over OpenSSH; it does not manage the daemon itself.

For `remote_ssh` you provide: the SVN base URL (`svn://host`), the SSH host/port/user, the private key (and optional OpenSSH certificate), an optional `known_hosts` file, the **Docker container name** (mandatory), the in-container repository root (svnserve `-r`, e.g. `/var/opt/svn`), and the in-container path to the studio-wide `passwd` file. Leave the passwd path blank to default to `<repo_root>/passwd`. The SSH passphrase is entered in the Session Credentials tab and kept in RAM for provisioning only.

Each repository created on the remote server gets a `conf/svnserve.conf` that points at the global passwd by **absolute path**, e.g.:

```
[general]
anon-access = none
auth-access = write
password-db = /var/opt/svn/passwd
realm = OpenStudio
```

The global passwd file is never modified by the Hub; provision it once on the server (bind-mounted into the container next to the repositories).

### Migrating an Existing Project
Migrating is **per project** and preserves history. From a project card (TD role), choose **Migrate VCS to Remote**:

1. The Hub verifies the target remote repository is present and empty.
2. It streams a local `svnadmin dump` into a remote `svnadmin load` (the repository UUID is preserved).
3. The existing working copy is repointed with `svn relocate`, so uncommitted local changes are kept.
4. The per-project `vcs_base_url` is recorded in `project_init.json`.
5. You are then asked whether to delete the old local repository or leave it orphaned.

The global `repository_url` is updated in the Infrastructure panel so newly created projects are provisioned on the remote server.
