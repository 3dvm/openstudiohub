# Access Profiles & View Switching

OpenStudioHub uses an incremental access model. Your Kitsu account determines
the profiles you can use, and the top bar shows the profile currently active.

## Available profiles

| Profile | Dashboards available | Notes |
|---|---|---|
| `TD` | TD, PM, Artist | Full studio administration. |
| `PM` | PM, Artist | Production management and batch creation. |
| `Editor` | Artist | A PM with the `lead` position. Uses the Artist dashboard and keeps the extra Kitsu permissions. |
| `Artist` | Artist | Own tasks and project workspace. |
| `Vendor` | Artist | Same dashboard as an artist; sparse checkout policy still applies. |

`Supervisor`, `Client` and `Guest` accounts are denied access for now. Client
support can be added later without changing the profile model.

## Switching views

The top bar always shows the active profile text (`TD`, `PM`, `Editor` or
`Artist`). When an account has more than one profile, that text opens a selector
menu. Selecting another profile rebuilds the dashboard with that profile's
visible capabilities:

- a TD viewing the Artist profile sees the artist workflow, not TD-only actions;
- a PM viewing the Artist profile sees the artist workflow;
- switching back restores the higher-level dashboard.

The switch is blocked while a critical background operation is running or while
a 3D session is open, so workers and locked files are not interrupted.
