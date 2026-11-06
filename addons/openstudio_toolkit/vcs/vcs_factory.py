from .vcs_svn import SVNManager


def get_vcs_manager(vcs_type: str, root: str, user: str, pwd: str, locale: str = ""):
    adapter = (vcs_type or "").strip().lower()
    if adapter == "svn":
        return SVNManager(root, user, pwd, locale)
    if adapter in ("", "none"):
        return None
    raise ValueError(f"VCS adapter not supported: {vcs_type}")
