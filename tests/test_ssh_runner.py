"""Unit tests for the SSH runner argument construction and askpass helper."""

import os

from src.domain.workspace.vcs_server_profile import RemoteSSHConfig
from src.infrastructure.vcs.ssh_runner import ASKPASS_ENV_VAR, SshRunner


def test_base_args_include_key_cert_and_known_hosts():
    remote = RemoteSSHConfig(
        host="svn-vps",
        ssh_port=2222,
        ssh_user="ops",
        ssh_key_path="/home/ops/.ssh/id_ed25519",
        ssh_cert_path="/home/ops/.ssh/id_ed25519-cert.pub",
        known_hosts_path="/home/ops/.ssh/known_hosts",
    )
    runner = SshRunner(remote)

    args = runner.base_args(has_passphrase=False)
    flat = " ".join(args)

    assert args[0] == "ssh"
    assert "-p" in args and "2222" in args
    assert "ops@svn-vps" in args
    assert "/home/ops/.ssh/id_ed25519" in flat
    assert "CertificateFile=/home/ops/.ssh/id_ed25519-cert.pub" in flat
    assert "UserKnownHostsFile=/home/ops/.ssh/known_hosts" in flat
    assert "BatchMode=yes" in flat
    assert "IdentitiesOnly=yes" in flat


def test_base_args_use_password_prompts_when_passphrase():
    runner = SshRunner(RemoteSSHConfig(host="h", ssh_user="u"))

    args = runner.base_args(has_passphrase=True)

    assert any("NumberOfPasswordPrompts=1" in token for token in args)
    assert not any("BatchMode=yes" in token for token in args)


def test_askpass_environment_injects_secret():
    if os.name == "nt":  # pragma: no cover - Windows askpass unsupported by design
        return

    runner = SshRunner(RemoteSSHConfig(host="h", ssh_user="u"))

    with runner._askpass_environment("super-secret") as env:
        assert env["SSH_ASKPASS_REQUIRE"] == "force"
        assert env[ASKPASS_ENV_VAR] == "super-secret"
        assert os.path.exists(env["SSH_ASKPASS"])

    # The helper is removed once the context exits.
    assert not os.path.exists(env["SSH_ASKPASS"])


def test_quote_escapes_shell_metacharacters():
    assert SshRunner.quote("a b; rm -rf /") == "'a b; rm -rf /'"
