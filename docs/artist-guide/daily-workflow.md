# The Daily Workflow: Work & Publish

OpenStudioHub simplifies your daily routine into two main actions: clicking **Work** to start, and clicking **Publish** when you are ready for review.

## 0. Choose your Project and Stay Up to Date
Your dashboard opens on **My Projects**, which lists only the productions where you have assigned tasks. Click a project card to open its **My Tasks** board.

Before you start a task, select the project in the **My Tasks** toolbar and click **Update from VCS**. If the update finds conflicts or obstructing files, the Hub opens a review dialog where you can move them aside or ignore them locally, then retry.

* **What happens?** The Hub pulls the latest revisions from the version control server into the project workspace, so you always work on top of your teammates' latest commits.
* **Availability:** The button is enabled only when a specific project that uses version control is selected. Projects stored on the NAS only are not affected.

## 1. Review Feedback, then Start your Task
Before launching, check the task's comment badge (`💬 N`, where `N` is the total number of comments). If it is highlighted in orange there are new comments from your supervisor or teammates. Click it to open the right-side comments drawer, read the thread and reply without leaving the Hub.

If the comment includes a checklist, tick the items you have finished. Each checklist stays under its own comment in the drawer. Checking a checklist item does not change the task status.

When the task is ready, click the **Launch Project** button.

* **What happens?** The Hub automatically launches your isolated Blender environment and opens your `.blend` file.
* **Dynamic Creation:** If the file doesn't exist yet, the Hub's Shot Builder dynamically generates it from the studio template so you don't start with an empty canvas.
* **Context Injection:** The interface is pre-navigated to your specific task context, and only the tools you need (like the Flamenco Render Farm for lighting artists) are enabled.

## 2. Working & Telemetry - TODO
While you work, the Hub operates silently in the background:

* **Auto-Save:** The system enforces an automatic save of your `.blend` file every 30 minutes.
* **Idle Tracking:** An idle tracker pauses your time logging if you step away from your workstation for more than 5 minutes, ensuring your timesheets are perfectly accurate.

## 3. Submitting your Work (The "Push / Publish" Button)

When you launch a task, the Hub locks the linked file. The lock is released only after a successful publish. If the session leaves changes unpublished, the card keeps the lock and reminds you to publish; if there are no changes, the lock is released automatically.

The publish window lists versioned changes and conflicts first. Untracked files are kept in a separate section and are **not published unless you select them**. The commit message is editable and already includes the checklist items you completed in the task comments. Conflicts must be resolved with **Keep mine**, **Take theirs** or **Mark resolved** before publishing.

Use the task card context menu to open **View VCS History…** for the revision log, diffs and a safe export of an older revision.
When your task is ready for review, hit **Publish**. Before the file is uploaded, the **Gatekeeper** audits your scene.

* **Silent Cleanup:** It automatically purges orphan data and ignores temporary collections (like `__TEMP__`).
* **The Concierge Pop-up:** If you accidentally linked a texture or HDRI from your personal `Downloads` folder, the Hub will intercept the publish and show a pop-up. It will ask you to classify the file, and then it will automatically copy it to the correct server folder and fix the paths for you.
* **Scale Auto-Fix:** If any of your meshes have unapplied rotations or scales, the Gatekeeper will apply them automatically to prevent broken rigs down the line.
