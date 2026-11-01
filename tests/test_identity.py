"""Unit tests for the Identity bounded context."""

import os

from src.application.credential_vault import CredentialVault
from src.domain.identity.entities import User
from src.domain.identity.value_objects import Role, ViewProfile


def test_role_from_kitsu_mapping():
    assert Role.from_kitsu("admin", "") is Role.TD
    assert Role.from_kitsu("supervisor", "") is Role.SUPERVISOR
    assert Role.from_kitsu("manager", "") is Role.MANAGER
    assert Role.from_kitsu("vendor", "") is Role.VENDOR
    assert Role.from_kitsu("client", "") is Role.CLIENT
    assert Role.from_kitsu("user", "lead") is Role.LEAD
    assert Role.from_kitsu("user", "artist") is Role.ARTIST
    assert Role.from_kitsu("user", "") is Role.ARTIST
    # Unknown / missing role falls back to artist (preserves legacy behavior)
    assert Role.from_kitsu("", "") is Role.ARTIST
    assert Role.from_kitsu("admin", "").value == "td"


def test_user_from_kitsu_dict():
    user = User.from_kitsu_dict(
        {
            "id": "u-1",
            "email": "ada@studio.com",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "role": "admin",
            "position": "CTO",
        }
    )
    assert user.id == "u-1"
    assert user.email == "ada@studio.com"
    assert user.full_name == "Ada Lovelace"
    assert user.role is Role.TD
    assert user.position == "cto"


def test_user_from_kitsu_dict_empty():
    user = User.from_kitsu_dict(None)
    assert user.role is Role.ARTIST
    assert user.email == ""


def test_credential_vault_roundtrip_and_env():
    for key in ("OPENSTUDIO_KITSU_USER", "OPENSTUDIO_KITSU_PWD", "OPENSTUDIO_SVN_USER", "OPENSTUDIO_SVN_PASSWORD"):
        os.environ.pop(key, None)

    vault = CredentialVault()
    assert vault.has_server_credentials("vps") is False

    vault.save_kitsu_credentials("ada@studio.com", "kitsu-secret")
    assert vault.get_kitsu_credentials() == ("ada@studio.com", "kitsu-secret")
    assert os.environ["OPENSTUDIO_KITSU_USER"] == "ada@studio.com"
    assert os.environ["OPENSTUDIO_KITSU_PWD"] == "kitsu-secret"

    vault.save_server_credentials("vps", "artist", "svn-secret")
    assert vault.has_server_credentials("vps") is True
    assert vault.get_server_credentials("vps") == ("artist", "svn-secret")
    assert vault.is_server_enabled("vps") is True

    vault.set_server_enabled("vps", False)
    assert vault.is_server_enabled("vps") is False

    vault.save_server_credentials("vps", "artist", "svn-secret", enabled=True)
    assert vault.is_server_enabled("vps") is True

    assert vault.has_ssh_passphrase("vps") is False
    vault.save_ssh_passphrase("vps", "key-secret")
    assert vault.get_ssh_passphrase("vps") == "key-secret"

    vault.export_server_env("vps")
    assert os.environ["OPENSTUDIO_SVN_USER"] == "artist"
    assert os.environ["OPENSTUDIO_SVN_PASSWORD"] == "svn-secret"

    vault.clear()
    assert vault.get_kitsu_credentials() == (None, None)
    assert vault.get_server_credentials("vps") == (None, None)
    assert vault.has_server_credentials("vps") is False
    assert vault.is_server_enabled("vps") is False
    assert "OPENSTUDIO_KITSU_USER" not in os.environ
    assert "OPENSTUDIO_SVN_PASSWORD" not in os.environ


def test_incremental_hub_access_profiles():
    assert Role.TD.access_profiles() == (
        ViewProfile.TD,
        ViewProfile.PM,
        ViewProfile.ARTIST,
    )
    assert Role.MANAGER.access_profiles() == (ViewProfile.PM, ViewProfile.ARTIST)
    assert Role.ARTIST.access_profiles() == (ViewProfile.ARTIST,)
    assert Role.VENDOR.access_profiles() == (ViewProfile.ARTIST,)
    assert Role.LEAD.access_profiles() == (ViewProfile.ARTIST,)

    assert Role.SUPERVISOR.has_hub_access() is False
    assert Role.CLIENT.has_hub_access() is False
    assert Role.GUEST.has_hub_access() is False


def test_pm_lead_uses_the_artist_dashboard_as_editor():
    assert Role.MANAGER.default_profile("lead") is ViewProfile.ARTIST
    assert Role.MANAGER.default_profile("") is ViewProfile.PM
    assert Role.MANAGER.profile_label(ViewProfile.ARTIST, "lead") == "Editor"
    assert Role.MANAGER.profile_label(ViewProfile.ARTIST, "") == "Artist"
