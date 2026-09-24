"""Unit tests for the per-server Session Credentials tab."""

from src.interfaces.qt.settings_tabs.tab_credentials import TabCredentials


def test_set_servers_selects_and_reports_changes(qapp):
    tab = TabCredentials()
    servers = [
        {"id": "local", "name": "Local", "is_default": True},
        {"id": "vps", "name": "VPS"},
    ]
    tab.set_servers(servers, "vps")

    assert tab.current_server_id() == "vps"
    assert tab.combo_server.itemText(0) == "Local  (default)"

    seen = []
    tab.server_changed.connect(seen.append)
    tab.combo_server.setCurrentIndex(0)

    assert tab.current_server_id() == "local"
    assert seen == ["local"]


def test_credentials_payload_includes_server(qapp):
    tab = TabCredentials()
    tab.set_servers([{"id": "vps", "name": "VPS"}], "vps")

    tab.entry_vcs_user.setText("artist")
    tab.entry_vcs_pwd.setText("secret")
    tab.chk_vcs_enabled.setChecked(True)
    tab.entry_ssh_pass.setText("key-pass")

    payload = tab.credentials_payload()
    assert payload["server_id"] == "vps"
    assert payload["username"] == "artist"
    assert payload["password"] == "secret"
    assert payload["enabled"] is True
    assert payload["ssh_passphrase"] == "key-pass"


def test_load_data_resets_password(qapp):
    tab = TabCredentials()
    tab.entry_vcs_user.setText("old")
    tab.entry_vcs_pwd.setText("old-pass")

    tab.load_data("new-user", True, ssh_passphrase_present=True)

    assert tab.entry_vcs_user.text() == "new-user"
    assert tab.entry_vcs_pwd.text() == ""
    assert tab.chk_vcs_enabled.isChecked() is True
