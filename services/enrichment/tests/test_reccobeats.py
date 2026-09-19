import httpx
import respx

from services.enrichment.reccobeats import ReccoBeatsClient

HOST = "api.reccobeats.com"


def _item(sid, tempo):
    return {"id": "uuid", "href": f"https://open.spotify.com/track/{sid}", "tempo": tempo, "energy": 0.8}


@respx.mock
def test_parses_spotify_id_from_href_and_skips_unknown():
    respx.get(host=HOST, path="/v1/audio-features").mock(
        return_value=httpx.Response(200, json={"content": [_item("a", 128.4)]})
    )
    result = ReccoBeatsClient(httpx.Client()).audio_features(["a", "b"])
    assert result.found["a"].tempo == 128.4
    assert "b" not in result.found
    assert result.failed == []


@respx.mock
def test_chunks_ids_by_40():
    route = respx.get(host=HOST, path="/v1/audio-features").mock(return_value=httpx.Response(200, json={"content": []}))
    ReccoBeatsClient(httpx.Client()).audio_features([f"id{i}" for i in range(41)])
    sizes = [len(c.request.url.params["ids"].split(",")) for c in route.calls]
    assert sizes == [40, 1]


@respx.mock
def test_retries_429_then_marks_chunk_failed_on_persistent_error():
    sleeps = []
    respx.get(host=HOST, path="/v1/audio-features").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(200, json={"content": [_item("a", 100)]}),
        httpx.Response(500), httpx.Response(500), httpx.Response(500), httpx.Response(500),
    ])
    client = ReccoBeatsClient(httpx.Client(), sleep=sleeps.append)
    ids = [f"x{i}" for i in range(39)] + ["a", "late"]
    result = client.audio_features(ids)
    assert result.found["a"].tempo == 100
    assert result.failed == ["late"]
    assert sleeps[0] == 1.0


@respx.mock
def test_network_error_marks_chunk_failed():
    respx.get(host=HOST, path="/v1/audio-features").mock(side_effect=httpx.ConnectError("offline"))
    result = ReccoBeatsClient(httpx.Client(), sleep=lambda s: None).audio_features(["a"])
    assert result.failed == ["a"]
