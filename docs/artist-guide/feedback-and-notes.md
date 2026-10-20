# Managing Feedback & Notes

Review cycles and supervisor feedback are an essential part of production. OpenStudioHub brings the Kitsu comment threads directly to your task board, so you can read and reply without switching to a browser.

## Project-first navigation

The artist dashboard opens on **My Projects**. It lists only the productions where you have assigned tasks, with the project thumbnail and the number of tasks you own.

Click a project card (or its **Open Tasks** button) to jump to **My Tasks** scoped to that project. Use the project and status selectors in the toolbar to broaden or narrow the list, and the **← Projects** button to return to the project grid.

## The comment badge

Every task card shows a comment badge in the top-left corner of its thumbnail:

* **`💬 N` in grey** — `N` is the **total** number of comments on the task (read + unread).
* **`💬 N` in orange** — the same total, highlighted because there are new comments since the last time you opened this task's thread.

The badge is always visible, so you can also use it as a quick activity indicator when scanning your tasks. Badges refresh when you load the dashboard or press **⟳ Refresh**.

## The comments drawer

Click the comment badge to open the comments drawer on the right side of **My Tasks**. The drawer only shows the thread of the selected task, and you can drag the splitter handle to resize it (the width is remembered for your user):

* **Timeline:** author, timestamp and text for every comment, with replies indented under their parent. Status labels and an attachment count are shown when present.
* **Composer:** write your reply in the box at the bottom and press **Send** (or `Ctrl+Enter`). The comment is posted to Kitsu together with the task's current status, so posting a note does not change the task status by itself.
* **Close:** use the **✕** button to dismiss the drawer; the board stays on the same task list.

Opening a thread marks it as seen for your Kitsu user on this machine, which clears the orange highlight. This read state is stored locally in `~/.openstudio/state/task_comments_seen.json`; Kitsu itself does not expose a per-user read flag, so a different workstation will show unread activity again.

## Checklists

Some comments carry a checklist (for example, "Check lighting", "Verify textures"). The drawer shows the list under the comment with a `Checklist x/y` header and one checkbox per item.

* **Marking items:** tick an item to mark it as finalized in Kitsu. The change is saved immediately; it does **not** change the task status.
* **Who can tick:** the assigned artist, managers and TDs with access to the task. Kitsu applies the final permission check.
* **Visual feedback:** checked items are struck through. While the Hub is saving, the checkboxes are temporarily disabled; if Kitsu rejects the update, the Hub reverts the check and shows the error in the status bar.
* **Task progress:** each comment keeps its own `Checklist x/y` header, so checklists from different comments never mix. The task card comment badge keeps showing the total comment count (read + unread) and only changes color when there is new activity.

TIP: Use **⟳ Refresh** after a teammate updates a checklist to pull their latest state.

## Working with feedback

* Read the latest notes and tick the checklist items before launching a task.
* Reply in the same thread to keep context; replies are linked to the original comment in Kitsu.
* If a supervisor changes a comment's attachment or adds a new preview, refresh the dashboard to pull the updated thread.
* Comment attachments are displayed as a count in this version; uploading new attachments from the Hub is not yet supported.
