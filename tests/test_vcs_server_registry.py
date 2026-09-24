"""Unit tests for the VCS server registry value objects."""

from src.domain.workspace.vcs_server import VCSServer, VCSServerRegistry, slugify
from src.domain.workspace.vcs_server_profile import REMOTE_SSH, RemoteSSHConfig, VCSServerProfile


def _local() -> VCSServer:
    return VCSServer(id="local", name="Local", adapter="svn", repository_url="svn://localhost")


def _remote() -> VCSServer:
    return VCSServer(
        id="vps",
        name="VPS",
        adapter="svn",
        repository_url="svn://vps",
        enable_vendor_sparse_checkout=False,
        profile=VCSServerProfile(
            mode=REMOTE_SSH,
            remote=RemoteSSHConfig(host="vps", ssh_user="ops", container="estudio_svn"),
        ),
    )


def test_slugify_is_human_readable():
    assert slugify("VPS Production") == "vps-production"
    assert slugify("  My / Server  ") == "my-server"
    assert slugify("") == "server"


def test_registry_default_and_resolve():
    registry = VCSServerRegistry(servers=(_local(), _remote()), default_server_id="vps")

    assert registry.default().id == "vps"
    assert registry.get("local").id == "local"
    assert registry.resolve("local").id == "local"
    assert registry.resolve("", "svn://vps").id == "vps"
    assert registry.resolve("missing").id == "vps"


def test_registry_round_trip():
    registry = VCSServerRegistry(servers=(_local(), _remote()), default_server_id="vps")
    restored = VCSServerRegistry.from_dict(registry.to_dict())

    assert restored == registry
    assert restored.get("vps").profile.mode == REMOTE_SSH
    assert restored.get("vps").enable_vendor_sparse_checkout is False


def test_registry_missing_default_falls_back_to_first():
    registry = VCSServerRegistry.from_dict({
        "servers": [_local().to_dict(), _remote().to_dict()],
        "default_server_id": "ghost",
    })
    assert registry.default_server_id == "local"


def test_registry_with_and_without_server():
    registry = VCSServerRegistry(servers=(_local(),), default_server_id="local")

    updated = registry.with_server(_remote())
    assert {s.id for s in updated.servers} == {"local", "vps"}
    assert updated.default_server_id == "local"

    removed = updated.without_server("local")
    assert {s.id for s in removed.servers} == {"vps"}
    assert removed.default_server_id == "vps"


def test_server_invalid_adapter_falls_back():
    server = VCSServer.from_dict({"name": "X", "adapter": "nonsense"})
    assert server.adapter == "svn"
    assert server.id == "x"


def test_server_is_enabled():
    assert _local().is_enabled is True
    assert VCSServer(id="n", name="None", adapter="none").is_enabled is False
