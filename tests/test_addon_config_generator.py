"""Unit tests for the add-on startup config generator."""

import py_compile

from src.application.services.addon_config_generator import AddonConfigGenerator
from src.domain.shared_kernel.addon_contract import AddonConfiguration
from src.domain.workspace.topography import WorkspaceTopography


def _topography(local: str = "local") -> WorkspaceTopography:
    return WorkspaceTopography(vfs_local=local)


def test_generate_writes_one_script_per_enabled_addon(tmp_path):
    generator = AddonConfigGenerator()
    generated = generator.generate(
        tmp_path,
        {
            "blender_kitsu": AddonConfiguration(
                name="blender_kitsu",
                settings={"shot_dir_name": "shots"},
                behaviors=["activate", "configure"],
            ),
            "openstudio_toolkit": AddonConfiguration(name="openstudio_toolkit"),
        },
        _topography(),
    )

    names = {path.name for path in generated}
    assert names == {"cfg_blender_kitsu.py", "cfg_openstudio_toolkit.py"}

    config_dir = tmp_path / "local" / "blender_data" / "scripts" / "openstudio"
    assert config_dir.is_dir()
    # Must stay out of Blender's auto-registered `startup/` folder.
    assert not (tmp_path / "local" / "blender_data" / "scripts" / "startup").exists()

    # DCC-side support modules are shipped next to bootstrap.py.
    local_dir = tmp_path / "local"
    assert (local_dir / "env_contract.py").exists()
    assert (local_dir / "addon_runtime.py").exists()

    kitsu_script = (config_dir / "cfg_blender_kitsu.py").read_text(encoding="utf-8")
    assert "__ADDON_CONFIG_JSON__" not in kitsu_script
    assert "'shot_dir_name': 'shots'" in kitsu_script
    assert "'activate'" in kitsu_script


def test_blender_kitsu_preserves_project_root_path_property(tmp_path):
    generator = AddonConfigGenerator()
    topography = _topography()
    generator.generate(
        tmp_path,
        {"blender_kitsu": AddonConfiguration(name="blender_kitsu")},
        topography,
    )
    script = (generator.config_dir(tmp_path, topography) / "cfg_blender_kitsu.py").read_text(
        encoding="utf-8"
    )
    assert "project_root_path = property(" in script
    assert "project_root_path = custom_project_root_path" not in script


def test_generated_scripts_are_valid_python(tmp_path):
    generator = AddonConfigGenerator()
    generated = generator.generate(
        tmp_path,
        {"blender_kitsu": AddonConfiguration(name="blender_kitsu")},
        _topography(),
    )
    for script in generated:
        py_compile.compile(str(script), doraise=True)


def test_disabled_addon_is_not_generated_and_removed(tmp_path):
    generator = AddonConfigGenerator()
    topography = _topography()
    generator.generate(
        tmp_path,
        {"blender_kitsu": AddonConfiguration(name="blender_kitsu")},
        topography,
    )
    script = generator.config_dir(tmp_path, topography) / "cfg_blender_kitsu.py"
    assert script.exists()

    generated = generator.generate(
        tmp_path,
        {"blender_kitsu": AddonConfiguration(name="blender_kitsu", enabled=False)},
        topography,
    )
    assert generated == []
    assert not script.exists()


def test_addon_without_template_is_skipped(tmp_path):
    generator = AddonConfigGenerator()
    generated = generator.generate(
        tmp_path,
        {"unknown_addon": AddonConfiguration(name="unknown_addon")},
        _topography(),
    )
    assert generated == []


def test_display_name_resolves_to_slugged_template(tmp_path):
    generator = AddonConfigGenerator()
    generated = generator.generate(
        tmp_path,
        {"Blender Kitsu": AddonConfiguration(name="Blender Kitsu")},
        _topography(),
    )
    assert [path.name for path in generated] == ["cfg_blender_kitsu.py"]


def test_config_dir_uses_topography_local_folder(tmp_path):
    topography = _topography("studio-local")
    assert AddonConfigGenerator.config_dir(tmp_path, topography) == (
        tmp_path / "studio-local" / "blender_data" / "scripts" / "openstudio"
    )


def test_legacy_startup_scripts_are_removed(tmp_path):
    generator = AddonConfigGenerator()
    topography = _topography()
    legacy_startup = AddonConfigGenerator.legacy_startup_dir(tmp_path, topography)
    legacy_startup.mkdir(parents=True)
    legacy_script = legacy_startup / "cfg_blender_kitsu.py"
    legacy_script.write_text("raise RuntimeError('should be removed')\n", encoding="utf-8")
    legacy_cache = legacy_startup / "__pycache__"
    legacy_cache.mkdir()
    legacy_bytecode = legacy_cache / "cfg_blender_kitsu.cpython-313.pyc"
    legacy_bytecode.write_bytes(b"stale")

    generator.generate(
        tmp_path,
        {"blender_kitsu": AddonConfiguration(name="blender_kitsu")},
        topography,
    )

    assert not legacy_script.exists()
    assert not legacy_bytecode.exists()
    assert (generator.config_dir(tmp_path, topography) / "cfg_blender_kitsu.py").exists()
