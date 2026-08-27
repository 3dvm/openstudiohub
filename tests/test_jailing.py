"""Unit tests for the JailingPolicy domain service."""

from src.domain.workspace.jailing import JailingPolicy


def test_resolve_dependency_relative():
    result = JailingPolicy.resolve_dependency("pro/shots/sq01/sh010", "//assets/char.blend")
    assert result == "pro/shots/sq01/sh010/assets/char.blend"


def test_resolve_dependency_ignores_non_relative():
    assert JailingPolicy.resolve_dependency("pro/shots/sq01/sh010", "assets/char.blend") is None
    assert JailingPolicy.resolve_dependency("pro/shots/sq01/sh010", "") is None


def test_resolve_dependency_collapses_parent():
    result = JailingPolicy.resolve_dependency("pro/shots/sq01", "//../assets/char.blend")
    assert result == "pro/shots/assets/char.blend"


def test_expand_with_meta_for_blend():
    assert JailingPolicy.expand_with_meta("a/b/char.blend") == ["a/b/char.blend", "a/b/char-meta.json"]


def test_expand_with_meta_non_blend():
    assert JailingPolicy.expand_with_meta("a/b/tex.png") == ["a/b/tex.png"]
