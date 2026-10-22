import unittest
from unittest.mock import patch, MagicMock
import tempfile
import json
import shutil
from pathlib import Path
from downfry.utils.formatting import sanitize_filename, parse_iso_date
from downfry.core.classifier import classify_youtube_url, normalize_channel_base_url, UrlType
from downfry.core.organizer import PathOrganizer
from downfry.core.downloader import detect_actual_quality_tag, DownloadWorker
import time
from downfry.core.extractor import get_effective_resolution, get_cookieless_client_args, CLIENT_FALLBACK_CHAIN
from downfry.core.recycle_bin import RecycleBinManager
from downfry.config import HistoryManager, record_archive_title, get_archive_title, config_manager


class TestDownfry(unittest.TestCase):

    def setUp(self):
        import downfry.config as cfg
        self._test_temp_dir = Path(tempfile.mkdtemp())
        self._orig_hist_file = cfg.HISTORY_FILE
        self._orig_hist_bak = cfg.HISTORY_FILE_BAK
        self._orig_hist_list = list(cfg.history_manager.history)
        cfg.HISTORY_FILE = self._test_temp_dir / "test_history.json"
        cfg.HISTORY_FILE_BAK = self._test_temp_dir / "test_history.json.bak"
        cfg.history_manager.history = []

    def tearDown(self):
        import downfry.config as cfg
        cfg.HISTORY_FILE = self._orig_hist_file
        cfg.HISTORY_FILE_BAK = self._orig_hist_bak
        cfg.history_manager.history = self._orig_hist_list
        shutil.rmtree(self._test_temp_dir, ignore_errors=True)

    def test_sanitize_filename(self):
        bad_name = 'Video: Cómo hacer palomitas? "Fácil & Rápido" <2025> | Guía*'
        clean = sanitize_filename(bad_name)
        for ch in [":", "?", '"', "<", ">", "|", "*"]:
            self.assertNotIn(ch, clean)
        self.assertTrue(len(clean) > 0)

    def test_parse_iso_date(self):
        iso, year, month_folder = parse_iso_date("20250928")
        self.assertEqual(iso, "2025-09-28")
        self.assertEqual(year, "2025")
        self.assertEqual(month_folder, "09 - Septiembre")

    def test_classifier_and_channel_tabs(self):
        t1, meta1 = classify_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(t1, UrlType.VIDEO)
        self.assertEqual(meta1["id"], "dQw4w9WgXcQ")

        t2, meta2 = classify_youtube_url("https://www.youtube.com/shorts/3f5G_wLp99s")
        self.assertEqual(t2, UrlType.SHORT)
        self.assertEqual(meta2["id"], "3f5G_wLp99s")

        # Canal con pestaña explícita (/shorts) debe normalizar clean_url y detectar la pestaña
        t4, meta4 = classify_youtube_url("https://www.youtube.com/@mkbhd/shorts")
        self.assertEqual(t4, UrlType.CHANNEL)
        self.assertEqual(meta4["clean_url"], "https://www.youtube.com/@mkbhd")
        self.assertEqual(meta4["detected_tab"], "shorts")

    def test_effective_resolution_aspect_ratios(self):
        # 16:9 tradicional (horizontal)
        self.assertEqual(get_effective_resolution(1920, 1080), 1080)
        # 9:16 Shorts (vertical) - ¡Debe ser 1080p, no 1920p!
        self.assertEqual(get_effective_resolution(1080, 1920), 1080)
        # 21:9 Ultrawide
        self.assertEqual(get_effective_resolution(2560, 1080), 1080)
        # 1:1 Cuadrado
        self.assertEqual(get_effective_resolution(1080, 1080), 1080)
        # 4:3 Clásico
        self.assertEqual(get_effective_resolution(1440, 1080), 1080)
        # Macroblock padding 1088 -> 1080
        self.assertEqual(get_effective_resolution(1920, 1088), 1080)
        # 4K horizontal y vertical
        self.assertEqual(get_effective_resolution(3840, 2160), 2160)
        self.assertEqual(get_effective_resolution(2160, 3840), 2160)
        # 720p vertical Short
        self.assertEqual(get_effective_resolution(720, 1280), 720)

    def test_detect_actual_quality_tag(self):
        mock_info = {
            "formats": [
                {"height": 360, "width": 640, "vcodec": "avc1"},
                {"height": 1080, "width": 1920, "vcodec": "avc1"},
                {"height": 2160, "width": 3840, "vcodec": "vp9"},
            ]
        }
        # 'best' debe detectar automáticamente 2160p en vez de escribir 'best'
        self.assertEqual(detect_actual_quality_tag(mock_info, "best", "video", "320"), "2160p")
        # Si el usuario limita a 1080p, debe devolver 1080p
        self.assertEqual(detect_actual_quality_tag(mock_info, "1080p", "video", "320"), "1080p")
        # Si el usuario limita a 480p pero solo hay 360p por debajo, devuelve 360p
        self.assertEqual(detect_actual_quality_tag(mock_info, "480p", "video", "320"), "360p")

    def test_detect_actual_quality_tag_shorts_vertical(self):
        # Short vertical con resolución 1080x1920
        mock_shorts_info = {
            "formats": [
                {"height": 1920, "width": 1080, "vcodec": "avc1"},
                {"height": 1280, "width": 720, "vcodec": "avc1"},
                {"height": 640, "width": 360, "vcodec": "avc1"},
            ]
        }
        # Para un Short, 'best' debe ser 1080p (NUNCA 1920p)
        self.assertEqual(detect_actual_quality_tag(mock_shorts_info, "best", "video", "320"), "1080p")
        # Si pide 720p en un Short, debe dar 720p
        self.assertEqual(detect_actual_quality_tag(mock_shorts_info, "720p", "video", "320"), "720p")

    def test_downloader_format_spec_strict_ceiling(self):
        # Verificar que la especificación de formato nunca permita descargar resoluciones superiores
        # Para 1080p:
        spec_1080 = DownloadWorker.build_format_spec("1080p", "video")
        self.assertIn("height<=1080", spec_1080)
        self.assertIn("width<=1080", spec_1080)
        # NUNCA debe contener el fallback sin restricciones '/bestvideo*+bestaudio/best'
        self.assertFalse(spec_1080.endswith("/bestvideo*+bestaudio/best"))

        # Para 480p:
        spec_480 = DownloadWorker.build_format_spec("480p", "video")
        self.assertIn("height<=480", spec_480)
        self.assertIn("width<=480", spec_480)
        self.assertNotIn("height<=1080", spec_480)
        self.assertFalse(spec_480.endswith("/bestvideo*+bestaudio/best"))

    def test_history_manager_atomic_and_repair(self):
        # Probar el guardado atómico, backup .bak y autoreparación
        temp_dir = Path(tempfile.mkdtemp())
        try:
            hist_file = temp_dir / "history.json"
            bak_file = temp_dir / "history.json.bak"

            # Modificar temporalmente las constantes de HistoryManager para la prueba
            import downfry.config as config_mod
            orig_hist = config_mod.HISTORY_FILE
            orig_bak = config_mod.HISTORY_FILE_BAK
            config_mod.HISTORY_FILE = hist_file
            config_mod.HISTORY_FILE_BAK = bak_file

            hm = HistoryManager()
            self.assertEqual(hm.history, [])

            # Agregar entradas
            hm.add_entry({"title": "Test 1", "filepath": "c:/test1.mp4", "quality": "1080p"})
            hm.add_entry({"title": "Test 2", "filepath": "c:/test2.mp4", "quality": "720p"})
            self.assertEqual(len(hm.history), 2)
            self.assertTrue(hist_file.exists())
            self.assertTrue(bak_file.exists())

            # Simular corrupción truncada (como la que ocurría al cerrar abruptamente)
            truncated_json = '[\n  {\n    "title": "Test 2",\n    "filepath": "c:/test2.mp4"\n  },\n  {\n    "title": "Corrupted'
            with open(hist_file, "w", encoding="utf-8") as f:
                f.write(truncated_json)

            # Cargar de nuevo: debe reparar automáticamente o recurrir al backup
            hm2 = HistoryManager()
            self.assertGreaterEqual(len(hm2.history), 1)
            self.assertEqual(hm2.history[0]["title"], "Test 2")

            config_mod.HISTORY_FILE = orig_hist
            config_mod.HISTORY_FILE_BAK = orig_bak
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_path_organizer_archive_paths(self):
        # 1. Video individual debe generar download_archive.txt en la carpeta base
        _, _, arch_single = PathOrganizer.get_output_paths(
            "C:/Downloads/Downfry",
            {"title": "Single Video", "uploader": "Canal"},
            download_type="video",
        )
        self.assertIsNotNone(arch_single)
        self.assertEqual(str(arch_single), str(Path("C:/Downloads/Downfry/download_archive.txt")))

        # 2. Canal debe generar download_archive.txt en la raíz del canal
        _, _, arch_chan = PathOrganizer.get_output_paths(
            "C:/Downloads/Downfry",
            {"title": "Chan Video", "uploader": "Canal"},
            download_type="channel",
        )
        self.assertIsNotNone(arch_chan)
        self.assertEqual(str(arch_chan), str(Path("C:/Downloads/Downfry/Canal/download_archive.txt")))

    def test_history_sanitize_intermediate_dash_file(self):
        temp_dir = Path(tempfile.mkdtemp())
        try:
            # Crear un archivo .mp4 real
            mp4_file = temp_dir / "Video [1080p].mp4"
            mp4_file.write_bytes(b"x" * 1024)

            # Entrada guardada erróneamente con .f251.webm intermedio
            fake_dash_path = str(temp_dir / "Video [1080p].f251.webm")
            entries = [{
                "title": "Video",
                "filepath": fake_dash_path,
                "size": 0,
                "mode": "video",
            }]

            hm = HistoryManager()
            sanitized = hm._sanitize_entries(entries)
            self.assertEqual(sanitized[0]["filepath"], str(mp4_file))
            self.assertEqual(sanitized[0]["size"], 1024)
            self.assertEqual(sanitized[0]["size_str"], "1.0 KB")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_cookieless_client_args(self):
        args = get_cookieless_client_args()
        clients = args["youtube"]["player_client"]
        self.assertTrue(len(clients) > 0)

    def test_hidden_temp_dir(self):
        temp_base = Path(tempfile.mkdtemp())
        try:
            temp_dir = DownloadWorker._ensure_hidden_temp_dir(temp_base)
            self.assertTrue(temp_dir.exists())
            self.assertEqual(temp_dir.name, ".temp")
            # Create a dummy file in .temp
            dummy = temp_dir / "test.part"
            dummy.write_text("dummy")
            self.assertTrue(dummy.exists())
            DownloadWorker._purge_temp_dir(temp_dir)
            self.assertFalse(dummy.exists())
            self.assertTrue(temp_dir.exists())
        finally:
            shutil.rmtree(temp_base, ignore_errors=True)

    def test_archive_title_cache(self):
        temp_dir = Path(tempfile.mkdtemp())
        try:
            import downfry.config as cfg
            orig = cfg.ARCHIVE_TITLES_FILE
            cfg.ARCHIVE_TITLES_FILE = temp_dir / "archive_titles.json"

            record_archive_title("dQw4w9WgXcQ", "Rick Astley - Never Gonna Give You Up")
            self.assertEqual(get_archive_title("dQw4w9WgXcQ"), "Rick Astley - Never Gonna Give You Up")
            self.assertIsNone(get_archive_title("unknown_id"))

            cfg.ARCHIVE_TITLES_FILE = orig
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_recycle_bin_lifecycle(self):
        temp_dir = Path(tempfile.mkdtemp())
        import downfry.config as cfg
        orig_hist_file = cfg.HISTORY_FILE
        orig_hist_bak = cfg.HISTORY_FILE_BAK
        orig_hist_list = list(cfg.history_manager.history)
        cfg.HISTORY_FILE = temp_dir / "test_history.json"
        cfg.HISTORY_FILE_BAK = temp_dir / "test_history.json.bak"
        cfg.history_manager.history = []

        try:
            orig_dir = config_manager.get("download_dir")
            orig_ret = config_manager.get("recycle_bin_retention")

            config_manager.set("download_dir", str(temp_dir))
            config_manager.set("recycle_bin_retention", "24h")

            # Crear un archivo de prueba
            test_file = temp_dir / "Test Video [1080p].mp4"
            test_file.write_bytes(b"A" * 2048)

            # 1. Mover a la papelera
            moved = RecycleBinManager.move_to_trash(str(test_file), "Test Video")
            self.assertTrue(moved)
            self.assertFalse(test_file.exists())

            # 2. Verificar estadísticas y get_items
            count, size_str = RecycleBinManager.get_trash_stats()
            self.assertEqual(count, 1)
            self.assertIn("2.0 KB", size_str)

            items = RecycleBinManager.get_items()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["title"], "Test Video")

            # 3. Probar restaurar archivo
            trash_filename = items[0]["trash_filename"]
            restored = RecycleBinManager.restore_item(trash_filename)
            self.assertTrue(restored)
            self.assertTrue(test_file.exists())
            self.assertEqual(RecycleBinManager.get_trash_stats()[0], 0)

            # Mover de nuevo a la papelera para continuar las pruebas
            RecycleBinManager.move_to_trash(str(test_file), "Test Video")
            self.assertEqual(RecycleBinManager.get_trash_stats()[0], 1)

            # 4. Purgar con límite de 24h (no debe purgarlo porque acaba de crearse)
            purged = RecycleBinManager.purge_expired()
            self.assertEqual(purged, 0)

            # 5. Simular que tiene más de 24h
            idx_file = RecycleBinManager._get_index_file()
            with open(idx_file, "r", encoding="utf-8") as f:
                idx_data = json.load(f)
            for k in idx_data:
                idx_data[k]["deleted_at"] = time.time() - (25 * 3600)
            with open(idx_file, "w", encoding="utf-8") as f:
                json.dump(idx_data, f)

            purged = RecycleBinManager.purge_expired()
            self.assertEqual(purged, 1)

            # Ahora la papelera debe estar vacía
            count_after, _ = RecycleBinManager.get_trash_stats()
            self.assertEqual(count_after, 0)

            # 6. Probar delete_item y empty_trash
            test_file2 = temp_dir / "Another [720p].mp4"
            test_file2.write_bytes(b"B" * 1024)
            RecycleBinManager.move_to_trash(str(test_file2), "Another")
            self.assertEqual(RecycleBinManager.get_trash_stats()[0], 1)

            items2 = RecycleBinManager.get_items()
            del_ok = RecycleBinManager.delete_item(items2[0]["trash_filename"])
            self.assertTrue(del_ok)
            self.assertEqual(RecycleBinManager.get_trash_stats()[0], 0)

            config_manager.set("download_dir", orig_dir)
            config_manager.set("recycle_bin_retention", orig_ret)
        finally:
            cfg.HISTORY_FILE = orig_hist_file
            cfg.HISTORY_FILE_BAK = orig_hist_bak
            cfg.history_manager.history = orig_hist_list
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_find_existing_download_and_unblock(self):
        temp_dir = Path(tempfile.mkdtemp())
        try:
            from downfry.core.organizer import find_existing_download, unblock_archive_id
            
            # Crear un archivo de prueba
            vid_file = temp_dir / "2026-01-01 - Mi Video Increible [1080p] - Canal.mp4"
            vid_file.write_bytes(b"dummy video data")

            # Crear download_archive.txt
            arch_file = temp_dir / "download_archive.txt"
            arch_file.write_text("youtube VID123\nyoutube VID456\n", encoding="utf-8")

            # 1. Buscar por título en disco
            res_disco = find_existing_download("VID999", "Mi Video Increible", str(temp_dir))
            self.assertIsNotNone(res_disco)
            self.assertEqual(res_disco[0], "Archivo en Disco")
            self.assertIn("Mi Video Increible", res_disco[1])

            # 2. Buscar por ID en archivo antiduplicados
            res_arch = find_existing_download("VID123", "Otro Titulo Distinto", str(temp_dir))
            self.assertIsNotNone(res_arch)
            self.assertEqual(res_arch[0], "Registro Antiduplicados")
            self.assertIn("VID123", res_arch[1])

            # 3. Video no existente
            res_none = find_existing_download("VID777", "Titulo Que Nunca Ha Existido", str(temp_dir))
            self.assertIsNone(res_none)

            # 4. Desbloquear ID
            unblock_archive_id(str(temp_dir), "VID123")
            res_unblocked = find_existing_download("VID123", "Otro Titulo Distinto", str(temp_dir))
            self.assertIsNone(res_unblocked)
            self.assertIn("VID456", arch_file.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_windows_reserved_names_and_path_truncation(self):
        # 1. Nombres reservados de Windows
        self.assertEqual(sanitize_filename("CON"), "_CON")
        self.assertEqual(sanitize_filename("aux.mp4"), "_aux.mp4")
        self.assertEqual(sanitize_filename("NUL"), "_NUL")
        self.assertEqual(sanitize_filename("com1"), "_com1")

        # 2. Truncado de rutas largas (< 240 caracteres)
        long_title = "Este es un titulo extremadamente largo que contiene muchas palabras " * 4
        long_uploader = "Canal Con Nombre Muy Extenso Y Descriptivo " * 2
        info = {"title": long_title, "uploader": long_uploader, "upload_date": "20261016"}
        target_dir, file_stem, _ = PathOrganizer.get_output_paths(
            "C:/Users/Usuario/Downloads/Downfry",
            info,
            download_type="channel",
            quality_tag="1080p",
        )
        full_path = str(target_dir / f"{file_stem}.mp4.part")
        self.assertLessEqual(len(full_path), 240)

    def test_history_deduplication(self):
        import downfry.config as cfg
        temp_dir = Path(tempfile.mkdtemp())
        orig_hist_file = cfg.HISTORY_FILE
        orig_hist_bak = cfg.HISTORY_FILE_BAK
        orig_hist_list = list(cfg.history_manager.history)
        cfg.HISTORY_FILE = temp_dir / "test_history.json"
        cfg.HISTORY_FILE_BAK = temp_dir / "test_history.json.bak"
        try:
            hm = HistoryManager()
            hm.history = []

            entry1 = {"title": "Original", "filepath": "C:/video.mp4", "video_id": "V1", "mode": "video"}
            hm.add_entry(entry1)
            self.assertEqual(len(hm.history), 1)

            # Mismo filepath debe reemplazar la entrada anterior
            entry2 = {"title": "Updated Title", "filepath": "C:/video.mp4", "video_id": "V1", "mode": "video"}
            hm.add_entry(entry2)
            self.assertEqual(len(hm.history), 1)
            self.assertEqual(hm.history[0]["title"], "Updated Title")

            # Mismo video_id y mismo mode pero diferente filepath debe deduplicar
            entry3 = {"title": "Third Title", "filepath": "C:/other.mp4", "video_id": "V1", "mode": "video"}
            hm.add_entry(entry3)
            self.assertEqual(len(hm.history), 1)
            self.assertEqual(hm.history[0]["title"], "Third Title")

            # Mismo video_id pero diferente mode (audio vs video) puede coexistir
            entry_audio = {"title": "Third Title Audio", "filepath": "C:/audio.mp3", "video_id": "V1", "mode": "audio"}
            hm.add_entry(entry_audio)
            self.assertEqual(len(hm.history), 2)
        finally:
            cfg.HISTORY_FILE = orig_hist_file
            cfg.HISTORY_FILE_BAK = orig_hist_bak
            cfg.history_manager.history = orig_hist_list
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_worker_temp_dir_isolation(self):
        temp_base = Path(tempfile.mkdtemp())
        try:
            dir1 = DownloadWorker._ensure_hidden_temp_dir(temp_base, "worker_1")
            dir2 = DownloadWorker._ensure_hidden_temp_dir(temp_base, "worker_2")
            self.assertNotEqual(str(dir1), str(dir2))
            self.assertTrue(dir1.exists())
            self.assertTrue(dir2.exists())

            # Crear archivos en ambas carpetas
            file1 = dir1 / "video.part"
            file2 = dir2 / "video.part"
            file1.write_text("w1")
            file2.write_text("w2")

            # Purgar worker 1 no debe afectar a worker 2
            DownloadWorker._purge_temp_dir(dir1)
            self.assertFalse(file1.exists())
            self.assertTrue(file2.exists())

            DownloadWorker._purge_temp_dir(dir2)
            self.assertFalse(file2.exists())
        finally:
            shutil.rmtree(temp_base, ignore_errors=True)

    def test_recycle_bin_metadata_preservation(self):
        temp_dir = Path(tempfile.mkdtemp())
        import downfry.config as cfg
        orig_hist_file = cfg.HISTORY_FILE
        orig_hist_bak = cfg.HISTORY_FILE_BAK
        orig_hist_list = list(cfg.history_manager.history)
        cfg.HISTORY_FILE = temp_dir / "test_history.json"
        cfg.HISTORY_FILE_BAK = temp_dir / "test_history.json.bak"
        cfg.history_manager.history = []

        try:
            orig_dir = config_manager.get("download_dir")
            config_manager.set("download_dir", str(temp_dir))

            test_file = temp_dir / "Video [1080p].mp4"
            test_file.write_bytes(b"data" * 512)

            meta = {
                "title": "Video Increible",
                "filepath": str(test_file),
                "video_id": "VID_PRESERVE",
                "quality": "1080p",
                "thumbnail": "https://i.ytimg.com/vi/VID_PRESERVE/hqdefault.jpg",
                "mode": "video",
                "url": "https://www.youtube.com/watch?v=VID_PRESERVE",
            }
            cfg.history_manager.add_entry(meta)

            # Mover a papelera pasando metadata
            moved = RecycleBinManager.move_to_trash(str(test_file), "Video Increible", metadata=meta)
            self.assertTrue(moved)

            items = RecycleBinManager.get_items()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["video_id"], "VID_PRESERVE")
            self.assertEqual(items[0]["quality"], "1080p")

            # Restaurar y verificar que el historial conserva calidad y video_id
            restored = RecycleBinManager.restore_item(items[0]["trash_filename"])
            self.assertTrue(restored)
            self.assertEqual(len(cfg.history_manager.history), 1)
            restored_entry = cfg.history_manager.history[0]
            self.assertEqual(restored_entry["video_id"], "VID_PRESERVE")
            self.assertEqual(restored_entry["quality"], "1080p")

            config_manager.set("download_dir", orig_dir)
        finally:
            cfg.HISTORY_FILE = orig_hist_file
            cfg.HISTORY_FILE_BAK = orig_hist_bak
            cfg.history_manager.history = orig_hist_list
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_unblock_archive_id_safe(self):
        temp_dir = Path(tempfile.mkdtemp())
        try:
            from downfry.core.organizer import unblock_archive_id
            arch_file = temp_dir / "download_archive.txt"
            # Caso de subcadenas y palabras como 'youtube' o 'yt'
            arch_file.write_text("youtube youtube\nyoutube yt\nyoutube VID123\nyoutube VID12345\n", encoding="utf-8")

            unblock_archive_id(str(temp_dir), "VID123")
            content = arch_file.read_text(encoding="utf-8")
            self.assertNotIn("VID123\n", content)
            # Debe mantener las demás líneas intactas
            self.assertIn("youtube youtube", content)
            self.assertIn("youtube yt", content)
            self.assertIn("youtube VID12345", content)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_get_resource_path(self):
        from downfry.config import get_resource_path
        icon_path = get_resource_path("packaging/app_icon.png")
        self.assertTrue(icon_path.exists())

    def test_client_fallback_chain_optimization(self):
        """Verifica que la cadena de clientes no empiece con 'default' y priorice android_vr."""
        self.assertGreater(len(CLIENT_FALLBACK_CHAIN), 1)
        self.assertNotEqual(CLIENT_FALLBACK_CHAIN[0], ["default"])
        self.assertEqual(CLIENT_FALLBACK_CHAIN[0], ["android_vr", "web_embedded"])
        self.assertEqual(CLIENT_FALLBACK_CHAIN[-1], ["default"])

    def test_subtitle_429_fallback_downloads_video(self):
        """Verifica que un error HTTP 429 en subtítulos no cancele la descarga del video."""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            worker = DownloadWorker(
                url="https://www.youtube.com/watch?v=sUzqz6G4y8g",
                target_dir=str(temp_dir),
                embed_subtitles=True,
            )
            ydl_opts = worker._build_ydl_opts(outtmpl={"default": "test.%(ext)s"})

            calls_opts = []
            class FakeYDL:
                def __init__(self, opts):
                    self.opts = opts
                    calls_opts.append(opts)
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
                def download(self, urls):
                    if self.opts.get("writesubtitles"):
                        raise Exception("ERROR: Unable to download video subtitles for 'es': HTTP Error 429: Too Many Requests")
                    return 0

            with patch("yt_dlp.YoutubeDL", FakeYDL):
                worker._execute_download_resilient("https://www.youtube.com/watch?v=sUzqz6G4y8g", ydl_opts)

            self.assertGreaterEqual(len(calls_opts), 2)
            first_call_opts = calls_opts[0]
            second_call_opts = calls_opts[1]

            self.assertTrue(first_call_opts.get("writesubtitles"))
            self.assertFalse(second_call_opts.get("writesubtitles"))
            self.assertNotIn("subtitleslangs", second_call_opts)
            pps = [pp.get("key") for pp in second_call_opts.get("postprocessors", [])]
            self.assertNotIn("FFmpegEmbedSubtitle", pps)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_clone_ydl_opts_safe_with_qthread_hooks(self):
        """Verifica que _clone_ydl_opts clone correctamente sin disparar error de pickle en QThread."""
        worker = DownloadWorker(
            url="https://www.youtube.com/watch?v=sUzqz6G4y8g",
            target_dir=".",
            embed_subtitles=True,
        )
        opts = worker._build_ydl_opts(outtmpl={"default": "test.%(ext)s"})
        self.assertIn(worker._progress_hook, opts["progress_hooks"])

        cloned = DownloadWorker._clone_ydl_opts(opts)
        self.assertEqual(cloned["outtmpl"], opts["outtmpl"])
        self.assertIsNot(cloned["outtmpl"], opts["outtmpl"])
        self.assertIsNot(cloned["postprocessors"], opts["postprocessors"])
        self.assertEqual(cloned["progress_hooks"], opts["progress_hooks"])

    def test_download_single_reuses_preloaded_info(self):
        """Verifica que si preloaded_info ya contiene metadatos, no se realiza una nueva extracción de red."""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            fake_preloaded = {
                "id": "sUzqz6G4y8g",
                "title": "Max Verstappen Qualifying",
                "thumbnail": "https://example.com/thumb.jpg",
                "_working_client": ["android_vr", "web_embedded"],
                "raw_info": {
                    "id": "sUzqz6G4y8g",
                    "title": "Max Verstappen Qualifying",
                    "thumbnail": "https://example.com/thumb.jpg",
                    "formats": [{"format_id": "18", "height": 360, "ext": "mp4"}],
                },
            }

            worker = DownloadWorker(
                url="https://www.youtube.com/watch?v=sUzqz6G4y8g",
                target_dir=str(temp_dir),
                preloaded_info=fake_preloaded,
            )

            def fake_execute(target_url, ydl_opts, preferred_client=None):
                home = Path(ydl_opts.get("paths", {}).get("home", temp_dir))
                out_name = ydl_opts["outtmpl"]["default"].replace("%(ext)s", "mp4")
                out_file = home / out_name
                out_file.write_bytes(b"dummy video data")

            with patch.object(worker, "_extract_video_metadata_resilient") as mock_extract, \
                 patch.object(worker, "_execute_download_resilient", side_effect=fake_execute) as mock_exec:
                worker._download_single(UrlType.VIDEO, "https://www.youtube.com/watch?v=sUzqz6G4y8g")

                mock_extract.assert_not_called()
                mock_exec.assert_called_once()
                call_args, call_kwargs = mock_exec.call_args
                self.assertEqual(call_kwargs.get("preferred_client"), ["android_vr", "web_embedded"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_open_in_explorer_command(self):
        """Verifica que open_in_explorer pase el comando sin comillas en /select."""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            from downfry.utils.formatting import open_in_explorer
            test_file = temp_dir / "Video Con Espacios En Nombre [1080p].mp4"
            test_file.write_bytes(b"dummy")

            with patch("subprocess.Popen") as mock_popen:
                success = open_in_explorer(str(test_file))
                self.assertTrue(success)
                mock_popen.assert_called_once()
                cmd = mock_popen.call_args[0][0]
                if isinstance(cmd, str):
                    self.assertTrue(cmd.startswith('explorer.exe /select,"'))
                    self.assertTrue(cmd.endswith('"'))
                    # Verificar que /select no esté entrecomillado
                    self.assertNotIn('"/select,', cmd)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_check_duplicates_config_option(self):
        """Verifica que el ajuste check_duplicates exista en la configuración."""
        orig = config_manager.get("check_duplicates")
        try:
            config_manager.set("check_duplicates", False)
            self.assertFalse(config_manager.get("check_duplicates"))
            config_manager.set("check_duplicates", True)
            self.assertTrue(config_manager.get("check_duplicates"))
        finally:
            config_manager.set("check_duplicates", orig if orig is not None else True)

    def test_channel_disk_based_duplicate_skipping(self):
        """Verifica el escaneo y detección de duplicados basado directamente en archivos de la carpeta."""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            channel_folder = temp_dir / "Mi Canal"
            channel_folder.mkdir(parents=True, exist_ok=True)

            # Archivo presente físicamente en disco
            existing_file = channel_folder / "2026-10-16 - Max Verstappen Qualifying [1080p] - Mi Canal.mp4"
            existing_file.write_bytes(b"dummy content 1080p")

            # Archivo en .temp o tamaño 0 (no debe considerarse existente)
            temp_sub = channel_folder / ".temp"
            temp_sub.mkdir(parents=True, exist_ok=True)
            (temp_sub / "in_temp.mp4").write_bytes(b"temporary")
            (channel_folder / "zero_bytes.mp4").write_bytes(b"")

            files = DownloadWorker._scan_disk_media_files(channel_folder)
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].name, existing_file.name)

            # 1. Video existente por título -> debe ser detectado
            match1 = DownloadWorker._is_item_already_on_disk(
                entry_title="Max Verstappen Qualifying",
                entry_id="sUzqz6G4y8g",
                existing_files=files,
            )
            self.assertIsNotNone(match1)
            self.assertEqual(match1, existing_file)

            # 2. Video que fue borrado o nunca existió -> debe retornar None (listo para descargar)
            match2 = DownloadWorker._is_item_already_on_disk(
                entry_title="Video Borrado Por El Usuario",
                entry_id="DELETED123",
                existing_files=files,
            )
            self.assertIsNone(match2)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_resolve_unique_stem_increments_counter(self):
        """Verifica que si ya existe un archivo con exactamente el mismo nombre se asigne (2), (3)..."""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            base_480 = "2026-10-16 - Max Verstappen Qualifying [480p] - GTWorld"
            # 1. Si no existe ningún archivo, debe retornar el nombre base
            stem1 = DownloadWorker._resolve_unique_stem(temp_dir, base_480, "mp4")
            self.assertEqual(stem1, base_480)

            # Crear el archivo en 480p
            (temp_dir / f"{base_480}.mp4").write_bytes(b"dummy 480p")

            # 2. Si se vuelve a descargar en 480p, debe retornar (2)
            stem2 = DownloadWorker._resolve_unique_stem(temp_dir, base_480, "mp4")
            self.assertEqual(stem2, f"{base_480} (2)")

            # Crear el archivo (2)
            (temp_dir / f"{base_480} (2).mp4").write_bytes(b"dummy 480p copy 2")

            # 3. Si se descarga una 3ra vez en 480p, debe retornar (3)
            stem3 = DownloadWorker._resolve_unique_stem(temp_dir, base_480, "mp4")
            self.assertEqual(stem3, f"{base_480} (3)")

            # 4. Si se cambia de calidad a 720p, NO debe llevar sufijo porque 720p no existía
            base_720 = "2026-10-16 - Max Verstappen Qualifying [720p] - GTWorld"
            stem_720 = DownloadWorker._resolve_unique_stem(temp_dir, base_720, "mp4")
            self.assertEqual(stem_720, base_720)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_single_download_does_not_pass_download_archive(self):
        """Verifica que en descargas individuales no se active download_archive en ydl_opts para no bloquear la descarga."""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            fake_preloaded = {
                "id": "sUzqz6G4y8g",
                "title": "Max Verstappen Qualifying",
                "thumbnail": "https://example.com/thumb.jpg",
                "raw_info": {
                    "id": "sUzqz6G4y8g",
                    "title": "Max Verstappen Qualifying",
                    "formats": [{"format_id": "18", "height": 360, "ext": "mp4"}],
                },
            }

            worker = DownloadWorker(
                url="https://www.youtube.com/watch?v=sUzqz6G4y8g",
                target_dir=str(temp_dir),
                preloaded_info=fake_preloaded,
            )

            executed_opts = []
            def fake_exec(url, opts, preferred_client=None):
                executed_opts.append(opts)
                # Crear el archivo resultante
                out_name = opts["outtmpl"]["default"].replace("%(ext)s", "mp4")
                (temp_dir / out_name).write_bytes(b"downloaded video")

            with patch.object(worker, "_execute_download_resilient", side_effect=fake_exec):
                worker._download_single(UrlType.VIDEO, "https://www.youtube.com/watch?v=sUzqz6G4y8g")

            self.assertEqual(len(executed_opts), 1)
            # download_archive NO debe estar presente en ydl_opts para permitir descargar calidades distintas y copias
            self.assertNotIn("download_archive", executed_opts[0])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extract_and_apply_publication_timestamps(self):
        from downfry.utils.formatting import extract_publication_timestamp, apply_publication_timestamps
        import os

        # 1. Verificar extracción de timestamp
        sample_info = {"upload_date": "20210515", "timestamp": 1621089000}
        ts = extract_publication_timestamp(sample_info)
        self.assertEqual(ts, 1621089000)

        # 2. Verificar aplicación en archivo físico
        temp_file = self._test_temp_dir / "test_file.mp4"
        temp_file.write_bytes(b"dummy video content")

        res = apply_publication_timestamps(temp_file, ts)
        self.assertTrue(res)

        stat = os.stat(temp_file)
        self.assertAlmostEqual(stat.st_mtime, 1621089000, delta=2)
        if os.name == "nt":
            self.assertAlmostEqual(stat.st_ctime, 1621089000, delta=2)

    def test_ffmpeg_metadata_and_chapters_postprocessor(self):
        # 1. En modo video
        worker_v = DownloadWorker(
            url="https://www.youtube.com/watch?v=dummy",
            target_dir=str(self._test_temp_dir),
            mode="video",
            embed_metadata=True,
            embed_chapters=True,
        )
        dummy_info = {
            "title": "Prueba Video",
            "channel": "Canal Prueba",
            "id": "abc123xyz",
            "upload_date": "20230101",
        }
        opts_v = worker_v._build_ydl_opts("out.mp4", media_info=dummy_info)
        pps_v = opts_v.get("postprocessors", [])
        meta_pp_v = [p for p in pps_v if p.get("key") == "FFmpegMetadata"]
        self.assertTrue(len(meta_pp_v) == 1)
        self.assertTrue(meta_pp_v[0].get("add_metadata"))
        self.assertTrue(meta_pp_v[0].get("add_chapters"))

        args_v = worker_v._build_ffmpeg_metadata_args(dummy_info, worker_v.url)
        self.assertIn("-metadata", args_v)
        self.assertTrue(any("artist=Canal Prueba" in a for a in args_v))
        self.assertTrue(any("downfry_video_id=abc123xyz" in a for a in args_v))
        self.assertTrue(any("date=2023-01-01" in a for a in args_v))

        # 2. En modo audio
        worker_a = DownloadWorker(
            url="https://www.youtube.com/watch?v=dummy",
            target_dir=str(self._test_temp_dir),
            mode="audio",
            audio_format="mp3",
            embed_metadata=True,
            embed_chapters=True,
        )
        opts_a = worker_a._build_ydl_opts("out.mp3", media_info=dummy_info)
        pps_a = opts_a.get("postprocessors", [])
        meta_pp_a = [p for p in pps_a if p.get("key") == "FFmpegMetadata"]
        self.assertTrue(len(meta_pp_a) == 1)
        self.assertTrue(meta_pp_a[0].get("add_metadata"))
        self.assertTrue(meta_pp_a[0].get("add_chapters"))

    def test_episodic_channel_titles_not_false_positive(self):
        # Simular archivos existentes en disco
        ep1_file = Path(r"C:\Downloads\2024-01-01 - Curso de Python Desde Cero - Episodio 1 [1080p] - Profe.mp4")
        existing = [ep1_file]

        # Episodio 1 debe detectarse como existente
        match_ep1 = DownloadWorker._is_item_already_on_disk(
            "Curso de Python Desde Cero - Episodio 1",
            "ID_EP1",
            existing,
        )
        self.assertIsNotNone(match_ep1)

        # Episodio 2 NO debe detectarse como existente aunque comparta las primeras 4 palabras
        match_ep2 = DownloadWorker._is_item_already_on_disk(
            "Curso de Python Desde Cero - Episodio 2",
            "ID_EP2",
            existing,
        )
        self.assertIsNone(match_ep2)

    def test_compute_ratelimit_bytes(self):
        from downfry.utils.formatting import compute_ratelimit_bytes
        self.assertIsNone(compute_ratelimit_bytes(0, "MB/s"))
        self.assertIsNone(compute_ratelimit_bytes(-5, "MB/s"))
        self.assertIsNone(compute_ratelimit_bytes(None, "MB/s"))
        self.assertEqual(compute_ratelimit_bytes(5, "MB/s"), 5 * 1000 * 1000)
        self.assertEqual(compute_ratelimit_bytes(500, "KB/s"), 500 * 1000)
        self.assertEqual(compute_ratelimit_bytes(2, "MiB/s"), 2 * 1024 * 1024)
        self.assertEqual(compute_ratelimit_bytes(256, "KiB/s"), 256 * 1024)

    def test_private_system_playlist_classification(self):
        url_wl = "https://www.youtube.com/playlist?list=WL"
        t_wl, meta_wl = classify_youtube_url(url_wl)
        self.assertEqual(t_wl, UrlType.PLAYLIST)
        self.assertTrue(meta_wl.get("is_private_system_playlist"))

        url_se = "https://music.youtube.com/playlist?list=SE"
        t_se, meta_se = classify_youtube_url(url_se)
        self.assertEqual(t_se, UrlType.PLAYLIST)
        self.assertTrue(meta_se.get("is_private_system_playlist"))

        url_pub = "https://www.youtube.com/playlist?list=PLREtiHbSfSnH3yx22T"
        t_pub, meta_pub = classify_youtube_url(url_pub)
        self.assertEqual(t_pub, UrlType.PLAYLIST)
        self.assertFalse(meta_pub.get("is_private_system_playlist"))

    def test_claimed_disk_files_prevents_false_skips(self):
        ep1_file = Path(r"C:\Downloads\2024-01-01 - Curso - Episodio 1 [1080p] - Canal.mp4")
        existing = [ep1_file]
        claimed = set()

        # Primer item reclama el archivo
        match1 = DownloadWorker._is_item_already_on_disk("Curso - Episodio 1", "ID1", existing, claimed_files=claimed)
        self.assertEqual(match1, ep1_file)
        claimed.add(str(match1))

        # Si otro video intenta emparejarse con el mismo archivo ya reclamado, debe dar None
        match2 = DownloadWorker._is_item_already_on_disk("Curso - Episodio 1", "ID2", existing, claimed_files=claimed)
        self.assertIsNone(match2)

    def test_history_sanitize_fixes_disco_quality(self):
        hm = HistoryManager()
        raw_entries = [
            {
                "title": "Video de prueba",
                "filepath": r"C:\Descargas\2022-10-19 - Video [720p] - Canal.mp4",
                "quality": "disco",
                "mode": "video",
            }
        ]
        sanitized = hm._sanitize_entries(raw_entries)
        self.assertEqual(sanitized[0]["quality"], "720p")

    def test_history_manager_remove_entry_safe(self):
        """Verifica que remove_entry elimine entradas por filepath o video_id de forma segura."""
        import downfry.config as cfg
        temp_dir = Path(tempfile.mkdtemp())
        orig_hist_file = cfg.HISTORY_FILE
        orig_hist_bak = cfg.HISTORY_FILE_BAK
        orig_hist_list = list(cfg.history_manager.history)
        cfg.HISTORY_FILE = temp_dir / "test_history.json"
        cfg.HISTORY_FILE_BAK = temp_dir / "test_history.json.bak"
        try:
            hm = HistoryManager()
            hm.history = []
            hm.add_entry({"title": "Test 1", "filepath": "C:/fake/1.mp4", "video_id": "V1", "mode": "video"})
            hm.add_entry({"title": "Test 2", "filepath": "C:/fake/2.mp4", "video_id": "V2", "mode": "video"})
            self.assertEqual(len(hm.history), 2)

            # Eliminar por filepath
            hm.remove_entry("C:/fake/1.mp4")
            self.assertEqual(len(hm.history), 1)
            self.assertEqual(hm.history[0]["video_id"], "V2")

            # Eliminar por video_id cuando filepath está vacío o desalineado
            hm.remove_entry("", video_id="V2")
            self.assertEqual(len(hm.history), 0)
        finally:
            cfg.HISTORY_FILE = orig_hist_file
            cfg.HISTORY_FILE_BAK = orig_hist_bak
            cfg.history_manager.history = orig_hist_list
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


