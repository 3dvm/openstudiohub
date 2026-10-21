"""Integration tests against a real svnserve repository.

These tests are skipped when the Subversion server tools are not installed.
They exercise the adapter over ``svn://`` with real authentication, commits,
conflicts, out-of-date commits and the needs-lock workflow.
"""

import shutil
import socket
import stat
import subprocess
import time
from pathlib import Path

import pytest

from src.infrastructure.vcs.svn_adapter import SVNAdapter
from src.infrastructure.vcs.svn_errors import SvnOutOfDateError

pytestmark = pytest.mark.skipif(
    shutil.which("svnadmin") is None or shutil.which("svnserve") is None,
    reason="svnadmin/svnserve are required for integration tests",
)

REPO_NAME = "repo"
USER = "artist"
PASSWORD = "secret"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"svnserve did not start on {host}:{port}")


@pytest.fixture()
def svn_server(tmp_path):
    root = tmp_path / "svnroot"
    repo = root / REPO_NAME
    repo.parent.mkdir(parents=True)
    subprocess.run(["svnadmin", "create", str(repo)], check=True, capture_output=True)

    conf = repo / "conf"
    (conf / "svnserve.conf").write_text(
        "[general]\n"
        "anon-access = none\n"
        "auth-access = write\n"
        "password-db = passwd\n"
        "realm = OpenStudioHub Tests\n",
        encoding="utf-8",
    )
    (conf / "passwd").write_text(f"[users]\n{USER} = {PASSWORD}\n", encoding="utf-8")

    port = _free_port()
    process = subprocess.Popen(
        [
            "svnserve",
            "-d",
            "--foreground",
            "--listen-host",
            "127.0.0.1",
            "--listen-port",
            str(port),
            "--root",
            str(root),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_port("127.0.0.1", port)
        yield f"svn://127.0.0.1:{port}/{REPO_NAME}"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _adapter(url: str, workspace: Path) -> SVNAdapter:
    return SVNAdapter(url, workspace)


def _checkout(url: str, workspace: Path) -> SVNAdapter:
    adapter = _adapter(url, workspace)
    adapter.full_pull(USER, PASSWORD)
    return adapter


def test_checkout_commit_log_and_diff(svn_server, tmp_path):
    workspace = tmp_path / "wc"
    adapter = _checkout(svn_server, workspace)

    file_path = workspace / "a.txt"
    file_path.write_text("version one\n", encoding="utf-8")
    adapter.add(["a.txt"])
    adapter.commit("Initial commit", ["a.txt"], USER, PASSWORD)

    assert adapter.get_status() == {}
    revisions = adapter.get_log("a.txt", limit=5, username=USER, password=PASSWORD)
    assert revisions
    assert revisions[0]["message"] == "Initial commit"

    file_path.write_text("version two\n", encoding="utf-8")
    adapter.commit("Second commit", ["a.txt"], USER, PASSWORD)
    diff = adapter.get_diff("a.txt", revision=2, username=USER, password=PASSWORD)
    assert "version one" in diff
    assert "version two" in diff


def test_conflict_detection_and_resolution(svn_server, tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    adapter_a = _checkout(svn_server, first)
    adapter_b = _checkout(svn_server, second)

    base = first / "shared.txt"
    base.write_text("base\n", encoding="utf-8")
    adapter_a.add(["shared.txt"])
    adapter_a.commit("Base", ["shared.txt"], USER, PASSWORD)
    adapter_b.full_pull(USER, PASSWORD)

    (first / "shared.txt").write_text("from first\n", encoding="utf-8")
    adapter_a.commit("First change", ["shared.txt"], USER, PASSWORD)

    (second / "shared.txt").write_text("from second\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        adapter_b.full_pull(USER, PASSWORD)

    status = adapter_b.get_status()
    assert status.get("shared.txt") == "C"

    adapter_b.resolve("shared.txt", "theirs-full")
    adapter_b.commit("Resolve conflict", ["shared.txt"], USER, PASSWORD)
    assert (second / "shared.txt").read_text(encoding="utf-8") == "from first\n"


def test_out_of_date_commit_raises_typed_error(svn_server, tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    adapter_a = _checkout(svn_server, first)
    adapter_b = _checkout(svn_server, second)

    (first / "o.txt").write_text("base\n", encoding="utf-8")
    adapter_a.add(["o.txt"])
    adapter_a.commit("Base", ["o.txt"], USER, PASSWORD)
    adapter_b.full_pull(USER, PASSWORD)

    (first / "o.txt").write_text("first\n", encoding="utf-8")
    adapter_a.commit("First", ["o.txt"], USER, PASSWORD)
    (second / "o.txt").write_text("second\n", encoding="utf-8")

    with pytest.raises(SvnOutOfDateError):
        adapter_b.commit("Stale", ["o.txt"], USER, PASSWORD)


def test_needs_lock_makes_file_read_only_until_locked(svn_server, tmp_path):
    workspace = tmp_path / "wc"
    adapter = _checkout(svn_server, workspace)

    file_path = workspace / "locked.txt"
    file_path.write_text("data\n", encoding="utf-8")
    adapter.add(["locked.txt"])
    adapter.set_needs_lock("locked.txt")
    adapter.commit("Add locked file", ["locked.txt"], USER, PASSWORD)

    adapter.full_pull(USER, PASSWORD)
    assert not (file_path.stat().st_mode & stat.S_IWUSR)

    adapter.lock("locked.txt", USER, PASSWORD)
    assert file_path.stat().st_mode & stat.S_IWUSR

    adapter.unlock("locked.txt", USER, PASSWORD)
    assert not (file_path.stat().st_mode & stat.S_IWUSR)
