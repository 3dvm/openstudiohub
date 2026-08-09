# Standardized Workspaces & Sandboxing

*"It works on my machine"* is a phrase that should never be heard in a professional pipeline. Mismatched software versions, outdated add-ons, and customized user preferences cause catastrophic render failures and broken files.

OpenStudio Hub enforces a strict **Golden Path** through zero-configuration Sandboxing.

## The Isolated Vault

### 1. Pristine DCC Deployment
The Hub acts as an autonomous package manager. It asynchronously scrapes and downloads the exact, studio-approved Blender executable directly from `download.blender.org`. The software is extracted into an isolated local vault (e.g., `06_conf_LOCAL`), completely ignoring any pre-existing Blender installations on the artist's machine.

### 2. Environment Variable Injection
To guarantee that the entire team uses the exact same tools without conflicts, the Hub launches Blender using injected environment variables like `BLENDER_USER_RESOURCES`. This forces the software to read configurations and add-ons strictly from the controlled Hub ecosystem.

### 3. Dynamic Tooling & Add-on Sync
Before the software even launches, the Hub performs a silent sync. 
* It pulls the latest studio tools (like the Kitsu add-on and Asset Pipeline) from the central NAS.
* It forces physical studio preferences (like injecting the `OPENSTUDIO_PROJECT_ROOT` path into the add-on settings), instantly reverting any manual, unauthorized modifications made by the user.
* Features are context-aware: Tools like the *Flamenco Render Farm* submitter are dynamically hidden from modelers and automatically enabled only for lighting and rendering artists.
