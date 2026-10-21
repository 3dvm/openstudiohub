# Automated Task Orchestration

Human error in folder naming and directory structures is the silent killer of 3D pipelines. OpenStudioHub completely removes the artist and the manager from the file-creation equation by integrating seamlessly with **Kitsu / Gazu API**.

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

### 4. Task Board, Comments & Responsibles
Kitsu is also the communication layer. The Hub reads and writes task comments through the Gazu API:

* **Artist flow:** the dashboard opens on **My Projects**, which contains only the productions where the artist has tasks. Opening a project shows its **My Tasks** board; every card carries a `💬 N` badge (total comments) that turns orange when there are new comments. Clicking it opens a resizable right-side comment drawer with the thread and a composer.
* **PM/TD flow:** a project-scoped **Tasks** board (sidebar entry or **View Tasks** on a project card) shows the same comments in a table/list or card layout. PMs can also edit the task's **responsibles** (multi-select) directly from the board.
* **Comment posting:** each comment is posted with the task's current status (Kitsu requires a status on comment creation), so adding a note does not change the task's status by itself.
* **Checklists:** comment checklists are rendered as interactive checkboxes inside the drawer, under their own comment. Assigned artists and managers/TDs with access can tick items; the Hub patches only the `checklist` field (`PUT /data/comments/{id}`), leaving the text and task status untouched. The UI updates optimistically and reverts on failure.
* **Unread state:** Kitsu does not expose a per-user read flag, so the Hub tracks the last-seen comment per task and user locally in `~/.openstudio/state/task_comments_seen.json`. Badges are recalculated on load/refresh and cleared when a thread is opened; the number displayed is always the total comment count, with new activity indicated by the highlight.
* **Permissions:** only the **manager (PM)** role can change responsibles; TDs and artists see them read-only.

### 5. Embedded Kitsu & Watchtower
Kitsu and Watchtower open **inside the Hub's content area**, so the sidebar, top bar and status bar stay visible. The embedded browser uses a dedicated off-the-record profile (tokens stay in RAM) and bridges the current Kitsu session by setting the JWT access/refresh cookies plus an `Authorization: Bearer` fallback for `/api/` requests. This works with a **remote Kitsu server** over HTTPS; the host and API URL come from `settings.json`.

Task links are built from the task's `entity_type_name` (`sequences`, `shots`, `assets`, `edits`), so a task on a sequence opens the sequence task page instead of always landing on `shots`. Kitsu/Watchtower navigation stays embedded; links to any other domain open in the OS browser.
