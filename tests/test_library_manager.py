import unittest
import tempfile
import shutil
import os
from pathlib import Path

from downfry.core.library_manager import PlaybackProgressManager, OfflineLibraryManager


class TestLibraryManager(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.progress_file = self.temp_dir / "test_progress.json"
        self.progress_mgr = PlaybackProgressManager(progress_file=self.progress_file)
        self.lib_mgr = OfflineLibraryManager()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_playback_progress_update_and_get(self):
        # 1. Video no registrado debe retornar valores por defecto
        p0 = self.progress_mgr.get_progress(video_id="VID1", filepath="C:/video1.mp4")
        self.assertEqual(p0["position_sec"], 0.0)
        self.assertEqual(p0["ratio"], 0.0)
        self.assertFalse(p0["completed"])

        # 2. Registrar progreso a la mitad (50%)
        rec = self.progress_mgr.update_progress(
            video_id="VID1",
            filepath=str(self.temp_dir / "video1.mp4"),
            position_sec=120.0,
            duration_sec=240.0,
        )
        self.assertEqual(rec["ratio"], 0.5)
        self.assertFalse(rec["completed"])
        self.assertEqual(rec["position_sec"], 120.0)

        # 3. Obtener por video_id
        p1 = self.progress_mgr.get_progress(video_id="VID1")
        self.assertEqual(p1["ratio"], 0.5)
        self.assertEqual(p1["duration_sec"], 240.0)

        # 4. Obtener por filepath
        p2 = self.progress_mgr.get_progress(filepath=str(self.temp_dir / "video1.mp4"))
        self.assertEqual(p2["ratio"], 0.5)

        # 5. Registrar video casi completado (>= 95% o <= 10s para el final)
        rec_complete = self.progress_mgr.update_progress(
            video_id="VID1",
            filepath=str(self.temp_dir / "video1.mp4"),
            position_sec=235.0,
            duration_sec=240.0,
        )
        self.assertTrue(rec_complete["completed"])

        # 6. Limpiar progreso
        self.progress_mgr.clear_progress(video_id="VID1")
        p_cleared = self.progress_mgr.get_progress(video_id="VID1")
        self.assertEqual(p_cleared["position_sec"], 0.0)
        self.assertFalse(p_cleared["completed"])

    def test_parse_file_path_standard_channel_format(self):
        base_dir = self.temp_dir / "Downloads"
        file_path = base_dir / "Formula 1" / "2024" / "05 - Mayo" / "Videos" / "2024-05-18 - Monaco GP Highlights [1080p] - Formula 1.mp4"
        meta = self.lib_mgr._parse_file_path(file_path, base_dir)

        self.assertEqual(meta["title"], "Monaco GP Highlights")
        self.assertEqual(meta["quality"], "1080p")
        self.assertEqual(meta["channel"], "Formula 1")
        self.assertEqual(meta["iso_date"], "2024-05-18")
        self.assertEqual(meta["year"], "2024")
        self.assertEqual(meta["month_folder"], "05 - Mayo")
        self.assertEqual(meta["category"], "Videos")

    def test_parse_file_path_shorts_detection(self):
        base_dir = self.temp_dir / "Downloads"
        file_path = base_dir / "Canal" / "2024" / "01 - Enero" / "Shorts" / "2024-01-10 - Mi short increible [1080p] - Canal.mp4"
        meta = self.lib_mgr._parse_file_path(file_path, base_dir)

        self.assertEqual(meta["category"], "Shorts")
        self.assertEqual(meta["title"], "Mi short increible")

    def test_scan_library_and_grouping(self):
        dl_dir = self.temp_dir / "Downfry"
        dl_dir.mkdir(parents=True, exist_ok=True)

        # Crear archivos simulados
        ch1_dir = dl_dir / "Canal Tech" / "2024" / "01 - Enero" / "Videos"
        ch1_dir.mkdir(parents=True, exist_ok=True)
        v1 = ch1_dir / "2024-01-15 - Review Laptop [1080p] - Canal Tech.mp4"
        v1.write_bytes(b"dummy video content 1")

        ch2_dir = dl_dir / "Canal Gaming" / "2024" / "02 - Febrero" / "Videos"
        ch2_dir.mkdir(parents=True, exist_ok=True)
        v2 = ch2_dir / "2024-02-20 - Gameplay [720p] - Canal Gaming.mp4"
        v2.write_bytes(b"dummy video content 2")

        # Carpeta especial excluida (Papelera)
        trash_dir = dl_dir / "Papelera"
        trash_dir.mkdir(parents=True, exist_ok=True)
        v_trash = trash_dir / "2024-01-01 - Borrado.mp4"
        v_trash.write_bytes(b"deleted content")

        # Escanear
        items = self.lib_mgr.scan_library(download_dir=str(dl_dir))
        self.assertEqual(len(items), 2)

        # Verificar canales agrupados
        channels = self.lib_mgr.get_channels(items)
        self.assertEqual(len(channels), 2)
        names = {c["name"] for c in channels}
        self.assertIn("Canal Tech", names)
        self.assertIn("Canal Gaming", names)


if __name__ == "__main__":
    unittest.main()
