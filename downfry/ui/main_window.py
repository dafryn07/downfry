from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import (
    FluentWindow,
    NavigationItemPosition,
    FluentIcon as FIF,
    setTheme,
    Theme,
    InfoBar,
    InfoBarPosition,
)
from downfry.config import config_manager
from downfry.ui.views.home_view import HomeView
from downfry.ui.views.queue_view import QueueView
from downfry.ui.views.history_view import HistoryView
from downfry.ui.views.recycle_bin_view import RecycleBinView
from downfry.ui.views.settings_view import SettingsView
from downfry.ui.views.library_view import LibraryView
from downfry.ui.views.player_view import PlayerView


class MainWindow(FluentWindow):
    """Ventana principal de Downfry para Windows 11 con efecto Mica y diseño Fluent 2."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Downfry - YouTube Media Downloader")
        self.resize(1020, 700)
        self.setMinimumSize(850, 580)

        # Configurar icono de la aplicación
        from downfry.config import get_resource_path
        icon_path = get_resource_path("packaging/app_icon.png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # Sincronizar automáticamente color de énfasis y tema con Windows 11
        from downfry.utils.formatting import get_windows_accent_color
        from qfluentwidgets import setThemeColor
        accent = get_windows_accent_color()
        if accent:
            setThemeColor(accent)

        # Aplicar tema guardado
        saved_theme = config_manager.get("theme", "Auto")
        if saved_theme == "Dark":
            setTheme(Theme.DARK)
        elif saved_theme == "Light":
            setTheme(Theme.LIGHT)
        else:
            setTheme(Theme.AUTO)

        self._init_sub_interfaces()
        self._init_navigation()

    def _init_sub_interfaces(self):
        self.home_view = HomeView(self)
        self.queue_view = QueueView(self)
        self.library_view = LibraryView(self)
        self.player_view = PlayerView(self)
        self.history_view = HistoryView(self)
        self.recycle_view = RecycleBinView(self)
        self.settings_view = SettingsView(self)

        # Conectar el inicio de descarga desde Home a la Cola
        self.home_view.start_download_requested.connect(self._on_start_download)
        self.queue_view.download_finished.connect(self.history_view.reload_history)
        self.queue_view.download_finished.connect(self.library_view.reload_library)

        # Conectar navegación de reproducción de la Biblioteca e Historial al Reproductor
        self.library_view.play_video_requested.connect(self._on_play_video)
        self.history_view.play_internal_requested.connect(self._on_play_history_video)
        self.player_view.progress_updated.connect(self._on_player_progress_updated)

        # Sincronización cruzada de papelera e historial
        self.history_view.file_deleted.connect(self.recycle_view.reload_trash)
        self.history_view.file_deleted.connect(self.settings_view.refresh_trash_stats)
        self.recycle_view.item_restored.connect(self.history_view.reload_history)
        self.recycle_view.item_restored.connect(self.settings_view.refresh_trash_stats)
        self.settings_view.trash_emptied.connect(self.recycle_view.reload_trash)

    def _init_navigation(self):
        # 1. Inicio
        self.addSubInterface(
            self.home_view,
            FIF.HOME,
            "Inicio",
            NavigationItemPosition.TOP,
        )

        # 2. Descargas activas
        self.addSubInterface(
            self.queue_view,
            FIF.DOWNLOAD,
            "Descargas",
            NavigationItemPosition.TOP,
        )

        # 3. Biblioteca Offline (Estilo YouTube)
        self.addSubInterface(
            self.library_view,
            FIF.VIDEO,
            "Explorar",
            NavigationItemPosition.TOP,
        )

        # 4. Reproductor Integrado
        self.addSubInterface(
            self.player_view,
            FIF.PLAY,
            "Reproductor",
            NavigationItemPosition.TOP,
        )

        # 5. Historial
        self.addSubInterface(
            self.history_view,
            FIF.FOLDER,
            "Historial",
            NavigationItemPosition.TOP,
        )

        # 6. Papelera de reciclaje
        self.addSubInterface(
            self.recycle_view,
            FIF.DELETE,
            "Papelera",
            NavigationItemPosition.TOP,
        )

        # 7. Configuración (abajo)
        self.addSubInterface(
            self.settings_view,
            FIF.SETTING,
            "Configuración",
            NavigationItemPosition.BOTTOM,
        )

    def _on_start_download(self, url: str, info: dict, options: dict):
        """Pasa la descarga a la cola y cambia a la vista de descargas."""
        self.queue_view.add_download(url, info, options)
        # Cambiar automáticamente a la vista de descargas para ver el progreso
        self.switchTo(self.queue_view)

    def _on_play_video(self, item: dict, queue: list = None):
        """Cambia a la vista del reproductor y carga el video."""
        self.switchTo(self.player_view)
        self.player_view.load_and_play(item, queue or [item])

    def _on_play_history_video(self, entry: dict):
        """Reproduce un elemento seleccionado desde el historial."""
        self.switchTo(self.player_view)
        self.player_view.load_and_play(entry, [entry])

    def _on_player_progress_updated(self, filepath: str, pos_sec: float, dur_sec: float):
        """Actualiza la barra de progreso en vivo en las tarjetas de la biblioteca."""
        ratio = min(1.0, max(0.0, pos_sec / dur_sec)) if dur_sec > 0 else 0.0
        completed = (ratio >= 0.95) or (dur_sec > 0 and (dur_sec - pos_sec) <= 10.0)
        self.library_view.update_card_progress(video_id="", filepath=filepath, ratio=ratio, completed=completed)

    def closeEvent(self, event):
        """Previene el cierre abrupto si hay descargas activas en curso y pausa la reproducción."""
        if hasattr(self, "player_view") and hasattr(self.player_view, "pause_playback"):
            try:
                self.player_view.pause_playback()
            except Exception:
                pass

        active = [w for w in getattr(self.queue_view, "active_workers", []) if w.isRunning()]
        if active:
            from qfluentwidgets import MessageBox
            w = MessageBox(
                "¿Cancelar descargas y salir?",
                f"Hay {len(active)} descarga(s) activa(s) en curso.\n\nSi sales ahora se cancelarán las descargas incompletas.",
                self,
            )
            w.yesButton.setText("Sí, cancelar y salir")
            w.cancelButton.setText("Continuar descargando")
            if w.exec():
                for worker in active:
                    worker.cancel()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
