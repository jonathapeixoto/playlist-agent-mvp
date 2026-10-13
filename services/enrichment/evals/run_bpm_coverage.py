"""Eval de cobertura de BPM contra Spotify + ReccoBeats reais, nas playlists do próprio usuário.

Mede a cobertura sem e com a busca por versões alternativas, usando um cache temporário
(o cache do app não é tocado). Precisa do login feito pelo app (data/token.json). Não grava nada no Spotify.

Uso: uv run python -m services.enrichment.evals.run_bpm_coverage [nome da playlist ...]
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

import httpx

from contracts.errors import AuthRequired, ExternalServiceError
from services.enrichment.alternates import AlternateFinder
from services.enrichment.cache import EnrichmentCache
from services.enrichment.enricher import Enricher
from services.enrichment.reccobeats import ReccoBeatsClient
from services.spotify.auth import SpotifyAuth, TokenStore
from services.spotify.client import SpotifyClient
from services.web.settings import Settings

THRESHOLD = 0.85
MAX_PLAYLISTS = 5


class _NoGenres:
    def start_batch(self) -> None:
        return None

    def genres_for(self, artist: object) -> list[str]:
        return []


def _coverage(enricher: Enricher, tracks: list) -> tuple[float, float]:
    """(cobertura de BPM, segundos gastos)."""
    start = time.monotonic()
    enriched = enricher.enrich(tracks)
    elapsed = time.monotonic() - start
    return (sum(1 for e in enriched if e.tempo) / len(enriched) if enriched else 0.0), elapsed


def main(argv: list[str]) -> int:
    settings = Settings.from_env()
    http = httpx.Client(timeout=20)
    auth = SpotifyAuth(settings.spotify_client_id, settings.redirect_uri, TokenStore(settings.data_dir / "token.json"), http)
    spotify = SpotifyClient(auth, http)
    recco = ReccoBeatsClient(http)
    try:
        playlists = spotify.my_playlists()
    except AuthRequired:
        print("Faça login pelo app (`uv run playlist-agent`) antes de rodar este eval.")
        return 2
    except ExternalServiceError as err:
        print(f"Spotify indisponível: {err}")
        return 2
    if argv:
        wanted = {name.lower() for name in argv}
        playlists = [p for p in playlists if p.name.lower() in wanted]
    playlists = playlists[:MAX_PLAYLISTS]
    rows = []
    # SQLite segura o arquivo aberto no Windows; a limpeza da pasta temporária é best effort.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        for playlist in playlists:
            tracks = spotify.playlist_tracks(playlist.id)
            if not tracks:
                continue
            plain = Enricher(recco, _NoGenres(), EnrichmentCache(Path(tmp) / f"plain-{playlist.id}.sqlite"))
            with_alts = Enricher(
                recco, _NoGenres(), EnrichmentCache(Path(tmp) / f"alts-{playlist.id}.sqlite"),
                AlternateFinder(spotify.search_tracks),
            )
            cov_plain, secs_plain = _coverage(plain, tracks)
            cov_alts, secs_alts = _coverage(with_alts, tracks)
            rows.append({
                "playlist": playlist.name, "tracks": len(tracks),
                "coverage_plain": round(cov_plain, 3), "coverage_with_alternates": round(cov_alts, 3),
                "seconds_plain": round(secs_plain, 1), "seconds_with_alternates": round(secs_alts, 1),
            })
    if not rows:
        print("Nenhuma playlist com faixas encontrada.")
        return 2
    total = sum(r["tracks"] for r in rows)
    before = sum(r["coverage_plain"] * r["tracks"] for r in rows) / total
    after = sum(r["coverage_with_alternates"] * r["tracks"] for r in rows) / total
    for r in rows:
        print(f"{r['playlist'][:35]:<35} {r['tracks']:>4} faixas  {r['coverage_plain']:.0%} -> "
              f"{r['coverage_with_alternates']:.0%}  ({r['seconds_plain']}s -> {r['seconds_with_alternates']}s)")
    print(f"\nCobertura de BPM: {before:.0%} -> {after:.0%} com versões alternativas (limiar {THRESHOLD:.0%})")
    out = Path("data/evals") / f"bpm-coverage-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    report = {"before": before, "after": after, "threshold": THRESHOLD, "rows": rows}
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Relatório: {out}")
    # Passa só se a cobertura final atinge o limiar E as alternativas ajudaram de fato
    # (a não ser que já estivesse em 100%, quando não há o que recuperar).
    improved = after > before or before >= 1.0
    if not improved:
        print("FALHA: a busca por versões alternativas não recuperou nenhuma faixa.")
    return 0 if after >= THRESHOLD and improved else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
