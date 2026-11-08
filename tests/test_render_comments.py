"""Unit tests for local shot and frame comments."""

from src.infrastructure.render.comments import RenderCommentStore


def test_shot_and_frame_comments_roundtrip(tmp_path):
    store = RenderCommentStore(tmp_path)

    store.add("Shot note", author="artist")
    data = store.add("Frame note", frame=160, author="artist")

    assert data["shot"][0]["text"] == "Shot note"
    assert data["frames"]["160"][0]["text"] == "Frame note"
    frame_id = data["frames"]["160"][0]["id"]

    data = store.set_resolved(frame_id, True)
    assert data["frames"]["160"][0]["resolved"] is True

    data = store.delete(frame_id)
    assert "160" not in data["frames"]
    assert store.read()["shot"][0]["text"] == "Shot note"
