"""Pure policy tests for per-project Blender preferences."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "addons" / "openstudio_toolkit" / "preferences_policy.py"


def _policy():
    spec = importlib.util.spec_from_file_location("preferences_policy", POLICY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_temporary_directory_uses_the_project_local_folder(tmp_path):
    policy = _policy()
    resources = tmp_path / "06_conf_LOCAL" / "blender_data"

    assert policy.local_root_from_resources(str(resources)) == (
        tmp_path / "06_conf_LOCAL"
    ).resolve()
    assert policy.temporary_directory(str(resources)) == (
        tmp_path / "06_conf_LOCAL" / "blender-tmp"
    ).resolve()


def test_temporary_directory_is_none_without_a_sandbox(tmp_path):
    policy = _policy()

    assert policy.local_root_from_resources("") is None
    assert policy.temporary_directory("") is None


def test_vcs_adapter_enables_save_version_policy():
    policy = _policy()

    assert policy.vcs_is_enabled("svn") is True
    assert policy.vcs_is_enabled("git") is True
    assert policy.vcs_is_enabled("none") is False
    assert policy.vcs_is_enabled("") is False
    assert policy.UNDO_STEPS == 256
    assert policy.SAVE_VERSIONS == 0


def test_mismatched_preferences_ignores_unavailable_values():
    policy = _policy()

    saved = {
        "select_mouse": "RIGHT",
        "cycles_device_type": "OPTIX",
        "undo_steps": 256,
        "active_keyconfig": "Blender",
    }
    current = {
        "select_mouse": "LEFT",
        "cycles_device_type": None,
        "undo_steps": 256,
    }

    assert policy.mismatched_preferences(saved, current) == ["select_mouse"]
