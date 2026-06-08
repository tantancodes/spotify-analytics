import os
import urllib.parse
import requests  # <-- Added this import
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import engine, Base, get_db

app = FastAPI(title="Spotify Listening Intelligence Engine API")

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

@app.get("/callback")
def spotify_callback(code: str = None, error: str = None):
    """Receives Spotify's secure passport code and exchanges it for real access tokens."""
    if error:
        raise HTTPException(status_code=400, detail=f"Spotify Authorization Failed: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code from Spotify.")

    # 1. Gather our credentials to prove this is our app requesting the swap
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI")

    # 2. Prepare the payload Spotify expects
    token_url = "https://accounts.spotify.com/api/token"
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    
    # 3. Fire the secure background request to Spotify's identity servers
    response = requests.post(token_url, data=payload, auth=(client_id, client_secret))
    
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"Token exchange failed: {response.text}")

    token_data = response.json()
    
    # For now, let's display the tokens on the screen to celebrate our success!
    return {
        "message": "Handshake Complete! Your backend is officially authorized.",
        "access_token": token_data.get("access_token")[:20] + "...", # Truncated for display security
        "refresh_token": token_data.get("refresh_token"),
        "expires_in": token_data.get("expires_in")
    }