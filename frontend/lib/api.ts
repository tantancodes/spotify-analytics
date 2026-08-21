// Typed client for the FastAPI backend. Talks to a different origin
// (the backend runs on :8000, this app runs on :3000), so every call
// here depends on the backend's CORS middleware allowing this origin.

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export interface Recommendation {
  track_id: string;
  title: string;
  artist: string;
  score: number;
  matched_genres: string[];
  reasons: string[];
}

export interface RecommendationsResponse {
  spotify_id: string;
  count: number;
  recommendations: Recommendation[];
}

export interface SimpleMessageResponse {
  message: string;
  spotify_id: string;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function authedFetch<T>(
  path: string,
  token: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...options.headers,
      Authorization: `Bearer ${token}`,
    },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(body.detail || `Request failed (${res.status})`, res.status);
  }

  return res.json() as Promise<T>;
}

export function loginUrl(): string {
  return `${API_BASE}/api/login`;
}

export function fetchTopTracks(token: string): Promise<SimpleMessageResponse> {
  return authedFetch<SimpleMessageResponse>("/api/fetch-top-tracks", token);
}

export function syncGenres(token: string): Promise<SimpleMessageResponse> {
  return authedFetch<SimpleMessageResponse>("/api/sync-genres", token, { method: "POST" });
}

export function getRecommendations(
  token: string,
  limit = 20
): Promise<RecommendationsResponse> {
  return authedFetch<RecommendationsResponse>(`/api/recommendations?limit=${limit}`, token);
}
