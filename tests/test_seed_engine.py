"""Unit tests for the StudioSeedService."""

from src.infrastructure.seed_engine import StudioSeedService


class FakeConfigFactory:
    def __init__(self):
        self.saved = None

    def guardar_configuracion(self, payload, from_seed=False):
        self.saved = payload
        return True


def test_seed_roundtrip(tmp_path):
    config_factory = FakeConfigFactory()
    service = StudioSeedService(config_factory)

    payload = {
        "studio_profile": {"name": "Macuare Estudio"},
        "kitsu_production": {"api_url": "http://localhost:8080"},
    }

    ok, seed_path = service.export_seed(payload, tmp_path)
    assert ok is True
    assert seed_path.endswith("macuare_estudio.seed")

    assert service.import_seed(tmp_path / "macuare_estudio.seed") is True
    assert config_factory.saved == payload


def test_export_seed_default_name(tmp_path):
    service = StudioSeedService(FakeConfigFactory())
    ok, seed_path = service.export_seed({}, tmp_path)
    assert ok is True
    assert seed_path.endswith("openstudio.seed")


def test_import_seed_missing_file(tmp_path):
    service = StudioSeedService(FakeConfigFactory())
    assert service.import_seed(tmp_path / "missing.seed") is False
