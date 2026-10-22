import os
import time
import json
import shutil
import threading
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from downfry.config import config_manager, history_manager

RETENTION_SECONDS: Dict[str, Optional[int]] = {
    "24h": 24 * 3600,
    "3d": 3 * 24 * 3600,
    "7d": 7 * 24 * 3600,
    "14d": 14 * 24 * 3600,
    "30d": 30 * 24 * 3600,
    "60d": 60 * 24 * 3600,
    "90d": 90 * 24 * 3600,
    "never": None,
}


class RecycleBinManager:
    """Gestiona la papelera interna de Downfry y la purga automática según retención."""

    _lock = threading.Lock()

    @classmethod
    def get_bin_dir(cls) -> Path:
        base = Path(config_manager.get("download_dir", str(Path.home() / "Downloads" / "Downfry")))
        bin_dir = base / "Papelera"

        # Migración automática desde .recycle_bin si existía previamente
        old_bin = base / ".recycle_bin"
        if old_bin.exists():
            try:
                if not bin_dir.exists():
                    shutil.move(str(old_bin), str(bin_dir))
                else:
                    for f in old_bin.iterdir():
                        target = bin_dir / f.name
                        if not target.exists():
                            shutil.move(str(f), str(target))
                    shutil.rmtree(str(old_bin), ignore_errors=True)
            except Exception:
                pass

        bin_dir.mkdir(parents=True, exist_ok=True)
        # Ocultar la carpeta en Windows preservando atributos de directorio
        if os.name == "nt":
            try:
                import ctypes
                attrs = ctypes.windll.kernel32.GetFileAttributesW(str(bin_dir))
                if attrs != -1:
                    FILE_ATTRIBUTE_HIDDEN = 0x02
                    ctypes.windll.kernel32.SetFileAttributesW(str(bin_dir), attrs | FILE_ATTRIBUTE_HIDDEN)
            except Exception:
                pass
        return bin_dir

    @classmethod
    def _get_index_file(cls) -> Path:
        return cls.get_bin_dir() / "trash_index.json"

    @classmethod
    def _load_index(cls) -> Dict[str, Any]:
        idx_f = cls._get_index_file()
        if idx_f.exists():
            try:
                with open(idx_f, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception:
                pass
        return {}

    @classmethod
    def _save_index(cls, index_data: Dict[str, Any]):
        idx_f = cls._get_index_file()
        tmp_f = idx_f.with_suffix(".tmp")
        try:
            with open(tmp_f, "w", encoding="utf-8") as f:
                json.dump(index_data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_f, idx_f)
        except Exception:
            if tmp_f.exists():
                try:
                    tmp_f.unlink()
                except Exception:
                    pass

    @classmethod
    def move_to_trash(cls, filepath: str, title: str = "", metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Mueve un archivo físico a la papelera interna y lo desvincula del historial."""
        if not filepath:
            return False
        p = Path(filepath)
        if not p.exists():
            history_manager.remove_entry(filepath)
            return False

        with cls._lock:
            bin_dir = cls.get_bin_dir()
            ts = int(time.time())
            trash_filename = f"{ts}_{p.name}"
            trash_path = bin_dir / trash_filename

            size_bytes = 0
            try:
                size_bytes = p.stat().st_size
                shutil.move(str(p), str(trash_path))
            except Exception as e:
                print(f"[RecycleBin] Error moviendo archivo a papelera: {e}")
                return False

            hist_meta = metadata or {}
            if not hist_meta:
                for h in history_manager.history:
                    if h.get("filepath") == filepath:
                        hist_meta = h
                        break

            # Actualizar índice de papelera
            index_data = cls._load_index()
            index_data[trash_filename] = {
                "title": title or hist_meta.get("title") or p.stem,
                "original_path": str(p),
                "trash_path": str(trash_path),
                "deleted_at": time.time(),
                "size": size_bytes,
                "video_id": hist_meta.get("video_id", ""),
                "thumbnail": hist_meta.get("thumbnail", ""),
                "mode": hist_meta.get("mode", "video"),
                "quality": hist_meta.get("quality", ""),
                "url": hist_meta.get("url", ""),
            }
            cls._save_index(index_data)

            # Quitar del historial activo
            history_manager.remove_entry(filepath)
            return True

    @classmethod
    def purge_expired(cls) -> int:
        """Elimina definitivamente los archivos de la papelera que hayan superado el tiempo de retención."""
        retention_key = config_manager.get("recycle_bin_retention", "7d")
        sec_limit = RETENTION_SECONDS.get(retention_key, 7 * 24 * 3600)
        if sec_limit is None:
            return 0  # "never": no purgar automáticamente

        now = time.time()
        cutoff = now - sec_limit

        purged_count = 0
        with cls._lock:
            index_data = cls._load_index()
            remaining = {}

            for trash_name, meta in index_data.items():
                del_time = meta.get("deleted_at", 0)
                t_path = Path(meta.get("trash_path", ""))
                if del_time < cutoff:
                    try:
                        if t_path.exists():
                            t_path.unlink()
                        purged_count += 1
                    except Exception:
                        pass
                else:
                    if t_path.exists():
                        remaining[trash_name] = meta

            cls._save_index(remaining)

        if purged_count > 0:
            print(f"[RecycleBin] Se purgaron {purged_count} archivos caducados de la papelera.")
        return purged_count

    @classmethod
    def empty_trash(cls) -> Tuple[int, int]:
        """Vacía manualmente toda la papelera eliminando los archivos físicos de forma permanente."""
        with cls._lock:
            index_data = cls._load_index()
            count = 0
            total_bytes = 0
            for trash_name, meta in index_data.items():
                t_path = Path(meta.get("trash_path", ""))
                try:
                    if t_path.exists():
                        total_bytes += t_path.stat().st_size
                        t_path.unlink()
                        count += 1
                except Exception:
                    pass

            cls._save_index({})
            return count, total_bytes

    @classmethod
    def get_trash_stats(cls) -> Tuple[int, str]:
        """Retorna (cantidad_archivos, tamaño_formateado) de la papelera."""
        with cls._lock:
            index_data = cls._load_index()
            valid_count = 0
            total_bytes = 0
            for trash_name, meta in index_data.items():
                t_path = Path(meta.get("trash_path", ""))
                if t_path.exists():
                    valid_count += 1
                    total_bytes += meta.get("size", 0)
            from downfry.utils.formatting import format_bytes
            return valid_count, format_bytes(total_bytes)

    @classmethod
    def get_items(cls) -> list:
        """Retorna la lista de archivos actualmente en la papelera."""
        with cls._lock:
            index_data = cls._load_index()
            items = []
            for trash_name, meta in index_data.items():
                t_path = Path(meta.get("trash_path", ""))
                if t_path.exists():
                    item = dict(meta)
                    item["trash_filename"] = trash_name
                    from downfry.utils.formatting import format_bytes
                    item["size_str"] = format_bytes(meta.get("size", 0))
                    import datetime
                    del_time = meta.get("deleted_at", 0)
                    item["date_str"] = datetime.datetime.fromtimestamp(del_time).strftime("%Y-%m-%d %H:%M")
                    items.append(item)
            items.sort(key=lambda x: x.get("deleted_at", 0), reverse=True)
            return items

    @classmethod
    def restore_item(cls, trash_filename: str) -> bool:
        """Restaura un archivo de la papelera a su ubicación original y lo re-agrega al historial."""
        with cls._lock:
            index_data = cls._load_index()
            meta = index_data.get(trash_filename)
            if not meta:
                return False

            trash_path = Path(meta.get("trash_path", ""))
            original_path = Path(meta.get("original_path", ""))

            if not trash_path.exists():
                index_data.pop(trash_filename, None)
                cls._save_index(index_data)
                return False

            dest_dir = original_path.parent
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                dest_dir = Path(config_manager.get("download_dir", str(Path.home() / "Downloads" / "Downfry")))

            target_file = dest_dir / original_path.name
            if target_file.exists():
                target_file = dest_dir / f"{original_path.stem}_restaurado{original_path.suffix}"

            try:
                shutil.move(str(trash_path), str(target_file))
            except Exception as e:
                print(f"[RecycleBin] Error al restaurar archivo: {e}")
                return False

            from downfry.utils.formatting import format_bytes
            import datetime
            now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            saved_quality = meta.get("quality")
            if not saved_quality or saved_quality == "Restaurado":
                saved_quality = "1080p" if "[1080p]" in target_file.name else ("720p" if "[720p]" in target_file.name else "Auto")

            history_manager.add_entry({
                "title": meta.get("title", target_file.stem),
                "filepath": str(target_file),
                "size": target_file.stat().st_size,
                "size_str": format_bytes(target_file.stat().st_size),
                "mode": meta.get("mode", "video" if target_file.suffix.lower() in (".mp4", ".mkv", ".webm", ".avi", ".mov") else "audio"),
                "quality": saved_quality,
                "date": now_iso,
                "video_id": meta.get("video_id", ""),
                "thumbnail": meta.get("thumbnail", ""),
                "url": meta.get("url", ""),
            })

            index_data.pop(trash_filename, None)
            cls._save_index(index_data)
            return True

    @classmethod
    def delete_item(cls, trash_filename: str) -> bool:
        """Elimina permanentemente un archivo específico de la papelera."""
        with cls._lock:
            index_data = cls._load_index()
            meta = index_data.pop(trash_filename, None)
            cls._save_index(index_data)
            if meta:
                trash_path = Path(meta.get("trash_path", ""))
                try:
                    if trash_path.exists():
                        trash_path.unlink()
                        return True
                except Exception:
                    pass
            return False
