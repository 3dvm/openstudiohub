# Technical Director: Project Creation Guide

This guide outlines the standard operating procedure for a Technical Director (TD) to create and bootstrap a new production project using the OpenStudioHub.

## 1. Project Initialization
The project creation process is initiated directly from the TD Dashboard. As a TD, you must provide:

* **Project Name:** A unique identifier for the production.
* **Blender Version:** The target Blender executable version for the project (e.g., 4.2.0, 5.2.0).
* **Project Template:** The base template for folder structures and tasks (e.g., `standard-3d-production`).
* **Splash Image (Optional):** A hero image for the project's dashboard.

## 2. Kitsu Database Integration
Once initialized, the OpenStudioHub automatically interfaces with the Kitsu API to:

* Forge the root project entity in the database using the selected template.
* Establish the base taxonomy (Departments, Task Types, and Asset Types) required for the pipeline.
* Extract the `project_id` to bind local NAS files to the Kitsu tracker permanently.

## 3. Storage and Semantic Topography Generation
The Hub builds the physical directory structure on your centralized NAS (Network Attached Storage):

* **VFS Folders:** Creates isolated structural environments including `vfs_local` (sandboxing), `vfs_shared` (symlinks), and `vfs_pipeline` (metadata).
* **Production Tree:** Scaffolds standard working directories such as `pro/assets`, `pro/shots`, `pro/edit`, and `tools`.
* **Metadata Injection:** Writes the `project_init.json` payload into the pipeline folder, acting as the blueprint for artists when they install the workspace.

## 4. Version Control (SVN) Setup
To ensure data integrity and enable Vendor Sparse Checkout (Jailing), the Hub configures Subversion (SVN) under the hood:

* **Server Repository:** Creates the remote repository on the SVN server (often using Dockerized SVN for local setups).
* **Access Control:** Configures `svnserve.conf` and injects baseline credentials to secure the repository.
* **Ignore Rules:** Sets `svn:ignore` patterns to exclude volatile local caches (`vfs_local`, `*.blend1`, etc.) from version control.
* **VFS Monkey Patching:** Injects the `00_openstudio_vfs_patch.py` script to route Blender's Virtual File System correctly upon launch.
* **Initial Commit:** Pushes the baseline blueprint to the server, making the project ready for artists to clone.
