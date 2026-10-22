import re
import yt_dlp
from pathlib import Path
from typing import Dict, Any, Optional, List
from downfry.core.classifier import classify_youtube_url, UrlType

ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

def clean_ansi(text: str) -> str:
    return ANSI_RE.sub("", str(text)).strip()

# Clientes optimizados inmunes al bloqueo anti-bot sin cookies y con soporte completo DASH (1080p, 4K, etc.)
CLIENT_FALLBACK_CHAIN = [
    ["android_vr", "web_embedded"],
    ["ios", "web_embedded"],
    ["tv", "web_embedded"],
    ["default"],
]


class _SilentYdlLogger:
    """Logger para YoutubeDL que silencia mensajes de depuración/advertencia durante fallbacks."""
    def __init__(self):
        self.messages: List[str] = []

    def debug(self, msg: str):
        pass

    def info(self, msg: str):
        pass

    def warning(self, msg: str):
        pass

    def error(self, msg: str):
        self.messages.append(str(msg))


def get_effective_resolution(width: Any, height: Any) -> Optional[int]:
    """Calcula la resolución efectiva basada en el lado menor (aplica a 16:9, 9:16 Shorts, 21:9, 1:1, etc.)."""
    try:
        w = int(width) if width else None
        h = int(height) if height else None
    except (ValueError, TypeError):
        return None

    if w and h:
        eff = min(w, h)
    else:
        eff = h or w

    if eff == 1088:
        return 1080
    return eff


def get_cookieless_client_args() -> Dict[str, Any]:
    """Argumentos de extractor por defecto para solicitudes sin cookies."""
    return {"youtube": {"player_client": CLIENT_FALLBACK_CHAIN[0]}}


class MetadataExtractor:
    @staticmethod
    def get_ydl_base_opts() -> Dict[str, Any]:
        return {
            "quiet": True,
            "no_warnings": True,
            "no_color": True,
            "skip_download": True,
            "ignore_no_formats_error": True,
            "logger": _SilentYdlLogger(),
            "extractor_args": {"youtube": {"lang": ["es"]}},
        }

    @classmethod
    def extract_info(cls, url: str) -> Dict[str, Any]:
        url_type, meta = classify_youtube_url(url)
        target_url = meta.get("clean_url", url)
        opts = cls.get_ydl_base_opts()

        if url_type in (UrlType.PLAYLIST, UrlType.CHANNEL):
            pl_opts = opts.copy()
            pl_opts["extract_flat"] = "in_playlist"
            pl_info = None
            pl_last_err = None
            for clients in CLIENT_FALLBACK_CHAIN:
                try_opts = pl_opts.copy()
                if clients != ["default"]:
                    try_opts["extractor_args"] = {
                        "youtube": {
                            "lang": ["es"],
                            "player_client": clients,
                        }
                    }
                try:
                    with yt_dlp.YoutubeDL(try_opts) as ydl:
                        cand = ydl.extract_info(target_url, download=False)
                    if cand:
                        cand["_working_client"] = clients
                        pl_info = cand
                        break
                except Exception as e:
                    pl_last_err = e
                    continue

            if pl_info:
                return cls._normalize_info(pl_info, url_type, meta)
            elif pl_last_err:
                err_str = clean_ansi(str(pl_last_err)).lower()
                if meta.get("is_private_system_playlist") or any(k in err_str for k in ("private", "sign in", "login", "episodes for later")) or any(k in target_url for k in ("list=wl", "list=ll", "list=se", "list=lm")):
                    raise ValueError(
                        "Esta lista de reproducción es privada del sistema de YouTube ('Ver más tarde', 'Episodes for later' o 'Videos que me gustan'). "
                        "Para descargarla, por favor cambia su visibilidad a 'Oculta / No listada' (Unlisted) o crea una lista pública."
                    )
                raise ValueError(clean_ansi(pl_last_err))

        # Para videos individuales, Shorts o Directos: usar cadena anti-bot
        info = None
        last_err = None
        for clients in CLIENT_FALLBACK_CHAIN:
            try_opts = opts.copy()
            if clients != ["default"]:
                try_opts["extractor_args"] = {
                    "youtube": {
                        "lang": ["es"],
                        "player_client": clients,
                    }
                }
            try:
                with yt_dlp.YoutubeDL(try_opts) as ydl:
                    cand = ydl.extract_info(target_url, download=False)
                # Verificar que realmente trajo formatos de video/audio
                if cand and (cand.get("formats") or cand.get("url")):
                    cand["_working_client"] = clients
                    info = cand
                    break
            except Exception as e:
                last_err = e
                continue

        if info is None:
            raise ValueError(clean_ansi(last_err or "No se pudo extraer información del enlace."))

        return cls._normalize_info(info, url_type, meta)

    @classmethod
    def _estimate_entry_bytes(cls, entry: Dict[str, Any], category: str) -> int:
        dur = entry.get("duration")
        if category == "shorts":
            eff_dur = dur if (dur and 0 < dur <= 90) else 35
            return int(eff_dur * 1300 * 1000 / 8)  # ~5.5 MB por Short
        elif category == "lives":
            eff_dur = dur if (dur and dur > 0) else 3600
            return int(eff_dur * 1800 * 1000 / 8)
        else:
            eff_dur = dur if (dur and dur > 0) else 420
            return int(eff_dur * 2200 * 1000 / 8)

    @classmethod
    def _normalize_info(cls, raw: Dict[str, Any], url_type: UrlType, meta: Dict[str, Any]) -> Dict[str, Any]:
        is_playlist = "entries" in raw or url_type in (UrlType.PLAYLIST, UrlType.CHANNEL)

        if is_playlist:
            raw_entries = list(raw.get("entries") or [])
            flat_entries = []
            tab_counts = {"videos": 0, "shorts": 0, "lives": 0}
            tab_sizes = {"videos": 0, "shorts": 0, "lives": 0}

            for item in raw_entries:
                if not item:
                    continue
                if item.get("_type") == "playlist" or "entries" in item:
                    sub_entries = [s for s in (item.get("entries") or []) if s]
                    tab_title = (item.get("title") or "").lower()
                    tab_url = (item.get("url") or item.get("webpage_url") or "").lower()

                    if "short" in tab_title or "/shorts" in tab_url:
                        cat_key = "shorts"
                    elif any(w in tab_title for w in ("live", "directo", "stream", "en vivo")) or "/streams" in tab_url:
                        cat_key = "lives"
                    else:
                        cat_key = "videos"

                    tab_counts[cat_key] += len(sub_entries)
                    for s in sub_entries:
                        tab_sizes[cat_key] += cls._estimate_entry_bytes(s, cat_key)
                    flat_entries.extend(sub_entries)
                else:
                    detected_tab = meta.get("detected_tab", "all")
                    cat_key = "shorts" if detected_tab == "shorts" else "lives" if detected_tab in ("streams", "live") else "videos"
                    tab_counts[cat_key] += 1
                    tab_sizes[cat_key] += cls._estimate_entry_bytes(item, cat_key)
                    flat_entries.append(item)

            entries = flat_entries if flat_entries else raw_entries
            title = raw.get("title") or raw.get("channel") or raw.get("uploader") or "Colección"
            for suffix in (" - Videos", " - Shorts", " - Live", " - Streams", " - Directos", " - Vídeos"):
                if title.endswith(suffix):
                    title = title[:-len(suffix)].strip()

            channel = raw.get("channel") or raw.get("uploader") or title or "YouTube"
            thumbnail = raw.get("thumbnail")
            if not thumbnail and raw.get("thumbnails"):
                thumbnail = raw["thumbnails"][-1].get("url")
            if not thumbnail and entries:
                first = entries[0]
                thumbnail = first.get("thumbnail") or (first.get("thumbnails") or [{}])[-1].get("url")

            total_est_bytes = sum(tab_sizes.values())

            return {
                "type": url_type.value,
                "id": raw.get("id"),
                "title": title,
                "channel": channel,
                "channel_id": raw.get("channel_id") or raw.get("uploader_id") or "",
                "channel_url": raw.get("channel_url") or raw.get("uploader_url") or "",
                "thumbnail": thumbnail or "",
                "item_count": len(entries),
                "tab_counts": tab_counts,
                "tab_sizes": tab_sizes,
                "detected_tab": meta.get("detected_tab", "all"),
                "clean_url": meta.get("clean_url", raw.get("webpage_url") or ""),
                "is_playlist": True,
                "estimated_sizes": {"best": total_est_bytes, "default": total_est_bytes},
                "raw_info": raw,
                "_working_client": raw.get("_working_client"),
            }

        formats = raw.get("formats") or []
        duration = raw.get("duration") or 0

        best_audio_size = 0
        for f in formats:
            if f.get("vcodec") == "none" and f.get("acodec") != "none":
                a_size = f.get("filesize") or f.get("filesize_approx")
                if not a_size and duration and f.get("tbr"):
                    a_size = int(f.get("tbr") * 1000 * duration / 8)
                if a_size and a_size > best_audio_size:
                    best_audio_size = a_size

        if not best_audio_size and duration:
            best_audio_size = int(160 * 1000 * duration / 8)

        estimated_sizes: Dict[str, int] = {}
        available_resolutions: List[int] = []

        for f in formats:
            vcodec = f.get("vcodec")
            if vcodec and vcodec != "none":
                res = get_effective_resolution(f.get("width"), f.get("height"))
                if res:
                    if res not in available_resolutions:
                        available_resolutions.append(res)
                    v_size = f.get("filesize") or f.get("filesize_approx")
                    if not v_size and duration and f.get("tbr"):
                        v_size = int(f.get("tbr") * 1000 * duration / 8)
                    if v_size:
                        tot = v_size + best_audio_size
                        key = f"{res}p"
                        if key not in estimated_sizes or tot > estimated_sizes[key]:
                            estimated_sizes[key] = tot

        available_resolutions.sort(reverse=True)
        if available_resolutions:
            best_res_key = f"{available_resolutions[0]}p"
            estimated_sizes["best"] = estimated_sizes.get(best_res_key, 0)
        else:
            rate = 1300 if url_type == UrlType.SHORT else 2200
            estimated_sizes["best"] = int(duration * rate * 1000 / 8) if duration else 15 * 1024 * 1024

        estimated_sizes["audio"] = best_audio_size if best_audio_size > 0 else int(192 * 1000 * duration / 8)

        raw_chapters = raw.get("chapters") or []
        chapters = []
        for ch in raw_chapters:
            if isinstance(ch, dict):
                chapters.append({
                    "title": str(ch.get("title", "")).strip(),
                    "start_time": float(ch.get("start_time") or 0.0),
                    "end_time": float(ch.get("end_time") or 0.0),
                })

        return {
            "type": url_type.value,
            "id": raw.get("id"),
            "title": raw.get("title") or "Sin título",
            "channel": raw.get("uploader") or raw.get("channel") or "YouTube",
            "channel_id": raw.get("channel_id") or raw.get("uploader_id") or "",
            "channel_url": raw.get("channel_url") or raw.get("uploader_url") or "",
            "duration": duration,
            "upload_date": raw.get("upload_date") or "",
            "release_timestamp": raw.get("release_timestamp") or raw.get("timestamp"),
            "timestamp": raw.get("timestamp"),
            "description": raw.get("description") or "",
            "categories": raw.get("categories") or [],
            "tags": raw.get("tags") or [],
            "chapters": chapters,
            "chapters_count": len(chapters),
            "thumbnail": raw.get("thumbnail") or "",
            "resolutions": available_resolutions,
            "max_resolution": f"{available_resolutions[0]}p" if available_resolutions else "1080p",
            "estimated_sizes": estimated_sizes,
            "webpage_url": meta.get("clean_url") or raw.get("webpage_url") or "",
            "has_playlist": meta.get("has_playlist", False),
            "playlist_id": meta.get("playlist_id"),
            "playlist_url": meta.get("playlist_url"),
            "is_playlist": False,
            "raw_info": raw,
            "_working_client": raw.get("_working_client"),
        }
