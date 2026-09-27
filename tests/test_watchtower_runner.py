"""Unit tests for the watchtower_pipeline compatibility shim."""

from src.infrastructure.watchtower_runner import safe_get_env_data_as_dict


def test_password_with_equals_is_preserved(tmp_path):
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "KITSU_DATA_SOURCE_URL=http://host/api\n"
        "KITSU_DATA_SOURCE_USER_EMAIL=artist@studio.com\n"
        "KITSU_DATA_SOURCE_USER_PASSWORD=YapiCv8BsSZi6B3uXM3Sg4bAtqPZ8LMuQfVg1fF=0YyA==\n",
        encoding="utf-8",
    )

    env_vars = safe_get_env_data_as_dict(str(env_file))

    assert env_vars == {
        "KITSU_DATA_SOURCE_URL": "http://host/api",
        "KITSU_DATA_SOURCE_USER_EMAIL": "artist@studio.com",
        "KITSU_DATA_SOURCE_USER_PASSWORD": "YapiCv8BsSZi6B3uXM3Sg4bAtqPZ8LMuQfVg1fF=0YyA==",
    }


def test_blank_and_comment_lines_are_ignored(tmp_path):
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "# Kitsu credentials\n"
        "\n"
        "KITSU_DATA_SOURCE_URL=http://host/api\n"
        "   \n"
        "KITSU_DATA_SOURCE_USER_EMAIL=artist@studio.com\n"
        "KITSU_DATA_SOURCE_USER_PASSWORD=s3cr3t\n",
        encoding="utf-8",
    )

    env_vars = safe_get_env_data_as_dict(str(env_file))

    assert env_vars["KITSU_DATA_SOURCE_USER_PASSWORD"] == "s3cr3t"
    assert len(env_vars) == 3
