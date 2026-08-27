"""Unit tests for the Workspace bounded context."""

from src.domain.workspace.blueprint import ProjectBlueprint
from src.domain.workspace.topography import WorkspaceTopography


def test_topography_from_dict_defaults():
    topo = WorkspaceTopography.from_dict({})
    assert topo.vfs_svn == "svn"
    assert topo.vfs_shared == "shared"
    assert topo.vfs_local == "local"
    assert topo.vfs_pipeline == "pipeline"
    assert topo.custom_dirs == ()


def test_topography_from_dict():
    topo = WorkspaceTopography.from_dict({"vfs_svn": "prod", "custom_dirs": ["briefs", "renders"]})
    assert topo.vfs_svn == "prod"
    assert topo.custom_dirs == ("briefs", "renders")


def test_base_folders():
    topo = WorkspaceTopography(custom_dirs=("briefs",))
    folders = topo.base_folders()
    assert "svn/pro" in folders
    assert "svn/tools" in folders
    assert "svn/pro/assets" in folders
    assert "briefs" in folders


def test_project_blueprint_roundtrip():
    bp = ProjectBlueprint(
        project_name="Neon",
        kitsu_project_id="p1",
        blender_version="5.1.2",
        template="standard",
        dependencies={"addons": {"blender_kitsu": "1.5.0"}},
        topography=WorkspaceTopography(vfs_svn="prod"),
    )
    data = bp.to_dict()
    assert data["project_name"] == "Neon"
    assert data["topography_signature"]["vfs_svn"] == "prod"

    restored = ProjectBlueprint.from_dict(data)
    assert restored.blender_version == "5.1.2"
    assert restored.topography.vfs_svn == "prod"
    assert restored.dependencies["addons"]["blender_kitsu"] == "1.5.0"
