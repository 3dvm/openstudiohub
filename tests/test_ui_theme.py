"""Consistency checks for the Qt theme and shared UI metrics."""

import re
from pathlib import Path
from types import SimpleNamespace

from src.interfaces.qt import ui_metrics
from src.interfaces.qt.components.sidebar import Sidebar
from src.interfaces.qt.components.top_bar import TopBar

ROOT = Path("src/interfaces/qt")
QSS = Path("macuare_theme.qss").read_text(encoding="utf-8")


class FakeConfig:
    def get_studio_name(self):
        return "Studio"


class FakeAuth:
    current_user = SimpleNamespace(first_name="Ada")

    def current_role(self):
        return SimpleNamespace(label="TD")

    def access_token(self):
        return ""

    host = ""


def _used_object_names():
    used = {}
    for path in ROOT.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        text = path.read_text(encoding="utf-8")
        for name in re.findall(r'setObjectName\(["\']([^"\']+)["\']\)', text):
            used.setdefault(name, set()).add(str(path))
    return used


def test_every_object_name_has_a_qss_selector():
    defined = {match for match in re.findall(r"#([A-Za-z][A-Za-z0-9_]*)", QSS)}
    missing = sorted(set(_used_object_names()) - defined)

    assert missing == [], f"Object names without QSS selectors: {missing}"


def test_semantic_selectors_exist():
    for selector in (
        "PageTitle",
        "PageDescription",
        "SectionTitle",
        "MutedLabel",
        "HintLabel",
        "CardFrame",
        "DataGrid",
        "DataList",
        "CodeView",
        "StandardComboBox",
        "NotificationPanel",
        "SidebarFooterInactive",
        "SidebarSeparator",
        "TopBar",
    ):
        assert f"#{selector}" in QSS


def test_shared_spacing_scale():
    assert ui_metrics.PAGE_MARGIN == 24
    assert ui_metrics.DIALOG_MARGIN == 24
    assert ui_metrics.CARD_MARGIN == 16
    assert ui_metrics.SECTION_SPACING == 16
    assert ui_metrics.CONTROL_SPACING == 10
    assert ui_metrics.GRID_SPACING == 16


def test_sidebar_footer_uses_compact_state(qapp):
    sidebar = Sidebar(None, FakeConfig())
    sidebar.add_footer_button("settings", "Settings", "", "settings.svg", lambda: None)

    assert sidebar.sidebar_buttons["settings"].objectName() == "SidebarFooterInactive"
    sidebar.set_active_button("settings")
    assert sidebar.sidebar_buttons["settings"].objectName() == "SidebarFooterActive"
    assert sidebar.separator.objectName() == "SidebarSeparator"
    sidebar.deleteLater()


def test_top_bar_uses_canonical_object_name(qapp):
    bar = TopBar(None, FakeAuth(), FakeConfig(), lambda: None)

    assert bar.objectName() == "TopBar"
    assert bar.btn_bell.objectName() == "TopBarBellButton"
    bar.deleteLater()


def test_vcs_dialogs_use_shared_data_widgets():
    for filename in (
        "views/vcs_publish_dialog.py",
        "views/vcs_history_dialog.py",
        "views/vcs_locks_dialog.py",
        "views/vcs_update_dialog.py",
        "widgets/vcs_audit_widget.py",
    ):
        text = (ROOT / filename).read_text(encoding="utf-8")
        assert 'setObjectName("DataList")' in text or 'setObjectName("DataGrid")' in text
        assert 'setObjectName("StatusLabel")' in text or 'setObjectName("MutedLabel")' in text


def test_top_bar_shows_and_switches_profiles(qapp):
    from src.domain.identity.value_objects import Role, ViewProfile

    selected = []

    class RoleAuth(FakeAuth):
        def current_role(self):
            return Role.TD

    bar = TopBar(
        None,
        RoleAuth(),
        FakeConfig(),
        lambda: None,
        profiles=[ViewProfile.TD, ViewProfile.PM, ViewProfile.ARTIST],
        active_profile="td",
        on_profile_selected=selected.append,
    )

    assert bar.btn_profile.objectName() == "TopBarProfileButton"
    assert bar.btn_profile.text() == "TD"

    menu = bar.btn_profile.menu()
    pm_action = next(action for action in menu.actions() if action.text() == "PM")
    pm_action.trigger()

    assert selected == ["pm"]
    bar.deleteLater()


def test_pm_lead_profile_is_labelled_editor(qapp):
    from types import SimpleNamespace

    from src.domain.identity.value_objects import Role, ViewProfile

    class LeadAuth(FakeAuth):
        current_user = SimpleNamespace(first_name="Ada", position="lead")

        def current_role(self):
            return Role.MANAGER

    bar = TopBar(
        None,
        LeadAuth(),
        FakeConfig(),
        lambda: None,
        profiles=[ViewProfile.PM, ViewProfile.ARTIST],
        active_profile="artist",
        on_profile_selected=lambda _profile: None,
    )

    assert bar.btn_profile.text() == "Editor"
    bar.deleteLater()


def test_checked_indicators_use_lucide_icons_and_assets_exist():
    checkbox_rule = QSS.split("QCheckBox::indicator:checked", 1)[1].split("}", 1)[0]
    radio_rule = QSS.split("QRadioButton::indicator:checked", 1)[1].split("}", 1)[0]
    assert "image: url(assets/icons/check-white.svg)" in checkbox_rule
    assert "image: url(assets/icons/radio-dot-white.svg)" in radio_rule
    assert re.search(r"QRadioButton::indicator \{\s*border-radius: 7px;", QSS)

    for asset in re.findall(r"url\(([^)]+)\)", QSS):
        path = Path(asset.strip().strip("'\""))
        assert path.is_file(), f"Missing QSS asset: {path}"
