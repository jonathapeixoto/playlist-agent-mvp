"""Junta BPM e gênero em EnrichedTrack. Falha de fonte externa vira 'sem dado', nunca derruba o fluxo."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from contracts.errors import AuthRequired, ExternalServiceError
from contracts.models import EnrichedTrack, Track
from services.enrichment.alternates import AlternateFinder
from services.enrichment.cache import AudioFeatures, EnrichmentCache
from services.enrichment.genres import GenreResolver
from services.enrichment.reccobeats import ReccoBeatsClient

# Cada faixa sem BPM custa uma busca no Spotify. Acima disso, o resto fica sem cache e tenta de novo depois.
MAX_ALTERNATE_LOOKUPS = 100
# Buscas simultâneas no Spotify: corta a espera sem provocar rate limit.
ALTERNATE_WORKERS = 4


class Enricher:
    def __init__(
        self,
        recco: ReccoBeatsClient,
        genres: GenreResolver,
        cache: EnrichmentCache,
        alternates: AlternateFinder | None = None,
    ) -> None:
        self.recco = recco
        self.genres = genres
        self.cache = cache
        self.alternates = alternates

    def enrich(self, tracks: list[Track]) -> list[EnrichedTrack]:
        self.genres.start_batch()
        by_id = {t.id: t for t in tracks}
        ids = list(by_id)
        features = self.cache.get_audio(ids)
        to_fetch = [i for i in ids if i not in features]
        if to_fetch:
            result = self.recco.audio_features(to_fetch)
            # Grava já: se a busca de alternativas cair (ex.: login expirou), o que achamos não se perde.
            self.cache.put_audio(result.found, [])
            features.update(result.found)
            failed = set(result.failed)
            unknown = [i for i in to_fetch if i not in result.found and i not in failed]
            recovered, unresolved = self._via_alternates(unknown, by_id)
            missing = [i for i in unknown if i not in recovered and i not in unresolved]
            self.cache.put_audio(recovered, missing)
            features.update(recovered)
        out: list[EnrichedTrack] = []
        for track in tracks:
            audio = features.get(track.id)
            genres = self.genres.genres_for(track.artists[0]) if track.artists else []
            out.append(
                EnrichedTrack(
                    track=track,
                    tempo=audio.tempo if audio else None,
                    energy=audio.energy if audio else None,
                    genres=genres,
                )
            )
        return out

    def _via_alternates(
        self, ids: list[str], by_id: dict[str, Track]
    ) -> tuple[dict[str, AudioFeatures], set[str]]:
        """BPM de outras versões da mesma gravação.

        Devolve (recuperadas por ID original, IDs não resolvidos). Não resolvido = a busca falhou,
        passou do limite ou a ReccoBeats falhou para as alternativas: esses não entram no cache.
        """
        if self.alternates is None or not ids:
            return {}, set()
        finder = self.alternates
        batch = ids[:MAX_ALTERNATE_LOOKUPS]
        unresolved: set[str] = set(ids[MAX_ALTERNATE_LOOKUPS:])
        spotify_down = threading.Event()

        def lookup(track_id: str) -> list[str] | None:
            # Disjuntor: depois da primeira falha, as buscas que ainda não começaram nem tentam.
            if spotify_down.is_set():
                return None
            try:
                return finder.find(by_id[track_id])
            except ExternalServiceError:
                spotify_down.set()
                return None
            except AuthRequired:
                # Login expirou: para as próximas buscas e deixa o erro subir para o app pedir login.
                spotify_down.set()
                raise

        with ThreadPoolExecutor(max_workers=ALTERNATE_WORKERS) as pool:
            found_alternates = list(pool.map(lookup, batch))
        alternates_of: dict[str, list[str]] = {}
        for track_id, alts in zip(batch, found_alternates):
            if alts is None:
                unresolved.add(track_id)
            else:
                alternates_of[track_id] = alts
        wanted = list(dict.fromkeys(a for alts in alternates_of.values() for a in alts))
        if not wanted:
            return {}, unresolved
        result = self.recco.audio_features(wanted)
        failed = set(result.failed)
        recovered: dict[str, AudioFeatures] = {}
        for track_id, alts in alternates_of.items():
            hit = next((result.found[a] for a in alts if a in result.found), None)
            if hit is not None:
                recovered[track_id] = hit
            elif any(a in failed for a in alts):
                unresolved.add(track_id)
        return recovered, unresolved
