# VCS Client, Locks and Audit

OpenStudioHub ships a production-focused Subversion client built on the `svn`
command-line tools. It covers the operations a 3D studio needs every day:
checkout, update, publish, conflicts, locks, history, revision export, server
policy and an audit trail. It intentionally does **not** expose code-centric
features such as branching, merging or tags.

## Requirements

* **SVN client 1.14 or newer** on every workstation. The Hub verifies the
  version at startup and before VCS actions.
* **SVN server 1.14 or newer** (`svnserve`). The server container used for
  administration must provide `svn`, `svnadmin` and `svnmucc`.
* The local projects folder must be a writable folder on the studio projects
  share. It is configured per machine, not in the Studio Seed.

## Initial machine setup

At startup the Hub checks the Studio Seed, the projects folder and the SVN
client. If any of them is missing, the **Initial Configuration** wizard opens
automatically:

1. **Studio Seed** — select and validate the `.seed` file.
2. **SVN Client** — detect the local client and its version. If it is missing,
   the wizard explains that Subversion 1.14 must be installed manually and the
   setup restarted. The setup does not run package managers.
3. **Projects Folder** — choose the local studio projects folder. The wizard
   explains its purpose, validates that it is writable and offers to create it
   with confirmation.
4. **Summary** — review the seed, SVN path, projects folder and vault path.

Nothing is written until **Finish** is pressed. Cancelling the wizard leaves the
machine unchanged. When the Studio Seed and projects folder already exist but
the SVN client is missing, the wizard resumes directly at the SVN step.

## Authentication and TLS

* VCS credentials are kept in RAM for the session. Passwords are sent to
  `svn` over **stdin** (`--password-from-stdin`) and never appear in the
  process list, command logs or audit entries.
* Authentication caching is disabled per command (`--no-auth-cache`).
* For `https://` repositories the server entry supports:
  * **TLS CA File** — pins a studio CA bundle with
    `servers:global:ssl-authority-files`.
  * **Trust system CA certificates** — can be disabled with
    `servers:global:ssl-trust-default-ca=no`.
  * **Allowed cert failures** — an explicit list passed to
    `--trust-server-cert-failures` (for example `unknown-ca,cn-mismatch`).
* The Hub never applies a blanket `--trust-server-cert`.
* If a configured CA file does not exist, the operation fails closed.
* `svn://` and `svn+ssh://` repositories do not use the TLS options.

## Updating a workspace

Use **Update from VCS** in the artist or project dashboard. The Hub:

1. Runs `svn update` with non-interactive conflict handling.
2. Detects conflicts and obstructions (`C`, `~`, `B`) with `svn status --xml`.
3. Opens the **VCS Update Needs Attention** dialog when cleanup is required.

The dialog offers:

* **Move aside** — moves the obstructing file or folder to
  `<workspace>/.openstudio_aside/<timestamp>/<path>` and adds
  `.openstudio_aside` to the local ignore list. Nothing is deleted.
* **Ignore** — adds a local ignore pattern to
  `<project>/<vfs_local>/vcs_local_ignores.json`. Local ignores are applied to
  every `svn` command with
  `--config-option config:miscellany:global-ignores=...` and never modify the
  repository.
* **Retry update** — starts the update again after cleanup.

Conflicts must be resolved from the task's publish window.

## Publishing files

The publish window separates the working copy into three groups:

* **Versioned changes** — selected by default.
* **Conflicts** — shown separately and cannot be published until resolved.
* **Untracked files** — **not selected by default**. They are only added to
  Subversion when the artist explicitly selects them. The list can be hidden.

The window also provides an editable commit message. It is pre-filled with the
project, task file and every **completed checklist item** from the task
comments. The final message is sent to `svn commit -m`.

## Conflicts

Conflicts are surfaced, not silently ignored. The publish window offers:

* **Keep mine** (`mine-full`).
* **Take theirs** (`theirs-full`).
* **Mark resolved** (`working`).

After resolution the workspace is rescanned and the publish window reopens with
the updated file list.

## Locks and `svn:needs-lock`

* `.blend` files must carry `svn:needs-lock`.
* New repositories receive `svn:auto-props` with
  `*.blend = svn:needs-lock=yes` and a `pre-commit` hook that rejects:
  * `.blend` files without `svn:needs-lock`;
  * backups, caches and temporary files such as `.blend1`, `.tmp`, `.cache`,
    `__pycache__`, `cache/` and `proxy/`.
* Existing repositories can be updated with **Apply VCS Lock Policy…** on the
  project card (TD only). The action installs/refreshes the hook and auto-props;
  existing `.blend` files may still need `svn:needs-lock` set manually.
* The Hub locks the task file **before opening the DCC**. If the lock cannot be
  acquired, the launch is blocked.
* A lock owned by the same user is treated as valid when the file is writable.
  If it is read-only, the artist is offered **Release my lock** on the task
  card.
* Locks are released **after a successful publish**. If the DCC closes with no
  changes, the lock is released because there is nothing to upload. If there
  are unpublished changes, the lock stays and the UI states that the files must
  be published to release it.
* A TD can break a foreign lock from the task card or from the project-level
  lock manager.

## History, diffs and revision export

From a task card, open **View VCS History…** to see:

* revision number, author, date and message;
* a textual diff for the selected revision;
* the **working copy diff** before publishing;
* **Export revision…**, which writes the selected revision to a destination
  file selected by the user. It never overwrites the working-copy file.

## TD operations

Project cards expose TD-only VCS actions:

* **Apply VCS Lock Policy…** — refresh hooks and auto-props.
* **Manage VCS Locks…** — list repository locks (`svnadmin lslocks`) and break a
  stale lock (`svnadmin rmlocks`) with confirmation.
* **Migrate VCS…** — move a repository between servers while preserving history.

The TD sidebar also includes **VCS Audit**.

## Audit trail

Every SVN client operation and repository-admin action is appended as JSON Lines
to:

```text
<state_dir>/vcs_audit.jsonl
```

The default state directory is `~/.openstudio/state`. Each event records:

* timestamp, operation, project, server and user;
* paths, working directory, result and return code;
* SVN error code (`E...`/`W...`), revision, duration and message;
* the sanitized command.

Passwords and passphrases are redacted. The log rotates automatically at 5 MB
and keeps three backups. The TD **VCS Audit** panel shows the most recent events,
supports text filters and a **Failures only** toggle, displays full event
details and can open the log folder.

## In-app notifications

The bell in the top bar opens the notification center. The first version is fed
by the VCS audit trail:

* failed commits, updates, locks and other client operations become unread
  notifications;
* TD users also receive repository-administration failures;
* artists and PMs only receive client/project failures;
* opening the bell, marking one item read or marking everything read updates
  the unread badge;
* each notification can be copied to the clipboard as plain text (title, time,
  project, SVN error code, paths and message) and dismissed with `×`;
* **Clear all** archives every visible notification at once;
* dismissed notifications leave the visible list but remain in a hidden archive
  under the per-user state file, so they can still be inspected for support
  without flooding the list again;
* read state, the hidden archive and the notification baseline are stored per
  user under `<state_dir>/notifications_<user>.json`, so historical failures do
  not flood the list on first launch.

Kitsu comment/assignment activity can be added later through the existing
`ActivityCard` component once `ProductionService.get_recent_activity()` is
implemented.

## Troubleshooting

* **SVN not found or older than 1.14** — install Subversion manually and run the
  Initial Configuration again.
* **File is locked by another user** — the launch is blocked. A TD can break the
  lock from the task card or the lock manager.
* **`W160035` / `E200009` when locking** — this normally means the same user
  already holds a stale lock. Use **Release my lock** on the task card and
  retry.
* **Update reports obstructed paths** — open the update dialog and use
  **Move aside**, then retry.
* **Commit fails as out of date** — update the workspace and resolve any
  conflicts before publishing again.
* **Audit questions** — open the TD **VCS Audit** panel or inspect
  `~/.openstudio/state/vcs_audit.jsonl`.
