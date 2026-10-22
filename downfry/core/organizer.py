import os
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
from downfry.utils.formatting import sanitize_filename, parse_iso_date
from downfry.config import config_manager, history_manager


class PathOrganizer:
    """Gestiona la jerarquía de directorios y nombres de archivos para Downfry.
    
    Regla estricta: Todos los nombres de archivo inician con YYYY-MM-DD para
    garantizar ordenamiento cronológico en cualquier sistema operativo.
    """

    @staticmethod
    def determine_video_category(info: Dict[str, Any]) -> str:
        """Determina si un video de canal es 'Videos', 'Shorts' o 'Directos'."""
        # 1. Directo / Transmisión en vivo
        if info.get("was_live") or info.get("is_live") or info.get("live_status") in ["was_live", "is_live"]:
            return "Directos"

        # 2. Short (URL contiene /shorts/, o duración <= 60s y aspecto vertical)
        webpage_url = info.get("webpage_url", "")
        original_url = info.get("original_url", "")
        duration = info.get("duration") or 0
        width = info.get("width") or 0
        height = info.get("height") or 0

        if "/shorts/" in webpage_url or "/shorts/" in original_url:
            return "Shorts"

        # Si dura 60s o menos y el alto supera al ancho, o está etiquetado como vertical
        if 0 < duration <= 62 and height > 0 and width > 0 and height >= width:
            return "Shorts"

        # 3. Video estándar / largo
        return "Videos"

    @classmethod
    def get_output_paths(
        cls,
        base_dir: str | Path,
        info: Dict[str, Any],
        download_type: str = "video",  # "video", "short", "playlist", "channel"
        playlist_title: Optional[str] = None,
        channel_name: Optional[str] = None,
        separate_channel_categories: bool = True,
        quality_tag: Optional[str] = None,
        forced_category: Optional[str] = None,
    ) -> tuple[Path, str, Path]:
        """Calcula la carpeta de destino y el nombre de archivo final.
        
        Retorna: (target_directory, filename_without_ext, full_archive_path_or_none)
        """
        base_path = Path(base_dir)

        # 1. Obtener y parsear metadatos básicos
        raw_title = info.get("title") or "Video_Sin_Titulo"
        uploader = (
            info.get("uploader")
            or info.get("channel")
            or channel_name
            or "YouTube"
        )
        from downfry.utils.formatting import extract_publication_timestamp
        upload_date_raw = info.get("upload_date") or info.get("release_date")
        if not upload_date_raw and isinstance(info.get("raw_info"), dict):
            raw_d = info["raw_info"]
            upload_date_raw = raw_d.get("upload_date") or raw_d.get("release_date")
        if not upload_date_raw:
            pub_ts = extract_publication_timestamp(info)
            if pub_ts and pub_ts > 0:
                from datetime import datetime, timezone
                dt_utc = datetime.fromtimestamp(pub_ts, timezone.utc)
                upload_date_raw = dt_utc.strftime("%Y%m%d")

        iso_date, year, month_folder = parse_iso_date(upload_date_raw)

        clean_title = sanitize_filename(raw_title)
        clean_uploader = sanitize_filename(uploader)

        # Evitar duplicar el canal si el título ya termina con el nombre del canal
        for sep in [" - ", " | ", " -- ", " : "]:
            suffix = f"{sep}{clean_uploader}".lower()
            if clean_title.lower().endswith(suffix):
                clean_title = clean_title[:-len(suffix)].strip()
                break

        # 2. Organización según tipo de descarga
        archive_path = None
        if download_type == "channel":
            # Jerarquía: Base / Canal / Año / Mes / [Videos | Shorts | Directos]
            channel_dir_name = sanitize_filename(channel_name or uploader)
            channel_root = base_path / channel_dir_name
            archive_path = channel_root / "download_archive.txt"

            if not separate_channel_categories:
                category = ""
            elif forced_category:
                category = forced_category
            else:
                category = cls.determine_video_category(info)

            if category:
                target_dir = channel_root / year / month_folder / category
            else:
                target_dir = channel_root / year / month_folder

        elif download_type == "playlist":
            # Jerarquía: Base / PlaylistTitle /
            pl_dir_name = sanitize_filename(playlist_title or info.get("playlist_title") or "Playlist")
            target_dir = base_path / pl_dir_name
            archive_path = target_dir / "download_archive.txt"

        else:
            # Video o Short individual: directo en base_dir
            target_dir = base_path
            archive_path = base_path / "download_archive.txt"

        # 3. Nombre de archivo estricto: YYYY-MM-DD - Título [Calidad] - Canal
        q_suffix = f" [{sanitize_filename(str(quality_tag))}]" if quality_tag else ""
        file_stem = f"{iso_date} - {clean_title}{q_suffix} - {clean_uploader}"

        # 4. Truncado inteligente para garantizar que la ruta completa nunca exceda 240 caracteres (Windows MAX_PATH)
        candidate_full_path = str(target_dir / f"{file_stem}.mp4.part")
        if len(candidate_full_path) > 240:
            excess = len(candidate_full_path) - 240
            if len(clean_title) > excess + 15:
                clean_title = clean_title[:len(clean_title) - excess].rstrip(". ")
            else:
                clean_title = clean_title[:15].rstrip(". ")
                cand_len = len(str(target_dir / f"{iso_date} - {clean_title}{q_suffix} - {clean_uploader}.mp4.part"))
                if cand_len > 240:
                    excess_up = cand_len - 240
                    if len(clean_uploader) > excess_up + 10:
                        clean_uploader = clean_uploader[:len(clean_uploader) - excess_up].rstrip(". ")
            file_stem = f"{iso_date} - {clean_title}{q_suffix} - {clean_uploader}"

        return target_dir, file_stem, archive_path


def find_existing_download(vid_id: str, title: str, download_dir: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """
    Comprueba exhaustivamente si un video ya fue descargado previamente o existe en disco.
    Retorna (tipo_coincidencia, ubicacion_o_detalle) o None si no existe duplicado.
    """
    if not download_dir:
        download_dir = config_manager.get("download_dir", str(Path.home() / "Downloads" / "Downfry"))
    target_path = Path(download_dir)

    # 1. Comprobar en el historial activo
    for item in history_manager.history:
        h_vid = item.get("video_id")
        h_fp = item.get("filepath", "")
        h_title = item.get("title", "")
        h_thumb = item.get("thumbnail", "")
        if vid_id and (h_vid == vid_id or (vid_id in h_fp) or (vid_id in h_thumb)):
            if h_fp and os.path.exists(h_fp):
                return ("Historial y Disco", h_fp)
            return ("Historial", h_fp or h_title)
        if title and h_title and title.lower().strip() == h_title.lower().strip():
            if h_fp and os.path.exists(h_fp):
                return ("Historial y Disco", h_fp)

    # 2. Comprobar en archivos download_archive.txt (coincidencia exacta de token)
    if target_path.exists() and vid_id:
        target_vid = vid_id.strip()
        for arch_file in target_path.glob("**/download_archive.txt"):
            try:
                for line in arch_file.read_text(encoding="utf-8").splitlines():
                    parts = line.strip().split()
                    if parts and parts[-1] == target_vid:
                        return ("Registro Antiduplicados", f"{arch_file.name} [{vid_id}]")
            except Exception:
                pass

    # 3. Comprobar archivos físicos en el directorio de descargas y subcarpetas (excluyendo .temp y papelera)
    if target_path.exists():
        clean_title = sanitize_filename(title).lower().strip() if title else ""
        norm_title = clean_title.replace("“", "").replace("”", "").replace('"', "").replace("'", "").strip()
        words = [w for w in norm_title.split() if len(w) > 3][:4] if len(norm_title) >= 10 else []

        scanned = 0
        try:
            for f in target_path.rglob("*"):
                scanned += 1
                if scanned > 1200:
                    break
                if any(part.startswith(".") or part.lower() in ("papelera", ".temp") for part in f.parts):
                    continue
                if not f.is_file():
                    continue
                if f.suffix.lower() not in (".mp4", ".mkv", ".webm", ".mp3", ".m4a"):
                    continue

                if vid_id and vid_id in f.name:
                    return ("Archivo en Disco", str(f))

                if words:
                    f_clean = f.stem.lower()
                    if all(w in f_clean for w in words):
                        return ("Archivo en Disco", str(f))
        except Exception:
            pass

    return None


def unblock_archive_id(download_dir: str, vid_id: str):
    """Elimina vid_id de todos los download_archive.txt para permitir re-descargar."""
    if not download_dir or not vid_id:
        return
    target_path = Path(download_dir)
    if not target_path.exists():
        return
    target_vid = vid_id.strip()
    for arch_file in target_path.glob("**/download_archive.txt"):
        try:
            lines = arch_file.read_text(encoding="utf-8").splitlines()
            new_lines = []
            changed = False
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                parts = stripped.split()
                if (len(parts) >= 2 and parts[-1] == target_vid) or (len(parts) == 1 and parts[0] == target_vid):
                    changed = True
                else:
                    new_lines.append(stripped)
            if changed:
                arch_file.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
        except Exception:
            pass
