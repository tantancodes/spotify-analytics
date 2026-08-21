"""
Diagnostic: prints the genre profile the recommendation engine actually
sees for a given spotify_id, plus how many artists in the whole database
have genres populated at all. Read-only, doesn't change anything.

Run: python3 debug_profile.py
"""
from database import SessionLocal
from recommendations import build_genre_profile
from models import ArtistModel, TrackModel, ListeningHistoryModel

SPOTIFY_ID = "31soii6ywzh2ikx3yrttkb5xtl3a"  # your real account, from earlier in this chat

db = SessionLocal()

total_artists = db.query(ArtistModel).count()
artists_with_genres = db.query(ArtistModel).filter(ArtistModel.genres.isnot(None)).count()
print(f"Artists in DB total: {total_artists}, with genres populated: {artists_with_genres}")

history_count = db.query(ListeningHistoryModel).filter(ListeningHistoryModel.spotify_id == SPOTIFY_ID).count()
print(f"Your listening_history rows: {history_count}")

profile = build_genre_profile(db, SPOTIFY_ID)
print(f"\nYour genre profile ({len(profile)} distinct genres):")
if not profile:
    print("  EMPTY -- means either no listening history, or none of your tracks' artists have genres saved.")
else:
    for genre, weight in sorted(profile.items(), key=lambda x: -x[1]):
        print(f"  {genre}: {weight:.3f}")

seed_present = db.query(ListeningHistoryModel).filter(ListeningHistoryModel.spotify_id == "seed_test_user_01").count()
print(f"\nSeed user's listening_history rows: {seed_present} (should be 9 if the seed script ran successfully)")

db.close()
