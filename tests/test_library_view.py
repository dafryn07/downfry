import os
import sys
import unittest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPoint

# Crear instancia de QApplication si no existe
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

from downfry.ui.components.library_cards import (
    YouTubeVideoCard,
    ChannelSidebarItem,
    SidebarNavButton,
    ThumbnailWidget,
    _get_channel_initials,
    _get_channel_color,
    _format_date_ddmmyyyy,
)
from downfry.ui.views.library_view import LibraryView
from downfry.ui.views.history_view import HistoryItemCard, HistoryView
from downfry.ui.main_window import MainWindow


class TestLibraryComponents(unittest.TestCase):
    def test_avatar_helpers(self):
        initials = _get_channel_initials("Los Falta de Modo")
        self.assertEqual(initials, "LF")
        single_initial = _get_channel_initials("Antigravity")
        self.assertEqual(single_initial, "AN")
        color = _get_channel_color("Canal Prueba")
        self.assertTrue(color.startswith("#"))

    def test_date_formatting(self):
        self.assertEqual(_format_date_ddmmyyyy("2022-12-21"), "21/12/2022")
        self.assertEqual(_format_date_ddmmyyyy("20220713"), "13/07/2022")
        self.assertEqual(_format_date_ddmmyyyy(""), "")
        self.assertEqual(_format_date_ddmmyyyy("15/08/2023"), "15/08/2023")

    def test_thumbnail_widget_progress(self):
        thumb = ThumbnailWidget(225, 126)
        thumb.set_data(
            duration_str="15:30",
            quality_str="1080p",
            progress_ratio=0.5,
            is_completed=False,
        )
        self.assertEqual(thumb.duration_str, "15:30")
        self.assertEqual(thumb.quality_str, "1080p")
        self.assertEqual(thumb.progress_ratio, 0.5)
        self.assertFalse(thumb.is_completed)

        thumb.set_progress(1.0, completed=True)
        self.assertEqual(thumb.progress_ratio, 1.0)
        self.assertTrue(thumb.is_completed)

    def test_youtube_video_card(self):
        item = {
            "video_id": "test12345",
            "title": "Video de prueba en la biblioteca",
            "filepath": "C:\\Downloads\\video.mp4",
            "uploader": "Canal Uno",
            "channel": "Canal Uno",
            "upload_date": "2022-07-13",
            "iso_date": "2022-07-13",
            "duration": 600,
            "duration_str": "10:00",
            "size": 104857600,
            "size_str": "100.0 MB",
            "quality": "1080p",
            "progress": {"ratio": 0.35, "completed": False},
        }
        card = YouTubeVideoCard(item)
        self.assertEqual(card.item["video_id"], "test12345")
        self.assertEqual(card.thumb_widget.progress_ratio, 0.35)

        # Verificar que NO existen botones de acción inferiores (reproducción limpia estilo YouTube)
        self.assertFalse(hasattr(card, "play_btn"))
        self.assertFalse(hasattr(card, "vlc_btn"))
        self.assertFalse(hasattr(card, "folder_btn"))

        # Verificar botón de más opciones ⋮
        self.assertTrue(hasattr(card, "more_btn"))
        self.assertIsNotNone(card.more_btn)

        # Verificar que la fecha está en DD/MM/AAAA y que se muestra la duración sin el peso en MB
        meta_text = card.meta_label.text()
        self.assertIn("13/07/2022", meta_text)
        self.assertIn("10:00", meta_text)
        self.assertNotIn("MB", meta_text)
        self.assertNotIn("GB", meta_text)

        # Probar emisión de señal play_clicked al accionar play
        received = []
        card.play_clicked.connect(lambda it: received.append(it))
        card._on_play()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["video_id"], "test12345")

    def test_sidebar_items(self):
        channel_item = ChannelSidebarItem(name="Los Falta de Modo", count=22)
        self.assertEqual(channel_item.name, "Los Falta de Modo")
        self.assertEqual(channel_item.count, 22)
        channel_item.set_selected(True)
        self.assertTrue(channel_item.is_selected)

        nav_btn = SidebarNavButton("all", "Todos los videos", "🎬", count=10)
        self.assertEqual(nav_btn.key, "all")
        self.assertEqual(nav_btn.count, 10)
        nav_btn.update_count(25)
        self.assertEqual(nav_btn.count, 25)

    def test_library_view_filtering_and_clean_months(self):
        view = LibraryView(auto_load=False)

        mock_items = [
            {
                "video_id": "v1",
                "title": "Primer Video",
                "channel": "Canal Alfa",
                "uploader": "Canal Alfa",
                "category": "Videos",
                "year": "2022",
                "month_folder": "07 - Julio",
                "iso_date": "2022-07-13",
                "duration": 500,
                "size": 50000000,
                "progress": {"ratio": 0.0, "completed": False},
            },
            {
                "video_id": "v2",
                "title": "Segundo Video Short",
                "channel": "Canal Beta",
                "uploader": "Canal Beta",
                "category": "Shorts",
                "year": "2023",
                "month_folder": "08 - Agosto",
                "iso_date": "2023-08-20",
                "duration": 60,
                "size": 10000000,
                "progress": {"ratio": 0.6, "completed": False},
            },
        ]
        mock_channels = [
            {"name": "Canal Alfa", "count": 1, "items": [mock_items[0]]},
            {"name": "Canal Beta", "count": 1, "items": [mock_items[1]]},
        ]
        mock_playlists = []

        view._on_scan_completed(mock_items, mock_channels, mock_playlists)
        self.assertEqual(len(view.all_items), 2)
        self.assertEqual(len(view.filtered_items), 2)

        # Comprobar que en el combo de meses NO se muestra el número "07 - " sino "Julio"
        month_texts = [view.month_combo.itemText(i) for i in range(view.month_combo.count())]
        self.assertIn("Julio", month_texts)
        self.assertIn("Agosto", month_texts)
        self.assertNotIn("07 - Julio", month_texts)

        # Filtrar por "Continuar viendo"
        view._on_nav_continue_clicked()
        self.assertEqual(len(view.filtered_items), 1)
        self.assertEqual(view.filtered_items[0]["video_id"], "v2")

        # Filtrar por búsqueda
        view._on_nav_all_clicked()
        view._on_search_text_changed("Primer")
        self.assertEqual(len(view.filtered_items), 1)
        self.assertEqual(view.filtered_items[0]["video_id"], "v1")

    def test_history_view_signals(self):
        entry = {
            "title": "Video Descargado Historial",
            "filepath": "C:\\Downloads\\test.mp4",
            "video_id": "hist_123",
        }
        card = HistoryItemCard(entry)
        emitted = []
        card.play_internal_requested.connect(lambda e: emitted.append(e))

        card._on_play_internal()
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            temp_path = tf.name
        try:
            entry["filepath"] = temp_path
            card_with_file = HistoryItemCard(entry)
            card_with_file.play_internal_requested.connect(lambda e: emitted.append(e))
            card_with_file._on_play_internal()
            self.assertEqual(len(emitted), 1)
            self.assertEqual(emitted[0]["video_id"], "hist_123")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_main_window_sub_interfaces(self):
        win = MainWindow()
        try:
            self.assertTrue(hasattr(win, "library_view"))
            self.assertTrue(hasattr(win, "player_view"))
            self.assertIsNotNone(win.library_view)
            self.assertIsNotNone(win.player_view)
        finally:
            if hasattr(win, "library_view") and hasattr(win.library_view, "close"):
                win.library_view.close()
            win.close()


if __name__ == "__main__":
    unittest.main()
