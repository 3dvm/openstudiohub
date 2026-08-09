# B2B Studio Deployment & Provisioning

Deploying a pipeline tool across a studio of 50+ artists can be a logistical nightmare. OpenStudio Hub simplifies Day 0 deployment by centralizing the entire studio infrastructure into a single configuration state.

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
