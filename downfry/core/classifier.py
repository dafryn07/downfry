from urllib.parse import urlparse, parse_qs
from enum import Enum
from typing import Tuple

class UrlType(Enum):
    VIDEO = "video"
    SHORT = "short"
    PLAYLIST = "playlist"
    CHANNEL = "channel"
    UNKNOWN = "unknown"

CHANNEL_TABS = (
    "videos", "shorts", "streams", "live", "releases",
    "podcasts", "playlists", "community", "featured", "about"
)

def normalize_channel_base_url(url: str) -> Tuple[str, str]:
    parsed = urlparse(url.strip())
    path_parts = [p for p in parsed.path.split("/") if p]
    detected_tab = "all"
    if not path_parts:
        return url.strip().rstrip("/"), detected_tab
    if path_parts[0].startswith("@"):
        base_path = f"/{path_parts[0]}"
        if len(path_parts) > 1 and path_parts[1].lower() in CHANNEL_TABS:
            detected_tab = path_parts[1].lower()
        return f"https://www.youtube.com{base_path}", detected_tab
    if path_parts[0].lower() in ("channel", "c", "user") and len(path_parts) >= 2:
        base_path = f"/{path_parts[0]}/{path_parts[1]}"
        if len(path_parts) > 2 and path_parts[2].lower() in CHANNEL_TABS:
            detected_tab = path_parts[2].lower()
        return f"https://www.youtube.com{base_path}", detected_tab
    return url.strip().rstrip("/"), detected_tab

def classify_youtube_url(url: str) -> Tuple[UrlType, dict]:
    url = url.strip()
    if not url:
        return UrlType.UNKNOWN, {}
    if not url.startswith(("http://", "https://")) and ("youtube.com" in url or "youtu.be" in url):
        url = "https://" + url
    try:
        parsed = urlparse(url)
    except Exception:
        return UrlType.UNKNOWN, {}

    netloc = parsed.netloc.lower()
    if not any(d in netloc for d in ("youtube.com", "youtu.be", "youtube-nocookie.com")):
        return UrlType.UNKNOWN, {}

    path = parsed.path
    query = parse_qs(parsed.query)

    if any(path.startswith(p) for p in ("/@", "/channel/", "/c/", "/user/")):
        base_url, tab = normalize_channel_base_url(url)
        return UrlType.CHANNEL, {"path": path, "clean_url": base_url, "detected_tab": tab}

    if "/shorts/" in path:
        short_id = path.split("/shorts/")[1].split("/")[0].split("?")[0]
        if short_id:
            return UrlType.SHORT, {"id": short_id, "clean_url": f"https://www.youtube.com/shorts/{short_id}"}

    if "/live/" in path:
        live_id = path.split("/live/")[1].split("/")[0].split("?")[0]
        if live_id:
            return UrlType.VIDEO, {"id": live_id, "clean_url": f"https://www.youtube.com/watch?v={live_id}", "is_live": True}

    for prefix in ("/embed/", "/v/"):
        if prefix in path:
            vid_id = path.split(prefix)[1].split("/")[0].split("?")[0]
            if vid_id:
                return UrlType.VIDEO, {"id": vid_id, "clean_url": f"https://www.youtube.com/watch?v={vid_id}"}

    if "/playlist" in path and "list" in query:
        playlist_id = query["list"][0]
        is_sys_priv = playlist_id in ("WL", "LL", "SE", "LM", "RDPN")
        return UrlType.PLAYLIST, {
            "id": playlist_id,
            "clean_url": f"https://www.youtube.com/playlist?list={playlist_id}",
            "is_private_system_playlist": is_sys_priv,
        }

    if "watch" in path and "v" in query:
        video_id = query["v"][0]
        pl_id = query["list"][0] if "list" in query else None
        has_playlist = bool(pl_id and pl_id not in ("WL", "LL", "SE", "LM", "RDPN"))
        return UrlType.VIDEO, {
            "id": video_id,
            "clean_url": f"https://www.youtube.com/watch?v={video_id}",
            "has_playlist": has_playlist,
            "playlist_id": pl_id if has_playlist else None,
            "playlist_url": f"https://www.youtube.com/playlist?list={pl_id}" if has_playlist else None,
        }

    if "youtu.be" in netloc and len(path) > 1:
        video_id = path.lstrip("/").split("/")[0].split("?")[0]
        pl_id = query["list"][0] if "list" in query else None
        has_playlist = bool(pl_id and pl_id not in ("WL", "LL", "SE", "LM", "RDPN"))
        return UrlType.VIDEO, {
            "id": video_id,
            "clean_url": f"https://www.youtube.com/watch?v={video_id}",
            "has_playlist": has_playlist,
            "playlist_id": pl_id if has_playlist else None,
            "playlist_url": f"https://www.youtube.com/playlist?list={pl_id}" if has_playlist else None,
        }

    if "@" in path:
        base_url, tab = normalize_channel_base_url(url)
        return UrlType.CHANNEL, {"clean_url": base_url, "detected_tab": tab}

    return UrlType.UNKNOWN, {}
