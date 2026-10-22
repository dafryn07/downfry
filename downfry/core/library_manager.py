import os
import re
import json
import time
import shutil
import hashlib
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from downfry.config import APPDATA_DIR, config_manager, history_manager, DEFAULT_DOWNLOAD_DIR
from downfry.core.downloader import locate_ffmpeg
from downfry.utils.formatting import parse_iso_date, format_bytes, format_seconds, sanitize_filename, SPANISH_MONTHS


class PlaybackProgressManager:
    """Gestiona de forma atómica y segura entre hilos la memoria de reproducción de videos."""

    def __init__(self, progress_file: Optional[Path] = None):
        self._lock = threading.Lock()
        self.progress_file = progress_file or (APPDATA_DIR / "playback_progress.json")
        self._progress: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        with self._lock:
            if self.progress_file.exists():
                try:
                    with open(self.progress_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            self._progress = data
                except Exception as e:
                    print(f"[PlaybackProgressManager] Error cargando progreso: {e}")
                    self._progress = {}
            else:
                self._progress = {}

    def _save(self):
        tmp_file = self.progress_file.with_suffix(".tmp")
        try:
            self.progress_file.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self._progress, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, self.progress_file)
        except Exception as e:
            print(f"[PlaybackProgressManager] Error guardando progreso: {e}")
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass

    def update_progress(
        self,
        video_id: str,
        filepath: str,
        position_sec: float,
        duration_sec: float,
    ) -> Dict[str, Any]:
        """Calcula el ratio y estado de finalización, y guarda el progreso por video_id y por ruta."""
        norm_path = os.path.normpath(str(filepath)) if filepath else ""
        pos = max(0.0, float(position_sec or 0.0))
        dur = max(0.0, float(duration_sec or 0.0))

        ratio = min(1.0, max(0.0, pos / dur)) if dur > 0 else 0.0
        completed = (ratio >= 0.95) or (dur > 0 and (dur - pos) <= 10.0)

        record: Dict[str, Any] = {
            "position_sec": round(pos, 2),
            "duration_sec": round(dur, 2),
            "ratio": round(ratio, 4),
            "completed": bool(completed),
            "updated_at": time.time(),
            "video_id": str(video_id or "").strip(),
            "filepath": norm_path,
        }

        with self._lock:
            vid = record["video_id"]
            if vid:
                self._progress[f"id:{vid}"] = record
            if norm_path:
                self._progress[f"path:{norm_path.lower()}"] = record
            self._save()

        return record

    def get_progress(self, video_id: str = "", filepath: str = "") -> Dict[str, Any]:
        """Obtiene el progreso registrado por video_id o filepath. Retorna valores por defecto si no existe."""
        norm_path = os.path.normpath(str(filepath)).lower() if filepath else ""
        vid = str(video_id or "").strip()

        with self._lock:
            if vid and f"id:{vid}" in self._progress:
                return dict(self._progress[f"id:{vid}"])
            if norm_path and f"path:{norm_path}" in self._progress:
                return dict(self._progress[f"path:{norm_path}"])

        return {
            "position_sec": 0.0,
            "duration_sec": 0.0,
            "ratio": 0.0,
            "completed": False,
            "updated_at": 0.0,
            "video_id": vid,
            "filepath": norm_path,
        }

    def clear_progress(self, video_id: str = "", filepath: str = ""):
        """Elimina el registro de progreso para el video especificado."""
        norm_path = os.path.normpath(str(filepath)).lower() if filepath else ""
        vid = str(video_id or "").strip()

        with self._lock:
            modified = False
            if vid and f"id:{vid}" in self._progress:
                del self._progress[f"id:{vid}"]
                modified = True
            if norm_path and f"path:{norm_path}" in self._progress:
                del self._progress[f"path:{norm_path}"]
                modified = True
            if modified:
                self._save()


playback_progress_manager = PlaybackProgressManager()


class OfflineLibraryManager:
    """Motor de biblioteca offline que escanea, clasifica y gestiona los medios descargados."""

    VALID_MEDIA_EXTS = {".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".opus", ".flac", ".wav"}
    AUDIO_EXTS = {".mp3", ".m4a", ".opus", ".flac", ".wav"}
    EXCLUDED_FOLDERS = {"Papelera", ".recycle_bin", ".temp", "thumbs_cache", "__pycache__"}

    def __init__(self):
        self._cache_dir = APPDATA_DIR / "thumbs_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._duration_cache_file = self._cache_dir / "media_duration_cache.json"
        self._duration_cache: Dict[str, float] = self._load_duration_cache()

    def _load_duration_cache(self) -> Dict[str, float]:
        if self._duration_cache_file.exists():
            try:
                with open(self._duration_cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return {str(k).lower(): float(v) for k, v in data.items() if isinstance(v, (int, float))}
            except Exception as e:
                print(f"[OfflineLibraryManager] Error cargando caché de duración: {e}")
        return {}

    def _save_duration_cache(self):
        tmp_file = self._duration_cache_file.with_suffix(".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self._duration_cache, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, self._duration_cache_file)
        except Exception as e:
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass

    def scan_library(self, download_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """Escanea recursivamente el directorio de descargas, cruza con history.json y parsea metadatos."""
        base_dir_str = download_dir or config_manager.get("download_dir", str(DEFAULT_DOWNLOAD_DIR))
        base_path = Path(base_dir_str)
        if not base_path.exists():
            return []

        # Indexar historial actual por filepath normalizado y por video_id
        hist_by_path: Dict[str, Dict[str, Any]] = {}
        hist_by_id: Dict[str, Dict[str, Any]] = {}
        for h in history_manager.history:
            fp = h.get("filepath")
            vid = h.get("video_id")
            if fp:
                hist_by_path[os.path.normpath(str(fp)).lower()] = h
            if vid:
                hist_by_id[str(vid).strip()] = h

        items: List[Dict[str, Any]] = []
        cache_modified = False

        try:
            for entry in base_path.rglob("*"):
                if entry.is_dir():
                    continue

                # Excluir carpetas especiales
                rel_parts = entry.relative_to(base_path).parts
                if any(p in self.EXCLUDED_FOLDERS for p in rel_parts):
                    continue

                # Excluir archivos temporales o no multimedia
                if entry.name.startswith(".") or entry.name.endswith(".part") or entry.name.endswith(".ytdl"):
                    continue
                if entry.suffix.lower() not in self.VALID_MEDIA_EXTS:
                    continue

                try:
                    file_size = entry.stat().st_size
                except Exception:
                    continue
                if file_size == 0:
                    continue

                norm_fp = os.path.normpath(str(entry))
                norm_fp_lower = norm_fp.lower()
                hist_match = hist_by_path.get(norm_fp_lower)

                parsed_meta = self._parse_file_path(entry, base_path)

                # Si coincide con historial, usar sus datos enriqueciendo lo que falte
                if hist_match:
                    video_id = hist_match.get("video_id") or parsed_meta.get("video_id", "")
                    title = hist_match.get("title") or parsed_meta.get("title", entry.stem)
                    uploader = (
                        hist_match.get("uploader")
                        or hist_match.get("channel")
                        or parsed_meta.get("uploader")
                        or "YouTube"
                    )
                    upload_date = (
                        hist_match.get("upload_date")
                        or parsed_meta.get("iso_date")
                        or parsed_meta.get("upload_date")
                        or hist_match.get("date", "")
                    )
                    iso_date, year, month_folder = parse_iso_date(parsed_meta.get("iso_date") or upload_date)
                    quality = hist_match.get("quality") or parsed_meta.get("quality", "")
                    duration = float(hist_match.get("duration") or parsed_meta.get("duration") or 0.0)
                    thumbnail = hist_match.get("thumbnail") or parsed_meta.get("thumbnail", "")
                    chapters = hist_match.get("chapters") or parsed_meta.get("chapters", [])
                    description = hist_match.get("description") or parsed_meta.get("description", "")
                    playlist = hist_match.get("playlist") or parsed_meta.get("playlist", "")
                    category = parsed_meta.get("category") or ("Audio" if entry.suffix.lower() in self.AUDIO_EXTS else "Videos")
                else:
                    video_id = parsed_meta.get("video_id", "")
                    title = parsed_meta.get("title", entry.stem)
                    uploader = parsed_meta.get("uploader", "YouTube")
                    upload_date = parsed_meta.get("upload_date", "")
                    iso_date = parsed_meta.get("iso_date", "")
                    year = parsed_meta.get("year", "")
                    month_folder = parsed_meta.get("month_folder", "")
                    quality = parsed_meta.get("quality", "")
                    duration = float(parsed_meta.get("duration", 0.0))
                    thumbnail = parsed_meta.get("thumbnail", "")
                    chapters = parsed_meta.get("chapters", [])
                    description = parsed_meta.get("description", "")
                    playlist = parsed_meta.get("playlist", "")
                    category = parsed_meta.get("category", "Videos")

                # Asegurar duración: si es 0, buscar en caché de disco o extraer con ffmpeg
                if duration <= 0:
                    if norm_fp_lower in self._duration_cache:
                        duration = self._duration_cache[norm_fp_lower]
                    else:
                        probed_dur = self._get_duration_fast(norm_fp)
                        if probed_dur > 0:
                            duration = probed_dur
                            self._duration_cache[norm_fp_lower] = probed_dur
                            cache_modified = True

                # Obtener progreso actual
                progress = playback_progress_manager.get_progress(video_id=video_id, filepath=norm_fp)

                # Miniatura local
                local_thumb = self.get_cached_thumbnail_path(norm_fp, video_id)

                item: Dict[str, Any] = {
                    "video_id": video_id,
                    "title": title,
                    "filepath": norm_fp,
                    "uploader": uploader,
                    "channel": uploader,
                    "upload_date": upload_date,
                    "iso_date": iso_date,
                    "year": year,
                    "month_folder": month_folder,
                    "category": category,
                    "playlist": playlist,
                    "quality": quality,
                    "duration": duration,
                    "duration_str": format_seconds(duration) if duration > 0 else "",
                    "size": file_size,
                    "size_str": format_bytes(file_size),
                    "thumbnail": thumbnail,
                    "local_thumbnail": local_thumb,
                    "chapters": chapters,
                    "description": description,
                    "progress": progress,
                }
                items.append(item)
        except Exception as e:
            print(f"[OfflineLibraryManager] Error escaneando biblioteca: {e}")

        if cache_modified:
            self._save_duration_cache()

        # Ordenar por fecha ISO descendente (más nuevos primero), luego título
        items.sort(key=lambda x: (x.get("iso_date") or "", x.get("title") or ""), reverse=True)
        return items

    def _get_duration_fast(self, filepath: str) -> float:
        """Obtiene rápidamente la duración usando probe_media_details."""
        probed = self.probe_media_details(filepath)
        dur = float(probed.get("duration") or 0.0)
        return dur if dur > 0 else 0.0

    def _parse_file_path(self, file_path: Path, base_path: Path) -> Dict[str, Any]:
        """Deduce metadatos a partir de la estructura de carpetas y convención de nombres."""
        stem = file_path.stem
        ext = file_path.suffix.lower()

        rel_parts = file_path.relative_to(base_path).parts
        channel = ""
        playlist = ""
        year = ""
        month_folder = ""
        category = "Audio" if ext in self.AUDIO_EXTS else "Videos"

        # Análisis de jerarquía de directorios
        # Caso 1: Canal / Año / Mes / Categoría / Archivo
        # Caso 2: Canal / Año / Mes / Archivo
        # Caso 3: Playlist / Archivo
        if len(rel_parts) >= 2:
            first_dir = rel_parts[0]
            if len(rel_parts) >= 4 and rel_parts[1].isdigit() and len(rel_parts[1]) == 4:
                channel = first_dir
                year = rel_parts[1]
                month_folder = rel_parts[2]
                if len(rel_parts) >= 5:
                    cat_candidate = rel_parts[3]
                    if cat_candidate in ("Videos", "Shorts", "Directos", "Audio"):
                        category = cat_candidate
            elif len(rel_parts) == 2:
                # Podría ser Playlist o Canal directo
                playlist = first_dir
            elif len(rel_parts) == 3 and rel_parts[1].isdigit() and len(rel_parts[1]) == 4:
                channel = first_dir
                year = rel_parts[1]

        # Análisis de nombre de archivo estándar:
        # YYYY-MM-DD - Título [Calidad] - Canal
        iso_date = ""
        title = stem
        quality = ""

        # 1. Extraer fecha ISO inicial: ^(\d{4}-\d{2}-\d{2})\s*-\s*(.+)
        date_match = re.match(r"^(\d{4}-\d{2}-\d{2})\s*-\s*(.+)$", stem)
        if date_match:
            iso_date = date_match.group(1)
            rest = date_match.group(2)
            y, m, d = iso_date.split("-")
            year = year or y
            month_folder = month_folder or SPANISH_MONTHS.get(int(m), m)
        else:
            rest = stem

        # 2. Extraer calidad: \[([0-9]+p|[0-9]+k|Auto|best)\]
        q_match = re.search(r"\[([0-9]+p|[0-9]+k|Auto|best)\]", rest, re.IGNORECASE)
        if q_match:
            quality = q_match.group(1)
            # Quitar calidad del título
            rest = rest[: q_match.start()] + rest[q_match.end() :]
            rest = re.sub(r"\s+", " ", rest).strip()

        # 3. Extraer canal final: -\s*([^\-]+)$
        if " - " in rest:
            parts = rest.rsplit(" - ", 1)
            title = parts[0].strip()
            ch_suffix = parts[1].strip()
            if not channel and ch_suffix:
                channel = ch_suffix
        else:
            title = rest.strip()

        # Detección de Shorts si está en la URL o en el nombre o carpeta
        if "short" in stem.lower() or "shorts" in [p.lower() for p in rel_parts]:
            if category != "Audio":
                category = "Shorts"

        return {
            "title": title or stem,
            "uploader": channel or "YouTube",
            "channel": channel or "YouTube",
            "iso_date": iso_date,
            "year": year,
            "month_folder": month_folder,
            "quality": quality,
            "category": category,
            "playlist": playlist,
            "duration": 0,
            "thumbnail": "",
            "chapters": [],
            "description": "",
            "video_id": "",
            "upload_date": iso_date.replace("-", "") if iso_date else "",
        }

    def get_channels(self, items: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Retorna lista ordenada de canales con el número de elementos descargados."""
        if items is None:
            items = self.scan_library()

        channels_map: Dict[str, List[Dict[str, Any]]] = {}
        for it in items:
            ch_name = (it.get("channel") or it.get("uploader") or "YouTube").strip()
            if not ch_name:
                ch_name = "Desconocido"
            if ch_name not in channels_map:
                channels_map[ch_name] = []
            channels_map[ch_name].append(it)

        result = [
            {"name": name, "count": len(ch_items), "items": ch_items}
            for name, ch_items in channels_map.items()
        ]
        # Ordenar canales por cantidad de videos descendente, luego nombre
        result.sort(key=lambda x: (-x["count"], x["name"].lower()))
        return result

    def get_playlists(self, items: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Retorna lista ordenada de playlists con sus elementos."""
        if items is None:
            items = self.scan_library()

        playlists_map: Dict[str, List[Dict[str, Any]]] = {}
        for it in items:
            pl_name = (it.get("playlist") or "").strip()
            if pl_name:
                if pl_name not in playlists_map:
                    playlists_map[pl_name] = []
                playlists_map[pl_name].append(it)

        result = [
            {"name": name, "count": len(pl_items), "items": pl_items}
            for name, pl_items in playlists_map.items()
        ]
        result.sort(key=lambda x: (-x["count"], x["name"].lower()))
        return result

    def _get_thumb_cache_path(self, filepath: str, video_id: str = "") -> Path:
        key = str(video_id).strip()
        if not key:
            key = hashlib.md5(os.path.normpath(filepath).lower().encode("utf-8")).hexdigest()
        return self._cache_dir / f"{key}.jpg"

    def get_cached_thumbnail_path(self, filepath: str, video_id: str = "") -> Optional[str]:
        """Retorna la ruta a la miniatura local en caché si ya existe."""
        p = self._get_thumb_cache_path(filepath, video_id)
        if p.exists() and p.stat().st_size > 0:
            return str(p)
        return None

    def ensure_local_thumbnail(self, filepath: str, video_id: str = "") -> Optional[str]:
        """Extrae la miniatura del video o audio con FFmpeg si no existe en caché."""
        thumb_path = self._get_thumb_cache_path(filepath, video_id)
        if thumb_path.exists() and thumb_path.stat().st_size > 0:
            return str(thumb_path)

        if not filepath or not os.path.exists(filepath):
            return None

        ffmpeg_exe = locate_ffmpeg()
        if not ffmpeg_exe:
            return None

        ext = Path(filepath).suffix.lower()
        is_audio = ext in self.AUDIO_EXTS

        # 1. Intentar extraer carátula adjunta (attached_pic)
        # En audios (MP3/M4A/FLAC), la carátula embebida suele estar en 0:v:0
        maps_to_try = ["0:v:0", "0:v:1"] if is_audio else ["0:v:1", "0:v:0"]
        for stream_map in maps_to_try:
            try:
                cmd1 = [
                    ffmpeg_exe,
                    "-y",
                    "-i",
                    filepath,
                    "-map",
                    stream_map,
                    "-vframes",
                    "1",
                    "-q:v",
                    "2",
                    str(thumb_path),
                ]
                res1 = subprocess.run(cmd1, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if res1.returncode == 0 and thumb_path.exists() and thumb_path.stat().st_size > 0:
                    return str(thumb_path)
            except Exception:
                pass

        if not is_audio:
            # 2. Intentar capturar fotograma en el segundo 3
            try:
                cmd2 = [
                    ffmpeg_exe,
                    "-y",
                    "-ss",
                    "00:00:03",
                    "-i",
                    filepath,
                    "-vframes",
                    "1",
                    "-vf",
                    "scale=480:-1",
                    "-q:v",
                    "2",
                    str(thumb_path),
                ]
                res2 = subprocess.run(cmd2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if res2.returncode == 0 and thumb_path.exists() and thumb_path.stat().st_size > 0:
                    return str(thumb_path)
            except Exception:
                pass

            # 3. Fallback: fotograma en el segundo 0 (para videos o shorts muy breves)
            try:
                cmd3 = [
                    ffmpeg_exe,
                    "-y",
                    "-ss",
                    "00:00:00",
                    "-i",
                    filepath,
                    "-vframes",
                    "1",
                    "-vf",
                    "scale=480:-1",
                    "-q:v",
                    "2",
                    str(thumb_path),
                ]
                res3 = subprocess.run(cmd3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if res3.returncode == 0 and thumb_path.exists() and thumb_path.stat().st_size > 0:
                    return str(thumb_path)
            except Exception:
                pass

        return None

    def probe_media_details(self, filepath: str) -> Dict[str, Any]:
        """Usa ffprobe o ffmpeg -i para extraer duración, capítulos y pistas de audio/subtítulos del archivo físico."""
        if not filepath or not os.path.exists(filepath):
            return {}

        ffmpeg_exe = locate_ffmpeg()
        if not ffmpeg_exe:
            return {}

        ffprobe_exe = str(Path(ffmpeg_exe).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe"))
        if not os.path.exists(ffprobe_exe):
            ffprobe_exe = shutil.which("ffprobe")

        # 1. Si ffprobe existe, usar salida JSON estructurada
        if ffprobe_exe and os.path.exists(ffprobe_exe):
            try:
                cmd = [
                    ffprobe_exe,
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_format",
                    "-show_chapters",
                    "-show_streams",
                    filepath,
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=12, encoding="utf-8", errors="ignore")
                if res.returncode == 0 and res.stdout.strip():
                    data = json.loads(res.stdout)
                    fmt = data.get("format", {})
                    duration = float(fmt.get("duration", 0.0))

                    raw_chapters = data.get("chapters", [])
                    chapters: List[Dict[str, Any]] = []
                    for ch in raw_chapters:
                        tags = ch.get("tags", {})
                        ch_title = tags.get("title") or tags.get("TITLE") or f"Capítulo {len(chapters) + 1}"
                        start_sec = float(ch.get("start_time", 0.0))
                        end_sec = float(ch.get("end_time", 0.0))
                        chapters.append({
                            "title": ch_title,
                            "start_time": start_sec,
                            "end_time": end_sec,
                        })

                    streams = data.get("streams", [])
                    audio_tracks = []
                    subtitle_tracks = []
                    for s in streams:
                        codec_type = s.get("codec_type")
                        tags = s.get("tags", {})
                        lang = tags.get("language") or "und"
                        label = tags.get("title") or f"Pista {s.get('index', 0)} ({lang})"
                        if codec_type == "audio":
                            audio_tracks.append({"index": s.get("index"), "language": lang, "label": label})
                        elif codec_type == "subtitle":
                            subtitle_tracks.append({"index": s.get("index"), "language": lang, "label": label})

                    return {
                        "duration": duration,
                        "chapters": chapters,
                        "audio_tracks": audio_tracks,
                        "subtitle_tracks": subtitle_tracks,
                    }
            except Exception:
                pass

        # 2. Fallback robusto usando ffmpeg -i analizando stderr (para paquetes como imageio-ffmpeg sin ffprobe)
        try:
            cmd = [ffmpeg_exe, "-i", filepath]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10, encoding="utf-8", errors="ignore")
            stderr = res.stderr or ""
            duration = 0.0
            m_dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
            if m_dur:
                duration = int(m_dur.group(1)) * 3600 + int(m_dur.group(2)) * 60 + float(m_dur.group(3))

            chapters: List[Dict[str, Any]] = []
            ch_matches = re.finditer(r"Chapter #\d+:\d+: start (\d+(?:\.\d+)?), end (\d+(?:\.\d+)?)", stderr)
            for ch_m in ch_matches:
                st = float(ch_m.group(1))
                et = float(ch_m.group(2))
                chapters.append({
                    "title": f"Capítulo {len(chapters) + 1}",
                    "start_time": st,
                    "end_time": et,
                })

            return {
                "duration": duration,
                "chapters": chapters,
                "audio_tracks": [],
                "subtitle_tracks": [],
            }
        except Exception as e:
            print(f"[OfflineLibraryManager] Error en fallback ffmpeg -i: {e}")
            return {}


offline_library_manager = OfflineLibraryManager()
