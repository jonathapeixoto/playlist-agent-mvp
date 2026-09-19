"""Junta BPM e gênero em EnrichedTrack. Falha de fonte externa vira 'sem dado', nunca derruba o fluxo."""

from __future__ import annotations

from contracts.models import EnrichedTrack, Track
from services.enrichment.cache import EnrichmentCache
from services.enrichment.genres import GenreResolver
from services.enrichment.reccobeats import ReccoBeatsClient


class Enricher:
    def __init__(self, recco: ReccoBeatsClient, genres: GenreResolver, cache: EnrichmentCache) -> None:
        self.recco = recco
        self.genres = genres
        self.cache = cache

    def enrich(self, tracks: list[Track]) -> list[EnrichedTrack]:
        ids = list(dict.fromkeys(t.id for t in tracks))
        features = self.cache.get_audio(ids)
        to_fetch = [i for i in ids if i not in features]
        if to_fetch:
            result = self.recco.audio_features(to_fetch)
            failed = set(result.failed)
            missing = [i for i in to_fetch if i not in result.found and i not in failed]
            self.cache.put_audio(result.found, missing)
            features.update(result.found)
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
