import os
import sys
from datetime import datetime, timedelta, timezone

import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth

PLAYLIST_NAME = "last week's finds"
SCOPES = "user-library-read playlist-read-private playlist-modify-private playlist-modify-public"


def get_client() -> spotipy.Spotify:
    # In GitHub Actions there's no browser, so we use a stored refresh token instead.
    refresh_token = os.environ.get("SPOTIFY_REFRESH_TOKEN")
    if refresh_token:
        res = requests.post(
            "https://accounts.spotify.com/api/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": os.environ["SPOTIPY_CLIENT_ID"],
                "client_secret": os.environ["SPOTIPY_CLIENT_SECRET"],
            },
            timeout=30,
        )
        res.raise_for_status()
        return spotipy.Spotify(auth=res.json()["access_token"], requests_timeout=30, retries=3)

    # Local run: interactive browser login, cached to .spotify_cache for next time.
    return spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=os.environ["SPOTIPY_CLIENT_ID"],
            client_secret=os.environ["SPOTIPY_CLIENT_SECRET"],
            redirect_uri="http://127.0.0.1:8888/callback",
            scope=SCOPES,
            cache_path=".spotify_cache",
        ),
        requests_timeout=30,
        retries=3,
    )


def last_week_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return [Monday 00:00, next Monday 00:00) for the previous Mon-Sun week (UTC)."""
    now = now or datetime.now(timezone.utc)
    this_monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return this_monday - timedelta(days=7), this_monday


def get_liked_tracks_in_range(sp, start, end) -> list[str]:
    """Liked songs are returned newest-first, so we can stop early once we pass the window."""
    uris, offset = [], 0
    while True:
        page = sp.current_user_saved_tracks(limit=50, offset=offset)
        items = page["items"]
        if not items:
            break
        for item in items:
            added_at = datetime.fromisoformat(item["added_at"].replace("Z", "+00:00"))
            if added_at < start:
                return uris  # everything after this is older than our window
            if start <= added_at < end and item["track"] and item["track"]["uri"]:
                uris.append(item["track"]["uri"])
        offset += 50
    return uris


def get_or_create_playlist(sp, name: str) -> str:
    user_id = sp.current_user()["id"]
    offset = 0
    while True:
        page = sp.current_user_playlists(limit=50, offset=offset)
        for pl in page["items"]:
            if pl["name"] == name and pl["owner"]["id"] == user_id:
                return pl["id"]
        if page["next"] is None:
            break
        offset += 50
    # POST /users/{id}/playlists returns 403 for Development Mode apps; /me/playlists is the supported endpoint.
    pl = sp.current_user_playlist_create(name, public=False, description="Auto-generated weekly")
    return pl["id"]


def replace_playlist_contents(sp, playlist_id: str, uris: list[str]) -> None:
    # First call replaces (wipes old songs); later calls append in chunks of 100.
    sp.playlist_replace_items(playlist_id, uris[:100])
    for i in range(100, len(uris), 100):
        sp.playlist_add_items(playlist_id, uris[i : i + 100])


def main():
    print("Authenticating...", flush=True)
    sp = get_client()
    start, end = last_week_bounds()
    print(f"Fetching liked tracks between {start} and {end}...", flush=True)
    uris = get_liked_tracks_in_range(sp, start, end)
    print(f"Found {len(uris)} tracks. Locating/creating playlist...", flush=True)
    playlist_id = get_or_create_playlist(sp, PLAYLIST_NAME)
    print("Updating playlist contents...", flush=True)
    replace_playlist_contents(sp, playlist_id, uris)
    print(f"{start:%Y-%m-%d} to {end - timedelta(days=1):%Y-%m-%d}: {len(uris)} tracks -> '{PLAYLIST_NAME}'", flush=True)


if __name__ == "__main__":
    main()