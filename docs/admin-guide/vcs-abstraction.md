# VCS Abstraction (SVN / Git LFS)

Modern studios have diverse infrastructure needs. Some rely on the centralized locking mechanisms of Apache Subversion (SVN), while others prefer the distributed nature of Git coupled with Git LFS. 

OpenStudio Hub solves this through a robust architectural pattern: **VCS Abstraction**.

## How the Abstraction Layer Works
The Hub does not hardcode version control commands into its application logic. Instead, it relies on an `AbstractVCS` interface that defines base methods such as `sparse_pull()`, `commit()`, and `lock()`.

* **The VCS Router:** When the application boots, a `VCSRouter` reads the studio's configuration and dynamically instantiates the correct concrete adapter (e.g., `SVNAdapter` or `GitLFSAdapter`). 
* **Seamless Polymorphism:** The Hub is capable of supporting SVN or Git LFS under the exact same abstract interface. 
* **Artist Transparency:** For the end-user (the artist), this underlying complexity is completely invisible. They simply interact with the "Work" and "Publish" buttons, while the `VCSRouter` dispatches the correct network commands in the background.

## Serialized Binary Access (Needs-Lock)
To prevent simultaneous file corruption on binary files (like `.blend`), the concrete adapters enforce strict file locking. The VCS adapter will execute `svn lock` before launching the DCC, and intercept the closure of the environment to mandate an `svn unlock`, safely passing the baton to the rest of the team.
