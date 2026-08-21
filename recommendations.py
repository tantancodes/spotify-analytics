"""
Content-based recommendation engine.

Two Spotify API changes shape this design:
- The audio-features endpoint (danceability/energy/valence/tempo) was
  deprecated in late 2024 for standard developer apps, so track-level
  audio characteristics can't be used as a signal.
- The February 2026 Dev Mode changes additionally removed the
  `popularity` and `followers` fields, and there is no
  "recommendations" or "related artists" endpoint left to pull fresh
  candidate tracks from either (both were removed alongside audio
  features).

Genres, returned per-artist by GET /v1/artists/{id}, are the richest
signal still available. So: build a recency-weighted genre profile
for a user from their own listening history, then score every track
already stored in our own database (the candidate pool, since Spotify
won't hand us new candidates) by genre overlap with that profile.
"""
import math
import requests
from collections import defaultdict
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from models import UserModel, TrackModel, ArtistModel, ListeningHistoryModel

SPOTIFY_ARTIST_URL = "https://api.spotify.com/v1/artists/{artist_id}"
RECENCY_HALF_LIFE_DAYS = 30  # a listen loses half its weight in the profile every 30 days


def sync_artist_genres(db: Session, spotify_id: str) -> int:
    """
    Fetch and store genres for any artist tied to this user's listening
    history that we haven't looked up yet. Spotify removed the batch
    /v1/artists endpoint in the Feb 2026 changes, so this fetches one
    artist at a time. Returns the number of artists updated.
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


def build_genre_profile(db: Session, spotify_id: str) -> dict:
    """Returns {genre: weight}, built from every track this user has
    listened to, weighted so recent listens count more than old ones."""
    rows = (
        db.query(ListeningHistoryModel.played_at, ArtistModel.genres)
        .join(TrackModel, TrackModel.track_id == ListeningHistoryModel.track_id)
        .join(ArtistModel, ArtistModel.artist_id == TrackModel.artist_id)
        .filter(ListeningHistoryModel.spotify_id == spotify_id)
        .all()
    )

    profile = defaultdict(float)
    for played_at, genres in rows:
        if not genres:
            continue
        weight = _recency_weight(played_at)
        for genre in genres:
            profile[genre] += weight
    return dict(profile)


def _cosine_similarity(profile: dict, candidate_genres: list) -> float:
    if not profile or not candidate_genres:
        return 0.0
    candidate_set = set(candidate_genres)
    dot = sum(profile.get(g, 0.0) for g in candidate_set)
    norm_profile = math.sqrt(sum(v * v for v in profile.values()))
    norm_candidate = math.sqrt(len(candidate_set))
    if norm_profile == 0 or norm_candidate == 0:
        return 0.0
    return dot / (norm_profile * norm_candidate)


def recommend_tracks(db: Session, spotify_id: str, limit: int = 20) -> list:
    """
    Content-based recommendations: score every track in our database
    that this user hasn't listened to yet, by how much its artist's
    genres overlap with the user's recency-weighted genre profile.
    The candidate pool is every track any user of this app has had
    ingested via /api/fetch-top-tracks -- there's no Spotify endpoint
    left to source fresh candidates from.
    """
    profile = build_genre_profile(db, spotify_id)
    if not profile:
        return []

    already_heard = {
        row.track_id
        for row in db.query(ListeningHistoryModel.track_id)
        .filter(ListeningHistoryModel.spotify_id == spotify_id)
        .all()
    }

    candidates = (
        db.query(TrackModel, ArtistModel)
        .join(ArtistModel, ArtistModel.artist_id == TrackModel.artist_id)
        .filter(ArtistModel.genres.isnot(None))
        .all()
    )

    scored = []
    for track, artist in candidates:
        if track.track_id in already_heard:
            continue
        score = _cosine_similarity(profile, artist.genres or [])
        if score <= 0:
            continue
        matched = sorted(
            set(artist.genres or []) & set(profile.keys()),
            key=lambda g: -profile[g],
        )
        scored.append({
            "track_id": track.track_id,
            "title": track.title,
            "artist": artist.name,
            "score": round(score, 4),
            "matched_genres": matched[:5],
        })

    scored.sort(key=lambda r: -r["score"])
    return scored[:limit]
