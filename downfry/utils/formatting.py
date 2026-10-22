import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Union

SPANISH_MONTHS = {
    1: "01 - Enero",
    2: "02 - Febrero",
    3: "03 - Marzo",
    4: "04 - Abril",
    5: "05 - Mayo",
    6: "06 - Junio",
    7: "07 - Julio",
    8: "08 - Agosto",
    9: "09 - Septiembre",
    10: "10 - Octubre",
    11: "11 - Noviembre",
    12: "12 - Diciembre",
}

# Caracteres no permitidos en nombres de archivos o carpetas en Windows:
# < > : " / \ | ? *
ILLEGAL_NTFS_CHARS = re.compile(r'[<>:"/\\|?*]')

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


def sanitize_filename(name: str, max_length: int = 90) -> str:
    """Limpia caracteres inválidos en Windows mientras preserva tildes y formato."""
    if not name:
        return "Sin_Titulo"

    # Sustituciones amigables
    cleaned = name.replace(":", " - ").replace('"', "'").replace("?", "").replace("*", "")
    cleaned = ILLEGAL_NTFS_CHARS.sub("", cleaned)

    # Eliminar espacios redundantes y saltos de línea
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Quitar puntos o espacios al final (no permitidos en Windows)
    cleaned = cleaned.rstrip(". ")

    if not cleaned:
        cleaned = "Sin_Titulo"

    # Proteger contra nombres reservados de Windows (ej. AUX, CON, NUL)
    stem_check = cleaned.split(".")[0].upper()
    if stem_check in WINDOWS_RESERVED_NAMES or cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"

    # Limitar longitud para evitar problemas con la ruta máxima de Windows (260 caracteres)
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(". ")

    return cleaned


def format_bytes(bytes_count: Optional[float]) -> str:
    """Formatea bytes a un formato legible (B, KB, MB, GB)."""
    if bytes_count is None or bytes_count < 0:
        return "-- MB"

    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_count < 1024.0:
            return f"{bytes_count:.1f} {unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.1f} PB"


def format_speed(speed_bytes_sec: Optional[float]) -> str:
    """Formatea la velocidad de descarga en MB/s o KB/s."""
    if speed_bytes_sec is None or speed_bytes_sec <= 0:
        return "0.0 KB/s"
    return f"{format_bytes(speed_bytes_sec)}/s"


def format_seconds(seconds: Optional[float]) -> str:
    """Formatea segundos en HH:MM:SS o MM:SS."""
    if seconds is None or seconds < 0:
        return "--:--"

    total_secs = int(seconds)
    hours = total_secs // 3600
    minutes = (total_secs % 3600) // 60
    secs = total_secs % 60

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def parse_iso_date(date_str: Optional[str]) -> tuple[str, str, str]:
    """Parsea fecha de yt-dlp (formato YYYYMMDD o YYYY-MM-DD).
    Retorna tupla: (fecha_iso, año, carpeta_mes_español)
    Ejemplo: ('2025-09-28', '2025', '09 - Septiembre')
    """
    now = datetime.now()
    default_iso = now.strftime("%Y-%m-%d")
    default_year = str(now.year)
    default_month = SPANISH_MONTHS.get(now.month, f"{now.month:02d}")

    if not date_str:
        return default_iso, default_year, default_month

    date_str = str(date_str).strip()

    # Formato YYYYMMDD
    if len(date_str) == 8 and date_str.isdigit():
        try:
            year = int(date_str[0:4])
            month = int(date_str[4:6])
            day = int(date_str[6:8])
            iso = f"{year:04d}-{month:02d}-{day:02d}"
            month_str = SPANISH_MONTHS.get(month, f"{month:02d}")
            return iso, str(year), month_str
        except Exception:
            return default_iso, default_year, default_month

    # Formato YYYY-MM-DD
    if "-" in date_str:
        parts = date_str.split("-")
        if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
            try:
                year = int(parts[0])
                month = int(parts[1])
                day = int(parts[2][:2])
                iso = f"{year:04d}-{month:02d}-{day:02d}"
                month_str = SPANISH_MONTHS.get(month, f"{month:02d}")
                return iso, str(year), month_str
            except Exception:
                return default_iso, default_year, default_month

    return default_iso, default_year, default_month


def compute_ratelimit_bytes(value: Union[float, int, str, None], unit: str = "MB/s") -> Optional[int]:
    """Calcula el límite de velocidad en bytes/s para yt-dlp según el valor y unidad elegida."""
    if value is None:
        return None
    try:
        val = float(str(value).strip().replace(",", "."))
    except (ValueError, TypeError):
        return None

    if val <= 0:
        return None

    unit_upper = (unit or "MB/s").strip().upper()
    if unit_upper in ("KB/S", "KB"):
        return int(val * 1000)
    elif unit_upper in ("KIB/S", "KIB"):
        return int(val * 1024)
    elif unit_upper in ("MIB/S", "MIB"):
        return int(val * 1024 * 1024)
    else:  # Por defecto MB/s (1000 * 1000)
        return int(val * 1000 * 1000)


def extract_publication_timestamp(info: Optional[Dict[str, Any]]) -> Optional[float]:
    """Extrae el timestamp Unix exacto de publicación de un diccionario de metadatos de yt-dlp."""
    if not info or not isinstance(info, dict):
        return None

    # 1. Prioridad: release_timestamp
    rel_ts = info.get("release_timestamp")
    if rel_ts and isinstance(rel_ts, (int, float)) and rel_ts > 0:
        return float(rel_ts)

    # 2. Prioridad: timestamp
    ts = info.get("timestamp")
    if ts and isinstance(ts, (int, float)) and ts > 0:
        return float(ts)

    # 3. Prioridad: release_date o upload_date (YYYYMMDD o YYYY-MM-DD)
    date_val = str(info.get("release_date") or info.get("upload_date") or "").strip()
    if date_val:
        cleaned_date = date_val.replace("-", "")
        if len(cleaned_date) == 8 and cleaned_date.isdigit():
            try:
                dt = datetime(
                    int(cleaned_date[0:4]),
                    int(cleaned_date[4:6]),
                    int(cleaned_date[6:8]),
                    12, 0, 0
                )
                return dt.timestamp()
            except Exception:
                pass

    return None


def apply_publication_timestamps(filepath: Union[str, Path], pub_timestamp: Optional[float]) -> bool:
    """Establece la fecha de creación, modificación y acceso del archivo al timestamp de publicación."""
    if not filepath or pub_timestamp is None or pub_timestamp <= 0:
        return False

    path_obj = Path(filepath)
    if not path_obj.exists():
        return False

    norm_path = str(path_obj.resolve())

    # 1. Multiplataforma: LastAccessTime y LastWriteTime (Fecha de modificación)
    try:
        os.utime(norm_path, (pub_timestamp, pub_timestamp))
    except Exception as e:
        print(f"[Formatting] Error en os.utime para {norm_path}: {e}")

    # 2. Windows NTFS: Fecha de creación + Fecha de modificación + Fecha de acceso
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32

            # Conversión de Unix Epoch (1970-01-01) a Windows FILETIME (1601-01-01 en intervalos de 100ns)
            EPOCH_AS_FILETIME = 116444736000000000
            HUNDREDS_OF_NANOSECONDS = 10000000
            ft_val = int(pub_timestamp * HUNDREDS_OF_NANOSECONDS) + EPOCH_AS_FILETIME
            low = ft_val & 0xFFFFFFFF
            high = (ft_val >> 32) & 0xFFFFFFFF
            ft = wintypes.FILETIME(low, high)

            handle = kernel32.CreateFileW(
                norm_path,
                0x0100,  # FILE_WRITE_ATTRIBUTES
                0x00000001 | 0x00000002 | 0x00000004,  # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
                None,
                3,  # OPEN_EXISTING
                0x02000000,  # FILE_FLAG_BACKUP_SEMANTICS
                None
            )
            if handle != -1 and handle != 0xFFFFFFFF:
                try:
                    kernel32.SetFileTime(handle, ctypes.byref(ft), ctypes.byref(ft), ctypes.byref(ft))
                finally:
                    kernel32.CloseHandle(handle)
        except Exception as e:
            print(f"[Formatting] Error en SetFileTime Windows para {norm_path}: {e}")

    return True


def get_windows_accent_color() -> Optional[str]:
    """Obtiene el color de énfasis configurado por el usuario en Windows 11."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as key:
            val, _ = winreg.QueryValueEx(key, "ColorizationColor")
            r = (val >> 16) & 0xFF
            g = (val >> 8) & 0xFF
            b = val & 0xFF
            return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return "#0078D4"  # Azul Fluent por defecto


def open_in_explorer(filepath: str) -> bool:
    """Abre Windows Explorer seleccionando el archivo exactamente, sin abrir Mis Documentos."""
    if not filepath:
        return False
    norm = os.path.normpath(str(filepath))
    try:
        if os.path.isfile(norm):
            if os.name == "nt":
                subprocess.Popen(f'explorer.exe /select,"{norm}"')
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(norm)])
            return True
        elif os.path.isdir(norm):
            if os.name == "nt":
                subprocess.Popen(f'explorer.exe "{norm}"')
            else:
                subprocess.Popen(["xdg-open", norm])
            return True
        else:
            parent = os.path.dirname(norm)
            if parent and os.path.isdir(parent):
                if os.name == "nt":
                    subprocess.Popen(f'explorer.exe "{parent}"')
                else:
                    subprocess.Popen(["xdg-open", parent])
                return True
    except Exception:
        pass
    return False


def open_file(filepath: str) -> bool:
    """Abre el archivo con el reproductor o aplicación predeterminada de Windows."""
    if not filepath:
        return False
    norm = os.path.normpath(str(filepath))
    try:
        if os.path.exists(norm):
            os.startfile(norm)
            return True
    except Exception:
        pass
    return False
