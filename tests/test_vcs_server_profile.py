"""Unit tests for the VCS server topology value objects."""

from src.domain.workspace.vcs_server_profile import (
    LOCAL_DOCKER,
    REMOTE_SSH,
    VCSServerProfile,
)


def test_default_profile_is_local_docker():
    profile = VCSServerProfile()
    assert profile.mode == LOCAL_DOCKER
    assert profile.is_remote is False
    assert profile.remote.repo_root == "/srv/svn"
    assert profile.remote.is_configured is False


def test_profile_round_trip_and_coercion():
    profile = VCSServerProfile.from_dict({
        "mode": "remote_ssh",
        "remote": {
            "host": "svn-vps",
            "ssh_user": "ops",
            "ssh_port": "2222",
            "container": "estudio_svn",
            "repo_root": "/var/opt/svn",
            "password_db": "/var/opt/svn/passwd",
        },
    })
    assert profile.is_remote is True
    assert profile.remote.ssh_port == 2222
    assert profile.remote.is_configured is True

    restored = VCSServerProfile.from_dict(profile.to_dict())
    assert restored == profile


def test_remote_requires_container_to_be_configured():
    without = VCSServerProfile.from_dict({"mode": "remote_ssh", "remote": {"host": "h", "ssh_user": "u"}})
    assert without.remote.is_configured is False

    with_container = VCSServerProfile.from_dict({
        "mode": "remote_ssh",
        "remote": {"host": "h", "ssh_user": "u", "container": "estudio_svn"},
    })
    assert with_container.remote.is_configured is True


def test_effective_password_db_defaults_to_repo_root_passwd():
    profile = VCSServerProfile.from_dict({
        "mode": "remote_ssh",
        "remote": {"container": "estudio_svn", "repo_root": "/var/opt/svn"},
    })
    assert profile.remote.effective_password_db() == "/var/opt/svn/passwd"

    explicit = VCSServerProfile.from_dict({
        "mode": "remote_ssh",
        "remote": {"container": "estudio_svn", "repo_root": "/var/opt/svn", "password_db": "passwd"},
    })
    assert explicit.remote.effective_password_db() == "passwd"


def test_invalid_mode_falls_back_to_local():
    assert VCSServerProfile.from_dict({"mode": "nonsense"}).mode == LOCAL_DOCKER


def test_missing_port_defaults_to_22():
    profile = VCSServerProfile.from_dict({"mode": REMOTE_SSH, "remote": {"host": "h"}})
    assert profile.remote.ssh_port == 22
