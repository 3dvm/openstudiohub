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


def test_addon_qa_rules_stay_in_sync_with_the_hub():
    hub_rules = (ROOT / "src" / "domain" / "qa" / "rules.py").read_text(encoding="utf-8")
    addon_rules = (PACKAGE_DIR / "qa_rules.py").read_text(encoding="utf-8")
    assert addon_rules == hub_rules
