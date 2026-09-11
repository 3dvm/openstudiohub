from .vcs_svn import SVNManager
# from .vcs_git import GitManager # Para el futuro

def get_vcs_manager(vcs_type: str, root: str, user: str, pwd: str):
    if vcs_type.lower() == "svn":
        return SVNManager(root, user, pwd)
    elif vcs_type.lower() == "git":
        # return GitManager(root, user, pwd)
        pass
    else:
        raise ValueError("VCS not supported")
