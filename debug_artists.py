"""
Diagnostic: lists your real artists by play count alongside whatever
genres Spotify actually returned for each. Read-only.

Run: python3 debug_artists.py
"""
from sqlalchemy import func
from database import SessionLocal
from models import ArtistModel, TrackModel, ListeningHistoryModel

SPOTIFY_ID = "31soii6ywzh2ikx3yrttkb5xtl3a"

db = SessionLocal()

rows = (
    db.query(ArtistModel.name, ArtistModel.genres, func.count(ListeningHistoryModel.history_id).label("plays"))
    .join(TrackModel, TrackModel.artist_id == ArtistModel.artist_id)
    .join(ListeningHistoryModel, ListeningHistoryModel.track_id == TrackModel.track_id)
    .filter(ListeningHistoryModel.spotify_id == SPOTIFY_ID)
    .group_by(ArtistModel.artist_id, ArtistModel.name, ArtistModel.genres)
    .order_by(func.count(ListeningHistoryModel.history_id).desc())
    .all()
)

print(f"{'Artist':<35} {'Plays':<7} Genres")
print("-" * 80)
for name, genres, plays in rows:
    genre_str = ", ".join(genres) if genres else "(EMPTY)"
    print(f"{(name or '?')[:33]:<35} {plays:<7} {genre_str}")

empty_count = sum(1 for _, g, _ in rows if not g)
print(f"\n{empty_count} / {len(rows)} of your artists have an empty genre list from Spotify.")

db.close()
