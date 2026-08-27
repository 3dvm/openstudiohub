"""Unit tests for the QA / Gatekeeper domain rules."""

from src.domain.qa.rules import (
    asset_name_from_filename,
    is_dirty_transform,
    is_forbidden_name,
    is_out_of_bounds,
    is_valid_object_name,
)


def test_is_dirty_transform():
    assert is_dirty_transform((0, 0, 0), (0, 0, 0), (1, 1, 1)) is False
    assert is_dirty_transform((1, 0, 0), (0, 0, 0), (1, 1, 1)) is True
    assert is_dirty_transform((0, 0, 0), (0, 0, 0.5), (1, 1, 1)) is True
    assert is_dirty_transform((0, 0, 0), (0, 0, 0), (2, 1, 1)) is True


def test_asset_name_from_filename():
    assert asset_name_from_filename("/x/prota-model.blend") == "prota"
    assert asset_name_from_filename("hero-rig.blend") == "hero"
    assert asset_name_from_filename("no_dash.blend") == "Asset"
    assert asset_name_from_filename("") == "Asset"


def test_is_forbidden_name():
    assert is_forbidden_name("Cube") is True
    assert is_forbidden_name("Cube.001") is True
    assert is_forbidden_name("prota-model") is False


def test_is_valid_object_name():
    assert is_valid_object_name("prota-model", "prota") is True
    assert is_valid_object_name("Cube", "prota") is False
    assert is_valid_object_name("other-model", "prota") is False


def test_is_out_of_bounds():
    assert is_out_of_bounds("/other/tex.png", "/proj") is True
    assert is_out_of_bounds("/proj/shots/tex.png", "/proj") is False
