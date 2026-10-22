import os
import re
import shutil
import time
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from PyQt6.QtCore import QThread, pyqtSignal

import yt_dlp
from downfry.config import config_manager, history_manager, record_archive_title
from downfry.core.organizer import PathOrganizer
from downfry.core.classifier import classify_youtube_url, normalize_channel_base_url, UrlType
from downfry.core.extractor import clean_ansi, CLIENT_FALLBACK_CHAIN, get_effective_resolution, _SilentYdlLogger
from datetime import datetime, timezone
from downfry.utils.formatting import (
    format_bytes,
    format_speed,
    format_seconds,
    sanitize_filename,
    extract_publication_timestamp,
    apply_publication_timestamps,
    parse_iso_date,
    compute_ratelimit_bytes,
)

def locate_ffmpeg() -> Optional[str]:
    import sys
    if hasattr(sys, "_MEIPASS"):
        meipass_ffmpeg = Path(sys._MEIPASS) / "ffmpeg.exe"
        if meipass_ffmpeg.exists():
            return str(meipass_ffmpeg)
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    local_appdata = Path(os.getenv("LOCALAPPDATA", ""))
    for c in [
        local_appdata / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe",
        Path.home() / "scoop" / "shims" / "ffmpeg.exe",
        Path("C:/ProgramData/chocolatey/bin/ffmpeg.exe"),
    ]:
        if c.exists():
            return str(c)
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return None

def detect_actual_quality_tag(info: Dict[str, Any], requested_quality: str, mode: str, audio_bitrate: str) -> str:
    if mode == "audio":
        return f"{audio_bitrate}k"
    formats = info.get("formats") or []
    resolutions = sorted(
        {
            get_effective_resolution(f.get("width"), f.get("height"))
            for f in formats
            if (f.get("height") or f.get("width")) and f.get("vcodec") != "none"
        } - {None},
        reverse=True,
    )
    if requested_quality != "best":
        req_res_str = requested_quality.replace("p", "").strip()
        if req_res_str.isdigit() and resolutions:
            req_res = int(req_res_str)
            matching = [r for r in resolutions if r <= req_res]
            if matching:
                return f"{matching[0]}p"
        return requested_quality
    if resolutions:
        return f"{resolutions[0]}p"
    eff = get_effective_resolution(info.get("width"), info.get("height"))
    if eff:
        return f"{eff}p"
    return "1080p"

class DownloadWorker(QThread):
    progress_changed = pyqtSignal(float, str, str, str)
    status_changed = pyqtSignal(str)
    task_started = pyqtSignal(str, str)
    batch_progress = pyqtSignal(int, int, str)
    item_completed = pyqtSignal(str)
    all_completed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        url: str,
        target_dir: str,
        mode: str = "video",
        quality: str = "best",
        audio_format: str = "mp3",
        audio_bitrate: str = "320",
        embed_subtitles: bool = True,
        embed_thumbnail: bool = True,
        include_videos: bool = True,
        include_shorts: bool = True,
        include_lives: bool = True,
        preloaded_info: Optional[Dict[str, Any]] = None,
        embed_metadata: Optional[bool] = None,
        embed_chapters: Optional[bool] = None,
        preserve_publish_date: Optional[bool] = None,
        speed_limit_value: Optional[float] = None,
        speed_limit_unit: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.url = url.strip()
        self.target_dir = Path(target_dir)
        self.mode = mode
        self.quality = quality
        self.audio_format = audio_format
        self.audio_bitrate = audio_bitrate
        self.embed_subtitles = embed_subtitles
        self.embed_thumbnail = embed_thumbnail
        self.include_videos = include_videos
        self.include_shorts = include_shorts
        self.include_lives = include_lives
        self.preloaded_info = preloaded_info

        self.embed_metadata = config_manager.get("embed_metadata", True) if embed_metadata is None else bool(embed_metadata)
        self.embed_chapters = config_manager.get("embed_chapters", True) if embed_chapters is None else bool(embed_chapters)
        self.preserve_publish_date = config_manager.get("preserve_publish_date", True) if preserve_publish_date is None else bool(preserve_publish_date)
        self.speed_limit_value = config_manager.get("speed_limit_value", 0) if speed_limit_value is None else speed_limit_value
        self.speed_limit_unit = config_manager.get("speed_limit_unit", "MB/s") if speed_limit_unit is None else speed_limit_unit

        self._is_cancelled = False
        self._last_downloaded_file: Optional[str] = None
        self._worker_id = f"{os.getpid()}_{id(self)}"

    def cancel(self):
        self._is_cancelled = True
        self.status_changed.emit("Cancelando descarga...")

    @staticmethod
    def _ensure_hidden_temp_dir(base_dir: Path, worker_id: Optional[str] = None) -> Path:
        temp_root = base_dir / ".temp"
        temp_root.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            try:
                import ctypes
                FILE_ATTRIBUTE_HIDDEN = 0x02
                ctypes.windll.kernel32.SetFileAttributesW(str(temp_root), FILE_ATTRIBUTE_HIDDEN)
            except Exception:
                pass
        if worker_id:
            worker_dir = temp_root / f"job_{worker_id}"
            worker_dir.mkdir(parents=True, exist_ok=True)
            return worker_dir
        return temp_root

    @staticmethod
    def _purge_temp_dir(temp_dir: Path):
        try:
            if temp_dir.exists():
                for item in temp_dir.iterdir():
                    try:
                        if item.is_file() or item.is_symlink():
                            item.unlink(missing_ok=True)
                        elif item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                    except Exception:
                        pass
                if temp_dir.name != ".temp":
                    try:
                        temp_dir.rmdir()
                    except Exception:
                        pass
                    parent = temp_dir.parent
                    if parent.name == ".temp":
                        try:
                            if not any(parent.iterdir()):
                                parent.rmdir()
                        except Exception:
                            pass
        except Exception:
            pass

    def _progress_hook(self, d: Dict[str, Any]):
        if self._is_cancelled:
            raise Exception("Descarga cancelada por el usuario.")
        status = d.get("status")
        if status == "downloading":
            total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            speed = d.get("speed") or 0
            eta = d.get("eta") or 0
            percent = (downloaded / total_bytes) * 100.0 if total_bytes > 0 else 0.0
            speed_str = format_speed(speed)
            eta_str = format_seconds(eta)
            size_str = f"{format_bytes(downloaded)} / {format_bytes(total_bytes)}"
            self.progress_changed.emit(percent, speed_str, eta_str, size_str)
            self.status_changed.emit(f"Descargando: {percent:.1f}% ({speed_str})")
        elif status == "finished":
            filename = d.get("filename")
            if filename:
                self._last_downloaded_file = str(filename)
            self.status_changed.emit("Uniendo video y audio en máxima calidad con FFmpeg...")

    def _postprocessor_hook(self, d: Dict[str, Any]):
        if d.get("status") == "finished":
            info = d.get("info_dict") or {}
            fp = info.get("filepath") or d.get("filepath")
            if fp and os.path.exists(fp):
                self._last_downloaded_file = str(fp)

    @staticmethod
    def build_format_spec(quality: str = "best", mode: str = "video") -> str:
        """Selector flexible con techo estricto para horizontal y vertical (Shorts, 21:9, 1:1, etc.)."""
        if mode == "audio":
            return "bestaudio/best"
        if quality == "best":
            return "bestvideo*+bestaudio/best"
        target_res = quality.replace("p", "").strip()
        if target_res.isdigit():
            t = int(target_res)
            return (
                f"bestvideo*[height<={t}]+bestaudio/"
                f"bestvideo*[width<={t}]+bestaudio/"
                f"best[height<={t}]/"
                f"best[width<={t}]"
            )
        return "bestvideo*+bestaudio/best"

    def _build_format_spec(self) -> str:
        return self.build_format_spec(self.quality, self.mode)

    def _build_ffmpeg_metadata_args(
        self,
        info: Optional[Dict[str, Any]],
        url: str,
        quality_tag: Optional[str] = None,
    ) -> List[str]:
        """Construye argumentos -metadata para FFmpeg reconocidos por VLC, Windows Explorer y Downfry."""
        if not info or not isinstance(info, dict):
            return []

        channel = (
            info.get("channel")
            or info.get("uploader")
            or info.get("creator")
            or "YouTube"
        )
        title = info.get("title") or ""
        vid_id = info.get("id") or ""
        channel_id = info.get("channel_id") or info.get("uploader_id") or ""
        channel_url = info.get("channel_url") or info.get("uploader_url") or ""
        description = info.get("description") or ""

        pub_ts = extract_publication_timestamp(info)
        if pub_ts and pub_ts > 0:
            dt_utc = datetime.fromtimestamp(pub_ts, timezone.utc)
            iso_date = dt_utc.strftime("%Y-%m-%d")
            creation_time_str = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            raw_date = str(info.get("upload_date") or "").strip()
            iso_date, _, _ = parse_iso_date(raw_date)
            creation_time_str = f"{iso_date}T12:00:00Z"

        categories = info.get("categories") or []
        genre = categories[0] if categories else "YouTube"
        q_tag = quality_tag or str(self.quality)

        meta_pairs = [
            ("artist", channel),
            ("album_artist", channel),
            ("author", channel),
            ("composer", channel),
            ("album", channel),
            ("title", title),
            ("date", iso_date),
            ("creation_time", creation_time_str),
            ("comment", f"{url} | ID: {vid_id}" if vid_id else url),
            ("purl", url),
            ("description", description[:1000] if description else ""),
            ("synopsis", description[:1000] if description else ""),
            ("genre", genre),
            ("downfry_video_id", vid_id),
            ("downfry_channel_id", channel_id),
            ("downfry_channel_url", channel_url),
            ("downfry_published_ts", str(int(pub_ts)) if pub_ts else ""),
            ("downfry_quality", q_tag),
        ]

        args = []
        for k, v in meta_pairs:
            if v:
                args.extend(["-metadata", f"{k}={v}"])
        return args

    def _extract_video_metadata_resilient(self, video_url: str) -> Optional[Dict[str, Any]]:
        """Obtiene metadatos en español probando clientes inmunes al bloqueo de bot."""
        for clients in CLIENT_FALLBACK_CHAIN:
            opts: Dict[str, Any] = {
                "quiet": True,
                "no_warnings": True,
                "no_color": True,
                "skip_download": True,
                "ignore_no_formats_error": True,
                "logger": _SilentYdlLogger(),
                "extractor_args": {
                    "youtube": {
                        "lang": ["es"],
                        "player_client": clients,
                    }
                },
            }
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(video_url, download=False)
                if info and (info.get("formats") or info.get("url")):
                    info["_working_client"] = clients
                    # Si el cliente ganador no trajo fecha de publicación, complementar con 'web' o 'tv'
                    if not extract_publication_timestamp(info):
                        for sup_client in (["web"], ["tv"], ["ios"]):
                            if sup_client == clients:
                                continue
                            try:
                                s_opts = dict(opts)
                                s_opts["extractor_args"] = {"youtube": {"lang": ["es"], "player_client": sup_client}}
                                with yt_dlp.YoutubeDL(s_opts) as ydl_s:
                                    s_info = ydl_s.extract_info(video_url, download=False)
                                if s_info:
                                    for k in ("upload_date", "release_date", "timestamp", "release_timestamp"):
                                        if s_info.get(k) and not info.get(k):
                                            info[k] = s_info[k]
                                    if extract_publication_timestamp(info):
                                        break
                            except Exception:
                                pass
                    return info
            except Exception:
                continue
        return None

    @staticmethod
    def _clone_ydl_opts(opts: Dict[str, Any]) -> Dict[str, Any]:
        cloned = dict(opts)
        for key in ("outtmpl", "paths", "extractor_args"):
            if isinstance(cloned.get(key), dict):
                cloned[key] = dict(cloned[key])
        for key in ("format_sort", "subtitleslangs", "progress_hooks", "postprocessor_hooks"):
            if isinstance(cloned.get(key), list):
                cloned[key] = list(cloned[key])
        if isinstance(cloned.get("postprocessors"), list):
            cloned["postprocessors"] = [dict(pp) for pp in cloned["postprocessors"]]
        return cloned

    def _execute_download_resilient(
        self,
        target_url: str,
        ydl_opts: Dict[str, Any],
        preferred_client: Optional[List[str]] = None,
    ):
        """Descarga probando la cadena de clientes; si falla solo por subtítulos (HTTP 429), reintenta sin subtítulos."""
        last_err = None

        chain = list(CLIENT_FALLBACK_CHAIN)
        if preferred_client and preferred_client in chain:
            chain.remove(preferred_client)
            chain.insert(0, preferred_client)

        for clients in chain:
            if self._is_cancelled:
                raise Exception("Descarga cancelada por el usuario.")

            try_opts = self._clone_ydl_opts(ydl_opts)
            try_opts["logger"] = _SilentYdlLogger()
            if clients != ["default"]:
                try_opts["extractor_args"] = {
                    "youtube": {
                        "lang": ["es"],
                        "player_client": clients,
                    }
                }
            else:
                try_opts["extractor_args"] = {"youtube": {"lang": ["es"]}}

            try:
                with yt_dlp.YoutubeDL(try_opts) as ydl:
                    ret = ydl.download([target_url])
                if ret == 0:
                    return
                last_err = Exception(f"No se pudo completar la descarga con el cliente {clients} (código {ret}).")
            except Exception as e:
                err_str = clean_ansi(str(e)).lower()
                if self._is_cancelled or "cancelada" in err_str:
                    raise e

                # Si el fallo fue exclusivamente al bajar subtítulos (ej. HTTP Error 429 Too Many Requests),
                # reintentar inmediatamente con este mismo cliente desactivando subtítulos para no abortar el video.
                is_sub_err = (
                    "subtitles" in err_str
                    or "timedtext" in err_str
                    or ("429" in err_str and try_opts.get("writesubtitles"))
                    or ("too many requests" in err_str and try_opts.get("writesubtitles"))
                )
                if is_sub_err:
                    self.status_changed.emit("Subtítulos limitados por YouTube (HTTP 429). Descargando video sin subtítulos...")
                    no_sub_opts = self._clone_ydl_opts(try_opts)
                    no_sub_opts["writesubtitles"] = False
                    no_sub_opts["writeautomaticsub"] = False
                    no_sub_opts.pop("subtitleslangs", None)
                    if "postprocessors" in no_sub_opts:
                        no_sub_opts["postprocessors"] = [
                            pp for pp in no_sub_opts["postprocessors"]
                            if pp.get("key") != "FFmpegEmbedSubtitle"
                        ]
                    try:
                        with yt_dlp.YoutubeDL(no_sub_opts) as ydl_nosub:
                            ret2 = ydl_nosub.download([target_url])
                        if ret2 == 0:
                            return
                    except Exception as e2:
                        if self._is_cancelled or "cancelada" in str(e2).lower():
                            raise e2
                        last_err = e2
                        continue

                last_err = e
                continue

        if last_err:
            raise last_err

    def run(self):
        try:
            self.status_changed.emit("Analizando enlace y preparando descarga...")
            url_type, meta = classify_youtube_url(self.url)
            if url_type in (UrlType.CHANNEL, UrlType.PLAYLIST):
                self._download_batch(url_type)
            else:
                clean_single_url = meta.get("clean_url", self.url)
                self._download_single(url_type, clean_single_url)
        except Exception as e:
            err_msg = clean_ansi(str(e))
            if "cancelada" in err_msg.lower():
                self.status_changed.emit("Descarga cancelada.")
            else:
                self.error_occurred.emit(f"Error durante la descarga: {err_msg}")

    @staticmethod
    def _resolve_unique_stem(target_dir: Path, base_stem: str, ext: str) -> str:
        """Si ya existe un archivo con el mismo nombre y calidad en disco, añade sufijo (2), (3)..."""
        candidate = target_dir / f"{base_stem}.{ext}"
        if not candidate.exists():
            return base_stem

        counter = 2
        while True:
            suffix = f" ({counter})"
            if len(base_stem) + len(suffix) > 230:
                truncated_base = base_stem[:230 - len(suffix)].rstrip(". ")
                candidate = target_dir / f"{truncated_base}{suffix}.{ext}"
                if not candidate.exists():
                    return f"{truncated_base}{suffix}"
            else:
                candidate = target_dir / f"{base_stem}{suffix}.{ext}"
                if not candidate.exists():
                    return f"{base_stem}{suffix}"
            counter += 1

    def _download_single(self, url_type: UrlType, target_url: str):
        info = None
        if self.preloaded_info:
            p_raw = self.preloaded_info.get("raw_info")
            if p_raw and (p_raw.get("formats") or p_raw.get("url")):
                info = p_raw
            elif self.preloaded_info.get("formats") or self.preloaded_info.get("url"):
                info = self.preloaded_info

        if not info:
            info = self._extract_video_metadata_resilient(target_url)

        if not info:
            raise ValueError("No se pudo obtener información del video.")

        title = info.get("title", "Video")
        thumbnail = info.get("thumbnail", "")
        vid_id = info.get("id")
        if vid_id and title:
            record_archive_title(vid_id, title)
        self.task_started.emit(title, thumbnail)

        preferred_client = info.get("_working_client") or (self.preloaded_info.get("_working_client") if self.preloaded_info else None)

        quality_tag = detect_actual_quality_tag(info, self.quality, self.mode, self.audio_bitrate)
        target_dir, base_file_stem, default_archive = PathOrganizer.get_output_paths(
            self.target_dir,
            info,
            download_type=url_type.value,
            quality_tag=quality_tag,
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = self._ensure_hidden_temp_dir(self.target_dir, self._worker_id)

        ext = "mp4" if self.mode == "video" else self.audio_format
        file_stem = self._resolve_unique_stem(target_dir, base_file_stem, ext)

        outtmpl = {
            "default": f"{file_stem}.%(ext)s",
            "subtitle": str(temp_dir / f"{file_stem}.%(ext)s"),
            "thumbnail": str(temp_dir / f"{file_stem}.%(ext)s"),
        }
        # En descarga individual NUNCA se pasa archive_path a ydl_opts para no bloquear la descarga
        ydl_opts = self._build_ydl_opts(
            outtmpl,
            archive_path=None,
            temp_dir=temp_dir,
            home_dir=target_dir,
            media_info=info,
        )

        try:
            self._execute_download_resilient(target_url, ydl_opts, preferred_client=preferred_client)
        finally:
            self._purge_temp_dir(temp_dir)

        if self._is_cancelled:
            return

        candidate_file = target_dir / f"{file_stem}.{ext}"

        final_path = None
        if self._last_downloaded_file and os.path.exists(self._last_downloaded_file) and not str(self._last_downloaded_file).startswith(str(temp_dir)) and os.path.getsize(self._last_downloaded_file) > 0:
            final_path = str(self._last_downloaded_file)
        elif candidate_file.exists() and candidate_file.stat().st_size > 0:
            final_path = str(candidate_file)

        if not final_path or not os.path.exists(final_path) or os.path.getsize(final_path) == 0:
            raise ValueError(f"No se pudo completar la descarga del archivo para '{title}'.")

        # Aplicar fecha de publicación en sistema de archivos (CreationTime y LastWriteTime)
        if self.preserve_publish_date:
            pub_ts = extract_publication_timestamp(info)
            if pub_ts:
                apply_publication_timestamps(final_path, pub_ts)

        # Sincronizar download_archive.txt solo al finalizar con éxito
        if config_manager.get("use_archive", True) and default_archive and vid_id:
            try:
                default_archive.parent.mkdir(parents=True, exist_ok=True)
                lines = default_archive.read_text(encoding="utf-8").splitlines() if default_archive.exists() else []
                if not any(l.strip().split()[-1] == vid_id for l in lines if l.strip().split()):
                    with open(default_archive, "a", encoding="utf-8") as f:
                        f.write(f"youtube {vid_id}\n")
            except Exception:
                pass

        self._record_history(
            title,
            final_path,
            thumbnail,
            quality_tag,
            video_id=vid_id,
            url=target_url,
            media_info=info,
        )
        self.item_completed.emit(final_path)
        self.all_completed.emit(str(target_dir))
        self.status_changed.emit(f"¡Guardado en: {final_path}!")

    @staticmethod
    def _scan_disk_media_files(root: Path) -> List[Path]:
        """Escanea todos los archivos multimedia existentes en la carpeta (excluyendo .temp y papelera)."""
        valid_exts = {".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".opus", ".flac", ".wav"}
        media_files = []
        if not root.exists():
            return media_files
        try:
            for p in root.rglob("*"):
                if p.is_file() and p.suffix.lower() in valid_exts:
                    if not any(part.startswith(".") or part.lower() in ("papelera", ".temp") for part in p.parts):
                        try:
                            if p.stat().st_size > 0:
                                media_files.append(p)
                        except Exception:
                            pass
        except Exception:
            pass
        return media_files

    @staticmethod
    def _is_item_already_on_disk(
        entry_title: str,
        entry_id: Optional[str],
        existing_files: List[Path],
        claimed_files: Optional[set] = None,
    ) -> Optional[Path]:
        """Comprueba con precisión si un video ya existe físicamente en disco."""
        if not existing_files:
            return None

        # 1. Coincidencia por ID en el nombre del archivo
        if entry_id:
            entry_id_clean = entry_id.strip()
            if len(entry_id_clean) >= 6:
                for f in existing_files:
                    if claimed_files and str(f) in claimed_files:
                        continue
                    if entry_id_clean in f.name:
                        return f

        # 2. Coincidencia por título sanitizado completo
        clean_title = sanitize_filename(entry_title).lower().strip()
        if not clean_title:
            return None

        norm_title = clean_title.replace("“", "").replace("”", "").replace('"', "").replace("'", "").replace("_", " ").strip()

        for f in existing_files:
            if claimed_files and str(f) in claimed_files:
                continue
            f_stem = f.stem.lower().replace("_", " ")

            # Coincidencia con el patrón estándar " - título ["
            if f" - {norm_title} [" in f_stem:
                return f

            # Extraer segmento de título entre "YYYY-MM-DD - " y " [calidad]"
            match = re.search(r"^\d{4}-\d{2}-\d{2}\s*-\s*(.+?)\s*\[", f_stem)
            if match:
                extracted = match.group(1).strip()
                if extracted == norm_title:
                    return f

            # Coincidencia exacta de tallo
            if norm_title == f_stem:
                return f

        return None

    def _collect_channel_tabs_entries(self, base_channel_url: str) -> Tuple[str, List[Tuple[str, Dict[str, Any]]]]:
        selected_tabs: List[Tuple[str, str]] = []
        if self.include_videos:
            selected_tabs.append(("Videos", f"{base_channel_url}/videos"))
        if self.include_shorts:
            selected_tabs.append(("Shorts", f"{base_channel_url}/shorts"))
        if self.include_lives:
            selected_tabs.append(("Directos", f"{base_channel_url}/streams"))

        channel_title = "Canal"
        items_to_download: List[Tuple[str, Dict[str, Any]]] = []
        seen_ids = set()

        for cat_name, tab_url in selected_tabs:
            if self._is_cancelled:
                break
            self.status_changed.emit(f"Explorando pestaña '{cat_name}' del canal...")
            tab_info = None
            for clients in CLIENT_FALLBACK_CHAIN:
                extract_opts: Dict[str, Any] = {
                    "quiet": True,
                    "no_warnings": True,
                    "no_color": True,
                    "extract_flat": "in_playlist",
                    "skip_download": True,
                    "logger": _SilentYdlLogger(),
                    "extractor_args": (
                        {"youtube": {"lang": ["es"], "player_client": clients}}
                        if clients != ["default"]
                        else {"youtube": {"lang": ["es"]}}
                    ),
                }
                try:
                    with yt_dlp.YoutubeDL(extract_opts) as ydl:
                        cand = ydl.extract_info(tab_url, download=False)
                    if cand:
                        cand["_working_client"] = clients
                        tab_info = cand
                        break
                except Exception:
                    continue

            try:
                if not tab_info:
                    continue

                raw_title = tab_info.get("channel") or tab_info.get("uploader") or tab_info.get("title") or channel_title
                for suffix in (" - Videos", " - Shorts", " - Live", " - Streams", " - Directos", " - Vídeos"):
                    if raw_title.endswith(suffix):
                        raw_title = raw_title[:-len(suffix)].strip()
                if raw_title:
                    channel_title = raw_title

                for entry in (tab_info.get("entries") or []):
                    if not entry:
                        continue
                    if entry.get("_type") == "playlist" or "entries" in entry:
                        for sub in (entry.get("entries") or []):
                            if sub and sub.get("id") not in seen_ids:
                                seen_ids.add(sub.get("id"))
                                items_to_download.append((cat_name, sub))
                    else:
                        vid_id = entry.get("id")
                        if vid_id and vid_id in seen_ids:
                            continue
                        if vid_id:
                            seen_ids.add(vid_id)
                        items_to_download.append((cat_name, entry))
            except Exception as e:
                print(f"[Downfry] Pestaña {cat_name} omitida o vacía: {clean_ansi(e)}")
                continue

        return channel_title, items_to_download

    def _download_batch(self, url_type: UrlType):
        items_to_download: List[Tuple[str, Dict[str, Any]]] = []

        if url_type == UrlType.CHANNEL:
            if not (self.include_videos or self.include_shorts or self.include_lives):
                raise ValueError("Debes seleccionar al menos una pestaña (Videos, Shorts o Directos).")
            base_channel_url, _ = normalize_channel_base_url(self.url)
            container_title, items_to_download = self._collect_channel_tabs_entries(base_channel_url)
        else:
            self.status_changed.emit("Recopilando lista de reproducción...")
            container_info = None
            pl_last_err = None
            for clients in CLIENT_FALLBACK_CHAIN:
                extract_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "no_color": True,
                    "extract_flat": "in_playlist",
                    "skip_download": True,
                    "logger": _SilentYdlLogger(),
                    "extractor_args": (
                        {"youtube": {"lang": ["es"], "player_client": clients}}
                        if clients != ["default"]
                        else {"youtube": {"lang": ["es"]}}
                    ),
                }
                try:
                    with yt_dlp.YoutubeDL(extract_opts) as ydl:
                        cand = ydl.extract_info(self.url, download=False)
                    if cand:
                        cand["_working_client"] = clients
                        container_info = cand
                        break
                except Exception as ex:
                    pl_last_err = ex
                    continue

            if not container_info:
                raise ValueError(clean_ansi(pl_last_err or "No se pudo obtener información de la playlist."))

            container_title = container_info.get("title") or container_info.get("channel") or "Playlist"
            for item in (container_info.get("entries") or []):
                if item:
                    items_to_download.append(("Videos", item))

        clean_container_name = sanitize_filename(container_title)
        channel_root = self.target_dir / clean_container_name
        channel_root.mkdir(parents=True, exist_ok=True)

        # Escanear directamente el disco para detectar qué archivos ya existen físicamente
        existing_disk_files = self._scan_disk_media_files(channel_root)

        total_items = len(items_to_download)
        if total_items == 0:
            raise ValueError("No se encontraron videos en las pestañas seleccionadas.")

        self.status_changed.emit(f"Descargando {total_items} elementos en '{channel_root}'...")

        claimed_disk_files = set()
        downloaded_count = 0
        skipped_count = 0
        failed_count = 0
        last_error_msg = ""
        temp_dir = self._ensure_hidden_temp_dir(self.target_dir, self._worker_id)

        for idx, (forced_cat, entry) in enumerate(items_to_download, 1):
            if self._is_cancelled:
                break

            self._last_downloaded_file = None
            entry_id = entry.get("id")
            if entry_id:
                entry_url = f"https://www.youtube.com/watch?v={entry_id}"
            else:
                entry_url = entry.get("webpage_url") or entry.get("url") or ""

            if not entry_url:
                continue

            entry_title = entry.get("title", f"Elemento #{idx}")

            # 1. Comprobación estricta en disco: si ya existe el archivo físico no reclamado, omitir sin peticiones de red
            matched_disk_file = self._is_item_already_on_disk(entry_title, entry_id, existing_disk_files, claimed_files=claimed_disk_files)
            if matched_disk_file and matched_disk_file.exists() and matched_disk_file.stat().st_size > 0:
                claimed_disk_files.add(str(matched_disk_file))
                skipped_count += 1
                self.batch_progress.emit(idx, total_items, f"[{forced_cat}] {entry_title} (Ya en disco)")
                self.status_changed.emit(f"[{idx}/{total_items}] Omitiendo (ya existe en disco): {entry_title}")
                q_match = re.search(r"\[(\d+p|\d+kbps|best)\]", matched_disk_file.stem, re.IGNORECASE)
                disk_quality = q_match.group(1) if q_match else str(self.quality)
                self._record_history(
                    entry_title,
                    str(matched_disk_file),
                    entry.get("thumbnail") or "",
                    disk_quality,
                    video_id=entry_id,
                    url=entry_url,
                    media_info=entry,
                )
                continue

            self.batch_progress.emit(idx, total_items, f"[{forced_cat}] {entry_title}")
            self.status_changed.emit(f"[{idx}/{total_items}] Analizando: {entry_title}")

            video_info = self._extract_video_metadata_resilient(entry_url) or entry
            item_title = video_info.get("title") or entry_title
            item_thumbnail = video_info.get("thumbnail") or entry.get("thumbnail") or ""
            target_vid_id = video_info.get("id") or entry_id
            if target_vid_id and item_title:
                record_archive_title(target_vid_id, item_title)

            quality_tag = detect_actual_quality_tag(video_info, self.quality, self.mode, self.audio_bitrate)
            target_folder, file_stem, _ = PathOrganizer.get_output_paths(
                self.target_dir,
                video_info,
                download_type=url_type.value,
                playlist_title=container_title if url_type == UrlType.PLAYLIST else None,
                channel_name=container_title if url_type == UrlType.CHANNEL else None,
                quality_tag=quality_tag,
                forced_category=forced_cat if url_type == UrlType.CHANNEL else None,
            )
            target_folder.mkdir(parents=True, exist_ok=True)

            # 2. Comprobar candidate_file: si existe pero YA fue reclamado por otro video, resolver nombre único (2)
            ext = "mp4" if self.mode == "video" else self.audio_format
            candidate_file = target_folder / f"{file_stem}.{ext}"
            if candidate_file.exists() and candidate_file.stat().st_size > 0:
                if str(candidate_file) in claimed_disk_files:
                    file_stem = self._resolve_unique_stem(target_folder, file_stem, ext)
                    candidate_file = target_folder / f"{file_stem}.{ext}"
                else:
                    claimed_disk_files.add(str(candidate_file))
                    skipped_count += 1
                    self.batch_progress.emit(idx, total_items, f"[{forced_cat}] {item_title} (Ya en disco)")
                    self.status_changed.emit(f"[{idx}/{total_items}] Omitiendo (ya existe en disco): {item_title}")
                    self._record_history(
                        item_title,
                        str(candidate_file),
                        item_thumbnail,
                        quality_tag,
                        video_id=target_vid_id,
                        url=entry_url,
                        media_info=video_info,
                    )
                    continue

            outtmpl = {
                "default": f"{file_stem}.%(ext)s",
                "subtitle": str(temp_dir / f"{file_stem}.%(ext)s"),
                "thumbnail": str(temp_dir / f"{file_stem}.%(ext)s"),
            }
            # En descargas de canal/lote no usamos archive_path: la verdad reside 100% en los archivos físicos del disco
            ydl_opts = self._build_ydl_opts(
                outtmpl,
                archive_path=None,
                temp_dir=temp_dir,
                home_dir=target_folder,
                media_info=video_info,
            )

            try:
                preferred_client = video_info.get("_working_client") if isinstance(video_info, dict) else None
                self._execute_download_resilient(entry_url, ydl_opts, preferred_client=preferred_client)
                final_f = None
                if candidate_file.exists() and candidate_file.stat().st_size > 0:
                    final_f = str(candidate_file)
                elif self._last_downloaded_file and os.path.exists(self._last_downloaded_file) and not str(self._last_downloaded_file).startswith(str(temp_dir)) and os.path.getsize(self._last_downloaded_file) > 0:
                    final_f = str(self._last_downloaded_file)
                else:
                    recent = [
                        p for p in target_folder.glob(f"*{file_stem[:20]}*.{ext}")
                        if p.is_file() and p.stat().st_size > 0
                    ]
                    if recent:
                        final_f = str(sorted(recent, key=lambda p: p.stat().st_mtime, reverse=True)[0])

                if not final_f or not os.path.exists(final_f) or os.path.getsize(final_f) == 0:
                    raise ValueError(f"No se generó el archivo de video/audio en disco.")

                # Aplicar fecha de publicación en sistema de archivos (CreationTime y LastWriteTime)
                if self.preserve_publish_date:
                    pub_ts = extract_publication_timestamp(video_info)
                    if pub_ts:
                        apply_publication_timestamps(final_f, pub_ts)

                downloaded_count += 1
                claimed_disk_files.add(str(final_f))
                existing_disk_files.append(Path(final_f))
                self._record_history(
                    item_title,
                    final_f,
                    item_thumbnail,
                    quality_tag,
                    video_id=target_vid_id,
                    url=entry_url,
                    media_info=video_info,
                )
                self.item_completed.emit(final_f)
            except Exception as item_err:
                if self._is_cancelled:
                    break
                failed_count += 1
                last_error_msg = clean_ansi(str(item_err))
                print(f"[Downfry] Error descargando elemento {idx} ({item_title}): {last_error_msg}")
                continue
            finally:
                self._purge_temp_dir(temp_dir)

        total_done = downloaded_count + skipped_count
        if self._is_cancelled:
            self.status_changed.emit("Descarga de la lista/canal detenida por el usuario.")
        elif total_done == 0 and failed_count > 0:
            raise ValueError(f"No se pudo descargar ningún video (0/{total_items}). Último error: {last_error_msg}")
        else:
            self.all_completed.emit(str(channel_root))
            if failed_count == 0:
                self.status_changed.emit(f"¡Completados {total_items} de {total_items} ({downloaded_count} nuevos, {skipped_count} ya en disco)!")
            else:
                self.status_changed.emit(f"Finalizado: {total_done}/{total_items} listos ({failed_count} fallaron: {last_error_msg})")

    def _build_ydl_opts(
        self,
        outtmpl: Any,
        archive_path: Optional[Path] = None,
        temp_dir: Optional[Path] = None,
        home_dir: Optional[Path] = None,
        media_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ydl_opts: Dict[str, Any] = {
            "outtmpl": outtmpl,
            "format": self._build_format_spec(),
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._postprocessor_hook],
            "quiet": True,
            "no_warnings": True,
            "no_color": True,
            "windowsfilenames": True,
            "concurrent_fragment_downloads": 4,
            "retries": 10,
            "fragment_retries": 10,
            "ignoreerrors": False,
        }

        ratelimit = compute_ratelimit_bytes(self.speed_limit_value, self.speed_limit_unit)
        if ratelimit and ratelimit > 0:
            ydl_opts["ratelimit"] = ratelimit

        if temp_dir:
            paths_dict = {"temp": str(temp_dir)}
            if home_dir:
                paths_dict["home"] = str(home_dir)
            ydl_opts["paths"] = paths_dict

        ffmpeg_exe = locate_ffmpeg()
        if ffmpeg_exe:
            ydl_opts["ffmpeg_location"] = ffmpeg_exe

        if self.mode == "video":
            if self.quality == "best":
                ydl_opts["format_sort"] = [
                    "res",
                    "vcodec:h264,vp9,av01",
                    "acodec:m4a,aac,mp3,opus",
                    "ext:mp4:m4a",
                ]
            else:
                h_str = self.quality.replace("p", "").strip()
                if h_str.isdigit():
                    ydl_opts["format_sort"] = [
                        f"res:{h_str}",
                        "vcodec:h264,vp9,av01",
                        "acodec:m4a,aac,mp3,opus",
                        "ext:mp4:m4a",
                    ]

        if archive_path:
            ydl_opts["download_archive"] = str(archive_path)

        # Construcción ordenada y completa de postprocessors
        postprocessors: List[Dict[str, Any]] = []

        if self.mode == "audio":
            postprocessors.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": self.audio_format,
                "preferredquality": self.audio_bitrate,
            })
        else:
            ydl_opts["merge_output_format"] = "mp4"

        # Incrustación de metadatos enriquecidos y capítulos
        if self.embed_metadata or self.embed_chapters:
            postprocessors.append({
                "key": "FFmpegMetadata",
                "add_metadata": bool(self.embed_metadata),
                "add_chapters": bool(self.embed_chapters),
                "add_infojson": False,
            })
            if self.embed_metadata and media_info:
                meta_args = self._build_ffmpeg_metadata_args(media_info, self.url)
                if meta_args:
                    ydl_opts["postprocessor_args"] = {
                        "ffmpegmetadata": meta_args,
                        "FFmpegMetadata": meta_args,
                    }

        if self.embed_subtitles and self.mode == "video":
            ydl_opts["writesubtitles"] = True
            ydl_opts["writeautomaticsub"] = False
            ydl_opts["subtitleslangs"] = ["es.*", "en.*"]
            postprocessors.append({"key": "FFmpegEmbedSubtitle"})

        if self.embed_thumbnail or self.mode == "audio":
            ydl_opts["writethumbnail"] = True
            postprocessors.append({
                "key": "FFmpegThumbnailsConvertor",
                "format": "jpg",
            })
            postprocessors.append({"key": "EmbedThumbnail"})

        ydl_opts["postprocessors"] = postprocessors
        return ydl_opts

    def _record_history(
        self,
        title: str,
        filepath: str,
        thumbnail: str,
        quality_tag: str,
        video_id: Optional[str] = None,
        url: Optional[str] = None,
        media_info: Optional[Dict[str, Any]] = None,
    ):
        try:
            size_bytes = os.path.getsize(filepath) if (filepath and os.path.exists(filepath)) else 0
        except Exception:
            size_bytes = 0

        mode_str = str(self.mode) if self.mode in ("video", "audio") else "video"

        pub_ts = extract_publication_timestamp(media_info) if media_info else None
        chapters = media_info.get("chapters") or [] if media_info else []
        duration = media_info.get("duration") or 0 if media_info else 0
        uploader = (
            (media_info.get("uploader") or media_info.get("channel") or "")
            if media_info else ""
        )
        upload_date = (media_info.get("upload_date") or "") if media_info else ""

        history_manager.add_entry({
            "title": str(title),
            "filepath": str(filepath),
            "thumbnail": str(thumbnail or ""),
            "size": size_bytes,
            "size_str": format_bytes(size_bytes),
            "date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mode": mode_str,
            "quality": str(quality_tag if mode_str == "video" else f"{self.audio_bitrate}k ({self.audio_format})"),
            "video_id": str(video_id or ""),
            "url": str(url or self.url or ""),
            "uploader": str(uploader),
            "upload_date": str(upload_date),
            "published_ts": pub_ts,
            "duration": duration,
            "chapters": chapters,
        })
