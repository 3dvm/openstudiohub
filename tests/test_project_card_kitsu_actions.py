# =====================================================================================
# OPENSTUDIOHUB
# Module: tests/test_project_card_kitsu_actions.py
# =====================================================================================

"""Verifies the TD project card exposes the Kitsu export/configure actions."""

from src.interfaces.qt.components.project_card import ProjectCard


def _card(on_export, on_configure=None, on_publish=None, on_reset=None):
    noop = lambda *args, **kwargs: None
    return ProjectCard(
        parent=None,
        project_data={"id": "p1", "name": "Neon"},
        user_role="td",
        status=None,
        token="",
        host="",
        thumbnail_fetcher=lambda *args: None,
        on_install=noop,
        on_launch=noop,
        on_delete=noop,
        on_open_kitsu=noop,
        on_watchtower=noop,
        on_open_wizard=noop,
        on_repair=noop,
        on_migrate=noop,
        on_export=on_export,
        on_publish=on_publish,
        on_reset=on_reset,
        on_configure=on_configure,
    )


def test_td_card_has_export_action_and_forwards(qapp):
    captured = {}
    card = _card(lambda name, pid: captured.update(name=name, pid=pid))

    actions = [a.text() for a in card.options_menu.actions()]
    assert any("Export Kitsu Project" in text for text in actions)

    export_action = next(a for a in card.options_menu.actions() if "Export Kitsu Project" in a.text())
    export_action.trigger()
    assert captured == {"name": "Neon", "pid": "p1"}


def test_td_card_publish_action_forwards(qapp):
    captured = {}
    card = _card(
        lambda *args: None,
        on_publish=lambda name, pid: captured.update(name=name, pid=pid),
    )

    publish_action = next(a for a in card.options_menu.actions() if "Publish Files to VCS" in a.text())
    publish_action.trigger()
    assert captured == {"name": "Neon", "pid": "p1"}


def test_td_card_reset_working_copy_action_forwards(qapp):
    captured = {}
    card = _card(
        lambda *args: None,
        on_reset=lambda name, pid: captured.update(name=name, pid=pid),
    )

    reset_action = next(
        a for a in card.options_menu.actions() if "Reset VCS Working Copy" in a.text()
    )
    reset_action.trigger()
    assert captured == {"name": "Neon", "pid": "p1"}


def test_td_card_configure_action_forwards(qapp):
    captured = {}
    card = _card(
        lambda *args: None,
        on_configure=lambda name, pid, pdir: captured.update(name=name, pid=pid, pdir=pdir),
    )

    configure_action = next(a for a in card.options_menu.actions() if "Configure Project" in a.text())
    assert configure_action.isEnabled()
    configure_action.trigger()
    assert captured == {"name": "Neon", "pid": "p1", "pdir": None}


def test_td_card_kitsu_menu_exposes_production_settings(qapp):
    card = _card(lambda *args: None, on_configure=lambda *args: None)

    texts = [a.text() for a in card.btn_kitsu_dropdown.menu().actions()]
    assert any("Production Settings" in text for text in texts)
