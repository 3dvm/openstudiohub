"""Unit tests for the Identity bounded context."""

import os

from src.application.credential_vault import CredentialVault
from src.domain.identity.entities import User
from src.domain.identity.value_objects import Role


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
    assert vault.has_svn_credentials() is False

    vault.save_kitsu_credentials("ada@studio.com", "kitsu-secret")
    assert vault.get_kitsu_credentials() == ("ada@studio.com", "kitsu-secret")
    assert os.environ["OPENSTUDIO_KITSU_USER"] == "ada@studio.com"
    assert os.environ["OPENSTUDIO_KITSU_PWD"] == "kitsu-secret"

    vault.save_svn_credentials("artist", "svn-secret")
    assert vault.has_svn_credentials() is True
    assert vault.get_svn_credentials() == ("artist", "svn-secret")
    assert os.environ["OPENSTUDIO_SVN_USER"] == "artist"

    vault.clear()
    assert vault.get_kitsu_credentials() == (None, None)
    assert vault.get_svn_credentials() == (None, None)
    assert vault.has_svn_credentials() is False
    assert "OPENSTUDIO_KITSU_USER" not in os.environ
    assert "OPENSTUDIO_SVN_PASSWORD" not in os.environ
