import os
import urllib.parse
import requests
import models
from models import UserModel, TrackModel, ArtistModel, ListeningHistoryModel
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import engine, Base, get_db
from datetime import datetime, timezone
from recommendations import sync_artist_genres, recommend_tracks

app = FastAPI(title="Spotify Listening Intelligence Engine API")
Base.metadata.create_all(bind=engine)


@app.get("/api/health")
def health_check(db: Session = Depends(get_db)):
    """Baseline operational diagnostic route verifying service and cloud database status."""
    try:
        db.execute(text("SELECT 1"))
        return {
            "status": "operational",
            "database_connected": True,
            "engine": "PostgreSQL (Neon Cloud)"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")


@app.get("/api/login")
def spotify_login():
    """Generates the secure authorization URL and redirects the client to Spotify."""
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI")
    scopes = "user-read-recently-played user-top-read user-library-read"

    state_params = {
        "response_type": "code",
        "client_id": client_id,
        "scope": scopes,
        "redirect_uri": redirect_uri,
    }
    spotify_auth_url = f"https://accounts.spotify.com/authorize?{urllib.parse.urlencode(state_params)}"
    return RedirectResponse(spotify_auth_url)


@app.get("/api/callback")
def spotify_callback(code: str = None, error: str = None):
    """Receives Spotify's secure passport code and exchanges it for real access tokens."""
    if error:
        raise HTTPException(status_code=400, detail=f"Spotify Authorization Failed: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code from Spotify.")

    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI")

    token_url = "https://accounts.spotify.com/api/token"
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    response = requests.post(token_url, data=payload, auth=(client_id, client_secret))

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"Token exchange failed: {response.text}")

    token_data = response.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")

    profile_response = requests.get(
        "https://api.spotify.com/v1/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    profile = profile_response.json()
    spotify_id = profile.get("id")
    display_name = profile.get("display_name")

    db = next(get_db())
    existing_user = db.query(UserModel).filter(UserModel.spotify_id == spotify_id).first()
    if existing_user:
        existing_user.access_token = access_token
        existing_user.refresh_token = refresh_token
    else:
        new_user = UserModel(
            spotify_id=spotify_id,
            display_name=display_name,
            access_token=access_token,
            refresh_token=refresh_token,
        )
        db.add(new_user)
    db.commit()

    return {
        "message": "Login successful and user saved to database",
        "spotify_id": spotify_id,
        "display_name": display_name,
    }


@app.get("/api/fetch-top-tracks")
def fetch_top_tracks(spotify_id: str, db: Session = Depends(get_db)):
    """Pulls the user's top tracks from Spotify and stores them in the database."""

    user = db.query(UserModel).filter(UserModel.spotify_id == spotify_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found. Log in first.")

    response = requests.get(
        "https://api.spotify.com/v1/me/top/tracks?limit=50&time_range=long_term",
        headers={"Authorization": f"Bearer {user.access_token}"},
    )

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"Spotify API error: {response.text}")

    tracks_data = response.json().get("items", [])
    saved_count = 0

    seen_artist_ids = set()
    seen_track_ids = set()
    history_entries = []

    for item in tracks_data:
        track_id = item.get("id")
        title = item.get("name")
        artists = item.get("artists", [])

        if not artists or not track_id:
            continue

        artist_id = artists[0].get("id")
        artist_name = artists[0].get("name")

        if artist_id not in seen_artist_ids:
            existing_artist = db.query(ArtistModel).filter(ArtistModel.artist_id == artist_id).first()
            if not existing_artist:
                db.add(ArtistModel(artist_id=artist_id, name=artist_name))
            seen_artist_ids.add(artist_id)

        if track_id not in seen_track_ids:
            existing_track = db.query(TrackModel).filter(TrackModel.track_id == track_id).first()
            if not existing_track:
                db.add(TrackModel(track_id=track_id, title=title, artist_id=artist_id))
            seen_track_ids.add(track_id)

        history_entries.append(ListeningHistoryModel(
            spotify_id=spotify_id,
            track_id=track_id,
            played_at=datetime.now(timezone.utc)
        ))
        saved_count += 1

    db.flush()

    for entry in history_entries:
        db.add(entry)

    db.commit()
    return {"message": f"Saved {saved_count} top tracks", "spotify_id": spotify_id}

@app.post("/api/sync-genres")
def sync_genres(spotify_id: str, db: Session = Depends(get_db)):
    """Backfills genre data (from Spotify's per-artist endpoint) for every
    artist tied to this user's listening history. Run this after
    fetch-top-tracks and before requesting recommendations."""
    try:
        updated = sync_artist_genres(db, spotify_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="User not found. Log in first.")
    return {"message": f"Updated genres for {updated} artists", "spotify_id": spotify_id}


@app.get("/api/recommendations")
def get_recommendations(spotify_id: str, limit: int = 20, db: Session = Depends(get_db)):
    """Content-based track recommendations, scored by genre overlap
    between this user's recency-weighted listening profile and every
    track already stored in the database that they haven't heard yet."""
    user = db.query(UserModel).filter(UserModel.spotify_id == spotify_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found. Log in first.")

    recs = recommend_tracks(db, spotify_id, limit=limit)
    return {"spotify_id": spotify_id, "count": len(recs), "recommendations": recs}