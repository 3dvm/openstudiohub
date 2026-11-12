"""Unit tests for recursive render dependency auditing."""

from pathlib import Path
from types import SimpleNamespace

from src.application.services.render_service import RenderService


def test_recursive_dependency_audit_finds_external_hdri(tmp_path, monkeypatch):
    project = tmp_path / "project"
    production = project / "02_archivos_de_produccion"
    shots = production / "pro" / "shots" / "sq010"
    asset = production / "pro" / "assets" / "env"
    shots.mkdir(parents=True)
    asset.mkdir(parents=True)
    shot_blend = shots / "sh040.blend"
    linked_blend = shots / "sh060.blend"
    hdri = tmp_path / "external" / "studio.hdr"
    shot_blend.write_bytes(b"shot")
    linked_blend.write_bytes(b"linked")
    hdri.parent.mkdir()
    hdri.write_bytes(b"hdri")

    class FakeProbe:
        def probe(self, path):
            path = str(path)
            if path.endswith("sh040.blend"):
                return SimpleNamespace(
                    blend_paths=(str(linked_blend),),
                    libraries=(),
                    images=(),
                )
            if path.endswith("sh060.blend"):
                return SimpleNamespace(
                    blend_paths=(str(hdri),),
                    libraries=(),
                    images=(),
                )
            return SimpleNamespace(blend_paths=(), libraries=(), images=())

    monkeypatch.setattr(
        "src.application.services.render_service.BlenderProbe",
        lambda _blender: FakeProbe(),
    )
    monkeypatch.setattr(RenderService, "load_blueprint", lambda self, root: SimpleNamespace(
        topography=SimpleNamespace(
            vfs_svn="02_archivos_de_produccion",
            vfs_local="06_conf_LOCAL",
            vfs_pipeline="05_config_estudio",
        )
    ))
    monkeypatch.setattr(RenderService, "resolve_blender", lambda self, root, blueprint: "/bin/true")

    service = RenderService()
    dependencies = set()
    issues = set()
    service._walk_dependencies(
        shot_blend,
        project_root=project,
        production_root=production,
        local_root=project / "06_conf_LOCAL",
        pipeline_root=project / "05_config_estudio",
        probe=FakeProbe(),
        cache={},
        dependencies=dependencies,
        issues=issues,
        visited=set(),
    )

    assert "02_archivos_de_produccion/pro/shots/sq010/sh060.blend" in dependencies
    external = [issue for issue in issues if issue.status == "external"]
    assert external and external[0].path == str(hdri)
    assert external[0].owner.endswith("sh060.blend")


def test_linked_library_images_use_absolute_blend_paths(tmp_path):
    project = tmp_path / "project"
    production = project / "02_archivos_de_produccion"
    shot_dir = production / "pro" / "shots" / "sq010" / "sh040"
    texture = (
        production
        / "pro"
        / "assets"
        / "environment"
        / "muckup_plant"
        / "textures"
        / "autoshop_01_2k.exr"
    )
    shot_dir.mkdir(parents=True)
    texture.parent.mkdir(parents=True)
    shot_blend = shot_dir / "sh040.blend"
    shot_blend.write_bytes(b"shot")
    texture.write_bytes(b"tex")

    class FakeProbe:
        def probe(self, _path):
            return SimpleNamespace(
                blend_paths=(str(texture),),
                libraries=(),
                images=("//../muckup_plant/textures/autoshop_01_2k.exr",),
            )

    dependencies = set()
    issues = set()
    service = RenderService()
    service._walk_dependencies(
        shot_blend,
        project_root=project,
        production_root=production,
        local_root=project / "06_conf_LOCAL",
        pipeline_root=project / "05_config_estudio",
        probe=FakeProbe(),
        cache={},
        dependencies=dependencies,
        issues=issues,
        visited=set(),
    )

    assert (
        "02_archivos_de_produccion/pro/assets/environment/muckup_plant/"
        "textures/autoshop_01_2k.exr"
    ) in dependencies
    assert not [issue for issue in issues if issue.status == "missing"]


def test_blenderkit_export_leftovers_are_not_missing_dependencies(tmp_path):
    project = tmp_path / "project"
    production = project / "02_archivos_de_produccion"
    shot_dir = production / "pro" / "shots" / "sq010" / "sh040"
    shot_dir.mkdir(parents=True)
    shot_blend = shot_dir / "sh040.blend"
    shot_blend.write_bytes(b"shot")
    stale = (
        production
        / "pro"
        / "assets"
        / "prop"
        / "external-device"
        / "assets"
        / "materials"
        / "powder-coated"
        / "export_blenderkit.blend"
    )
    temp_stale = Path("/tmp/Local/Temp/tmpzntxzb7z/export_blenderkit.blend")

    class FakeProbe:
        def probe(self, _path):
            return SimpleNamespace(
                blend_paths=(str(stale), str(temp_stale)),
                libraries=(),
                images=(),
            )

    dependencies = set()
    issues = set()
    RenderService()._walk_dependencies(
        shot_blend,
        project_root=project,
        production_root=production,
        local_root=project / "06_conf_LOCAL",
        pipeline_root=project / "05_config_estudio",
        probe=FakeProbe(),
        cache={},
        dependencies=dependencies,
        issues=issues,
        visited=set(),
    )

    assert dependencies == set()
    assert issues == set()


def test_real_missing_library_is_still_reported(tmp_path):
    project = tmp_path / "project"
    production = project / "02_archivos_de_produccion"
    shot_dir = production / "pro" / "shots" / "sq010" / "sh040"
    shot_dir.mkdir(parents=True)
    shot_blend = shot_dir / "sh040.blend"
    shot_blend.write_bytes(b"shot")
    missing = production / "pro" / "assets" / "missing-library.blend"

    class FakeProbe:
        def probe(self, _path):
            return SimpleNamespace(
                blend_paths=(str(missing),),
                libraries=(),
                images=(),
            )

    issues = set()
    RenderService()._walk_dependencies(
        shot_blend,
        project_root=project,
        production_root=production,
        local_root=project / "06_conf_LOCAL",
        pipeline_root=project / "05_config_estudio",
        probe=FakeProbe(),
        cache={},
        dependencies=set(),
        issues=issues,
        visited=set(),
    )

    assert [issue.status for issue in issues] == ["missing"]
