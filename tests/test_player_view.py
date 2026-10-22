import unittest
import sys
import tempfile
import shutil
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from downfry.ui.views.player_view import PlayerView, ChapterSlider

app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)


class TestPlayerView(unittest.TestCase):

    def setUp(self):
        self.player_view = PlayerView()
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        self.player_view.pause_playback()
        self.player_view.deleteLater()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_chapter_slider(self):
        slider = ChapterSlider()
        slider.setRange(0, 300)

        chapters = [
            {"title": "Intro", "start_time": 0.0, "end_time": 60.0},
            {"title": "Desarrollo", "start_time": 60.0, "end_time": 200.0},
            {"title": "Conclusión", "start_time": 200.0, "end_time": 300.0},
        ]
        slider.set_chapters(chapters)
        self.assertEqual(len(slider.chapters), 3)

        # Buscar capítulo según segundo actual
        ch1 = slider.get_chapter_at_sec(15.0)
        self.assertIsNotNone(ch1)
        self.assertEqual(ch1["title"], "Intro")

        ch2 = slider.get_chapter_at_sec(120.0)
        self.assertIsNotNone(ch2)
        self.assertEqual(ch2["title"], "Desarrollo")

        ch3 = slider.get_chapter_at_sec(250.0)
        self.assertIsNotNone(ch3)
        self.assertEqual(ch3["title"], "Conclusión")

    def test_player_view_api_and_state(self):
        self.assertEqual(self.player_view.objectName(), "PlayerView")
        self.assertTrue(hasattr(self.player_view, "load_and_play"))
        self.assertTrue(hasattr(self.player_view, "play_filepath"))
        self.assertTrue(hasattr(self.player_view, "pause_playback"))
        self.assertTrue(hasattr(self.player_view, "progress_updated"))

        # Cargar video simulado
        fake_video = self.temp_dir / "test_video.mp4"
        fake_video.write_bytes(b"test data")

        item = {
            "title": "Prueba de Video",
            "filepath": str(fake_video),
            "video_id": "TEST_VID",
            "duration": 180.0,
            "chapters": [{"title": "Inicio", "start_time": 0.0, "end_time": 180.0}],
            "channel": "Canal Downfry",
            "description": "Descripción completa de prueba",
        }

        self.player_view.load_and_play(item, resume=False)
        self.assertEqual(self.player_view.current_title, "Prueba de Video")
        self.assertEqual(self.player_view.current_filepath, str(fake_video))
        self.assertEqual(len(self.player_view.chapters), 1)

        # Pausar
        self.player_view.pause_playback()


if __name__ == "__main__":
    unittest.main()
