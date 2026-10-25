"""gazu version-compatibility shims used by the Blender headless builder."""

from src.infrastructure import kitsu_manager
from src.infrastructure.kitsu_manager import KitsuManager


def test_get_task_type_by_name_falls_back_for_old_gazu(monkeypatch):
    received = []

    def fake(task_type_name, *args, **kwargs):
        if kwargs:
            raise TypeError("get_task_type_by_name() got an unexpected keyword argument 'for_entity'")
        received.append(task_type_name)
        return {"id": "tt1", "name": task_type_name}

    monkeypatch.setattr(kitsu_manager.gazu.task, "get_task_type_by_name", fake)

    result = KitsuManager().get_task_type_by_name("Modeling", for_entity="Asset")

    assert received == ["Modeling"]
    assert result == {"id": "tt1", "name": "Modeling"}


def test_get_task_by_entity_falls_back_to_name_lookup(monkeypatch):
    def fake_entity(entity, task_type, *args, **kwargs):
        if kwargs:
            raise TypeError("get_task_by_entity() got an unexpected keyword argument 'name'")
        return {"id": "old"}

    def fake_by_name(entity, task_type, name="main"):
        return {"id": "new", "name": name}

    monkeypatch.setattr(kitsu_manager.gazu.task, "get_task_by_entity", fake_entity)
    # ``get_task_by_name`` only exists in the older gazu bundled with Blender.
    monkeypatch.setattr(kitsu_manager.gazu.task, "get_task_by_name", fake_by_name, raising=False)

    result = KitsuManager().get_task_by_entity("asset-1", "tt1", name="main")

    assert result == {"id": "new", "name": "main"}
