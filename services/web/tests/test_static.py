from fastapi.testclient import TestClient

from services.web.app import create_app
from services.web.settings import Settings
from services.web.wiring import AppDeps


class _Auth:
    def has_token(self):
        return False


def _client(tmp_path):
    deps = AppDeps(agent=None, auth=_Auth(), settings=Settings(spotify_client_id="c"), trace_path=tmp_path / "t", claude_ok=True)
    return TestClient(create_app(deps))


def test_index_and_assets_are_served(tmp_path):
    client = _client(tmp_path)
    page = client.get("/")
    assert page.status_code == 200 and 'id="chat-log"' in page.text and 'lang="pt-BR"' in page.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_frontend_never_uses_innerhtml(tmp_path):
    # Títulos de música vêm de fora; tudo entra na página como texto (textContent), nunca como HTML.
    assert "innerHTML" not in _client(tmp_path).get("/static/app.js").text
