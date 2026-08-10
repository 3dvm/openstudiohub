# Production Manager: Workflow & Guide

Welcome to the Production Manager (PM) guide for the OpenStudioHub. As a PM, your primary responsibility is bridging the gap between the studio's production tracker (Kitsu) and the physical file system (VCS/SVN).

## 1. The PM Dashboard & Core Responsibilities
The PM Dashboard provides a high-level view of the **Overall Project Health**. It features the **Pipeline Wizard**, a sequential orchestrator designed to guide you through the initial phases of production.

Your core responsibilities follow a strict chronological flow:

* **Sequence & Storyboard Initialization:** Generating the initial sequence files so artists can start drawing the storyboards.
* **Editorial Setup:** Spawning the master edit file for the Editor to assemble the animatic and push the required shots and assets to the pipeline.
* **Entity Validation:** Reviewing and approving the new Shots and Assets proposed by the Editor.
* **Batch Genesis:** Automating the creation of nested directory structures, copying base `.blend` templates, and generating tasks in Kitsu for the 3D artists to claim.

By following the Pipeline Wizard, you ensure that no artist starts working without the proper Kitsu tasks, SVN directories, and Master files in place.

## 2. Entity Validation & Kitsu Sync
Before physical files can be generated for 3D production, the entities (Assets and Shots) must be properly registered in Kitsu. 

### The Editorial Handoff
In the OpenStudio workflow, the production pipeline starts with the storyboards. Once the storyboard artists finish their work, the Editor uses the Master Edit file to cut the animatic. From Blender's VSE, the Editor pushes the proposed Shots and Assets directly to Kitsu. 

As the PM, you act as the gatekeeper for these new entities:

* The Hub queries the Kitsu API to fetch pending entities pushed by the Editor.
* It looks for Shots and Assets currently sitting in `Todo` or `Ready To Start` statuses.
* Only valid, approved entities will be passed onto the Batch Creation engine.

### Validating the Data
Before moving forward, ensure that:

* **Shots** belong to a valid Sequence.
* **Assets** have a properly assigned Asset Type (e.g., Character, Prop, Environment).
* Naming conventions are respected (the Hub will automatically sanitize names by removing spaces and forcing lowercase/underscores during physical file creation).

## 3. Batch Spawning & Directory Generation
The **Batch Create** engine is the most powerful tool in the PM arsenal. It physically materializes the Kitsu data into the studio's SVN repository.

### The 4-Step Pipeline Wizard
You will progress through four distinct stages that map to the chronological workflow:

1. **Spawn Storyboard Master:** Creates the initial 2D Animation/Storyboard `.blend` files in `edit/storyboards/` so the storyboard artists can begin sketching the sequences.
2. **Spawn Edit Master:** Generates the Master Edit `.blend` file in `edit/`. The Editor uses this file to assemble the storyboards into an animatic and subsequently upload/push the required shots and assets to Kitsu.
3. **Batch Create Assets:** Iterates through the approved Assets (pushed by the Editor), creates their folders in `pro/assets/<type>/<name>`, copies the project template, and spawns the required tasks (e.g., Modeling, Rigging) in Kitsu.
4. **Batch Create Shots:** Iterates through the approved Shots, creates folders in `pro/shots/<sequence>/<name>`, copies the template, and spawns the required tasks (e.g., Layout, Animation) in Kitsu.

### Under the Hood
When you click "Batch Create", the Hub:

1. Resolves the Semantic Topography on the NAS (SVN root).
2. Scaffolds the nested directories.
3. Copies the base `.blend` template to prevent Sparse Checkout deadlocks for Vendors.
4. Updates the Kitsu task metadata with the relative path to the newly created `.blend` file, allowing artists to launch the files directly from their Hub dashboards.
