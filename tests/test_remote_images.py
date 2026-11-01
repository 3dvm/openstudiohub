"""Helpers for Kitsu shell thumbnails."""

from src.interfaces.qt.components.remote_images import thumbnail_url


def test_thumbnail_url_builds_kitsu_picture_route():
    assert (
        thumbnail_url("https://kitsu.example/api", "persons", "p1")
        == "https://kitsu.example/api/pictures/thumbnails/persons/p1.png"
    )
    assert (
        thumbnail_url("https://kitsu.example/api/", "organisations", "o1")
        == "https://kitsu.example/api/pictures/thumbnails/organisations/o1.png"
    )


def test_thumbnail_url_requires_all_parts():
    assert thumbnail_url("", "persons", "p1") == ""
    assert thumbnail_url("https://kitsu.example/api", "", "p1") == ""
    assert thumbnail_url("https://kitsu.example/api", "persons", "") == ""
