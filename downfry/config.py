import os
import json
import shutil
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional

APPDATA_DIR = Path(os.getenv("APPDATA", Path.home())) / "Downfry"
CONFIG_FILE = APPDATA_DIR / "config.json"
CONFIG_FILE_BAK = APPDATA_DIR / "config.json.bak"
HISTORY_FILE = APPDATA_DIR / "history.json"
HISTORY_FILE_BAK = APPDATA_DIR / "history.json.bak"
ARCHIVE_TITLES_FILE = APPDATA_DIR / "archive_titles.json"
DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "Downfry"

DEFAULT_CONFIG: Dict[str, Any] = {
    "download_dir": str(DEFAULT_DOWNLOAD_DIR),
    "default_format_mode": "video",  # "video" o "audio"
    "default_video_quality": "best",  # "best", "1080p", "720p", "480p", "360p", etc.
    "default_audio_format": "mp3",  # "mp3", "m4a", "opus", "flac", "wav"
    "default_audio_bitrate": "320",  # "320", "256", "192", "128"
    "embed_subtitles": True,
    "embed_thumbnail": True,
    "embed_metadata": True,
    "embed_chapters": True,
    "preserve_publish_date": True,
    "speed_limit_value": 0,
    "speed_limit_unit": "MB/s",
    "theme": "Auto",  # "Auto", "Dark", "Light"
    "channel_download_videos": True,
    "channel_download_shorts": True,
    "channel_download_lives": True,
    "use_archive": True,
    "check_duplicates": True,
    "recycle_bin_retention": "7d",  # "24h", "3d", "7d", "14d", "30d", "60d", "90d", "never"
}


def get_resource_path(relative_path: str) -> Path:
    """Obtiene la ruta absoluta a un recurso, compatible con PyInstaller (_MEIPASS) y desarrollo."""
    import sys
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base_path / relative_path


class ConfigManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._ensure_dirs()
        self.config: Dict[str, Any] = self._load_config()

    def _ensure_dirs(self):
        APPDATA_DIR.mkdir(parents=True, exist_ok=True)
        DEFAULT_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    def _load_config(self) -> Dict[str, Any]:
        cfg = DEFAULT_CONFIG.copy()
        target = CONFIG_FILE if CONFIG_FILE.exists() else CONFIG_FILE_BAK
        if target.exists():
            try:
                with open(target, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        data.pop("browser_cookies", None)
                        cfg.update(data)
                        return cfg
            except Exception as e:
                print(f"[ConfigManager] Error leyendo {target.name}: {e}")
                if target == CONFIG_FILE and CONFIG_FILE_BAK.exists():
                    try:
                        with open(CONFIG_FILE_BAK, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            if isinstance(data, dict):
                                cfg.update(data)
                                return cfg
                    except Exception:
                        pass
        return cfg

    def save(self):
        with self._lock:
            tmp_file = CONFIG_FILE.with_suffix(".tmp")
            try:
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(self.config, f, indent=4, ensure_ascii=False, default=str)
                    f.flush()
                    os.fsync(f.fileno())

                if CONFIG_FILE.exists() and CONFIG_FILE.stat().st_size > 0:
                    try:
                        shutil.copy2(CONFIG_FILE, CONFIG_FILE_BAK)
                    except Exception:
                        pass

                os.replace(tmp_file, CONFIG_FILE)
            except Exception as e:
                print(f"[ConfigManager] Error guardando config: {e}")
                if tmp_file.exists():
                    try:
                        tmp_file.unlink()
                    except Exception:
                        pass

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self.config.get(key, default)

    def set(self, key: str, value: Any):
        with self._lock:
            self.config[key] = value
        self.save()


class HistoryManager:
    """Gestor de historial con persistencia atómica, respaldos .bak y autoreparación estilo Mindustry."""

    def __init__(self):
        self._lock = threading.Lock()
        self._ensure_dirs()
        self.history: List[Dict[str, Any]] = self._load_history()

    def _ensure_dirs(self):
        APPDATA_DIR.mkdir(parents=True, exist_ok=True)

    def _attempt_json_repair(self, content: str) -> Optional[List[Dict[str, Any]]]:
        """Repara archivos JSON truncados o incompletos recuperando todas las entradas válidas."""
        if not content:
            return None
        pos = len(content)
        while True:
            pos = content.rfind("}", 0, pos)
            if pos == -1:
                break
            candidate = content[:pos + 1].strip() + "\n]"
            try:
                data = json.loads(candidate)
                if isinstance(data, list):
                    return data
            except Exception:
                pass
        return None

    def _try_read_json(self, path: Path) -> Optional[List[Dict[str, Any]]]:
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                return None
            data = json.loads(content)
            if isinstance(data, list):
                return data
            return None
        except Exception as e:
            print(f"[HistoryManager] Aviso al parsear {path.name}: {e}. Intentando autoreparación...")
            try:
                repaired = self._attempt_json_repair(content)
                if repaired is not None:
                    print(f"[HistoryManager] Historial recuperado con éxito: {len(repaired)} entradas.")
                    return repaired
            except Exception:
                pass
            return None

    def _sanitize_entries(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        from downfry.utils.formatting import format_bytes
        for entry in entries:
            if entry.get("mode") not in ("video", "audio"):
                entry["mode"] = "video"
            fp = str(entry.get("filepath") or "")
            if not entry.get("quality") or entry.get("quality") == "disco":
                import re
                q_match = re.search(r"\[(\d+p|\d+kbps|best)\]", fp, re.IGNORECASE)
                if q_match:
                    entry["quality"] = q_match.group(1)
                else:
                    entry["quality"] = "1080p" if "[1080p]" in fp else ("720p" if "[720p]" in fp else "Auto")
            # Si la ruta guardada fue un archivo intermedio DASH (.f251.webm, .f137.mp4) y existe el .mp4 final
            if fp and any(part in fp for part in (".f251", ".f137", ".webm")):
                for candidate_ext in [".mp4", ".mkv"]:
                    # Buscar quitando la parte del formato intermedio
                    import re
                    clean_fp = re.sub(r"\.f\d+(\.[a-zA-Z0-9]+)?$", candidate_ext, fp)
                    if clean_fp != fp and os.path.exists(clean_fp):
                        entry["filepath"] = clean_fp
                        entry["size"] = os.path.getsize(clean_fp)
                        entry["size_str"] = format_bytes(entry["size"])
                        break
            elif fp and os.path.exists(fp) and entry.get("size", 0) == 0:
                entry["size"] = os.path.getsize(fp)
                entry["size_str"] = format_bytes(entry["size"])
        return entries

    def _load_history(self) -> List[Dict[str, Any]]:
        # 1. Intentar cargar el archivo principal
        data = self._try_read_json(HISTORY_FILE)
        if data is not None:
            return self._sanitize_entries(data)

        # 2. Si falló o está corrupto, cargar el respaldo .bak
        if HISTORY_FILE_BAK.exists():
            print("[HistoryManager] Restaurando historial desde copia de seguridad .bak...")
            bak_data = self._try_read_json(HISTORY_FILE_BAK)
            if bak_data is not None:
                # Restaurar el archivo principal con los datos del backup
                try:
                    shutil.copy2(HISTORY_FILE_BAK, HISTORY_FILE)
                except Exception:
                    pass
                return self._sanitize_entries(bak_data)

        return []

    def save(self):
        with self._lock:
            tmp_file = HISTORY_FILE.with_suffix(".tmp")
            try:
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(self.history, f, indent=2, ensure_ascii=False, default=str)
                    f.flush()
                    os.fsync(f.fileno())

                # Si el archivo actual existe y es válido, respaldarlo antes de sobrescribir
                if HISTORY_FILE.exists() and HISTORY_FILE.stat().st_size > 0:
                    try:
                        shutil.copy2(HISTORY_FILE, HISTORY_FILE_BAK)
                    except Exception:
                        pass

                os.replace(tmp_file, HISTORY_FILE)
            except Exception as e:
                print(f"[HistoryManager] Error guardando historial: {e}")
                if tmp_file.exists():
                    try:
                        tmp_file.unlink()
                    except Exception:
                        pass

    def add_entry(self, entry: Dict[str, Any]):
        with self._lock:
            vid = entry.get("video_id")
            fp = entry.get("filepath")
            mode = entry.get("mode")
            # Evitar duplicados por filepath o (si tienen video_id y mismo mode) por video_id
            self.history = [
                h for h in self.history
                if not (
                    (fp and h.get("filepath") == fp) or
                    (vid and h.get("video_id") == vid and h.get("mode") == mode)
                )
            ]
            self.history.insert(0, entry)
            # Mantener un máximo de 200 elementos en historial
            if len(self.history) > 200:
                self.history = self.history[:200]
        self.save()

    def remove_entry(self, filepath: str, video_id: str = ""):
        with self._lock:
            self.history = [
                h for h in self.history
                if not (
                    (filepath and h.get("filepath") == filepath) or
                    (video_id and h.get("video_id") == video_id)
                )
            ]
        self.save()

    def clear(self):
        with self._lock:
            self.history = []
        self.save()


config_manager = ConfigManager()
history_manager = HistoryManager()

_archive_titles_lock = threading.Lock()
_archive_titles_cache: Optional[Dict[str, str]] = None
_cached_archive_file: Optional[Path] = None


def record_archive_title(video_id: str, title: str):
    """Guarda el mapeo video_id -> title para mostrar nombres reales en el registro antiduplicados."""
    global _archive_titles_cache, _cached_archive_file
    if not video_id or not title:
        return
    vid = video_id.strip()
    tit = title.strip()
    with _archive_titles_lock:
        try:
            if _archive_titles_cache is None or _cached_archive_file != ARCHIVE_TITLES_FILE:
                _cached_archive_file = ARCHIVE_TITLES_FILE
                if ARCHIVE_TITLES_FILE.exists():
                    try:
                        with open(ARCHIVE_TITLES_FILE, "r", encoding="utf-8") as f:
                            _archive_titles_cache = json.load(f)
                    except Exception:
                        _archive_titles_cache = {}
                else:
                    _archive_titles_cache = {}

            _archive_titles_cache[vid] = tit
            tmp_f = ARCHIVE_TITLES_FILE.with_suffix(f".{os.getpid()}_{threading.get_ident()}.tmp")
            with open(tmp_f, "w", encoding="utf-8") as f:
                json.dump(_archive_titles_cache, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_f, ARCHIVE_TITLES_FILE)
        except Exception as e:
            print(f"[record_archive_title] Error: {e}")


def get_archive_title(video_id: str) -> Optional[str]:
    """Obtiene el título asociado a un video_id."""
    global _archive_titles_cache, _cached_archive_file
    if not video_id:
        return None
    vid = video_id.strip()
    with _archive_titles_lock:
        if _archive_titles_cache is not None and _cached_archive_file == ARCHIVE_TITLES_FILE:
            return _archive_titles_cache.get(vid)
        try:
            _cached_archive_file = ARCHIVE_TITLES_FILE
            if ARCHIVE_TITLES_FILE.exists():
                with open(ARCHIVE_TITLES_FILE, "r", encoding="utf-8") as f:
                    _archive_titles_cache = json.load(f)
                    return _archive_titles_cache.get(vid)
            else:
                _archive_titles_cache = {}
        except Exception:
            pass
        return None

