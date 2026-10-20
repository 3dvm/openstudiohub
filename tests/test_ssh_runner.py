"""Unit tests for the SSH runner argument construction and askpass helper."""

import base64
import os
import struct
from types import SimpleNamespace

from src.domain.workspace.vcs_server_profile import RemoteSSHConfig
from src.infrastructure.vcs import ssh_runner
from src.infrastructure.vcs.ssh_runner import (
    ASKPASS_ENV_VAR,
    SshDiagnostics,
    SshRunner,
    private_key_is_encrypted,
    redact_args,
)


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


def test_verbose_adds_ssh_v_flag():
    plain = SshRunner(RemoteSSHConfig(host="h", ssh_user="u"))
    verbose = SshRunner(RemoteSSHConfig(host="h", ssh_user="u"), verbose=True)

    assert "-v" not in plain.base_args(has_passphrase=False)
    assert "-v" in verbose.base_args(has_passphrase=False)


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


def test_redact_args_masks_secret_flag_values():
    assert redact_args(["--password", "s3cret", "-p", "22"]) == [
        "--password",
        "********",
        "-p",
        "22",
    ]


def test_masked_args_shows_target_and_hides_secrets():
    remote = RemoteSSHConfig(
        host="svn-vps",
        ssh_port=2222,
        ssh_user="ops",
        ssh_key_path="/home/ops/.ssh/id_ed25519",
    )
    runner = SshRunner(remote, passphrase_provider=lambda: "topsecret")

    masked = runner.masked_args(True, "docker exec c sh -c true")

    assert "-p 2222" in masked
    assert "ops@svn-vps" in masked
    assert "/home/ops/.ssh/id_ed25519" in masked
    assert "topsecret" not in masked


def _openssh_key_file(cipher: bytes) -> bytes:
    raw = b"openssh-key-v1\x00" + struct.pack(">I", len(cipher)) + cipher + b"\x00" * 16
    body = base64.b64encode(raw).decode()
    lines = [body[i:i + 70] for i in range(0, len(body), 70)]
    text = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        + "\n".join(lines)
        + "\n-----END OPENSSH PRIVATE KEY-----\n"
    )
    return text.encode()


def test_private_key_is_encrypted_openssh_format(tmp_path):
    unencrypted = tmp_path / "id_plain"
    unencrypted.write_bytes(_openssh_key_file(b"none"))
    encrypted = tmp_path / "id_locked"
    encrypted.write_bytes(_openssh_key_file(b"aes256-ctr"))

    assert private_key_is_encrypted(unencrypted) is False
    assert private_key_is_encrypted(encrypted) is True


def test_private_key_is_encrypted_legacy_pem(tmp_path):
    legacy = tmp_path / "id_rsa"
    legacy.write_bytes(
        b"-----BEGIN RSA PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\n"
        b"DEK-Info: AES-128-CBC,0123\n\nAAAA\n-----END RSA PRIVATE KEY-----\n"
    )
    plain = tmp_path / "id_rsa_plain"
    plain.write_bytes(b"-----BEGIN RSA PRIVATE KEY-----\nAAAA\n-----END RSA PRIVATE KEY-----\n")

    assert private_key_is_encrypted(legacy) is True
    assert private_key_is_encrypted(plain) is False


def test_diagnostics_append_to_server_log(tmp_path):
    diagnostics = SshDiagnostics("svn-vps", log_dir=tmp_path)
    diagnostics.record("first line")
    diagnostics.record("second line")

    assert diagnostics.log_path == tmp_path / "ssh_svn-vps.log"
    content = diagnostics.log_path.read_text()
    assert "first line" in content
    assert "second line" in content


def test_run_traces_argv_and_exit_without_leaking_passphrase(tmp_path, monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return SimpleNamespace(
            returncode=255, stdout=b"", stderr=b"Permission denied (publickey)."
        )

    monkeypatch.setattr(ssh_runner.subprocess, "run", fake_run)

    remote = RemoteSSHConfig(
        host="academia-core",
        ssh_port=2222,
        ssh_user="linuxuser",
        ssh_key_path="/does/not/exist",
        container="estudio_svn",
    )
    runner = SshRunner(remote, passphrase_provider=lambda: "topsecret", log_dir=tmp_path)

    result = runner.run("true", check=False)

    assert result.returncode == 255
    assert "-p" in captured["args"] and "2222" in captured["args"]
    log = (tmp_path / "ssh_academia-core.log").read_text()
    assert "port=2222" in log
    assert "exit code: 255" in log
    assert "Permission denied (publickey)." in log
    assert "passphrase present: True" in log
    assert "topsecret" not in log
