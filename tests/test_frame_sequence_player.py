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
    assert player.chk_approve.isChecked() is False
    player._show_index(1)
    assert player.current_frame() == 102
    assert player.chk_approve.isChecked() is True
    player.chk_approve.setChecked(False)
    assert approvals == [([102], False)]
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
