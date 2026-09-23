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


def test_page_has_the_engine_panel(tmp_path):
    page = _client(tmp_path).get("/").text
    assert 'id="engine"' in page and 'id="llm-panel"' in page
    assert 'id="llm-preset"' in page and 'id="llm-model"' in page and 'id="llm-key"' in page
    assert 'type="password"' in page


def test_frontend_talks_to_the_engine_routes(tmp_path):
    script = _client(tmp_path).get("/static/app.js").text
    assert '"/api/llm"' in script and '"/api/llm/test"' in script
    assert "innerHTML" not in script


def test_hidden_panel_rows_are_really_hidden(tmp_path):
    # display: grid nos labels venceria o [hidden] do navegador sem esta regra.
    css = _client(tmp_path).get("/static/style.css").text
    assert "label[hidden]" in css and "display: none" in css.split("label[hidden]")[1][:60]
