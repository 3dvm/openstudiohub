"""Unit tests for the lightweight frame sequence player."""

from PySide6.QtGui import QPixmap

from src.interfaces.qt.components.frame_sequence_player import FrameSequencePlayer


def _frame(path, color):
    pixmap = QPixmap(8, 8)
    pixmap.fill(color)
    pixmap.save(str(path), "PNG")
    return path


def test_player_tracks_the_current_frame_and_approval(qapp, tmp_path):
    first = _frame(tmp_path / "frame_0101.png", "red")
    second = _frame(tmp_path / "frame_0102.png", "blue")
    player = FrameSequencePlayer()
    approvals = []
    player.approve_frames_requested.connect(
        lambda frames, checked: approvals.append((frames, checked))
    )

    player.set_sequence([(101, first), (102, second)], fps=24, approved={102}, autoplay=False)

    assert player.current_frame() == 101
    player._show_index(1)
    assert player.current_frame() == 102
    player.btn_unapprove_selection.click()
    player._show_index(0)
    player.btn_approve_selection.click()
    assert approvals == [([102], False), ([101], True)]
    player.deleteLater()


def test_delete_removes_the_frame_from_the_timeline(qapp, tmp_path):
    first = _frame(tmp_path / "frame_0101.png", "red")
    second = _frame(tmp_path / "frame_0102.png", "blue")
    player = FrameSequencePlayer()
    requested = []
    player.delete_frames_requested.connect(requested.append)
    player.set_sequence([(101, first), (102, second)], fps=24, autoplay=False)

    player.btn_delete.click()
    player.remove_frame(101)

    assert requested == [[101]]
    assert [entry[0] for entry in player._entries] == [102]
    assert player.current_frame() == 102
    player.deleteLater()


def test_empty_sequence_disables_controls(qapp):
    player = FrameSequencePlayer()

    player.set_sequence([], fps=24, autoplay=False)

    assert player.current_frame() is None
    assert player.btn_play.isEnabled() is False
    player.deleteLater()


def test_range_selection_emits_all_frames(qapp, tmp_path):
    frames = [(101 + index, _frame(tmp_path / f"frame_{101 + index:04d}.png", "red")) for index in range(4)]
    player = FrameSequencePlayer()
    requested = []
    player.delete_frames_requested.connect(requested.append)
    player.set_sequence(frames, fps=24, autoplay=False)

    player._show_index(0)
    player.btn_in.click()
    player._show_index(2)
    player.btn_out.click()
    player.btn_delete.click()

    assert requested == [[101, 102, 103]]
    player.deleteLater()


def test_step_and_loop_controls(qapp, tmp_path):
    frames = [(101 + index, _frame(tmp_path / f"frame_{101 + index:04d}.png", "red")) for index in range(3)]
    player = FrameSequencePlayer()
    player.set_sequence(frames, fps=24, autoplay=False)

    player.btn_step_forward.click()
    assert player.current_frame() == 102
    player.btn_step_back.click()
    assert player.current_frame() == 101
    player.btn_loop.setChecked(False)
    player._show_index(2)
    player._advance()
    assert player.current_frame() == 103
    assert player.is_playing() is False
    player.deleteLater()


def test_missing_frame_uses_missing_icon_and_disables_actions(qapp, tmp_path):
    existing = _frame(tmp_path / "frame_0101.png", "red")
    player = FrameSequencePlayer()
    player.set_sequence([(101, existing), (102, None)], fps=24, autoplay=False)

    player._show_index(1)

    assert player.current_frame() == 102
    assert player.current_path() is None
    assert player.btn_approve_selection.isEnabled() is False
    assert player.btn_delete.isEnabled() is False
    player.deleteLater()


def test_fullscreen_roundtrip_keeps_the_sequence(qapp, tmp_path):
    frame = _frame(tmp_path / "frame_0101.png", "red")
    player = FrameSequencePlayer()
    player.set_sequence([(101, frame)], fps=24, autoplay=False)

    player.toggle_fullscreen()
    assert player._fullscreen_dialog is not None
    player.exit_fullscreen()

    assert player._fullscreen_dialog is None
    assert player.current_frame() == 101
    player.deleteLater()


def test_status_badge_reflects_the_current_frame(qapp, tmp_path):
    frame = _frame(tmp_path / "frame_0101.png", "red")
    missing = tmp_path / "frame_0102.png"
    player = FrameSequencePlayer()
    player.set_sequence([(101, frame), (102, missing)], fps=24, approved={101}, autoplay=False)

    assert "Approved" in player.lbl_badge.text()
    player._show_index(1)
    assert "Missing" in player.lbl_badge.text()
    player.deleteLater()
