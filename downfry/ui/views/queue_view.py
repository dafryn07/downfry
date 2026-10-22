from typing import Dict, Any, List
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
)
from qfluentwidgets import (
    TitleLabel,
    SubtitleLabel,
    CaptionLabel,
    CardWidget,
    ProgressBar,
    PushButton,
    InfoBar,
    InfoBarPosition,
    FluentIcon as FIF,
)
from downfry.core.downloader import DownloadWorker
from downfry.ui.components.download_item import DownloadItemCard


class QueueView(QWidget):
    """Vista de cola y progreso de descargas en tiempo real."""

    download_finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("QueueView")
        self.active_workers: List[DownloadWorker] = []
        self.batch_workers: List[DownloadWorker] = []
        self.current_batch_worker: Optional[DownloadWorker] = None
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 24, 30, 24)
        main_layout.setSpacing(16)

        header = TitleLabel("Descargas en Curso", self)
        main_layout.addWidget(header)

        self.batch_card = CardWidget(self)
        self.batch_card.setVisible(False)
        bc_layout = QVBoxLayout(self.batch_card)
        bc_layout.setContentsMargins(16, 12, 16, 12)
        bc_layout.setSpacing(8)

        self.batch_title_label = SubtitleLabel("Progreso de Lista / Canal", self.batch_card)
        self.batch_title_label.setWordWrap(True)
        bc_layout.addWidget(self.batch_title_label)

        self.batch_progress_bar = ProgressBar(self.batch_card)
        self.batch_progress_bar.setValue(0)
        bc_layout.addWidget(self.batch_progress_bar)

        status_row = QHBoxLayout()
        self.batch_status_label = CaptionLabel("0 / 0 completados", self.batch_card)
        self.batch_status_label.setWordWrap(True)
        self.batch_status_label.setStyleSheet("color: #0078D4; font-weight: bold;")
        status_row.addWidget(self.batch_status_label, stretch=1)

        self.batch_cancel_btn = PushButton(FIF.CLOSE, "🛑 Detener / Cancelar Lista", self.batch_card)
        self.batch_cancel_btn.setStyleSheet(
            "background-color: #D83B01; color: white; font-weight: bold; border-radius: 6px; padding: 4px 12px;"
        )
        self.batch_cancel_btn.clicked.connect(self._on_cancel_batch)
        status_row.addWidget(self.batch_cancel_btn)

        bc_layout.addLayout(status_row)
        main_layout.addWidget(self.batch_card)

        self.empty_card = CardWidget(self)
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(40, 40, 40, 40)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_label = SubtitleLabel("No hay descargas activas", self.empty_card)
        empty_sub = CaptionLabel(
            "Las descargas que inicies aparecerán aquí con su velocidad, ruta en disco y progreso.",
            self.empty_card,
        )
        empty_sub.setStyleSheet("color: #888888;")
        empty_layout.addWidget(empty_label, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_sub, alignment=Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.empty_card)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.items_container = QWidget()
        self.items_layout = QVBoxLayout(self.items_container)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(12)
        self.items_layout.addStretch()

        self.scroll.setWidget(self.items_container)
        self.scroll.setVisible(False)
        main_layout.addWidget(self.scroll, stretch=1)

    def add_download(self, url: str, info: Dict[str, Any], options: Dict[str, Any]):
        self.empty_card.setVisible(False)
        self.scroll.setVisible(True)

        title = info.get("title", "Descarga")
        target_dir = options.get("target_dir", "")
        item_card = DownloadItemCard(title, target_dir=target_dir, parent=self.items_container)
        self.items_layout.insertWidget(0, item_card)

        worker = DownloadWorker(
            url=url,
            target_dir=target_dir,
            mode=options.get("mode", "video"),
            quality=options.get("quality", "best"),
            audio_format=options.get("audio_format", "mp3"),
            audio_bitrate=options.get("audio_bitrate", "320"),
            embed_subtitles=options.get("embed_subtitles", True),
            embed_thumbnail=options.get("embed_thumbnail", True),
            embed_metadata=options.get("embed_metadata", True),
            embed_chapters=options.get("embed_chapters", True),
            preserve_publish_date=options.get("preserve_publish_date", True),
            speed_limit_value=options.get("speed_limit_value", 0),
            speed_limit_unit=options.get("speed_limit_unit", "MB/s"),
            include_videos=options.get("include_videos", True),
            include_shorts=options.get("include_shorts", True),
            include_lives=options.get("include_lives", True),
            preloaded_info=info,
            parent=self,
        )

        self.active_workers.append(worker)

        worker.progress_changed.connect(item_card.update_progress)
        worker.status_changed.connect(item_card.update_status)
        item_card.cancel_requested.connect(worker.cancel)

        if info.get("is_playlist", False) or info.get("type") in ("playlist", "channel"):
            worker.batch_progress.connect(item_card.update_batch_progress)
            self.batch_workers.append(worker)
            self.batch_card.setVisible(True)
            self.batch_cancel_btn.setEnabled(True)
            self.current_batch_worker = worker
            self.batch_title_label.setText(f"Descargando colección: {title}")
            worker.batch_progress.connect(self._on_batch_progress)

        worker.item_completed.connect(lambda fp: item_card.set_completed(fp))
        worker.all_completed.connect(lambda dir_path: self._on_download_finished(worker, title, dir_path))
        worker.error_occurred.connect(lambda err: self._on_worker_error(worker, item_card, err))

        worker.start()

    def _on_worker_error(self, worker: DownloadWorker, item_card: DownloadItemCard, err: str):
        if worker in self.active_workers:
            self.active_workers.remove(worker)
        if worker in self.batch_workers:
            self.batch_workers.remove(worker)
            if self.batch_workers:
                self.current_batch_worker = self.batch_workers[-1]
            else:
                self.current_batch_worker = None
                self.batch_card.setVisible(False)
        item_card.set_error(err)
        self.batch_cancel_btn.setEnabled(False)
        InfoBar.error(
            title="Error en la descarga",
            content=err,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=6000,
            parent=self.window(),
        )

    def _on_cancel_batch(self):
        if hasattr(self, "current_batch_worker") and self.current_batch_worker:
            self.current_batch_worker.cancel()
            self.batch_status_label.setText("⏹️ Descarga de lista/canal detenida por el usuario")
            self.batch_status_label.setStyleSheet("color: #D83B01; font-weight: bold;")
            self.batch_cancel_btn.setEnabled(False)

    def _on_batch_progress(self, current: int, total: int, current_title: str):
        if total > 0:
            pct = int((current / total) * 100)
            self.batch_progress_bar.setValue(pct)
            self.batch_status_label.setText(f"[{current}/{total}] {current_title}")

    def _on_download_finished(self, worker: DownloadWorker, title: str, dir_path: str):
        if worker in self.active_workers:
            self.active_workers.remove(worker)
        if worker in self.batch_workers:
            self.batch_workers.remove(worker)
            if self.batch_workers:
                self.current_batch_worker = self.batch_workers[-1]
            else:
                self.current_batch_worker = None
                self.batch_card.setVisible(False)

        self.batch_cancel_btn.setEnabled(False)
        self.download_finished.emit()

        InfoBar.success(
            title="Descarga Finalizada",
            content=f"'{title}' guardado en: {dir_path}",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self.window(),
        )
