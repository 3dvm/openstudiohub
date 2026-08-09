# Automated Task Orchestration

Human error in folder naming and directory structures is the silent killer of 3D pipelines. OpenStudio Hub completely removes the artist and the manager from the file-creation equation by integrating seamlessly with **Kitsu / Gazu API**.

## Seamless Pipeline Synchronization

### 1. Batch Task Spawning
Production Managers (PMs) no longer need to manually set up project folders. Through the Hub's interface, a PM can select approved storyboards or edit master shots, and the system will automatically trigger a **Batch Task Spawning** routine. The Hub generates the entire task tree (Animation, Rigging, Layout) and injects the master `.blend` templates directly into the SVN repository in one click.

### 2. The Path Resolver Engine
Artists never have to worry about where to save their files. The Hub's internal `PathResolver` translates the Kitsu Task API data into absolute physical paths on the disk. It automatically evaluates if the task belongs to a Shot or an Asset, routing it to the correct standardized template (e.g., `shots/{seq}/{shot}/`).

### 3. One-Click Context Injection
When an artist clicks "Work" on their Hub dashboard, the magic happens under the hood:
* The system injects Kitsu IDs (Task ID, Entity ID, Sequence ID) directly into Blender's RAM (Scene RNA).
* The artist's 3D interface is pre-navigated to their specific task context.
* The UI workspace is forced into the correct layout (e.g., forcing the Video Sequence Editor for editorial tasks or 2D Animation for Storyboards) based on the assigned discipline.
