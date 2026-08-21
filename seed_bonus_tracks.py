"""
Adds a few synthetic "unheard" tracks under artists you already listen
to a lot, so the artist-affinity recommendation signal has something
real to surface. Doesn't touch your listening history or invent a fake
user -- it just adds extra catalog entries under real artist IDs
pulled from your own top artists.

Safe to re-run.

Run: python3 seed_bonus_tracks.py
"""
from sqlalchemy import func
from database import SessionLocal
from models import ArtistModel, TrackModel, ListeningHistoryModel

SPOTIFY_ID = "31soii6ywzh2ikx3yrttkb5xtl3a"  # your real account
BONUS_TRACKS_PER_ARTIST = 2
TOP_N_ARTISTS = 3

db = SessionLocal()

top_artists = (
    db.query(ArtistModel.artist_id, ArtistModel.name, func.count(ListeningHistoryModel.history_id).label("plays"))
    .join(TrackModel, TrackModel.artist_id == ArtistModel.artist_id)
    .join(ListeningHistoryModel, ListeningHistoryModel.track_id == TrackModel.track_id)
    .filter(ListeningHistoryModel.spotify_id == SPOTIFY_ID)
    .group_by(ArtistModel.artist_id, ArtistModel.name)
    .order_by(func.count(ListeningHistoryModel.history_id).desc())
    .limit(TOP_N_ARTISTS)
    .all()
)

if not top_artists:
    print("No listening history found for this spotify_id -- run /api/fetch-top-tracks first.")
    db.close()
    raise SystemExit(1)

added = 0
for artist_id, name, plays in top_artists:
    for i in range(1, BONUS_TRACKS_PER_ARTIST + 1):
        bonus_id = f"bonus_{artist_id}_{i}"
        if not db.query(TrackModel).filter(TrackModel.track_id == bonus_id).first():
            db.add(TrackModel(track_id=bonus_id, title=f"(Unheard) Another track by {name}", artist_id=artist_id))
            added += 1
    print(f"Added bonus tracks for {name} ({plays} real plays)")

db.commit()
print(f"\n{added} new candidate track(s) added. Run /api/recommendations again.")
db.close()
