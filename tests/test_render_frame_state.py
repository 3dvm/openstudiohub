"""Unit tests for the per-shot frame approval sidecar."""

from src.infrastructure.render.frame_state import RenderFrameStateStore


def test_approve_and_unapprove_roundtrip(tmp_path):
    store = RenderFrameStateStore(tmp_path)

    store.approve(101, user="artist")
    assert store.approved_frames() == {101}
    assert store.is_approved(101) is True

    store.unapprove(101)
    assert store.approved_frames() == set()
    assert store.is_approved(101) is False


def test_malformed_state_is_ignored(tmp_path):
    (tmp_path / ".frame_state.json").write_text("{not json", encoding="utf-8")
    store = RenderFrameStateStore(tmp_path)

    assert store.approved_frames() == set()
