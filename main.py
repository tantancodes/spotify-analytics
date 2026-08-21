import os
import secrets
import urllib.parse
import requests
import models
from models import UserModel, TrackModel, ArtistModel, ListeningHistoryModel
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import engine, Base, get_db
from datetime import datetime, timezone
from recommendations import sync_artist_genres, recommend_tracks

app = FastAPI(title="Spotify Listening Intelligence Engine API")
Base.metadata.create_all(bind=engine)

# Base.metadata.create_all() only creates missing TABLES, not missing
# COLUMNS on tables that already exist -- so adding session_token to
# UserModel above wouldn't reach an already-running database without
# this. A real migration tool (Alembic) would replace this if the
# schema keeps growing.
with engine.connect() as _conn:
    _conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS session_token VARCHAR"))
    _conn.commit()


def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)) -> UserModel:
    """
    Resolves the authenticated user from a session token, instead of
    trusting a client-supplied spotify_id. Every route that touches a
    specific user's data depends on this rather than taking spotify_id
    as a parameter -- that's what stops one user from ever being able
    to request another user's data by simply changing an ID in the URL.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header. Expected: 'Bearer <session_token>' (returned by /api/callback after login).",
        )
    token = authorization.removeprefix("Bearer ").strip()
    user = db.query(UserModel).filter(UserModel.session_token == token).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session token. Log in again via /api/login.")
    return user


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

    session_token = secrets.token_urlsafe(32)

    db = next(get_db())
    existing_user = db.query(UserModel).filter(UserModel.spotify_id == spotify_id).first()
    if existing_user:
        existing_user.access_token = access_token
        existing_user.refresh_token = refresh_token
        existing_user.session_token = session_token
    else:
        new_user = UserModel(
            spotify_id=spotify_id,
            display_name=display_name,
            access_token=access_token,
            refresh_token=refresh_token,
            session_token=session_token,
        )
        db.add(new_user)
    db.commit()

    redirect_params = urllib.parse.urlencode({
        "session_token": session_token,
        "display_name": display_name or "",
    })
    return RedirectResponse(f"/?{redirect_params}")


@app.get("/api/fetch-top-tracks")
def fetch_top_tracks(user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    """Pulls the authenticated user's top tracks from Spotify and stores them in the database."""

    spotify_id = user.spotify_id

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
def sync_genres(user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    """Backfills genre data (from Spotify's per-artist endpoint) for every
    artist tied to the authenticated user's listening history. Run this
    after fetch-top-tracks and before requesting recommendations."""
    updated = sync_artist_genres(db, user.spotify_id)
    return {"message": f"Updated genres for {updated} artists", "spotify_id": user.spotify_id}


@app.get("/api/recommendations")
def get_recommendations(limit: int = 20, user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    """Content-based track recommendations for the authenticated user,
    scored by genre overlap between their recency-weighted listening
    profile and every track already stored in the database that they
    haven't heard yet."""
    recs = recommend_tracks(db, user.spotify_id, limit=limit)
    return {"spotify_id": user.spotify_id, "count": len(recs), "recommendations": recs}


# Mounted last, deliberately -- Starlette matches routes in the order
# they're registered, so every /api/* route above still takes priority.
# This just serves the frontend for everything else, including "/".
app.mount("/", StaticFiles(directory="static", html=True), name="static")