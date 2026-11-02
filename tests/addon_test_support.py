"""Minimal ``bpy`` stubs so add-on modules can be exercised without Blender."""

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON_DIR = ROOT / "addons" / "openstudio_toolkit"


class FakeTimers:
    def __init__(self):
        self.callbacks = {}

    def register(self, function, first_interval=0.0, persistent=False):
        self.callbacks[function] = first_interval

    def unregister(self, function):
        self.callbacks.pop(function, None)

    def is_registered(self, function):
        return function in self.callbacks

    def run(self, function):
        self.callbacks.pop(function, None)
        return function()


class FakeOperator:
    def __init__(self):
        self.reports = []

    def report(self, level, message):
        self.reports.append((set(level), message))


class FakePanel:
    layout = None


class RecordingLayout:
    """Layout stub that records sections and the operators inside each one."""

    def __init__(self, collapsed=(), opened=()):
        self.collapsed = set(collapsed)
        self.opened = set(opened)
        self.sections = {}
        self.operators = []
        self.labels = []
        self.separators = 0

    def panel(self, idname, default_closed=False):
        is_open = idname in self.opened or (
            idname not in self.collapsed and not default_closed
        )
        body = RecordingLayout() if is_open else None
        self.sections[idname] = body
        return RecordingLayout(), body

    def label(self, text="", icon=""):
        self.labels.append(text)

    def operator(self, idname, text="", icon=""):
        self.operators.append(idname)

    def row(self):
        return RecordingLayout()

    def separator(self):
        self.separators += 1


def _build_bpy(tmp_path):
    bpy = types.ModuleType("bpy")
    bpy.types = types.SimpleNamespace(Operator=FakeOperator, Panel=FakePanel)
    bpy.props = types.SimpleNamespace(StringProperty=lambda **kwargs: None)
    config_dir = tmp_path / "config"
    bpy.utils = types.SimpleNamespace(
        user_resource=lambda kind: str(config_dir),
        register_class=lambda cls: None,
        unregister_class=lambda cls: None,
        resource_path=lambda kind: str(tmp_path),
    )
    timers = FakeTimers()
    bpy.app = types.SimpleNamespace(timers=timers, driver_namespace={})
    calls = {"read_userpref": 0, "save_userpref": 0}
    bpy.ops = types.SimpleNamespace(
        wm=types.SimpleNamespace(
            read_userpref=lambda *args, **kwargs: calls.__setitem__(
                "read_userpref", calls["read_userpref"] + 1
            ),
            save_userpref=lambda *args, **kwargs: calls.__setitem__(
                "save_userpref", calls["save_userpref"] + 1
            ),
        )
    )
    bpy.context = types.SimpleNamespace(
        preferences=types.SimpleNamespace(
            filepaths=types.SimpleNamespace(temporary_directory="", save_version=0),
            edit=types.SimpleNamespace(undo_steps=0),
            addons={},
        ),
        window_manager=types.SimpleNamespace(),
    )
    bpy.data = types.SimpleNamespace(filepath="")
    bpy.path = types.SimpleNamespace(basename=lambda path: Path(path).name)
    return bpy, calls, timers, config_dir


def _fake_bpy_extras():
    module = types.ModuleType("bpy_extras")
    io_utils = types.ModuleType("bpy_extras.io_utils")
    io_utils.ExportHelper = type("ExportHelper", (), {})
    io_utils.ImportHelper = type("ImportHelper", (), {})
    module.io_utils = io_utils
    return module, io_utils


def load_addon_module(monkeypatch, tmp_path, name):
    """Import ``addons/openstudio_toolkit/<name>.py`` with stubbed Blender modules."""
    bpy, calls, timers, config_dir = _build_bpy(tmp_path)
    monkeypatch.setitem(sys.modules, "bpy", bpy)

    bpy_extras, io_utils = _fake_bpy_extras()
    monkeypatch.setitem(sys.modules, "bpy_extras", bpy_extras)
    monkeypatch.setitem(sys.modules, "bpy_extras.io_utils", io_utils)

    package = types.ModuleType("openstudio_toolkit")
    package.__path__ = [str(ADDON_DIR)]
    monkeypatch.setitem(sys.modules, "openstudio_toolkit", package)

    policy_spec = importlib.util.spec_from_file_location(
        "openstudio_toolkit.preferences_policy", ADDON_DIR / "preferences_policy.py"
    )
    policy = importlib.util.module_from_spec(policy_spec)
    monkeypatch.setitem(sys.modules, policy_spec.name, policy)
    policy_spec.loader.exec_module(policy)

    spec = importlib.util.spec_from_file_location(
        f"openstudio_toolkit.{name}", ADDON_DIR / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module, bpy, calls, timers, config_dir
