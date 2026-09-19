from pathlib import Path

import pytest

from services.web.settings import Settings


def test_missing_client_id_exits_with_instructions():
    with pytest.raises(SystemExit, match="SPOTIFY_CLIENT_ID"):
        Settings.from_env({})


def test_reads_env_and_treats_blank_lastfm_as_none():
    settings = Settings.from_env({"SPOTIFY_CLIENT_ID": " abc ", "LASTFM_API_KEY": ""})
    assert settings.spotify_client_id == "abc"
    assert settings.lastfm_api_key is None
    assert settings.redirect_uri == "http://127.0.0.1:8000/callback"
    assert settings.data_dir == Path("data")
