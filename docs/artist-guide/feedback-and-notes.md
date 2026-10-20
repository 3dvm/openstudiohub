# Managing Feedback & Notes

Review cycles and supervisor feedback are an essential part of production. OpenStudioHub brings the Kitsu comment threads directly to your task board, so you can read and reply without switching to a browser.

## Project-first navigation

The artist dashboard opens on **My Projects**. It lists only the productions where you have assigned tasks, with the project thumbnail and the number of tasks you own.

Click a project card (or its **Open Tasks** button) to jump to **My Tasks** scoped to that project. Use the project and status selectors in the toolbar to broaden or narrow the list, and the **← Projects** button to return to the project grid.

## The comment badge

Every task card shows a comment badge in the top-left corner of its thumbnail:

* **`💬 N` in grey** — the task has `N` comments and you have already seen the latest activity.
* **`💬 N` in orange** — there are new comments since the last time you opened this task's thread.

The badge is always visible, so you can also use it as a quick activity indicator when scanning your tasks. Badges refresh when you load the dashboard or press **⟳ Refresh**.

## The comments drawer

Click the comment badge to slide open the comments drawer on the right side of **My Tasks**. The drawer only shows the thread of the selected task:

* **Timeline:** author, timestamp and text for every comment, with replies indented under their parent. Status labels and an attachment count are shown when present.
* **Composer:** write your reply in the box at the bottom and press **Send** (or `Ctrl+Enter`). The comment is posted to Kitsu together with the task's current status, so posting a note does not change the task status by itself.
* **Close:** use the **✕** button to dismiss the drawer; the board stays on the same task list.

Opening a thread marks it as seen for your Kitsu user on this machine, which clears the orange highlight. This read state is stored locally in `~/.openstudio/state/task_comments_seen.json`; Kitsu itself does not expose a per-user read flag, so a different workstation will show unread activity again.

## Working with feedback

* Read the latest notes before launching a task.
* Reply in the same thread to keep context; replies are linked to the original comment in Kitsu.
* If a supervisor changes a comment's attachment or adds a new preview, refresh the dashboard to pull the updated thread.
* Comment attachments are displayed as a count in this version; uploading new attachments from the Hub is not yet supported.
