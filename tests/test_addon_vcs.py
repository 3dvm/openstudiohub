"""Unit tests for the Blender add-on VCS adapters (no Blender required)."""

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "addons" / "openstudio_toolkit"
VCS_DIR = PACKAGE_DIR / "vcs"


def _load_vcs_modules():
    package = types.ModuleType("addons.openstudio_toolkit")
    package.__path__ = [str(PACKAGE_DIR)]
    vcs_package = types.ModuleType("addons.openstudio_toolkit.vcs")
    vcs_package.__path__ = [str(VCS_DIR)]
    sys.modules.setdefault("addons", types.ModuleType("addons"))
    sys.modules["addons"].__path__ = [str(ROOT / "addons")]
    sys.modules["addons.openstudio_toolkit"] = package
    sys.modules["addons.openstudio_toolkit.vcs"] = vcs_package

    for name in ("vcs_base", "vcs_svn", "vcs_factory"):
        spec = importlib.util.spec_from_file_location(
            f"addons.openstudio_toolkit.vcs.{name}", VCS_DIR / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

    return sys.modules["addons.openstudio_toolkit.vcs.vcs_svn"]


def test_svn_commit_does_not_pass_the_password_in_argv(monkeypatch):
    vcs_svn = _load_vcs_modules()
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(vcs_svn.subprocess, "run", fake_run)
    manager = vcs_svn.SVNManager("/workspace", "artist", "secret-password")

    assert manager.commit("message", "/workspace/pro/a.blend") is True

    assert "--password-from-stdin" in captured["cmd"]
    assert "--password" not in captured["cmd"]
    assert "secret-password" not in captured["cmd"]
    assert captured["kwargs"]["input"] == "secret-password"


def _run_lock(monkeypatch, vcs_svn, *, info_stdout="", lock_stderr="", lock_returncode=0):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[:2] == ["svn", "info"]:
            return types.SimpleNamespace(returncode=0, stdout=info_stdout, stderr="")
        return types.SimpleNamespace(
            returncode=lock_returncode, stdout="", stderr=lock_stderr
        )

    monkeypatch.setattr(vcs_svn.subprocess, "run", fake_run)
    manager = vcs_svn.SVNManager("/workspace", "artist", "secret-password")
    return manager, calls


def test_svn_lock_does_not_pass_the_password_in_argv(monkeypatch):
    vcs_svn = _load_vcs_modules()
    manager, calls = _run_lock(monkeypatch, vcs_svn)

    assert manager.lock("/workspace/pro/a.blend") is True

    cmd, kwargs = calls[-1]
    assert cmd[0] == "svn" and cmd[1] == "lock"
    assert "--password-from-stdin" in cmd
    assert "--password" not in cmd
    assert "secret-password" not in cmd
    assert kwargs["input"] == "secret-password"


def test_svn_lock_returns_true_when_owned_by_the_same_user(monkeypatch):
    vcs_svn = _load_vcs_modules()
    manager, calls = _run_lock(
        monkeypatch, vcs_svn, info_stdout="Lock Owner: artist\nLock Token: abc\n"
    )

    assert manager.lock("/workspace/pro/a.blend") is True
    assert all(cmd[:2] != ["svn", "lock"] for cmd, _ in calls)


def test_svn_lock_raises_for_a_foreign_owner(monkeypatch):
    vcs_svn = _load_vcs_modules()
    manager, _calls = _run_lock(
        monkeypatch, vcs_svn, info_stdout="Lock Owner: edv\nLock Token: abc\n"
    )

    try:
        manager.lock("/workspace/pro/a.blend")
    except vcs_svn.VCSLockError as error:
        assert error.owner == "edv"
    else:  # pragma: no cover - the call must fail
        raise AssertionError("lock should have raised for a foreign owner")


def test_svn_lock_treats_a_race_held_by_the_same_user_as_success(monkeypatch):
    vcs_svn = _load_vcs_modules()
    manager, _calls = _run_lock(
        monkeypatch,
        vcs_svn,
        lock_stderr="svn: warning: W160035: Path is already locked by user 'artist'.",
        lock_returncode=1,
    )

    assert manager.lock("/workspace/pro/a.blend") is True


def test_svn_lock_raises_for_a_foreign_race(monkeypatch):
    vcs_svn = _load_vcs_modules()
    manager, _calls = _run_lock(
        monkeypatch,
        vcs_svn,
        lock_stderr="svn: E160039: Path is already locked by user 'edv'.",
        lock_returncode=1,
    )

    try:
        manager.lock("/workspace/pro/a.blend")
    except vcs_svn.VCSLockError as error:
        assert error.owner == "edv"
    else:  # pragma: no cover - the call must fail
        raise AssertionError("lock should have raised for a foreign owner")


def test_addon_qa_rules_stay_in_sync_with_the_hub():
    hub_rules = (ROOT / "src" / "domain" / "qa" / "rules.py").read_text(encoding="utf-8")
    addon_rules = (PACKAGE_DIR / "qa_rules.py").read_text(encoding="utf-8")
    assert addon_rules == hub_rules


def test_svn_commit_forces_the_configured_locale(monkeypatch):
    vcs_svn = _load_vcs_modules()
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["kwargs"] = kwargs
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(vcs_svn.subprocess, "run", fake_run)
    manager = vcs_svn.SVNManager(
        "/workspace", "artist", "secret-password", locale="C.UTF-8"
    )

    assert manager.commit("mensaje con acentos: cámara", "/workspace/pro/a.blend") is True

    assert captured["kwargs"]["env"]["LC_ALL"] == "C.UTF-8"
    assert captured["kwargs"]["env"]["LANG"] == "C.UTF-8"
