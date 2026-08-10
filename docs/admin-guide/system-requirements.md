# System Requirements

To successfully install, deploy, and run the OpenStudioHub ecosystem in your studio, ensure your infrastructure meets the following prerequisites.

## 1. Operating System Requirements
OpenStudioHub is built to be cross-platform, but certain environments have specific demands:
* **Linux:** **Ubuntu 24.04 or higher** is strictly required to run the compiled binary smoothly.
* **Windows:** Windows 10 or Windows 11 (64-bit) for standard artists and pipeline execution.
* **macOS:** macOS 12+ (Compatible with both Apple Silicon and Intel architectures).

## 2. Server & Backend Infrastructure
* **SVN Server:** A Subversion (SVN) server is mandatory for version control, binary asset locking, and sparse checkout (vendor jailing). The Hub supports Docker-based SVN containers for local deployments or dedicated remote servers accessed via SSH.
* **Kitsu / Zou Server:** A fully operational Kitsu instance (production tracker) accessible via HTTP/HTTPS API. The Hub requires an admin account to seed initial templates and establish API bindings.

## 3. Network & Storage
* **NAS / Shared Storage:** A centralized Network Attached Storage (NAS) accessible by all artists and TDs.
* **File Manager:** A working, correctly configured file manager environment. The system relies heavily on creating Virtual File Systems (VFS), symbolic links (`vfs_shared`), and isolated sandboxes (`vfs_local`). Your file manager and NAS file system must support these operations (e.g., NTFS, ext4, APFS).

## 4. Software Dependencies
* **Blender:** Target versions supported as defined in your studio's Vault manifest (e.g., 3.6 LTS, 4.2 LTS, 5.1+). The Hub handles Blender binary deployment automatically via the Vault.
* **Git & Git LFS (Optional):** If future pipeline extensions require Git-based repositories instead of SVN, both Git and Git LFS must be installed in the system PATH.
