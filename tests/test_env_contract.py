"""Unit tests for the SandboxEnvironment contract."""

from src.domain.shared_kernel.env_contract import EnvKey, SandboxEnvironment


def test_to_os_environ_maps_fields_and_drops_none():
    env = SandboxEnvironment(
        project_root="/x",
        kitsu_user="u",
        svn_password="s",
        user_role="artist",
        splash_path="",
    ).to_os_environ()

    assert env[EnvKey.PROJECT_ROOT] == "/x"
    assert env[EnvKey.KITSU_USER] == "u"
    assert env[EnvKey.SVN_PASSWORD] == "s"
    assert env[EnvKey.USER_ROLE] == "artist"
    # None fields are dropped, not serialized as "None".
    assert EnvKey.KITSU_PWD not in env
    # Empty string is preserved (matches legacy behavior).
    assert env[EnvKey.SPLASH_PATH] == ""


def test_roundtrip():
    env = SandboxEnvironment(
        project_root="/x",
        kitsu_pwd="p",
        blender_user_resources="/y",
    ).to_os_environ()
    restored = SandboxEnvironment.from_os_environ(env)
    assert restored.project_root == "/x"
    assert restored.kitsu_pwd == "p"
    assert restored.blender_user_resources == "/y"
    assert restored.kitsu_user is None


def test_full_launch_scenario_keys():
    env = SandboxEnvironment(
        project_root="/p",
        kitsu_host="http://h/api",
        kitsu_asset_type_id="at1",
        kitsu_entity_type="SHOT",
    ).to_os_environ()
    assert env[EnvKey.KITSU_HOST] == "http://h/api"
    assert env[EnvKey.KITSU_ASSET_TYPE_ID] == "at1"
    assert env[EnvKey.KITSU_ENTITY_TYPE] == "SHOT"
