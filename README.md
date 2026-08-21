# Spotify Listening Intelligence

A FastAPI backend (plus a small static frontend) that authenticates a Spotify user, ingests their listening history into a Postgres database, and generates content-based track recommendations from artist affinity and (where available) genre overlap.

## Why artist-affinity, not audio-feature-based or purely genre-based

Spotify deprecated the `audio-features` endpoint (danceability, energy, valence, tempo) for standard developer apps in late 2024, and its February 2026 Dev Mode changes additionally removed `popularity`, `followers`, and the `recommendations`/`related-artists` endpoints. None of those signals are available to this app.

The original design scored tracks by genre overlap instead, using per-artist genre tags (`GET /v1/artists/{id}`). Testing against a real account showed **100% of stored artists came back with an empty genre list** — not a bug in this code, but a known, longstanding gap in Spotify's API itself (see [spotify/web-api#312](https://github.com/spotify/web-api/issues/312) and the [Spotify Community thread](https://community.spotify.com/t5/Spotify-for-Developers/Get-Artist-API-is-not-returning-any-or-all-Genres/td-p/6880841) reporting the same). So genres are effectively unusable in practice, not just theoretically scarce.

The engine now scores primarily by **artist affinity**: an artist's share of a user's own recency-weighted listening history. A candidate track scores well if it's by an artist the user already listens to a lot and they haven't heard that specific track. Genre overlap is kept as a secondary, additive signal — if Spotify's genre field ever starts working again, matches improve automatically without a design change, but nothing depends on it working today. Candidates are drawn from every track already stored in the database (across all users of this app), since there's no Spotify endpoint left to source fresh candidates from.

Dev Mode apps are also capped at 5 total users and require the app owner to have Spotify Premium, which bounds how this can be tested/demoed with real accounts — a synthetic-data seed script (`seed_bonus_tracks.py`) is included for testing without needing multiple active Spotify accounts.

## Architecture

- **FastAPI** — API server
- **SQLAlchemy** — ORM (`models.py`), talking to **Neon** (serverless Postgres) via `DATABASE_URL`
- **Spotify Web API** — OAuth 2.0 authorization code flow for login; `/v1/me/top/tracks` for ingestion; `/v1/artists/{id}` for genres
- **Session-token auth** — after login, the server issues a random per-user token (`secrets.token_urlsafe(32)`); every user-scoped route requires it as `Authorization: Bearer <token>` and resolves the user from the token rather than trusting a client-supplied ID. This is what keeps one user's data from being readable by another.
- **Static frontend** (`static/index.html`) — single-page vanilla JS/HTML/CSS, served by FastAPI itself via `StaticFiles`

## Data model

| Table | Purpose |
|---|---|
| `users` | Spotify identity, OAuth tokens, session token |
| `artists` | artist id, name, genres (backfilled separately from track ingestion) |
| `tracks` | track id, title, artist FK |
| `listening_history` | one row per (user, track, timestamp) — the basis for the genre profile and the "already heard" filter |

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file (never committed — see `.gitignore`) with:

```
DATABASE_URL=postgresql://...        # from your Neon project dashboard
SPOTIFY_CLIENT_ID=...                # from developer.spotify.com/dashboard
SPOTIFY_CLIENT_SECRET=...
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8000/api/callback   # must match the app's registered redirect URI exactly
```

Run it:

```bash
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000/` and log in with Spotify.

## API

| Route | Method | Auth | Purpose |
|---|---|---|---|
| `/api/health` | GET | none | Confirms the app and database connection are up |
| `/api/login` | GET | none | Redirects to Spotify's OAuth consent screen |
| `/api/callback` | GET | none (Spotify calls this) | Exchanges the auth code for tokens, creates/updates the user, redirects to `/` with a session token |
| `/api/fetch-top-tracks` | GET | Bearer session token | Pulls the caller's top tracks from Spotify, stores tracks/artists/history |
| `/api/sync-genres` | POST | Bearer session token | Backfills genre tags for artists tied to the caller's history |
| `/api/recommendations` | GET | Bearer session token | Returns content-based recommendations, scored by artist affinity plus any genre overlap, with the reasons for each match |

## Known limitations / next steps

- **Single-user testing shows empty recommendations.** The candidate pool is every track stored by any user of the app, minus what the requesting user has already heard. With only one user and no other candidate tracks in the database, that pool is empty by construction — this is correct behavior, not a bug. `seed_bonus_tracks.py` works around this for testing by adding synthetic "unheard" tracks under the user's own real top artists.
- **Spotify's artist-genres endpoint returns empty data in practice** (see above) — the genre component of scoring is currently inert for essentially all real artists, though the code path is kept in case that changes.
- **No refresh-token flow.** Spotify access tokens expire in about an hour; `refresh_token` is stored but never used to silently re-authenticate. A logged-in session currently degrades to needing another login once the underlying Spotify token expires.
- **Schema changes are applied with a manual `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`** at startup rather than a real migration tool. Fine at this scale; would move to Alembic if the schema kept growing.
- **No rate limiting or retry/backoff** on Spotify API calls — `sync-genres` calls Spotify once per artist sequentially, which is simple but slow for a user with many distinct artists, and does not gracefully handle Spotify's per-app rate limits.
