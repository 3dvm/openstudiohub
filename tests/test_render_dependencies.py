"""Unit tests for recursive render dependency auditing."""

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
