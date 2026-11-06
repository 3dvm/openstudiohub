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
* **Missing files:** If the task has no file on disk, the card shows **File Missing on Disk** and the launch is blocked. Ask a PM or TD to create or link the file.
* **Context Injection:** The interface is pre-navigated to your specific task context, and only the tools you need are enabled. Rendering is currently triggered by a TD or Manager from the project card; Flamenco-based artist submission is on the roadmap.

## 2. Working & Telemetry - TODO
While you work, the Hub operates silently in the background:

* **Auto-Save:** The system enforces an automatic save of your `.blend` file every 30 minutes.
* **Idle Tracking:** An idle tracker pauses your time logging if you step away from your workstation for more than 5 minutes, ensuring your timesheets are perfectly accurate.

## 3. Submitting your Work (The "Push / Publish" Button)

When you launch a task, the Hub locks the linked file. The lock is released only after a successful publish. If the session leaves changes unpublished, the card keeps the lock and reminds you to publish; if there are no changes, the lock is released automatically.

The publish window lists versioned changes and conflicts first. Untracked files are kept in a separate section and are **not published unless you select them**. Files you deleted from disk appear under **Missing files**; use **Restore selected** to bring them back or **Delete from repository** to schedule their removal, then publish to commit it. The commit message is editable and lists the checklist items you tick in the same window; each tick is saved to Kitsu immediately. Conflicts must be resolved with **Keep mine**, **Take theirs** or **Mark resolved** before publishing.

Use the task card context menu to open **View VCS History…** for the revision log, diffs and a safe export of an older revision.
When your task is ready for review, run the Toolkit actions from the OpenStudio
panel in Blender:

* **Audit Scene** checks dependencies, transforms and naming;
* **Fix Out-of-Bounds Textures** copies external textures into the project and
  makes the paths relative;
* **Purge Orphans** removes unused data blocks and excludes `__TEMP__`;
* **Save & Commit** saves the file and commits it when the project uses VCS.

Auditing no longer saves or publishes automatically. For prop tasks the scene
range is set to `1–2`; shot ranges are left untouched.
