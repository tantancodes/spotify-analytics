"use client";

import { useEffect, useState } from "react";
import {
  ApiError,
  Recommendation,
  fetchTopTracks,
  getRecommendations,
  loginUrl,
  syncGenres,
} from "@/lib/api";
import styles from "./page.module.css";

export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState<boolean>(false);

  // /api/callback redirects here with ?session_token=...&display_name=...
  // after a successful Spotify login. Pick it up once, persist it, then
  // scrub the URL so the token doesn't sit in browser history.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlToken = params.get("session_token");
    if (urlToken) {
      const name = params.get("display_name") || "";
      localStorage.setItem("session_token", urlToken);
      if (name) localStorage.setItem("display_name", name);
      window.history.replaceState({}, "", window.location.pathname);
      setToken(urlToken);
      setDisplayName(name);
      return;
    }
    const stored = localStorage.getItem("session_token");
    if (stored) {
      setToken(stored);
      setDisplayName(localStorage.getItem("display_name") || "");
    }
  }, []);

  function logout() {
    localStorage.removeItem("session_token");
    localStorage.removeItem("display_name");
    setToken(null);
    setDisplayName("");
    setRecommendations([]);
    setStatus("");
  }

  function handleError(err: unknown) {
    if (err instanceof ApiError && err.status === 401) {
      logout();
      setStatus("Session expired -- log in again.");
      return;
    }
    setStatus(err instanceof Error ? err.message : "Something went wrong.");
  }

  async function handleSync() {
    if (!token) return;
    setLoading(true);
    try {
      setStatus("Fetching your top tracks from Spotify...");
      const fetchResult = await fetchTopTracks(token);
      setStatus(`${fetchResult.message} -- syncing genres...`);
      const syncResult = await syncGenres(token);
      setStatus(`${fetchResult.message}. ${syncResult.message}.`);
    } catch (err) {
      handleError(err);
    } finally {
      setLoading(false);
    }
  }

  async function handleRecommendations() {
    if (!token) return;
    setLoading(true);
    try {
      setStatus("Scoring recommendations...");
      const data = await getRecommendations(token);
      setRecommendations(data.recommendations);
      setStatus(
        data.count === 0
          ? "No recommendations yet -- this shows up once there's at least one candidate track in the database that you haven't heard."
          : `${data.count} recommendation(s).`
      );
    } catch (err) {
      handleError(err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className={styles.main}>
      <h1>Spotify Listening Intelligence</h1>
      <p className={styles.sub}>A personal taste profile, built from your own listening history.</p>

      <div className={styles.card}>
        {!token ? (
          <>
            <p>Log in with Spotify to build your profile.</p>
            <a className={styles.button} href={loginUrl()}>
              Log in with Spotify
            </a>
          </>
        ) : (
          <div className={styles.row}>
            <span>{displayName ? `Logged in as ${displayName}` : "Logged in"}</span>
            <button className={styles.secondary} onClick={logout}>
              Log out
            </button>
          </div>
        )}
      </div>

      {token && (
        <div className={styles.card}>
          <div className={styles.row}>
            <button onClick={handleSync} disabled={loading}>
              Sync my listening data
            </button>
            <button className={styles.secondary} onClick={handleRecommendations} disabled={loading}>
              Get recommendations
            </button>
          </div>
          <div className={styles.status}>{status}</div>
        </div>
      )}

      {recommendations.length > 0 && (
        <div className={styles.card}>
          <strong>Recommended for you</strong>
          <ul className={styles.tracks}>
            {recommendations.map((rec) => (
              <li key={rec.track_id}>
                <span className={styles.score}>match {rec.score}</span>
                <div className={styles.trackTitle}>{rec.title}</div>
                <div className={styles.trackArtist}>{rec.artist}</div>
                {rec.reasons.length > 0 && (
                  <div className={styles.reasons}>{rec.reasons.join(" · ")}</div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </main>
  );
}
