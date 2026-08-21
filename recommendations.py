"""
Content-based recommendation engine.

Original design scored tracks purely by genre overlap (artist genres
returned by GET /v1/artists/{id}). In practice, testing against a real
account showed 100% of stored artists came back with an EMPTY genre
list from Spotify -- not a bug here, but a known, longstanding gap in
Spotify's own API (see spotify/web-api#312 on GitHub, and multiple
threads on the Spotify Community forum reporting the same). Combined
with the audio-features deprecation (2024) and the Feb 2026 removal of
popularity/followers/recommendations/related-artists, genres turned
out to be effectively unusable as a signal too, not just theoretically
scarce.

So the primary signal is now artist affinity: how much of a user's own
recency-weighted listening is attributable to a given artist. A track
is scored highly if it's by an artist the user already listens to a
lot, and they haven't heard that specific track yet. Genre overlap is
kept as a secondary signal that adds to the score when genres ARE
present -- so if Spotify ever fixes the empty-genres issue, matches
improve automatically without a design change, but the engine doesn't
depend on that.
"""
import math
from collections import defaultdict
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from models import UserModel, TrackModel, ArtistModel, ListeningHistoryModel

import requests

SPOTIFY_ARTIST_URL = "https://api.spotify.com/v1/artists/{artist_id}"
RECENCY_HALF_LIFE_DAYS = 30  # a listen loses half its weight in a profile every 30 days


def sync_artist_genres(db: Session, spotify_id: str) -> int:
    """
    Fetch and store genres for any artist tied to this user's listening
    history that we haven't looked up yet. Kept even though genres have
    been empty in practice -- if Spotify's API starts returning real
    genre data again, this (and the genre component of scoring below)
    starts contributing without any other code changing.
    """
    user = db.query(UserModel).filter(UserModel.spotify_id == spotify_id).first()
    if not user:
        raise ValueError("User not found")

    artist_ids = (
        db.query(ArtistModel.artist_id)
        .join(TrackModel, TrackModel.artist_id == ArtistModel.artist_id)
        .join(ListeningHistoryModel, ListeningHistoryModel.track_id == TrackModel.track_id)
        .filter(ListeningHistoryModel.spotify_id == spotify_id)
        .filter(ArtistModel.genres.is_(None))
        .distinct()
        .all()
    )

    updated = 0
    for (artist_id,) in artist_ids:
        resp = requests.get(
            SPOTIFY_ARTIST_URL.format(artist_id=artist_id),
            headers={"Authorization": f"Bearer {user.access_token}"},
        )
        if resp.status_code != 200:
            continue
        genres = resp.json().get("genres", [])
        artist = db.query(ArtistModel).filter(ArtistModel.artist_id == artist_id).first()
        if artist:
            artist.genres = genres
            updated += 1
    db.commit()
    return updated


def _recency_weight(played_at: datetime) -> float:
    """Exponential half-life decay: a listen from today counts as 1.0,
    a listen from RECENCY_HALF_LIFE_DAYS ago counts as 0.5, and so on."""
    if played_at is None:
        return 0.5
    now = datetime.now(timezone.utc)
    days_ago = max((now - played_at).total_seconds() / 86400, 0)
    return 0.5 ** (days_ago / RECENCY_HALF_LIFE_DAYS)


def _listening_rows(db: Session, spotify_id: str):
    return (
        db.query(ListeningHistoryModel.played_at, ArtistModel.artist_id, ArtistModel.name, ArtistModel.genres)
        .join(TrackModel, TrackModel.track_id == ListeningHistoryModel.track_id)
        .join(ArtistModel, ArtistModel.artist_id == TrackModel.artist_id)
        .filter(ListeningHistoryModel.spotify_id == spotify_id)
        .all()
    )


def build_artist_profile(db: Session, spotify_id: str) -> dict:
    """
    Returns {artist_id: share}, where share is this artist's fraction of
    the user's total recency-weighted listening (so it sums to ~1.0
    across all artists). An artist the user plays constantly and
    recently scores close to that share; a one-off listen from a year
    ago barely registers.
    """
    rows = _listening_rows(db, spotify_id)
    raw = defaultdict(float)
    for played_at, artist_id, _name, _genres in rows:
        raw[artist_id] += _recency_weight(played_at)

    total = sum(raw.values())
    if total == 0:
        return {}
    return {artist_id: weight / total for artist_id, weight in raw.items()}


def build_genre_profile(db: Session, spotify_id: str) -> dict:
    """Returns {genre: weight}. Empty whenever Spotify hasn't returned
    genre data for the user's artists -- which, as of this build, is
    all the time -- but the function stays generic rather than assuming
    that permanently."""
    rows = _listening_rows(db, spotify_id)
    profile = defaultdict(float)
    for played_at, _artist_id, _name, genres in rows:
        if not genres:
            continue
        weight = _recency_weight(played_at)
        for genre in genres:
            profile[genre] += weight
    return dict(profile)


def _genre_similarity(genre_profile: dict, candidate_genres: list) -> float:
    if not genre_profile or not candidate_genres:
        return 0.0
    candidate_set = set(candidate_genres)
    dot = sum(genre_profile.get(g, 0.0) for g in candidate_set)
    norm_profile = math.sqrt(sum(v * v for v in genre_profile.values()))
    norm_candidate = math.sqrt(len(candidate_set))
    if norm_profile == 0 or norm_candidate == 0:
        return 0.0
    return dot / (norm_profile * norm_candidate)


def recommend_tracks(db: Session, spotify_id: str, limit: int = 20) -> list:
    """
    Scores every track in the database (candidate pool = everything any
    user of this app has had ingested, since there's no Spotify endpoint
    left to source fresh candidates from) that this user hasn't heard,
    combining two content signals:
      - artist affinity: this artist's share of the user's own
        recency-weighted listening (0 if it's an artist they've never
        played)
      - genre overlap: cosine similarity between the candidate's
        artist genres and the user's genre profile (0 whenever genres
        are empty, which is the common case right now)
    A track only shows up if at least one signal is nonzero.
    """
    artist_profile = build_artist_profile(db, spotify_id)
    genre_profile = build_genre_profile(db, spotify_id)
    if not artist_profile and not genre_profile:
        return []

    already_heard = {
        row.track_id
        for row in db.query(ListeningHistoryModel.track_id)
        .filter(ListeningHistoryModel.spotify_id == spotify_id)
        .all()
    }

    candidates = db.query(TrackModel, ArtistModel).join(ArtistModel, ArtistModel.artist_id == TrackModel.artist_id).all()

    scored = []
    for track, artist in candidates:
        if track.track_id in already_heard:
            continue

        artist_score = artist_profile.get(artist.artist_id, 0.0)
        genre_score = _genre_similarity(genre_profile, artist.genres or [])
        combined = artist_score + genre_score
        if combined <= 0:
            continue

        reasons = []
        if artist_score > 0:
            reasons.append(f"{round(artist_score * 100)}% of your recent listening is this artist")
        matched_genres = sorted(
            set(artist.genres or []) & set(genre_profile.keys()),
            key=lambda g: -genre_profile[g],
        )[:5]
        if matched_genres:
            reasons.append("genre overlap: " + ", ".join(matched_genres))

        scored.append({
            "track_id": track.track_id,
            "title": track.title,
            "artist": artist.name,
            "score": round(combined, 4),
            "matched_genres": matched_genres,
            "reasons": reasons,
        })

    scored.sort(key=lambda r: -r["score"])
    return scored[:limit]
