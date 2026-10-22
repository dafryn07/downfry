from typing import Optional, Dict, Any
from pathlib import Path
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QApplication,
)
from qfluentwidgets import (
    SubtitleLabel,
    TitleLabel,
    BodyLabel,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    CardWidget,
    IndeterminateProgressBar,
    InfoBar,
    InfoBarPosition,
    FluentIcon as FIF,
)
from downfry.core.extractor import MetadataExtractor
from downfry.core.classifier import classify_youtube_url, UrlType
from downfry.core.organizer import PathOrganizer
from downfry.utils.formatting import sanitize_filename
from downfry.ui.components.video_card import VideoCard
from downfry.ui.components.options_dialog import DownloadOptionsDialog
from downfry.ui.components.duplicate_dialog import DuplicateWarningDialog


class AnalyzeThread(QThread):
    info_extracted = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            info = MetadataExtractor.extract_info(self.url)
            if not self._cancelled:
                self.info_extracted.emit(info)
        except Exception as e:
            if not self._cancelled:
                self.error_occurred.emit(str(e))


class HomeView(QWidget):
    start_download_requested = pyqtSignal(str, dict, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HomeView")
        self.analyze_thread: Optional[AnalyzeThread] = None
        self.current_info: Optional[Dict[str, Any]] = None
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 24, 30, 24)
        main_layout.setSpacing(20)

        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)
        title = TitleLabel("Downfry", self)
        subtitle = BodyLabel("Descarga videos, shorts, directos, playlists y canales de YouTube en su idioma y calidad original", self)
        subtitle.setStyleSheet("color: #888888;")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        main_layout.addLayout(header_layout)

        input_card = CardWidget(self)
        input_layout = QHBoxLayout(input_card)
        input_layout.setContentsMargins(12, 10, 12, 10)
        input_layout.setSpacing(10)

        self.url_input = LineEdit(self)
        self.url_input.setPlaceholderText("Pega aquí el enlace de YouTube (Video, Short, Directo, Playlist o Canal)...")
        self.url_input.setClearButtonEnabled(True)
        self.url_input.returnPressed.connect(self._on_analyze_clicked)
        input_layout.addWidget(self.url_input, stretch=1)

        self.paste_btn = PushButton(FIF.PASTE, "Pegar", self)
        self.paste_btn.clicked.connect(self._on_paste_clicked)
        input_layout.addWidget(self.paste_btn)

        self.analyze_btn = PrimaryPushButton(FIF.SEARCH, "Analizar Enlace", self)
        self.analyze_btn.clicked.connect(self._on_analyze_clicked)
        input_layout.addWidget(self.analyze_btn)

        main_layout.addWidget(input_card)

        self.progress_bar = IndeterminateProgressBar(self)
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        self.video_card = VideoCard(self)
        self.video_card.setVisible(False)
        self.video_card.configure_requested.connect(self._open_options_dialog)
        main_layout.addWidget(self.video_card)

        main_layout.addStretch()

    def _on_paste_clicked(self):
        clipboard = QApplication.clipboard()
        text = clipboard.text().strip()
        if text:
            self.url_input.setText(text)
            self._on_analyze_clicked()

    def _on_analyze_clicked(self):
        url = self.url_input.text().strip()
        if not url:
            InfoBar.warning(
                title="Enlace vacío",
                content="Por favor, introduce o pega un enlace de YouTube.",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
            return

        url_type, _ = classify_youtube_url(url)
        if url_type == UrlType.UNKNOWN:
            InfoBar.warning(
                title="Enlace no reconocido",
                content="Introduce un enlace válido de YouTube (video, short, directo, playlist o canal).",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self,
            )
            return

        self.progress_bar.setVisible(True)
        self.analyze_btn.setEnabled(False)
        self.video_card.setVisible(False)

        if self.analyze_thread is not None:
            try:
                if self.analyze_thread.isRunning():
                    self.analyze_thread.cancel()
                self.analyze_thread.info_extracted.disconnect()
                self.analyze_thread.error_occurred.disconnect()
            except (RuntimeError, TypeError, Exception):
                pass
            self.analyze_thread = None

        self.analyze_thread = AnalyzeThread(url, self)
        self.analyze_thread.info_extracted.connect(self._on_info_extracted)
        self.analyze_thread.error_occurred.connect(self._on_analyze_error)
        self.analyze_thread.start()

    def _on_info_extracted(self, info: Dict[str, Any]):
        self.progress_bar.setVisible(False)
        self.analyze_btn.setEnabled(True)
        self.current_info = info
        self.video_card.set_data(info)
        self.video_card.setVisible(True)

    def _on_analyze_error(self, err_msg: str):
        self.progress_bar.setVisible(False)
        self.analyze_btn.setEnabled(True)
        InfoBar.error(
            title="Error al analizar enlace",
            content=f"No se pudo extraer la información: {err_msg}",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self,
        )

    def _open_options_dialog(self):
        if not self.current_info:
            return

        from downfry.core.organizer import find_existing_download, unblock_archive_id
        from downfry.config import config_manager

        default_dir = config_manager.get("download_dir", str(Path.home() / "Downloads" / "Downfry"))
        vid_id = str(self.current_info.get("id") or "")
        title = str(self.current_info.get("title") or "")
        is_batch = self.current_info.get("is_playlist") or self.current_info.get("type") in ("channel", "playlist")

        # 1. Comprobar si ya existe antes de configurar la descarga (si está activado en configuración)
        check_dups = config_manager.get("check_duplicates", True)
        if check_dups and not is_batch:
            existing = find_existing_download(vid_id, title, default_dir)
            if existing:
                match_type, match_loc = existing
                warn_dialog = DuplicateWarningDialog(
                    title,
                    match_type=match_type,
                    match_loc=match_loc,
                    parent=self.window(),
                )
                if not warn_dialog.exec():
                    return
                unblock_archive_id(default_dir, vid_id)

        dialog = DownloadOptionsDialog(self.current_info, parent=self.window())
        if dialog.exec():
            options = dialog.get_options()
            url = self.url_input.text().strip()
            info_to_pass = self.current_info.copy()

            # Si era un video con playlist y el usuario eligió descargar toda la playlist
            if options.get("download_playlist_scope") == "playlist" and self.current_info.get("playlist_url"):
                url = self.current_info["playlist_url"]
                info_to_pass["type"] = "playlist"
                info_to_pass["is_playlist"] = True
            elif self.current_info.get("webpage_url") and not info_to_pass.get("is_playlist"):
                url = self.current_info["webpage_url"]

            target_dir = options.get("target_dir", default_dir)
            if check_dups and not info_to_pass.get("is_playlist") and info_to_pass.get("type") not in ("channel", "playlist"):
                if target_dir != default_dir:
                    existing2 = find_existing_download(vid_id, title, target_dir)
                    if existing2:
                        match_type2, match_loc2 = existing2
                        warn_dialog2 = DuplicateWarningDialog(
                            title,
                            match_type=match_type2,
                            match_loc=match_loc2,
                            parent=self.window(),
                        )
                        if not warn_dialog2.exec():
                            return
                unblock_archive_id(target_dir, vid_id)

            self.start_download_requested.emit(url, info_to_pass, options)
