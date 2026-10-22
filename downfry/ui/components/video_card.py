from typing import Dict, Any, Optional
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
)
from qfluentwidgets import (
    CardWidget,
    SubtitleLabel,
    BodyLabel,
    CaptionLabel,
    PrimaryPushButton,
    PushButton,
    FluentIcon as FIF,
)
import requests
from downfry.utils.formatting import format_seconds, parse_iso_date


_PIXMAP_CACHE: Dict[str, QPixmap] = {}


class ImageLoaderThread(QThread):
    image_loaded = pyqtSignal(QPixmap)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if not self.url or self._cancelled:
            return
        if self.url in _PIXMAP_CACHE:
            if not self._cancelled:
                self.image_loaded.emit(_PIXMAP_CACHE[self.url])
            return
        try:
            resp = requests.get(self.url, timeout=5)
            if self._cancelled:
                return
            if resp.status_code == 200:
                img = QImage()
                if img.loadFromData(resp.content):
                    pix = QPixmap.fromImage(img)
                    if len(_PIXMAP_CACHE) > 50:
                        _PIXMAP_CACHE.pop(next(iter(_PIXMAP_CACHE)))
                    _PIXMAP_CACHE[self.url] = pix
                    if not self._cancelled:
                        self.image_loaded.emit(pix)
        except Exception:
            pass


class VideoCard(CardWidget):
    """Tarjeta interactiva para previsualizar el contenido antes de descargarlo."""

    configure_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loader_thread: Optional[ImageLoaderThread] = None
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(20)

        # 1. Miniatura
        self.thumb_label = QLabel(self)
        self.thumb_label.setFixedSize(200, 112)
        self.thumb_label.setScaledContents(True)
        self.thumb_label.setStyleSheet("border-radius: 8px; background-color: #2b2b2b;")
        layout.addWidget(self.thumb_label)

        # 2. Detalles de texto
        details_layout = QVBoxLayout()
        details_layout.setSpacing(6)

        # Badge de tipo (Video, Short, Playlist, Canal)
        self.badge_label = CaptionLabel("Contenido", self)
        self.badge_label.setStyleSheet(
            "padding: 2px 8px; border-radius: 4px; background-color: #0078D4; color: white; font-weight: bold;"
        )
        details_layout.addWidget(self.badge_label, alignment=Qt.AlignmentFlag.AlignLeft)

        # Título
        self.title_label = SubtitleLabel("Título del video", self)
        self.title_label.setWordWrap(True)
        details_layout.addWidget(self.title_label)

        # Canal y Metadatos
        meta_layout = QHBoxLayout()
        self.channel_label = BodyLabel("Canal", self)
        self.channel_label.setStyleSheet("color: #888888; font-weight: 500;")
        meta_layout.addWidget(self.channel_label)

        self.info_label = CaptionLabel("", self)
        self.info_label.setStyleSheet("color: #888888;")
        meta_layout.addWidget(self.info_label)
        meta_layout.addStretch()

        details_layout.addLayout(meta_layout)
        details_layout.addStretch()
        layout.addLayout(details_layout, stretch=1)

        # 3. Botón de acción para configurar descarga
        btn_layout = QVBoxLayout()
        btn_layout.addStretch()
        self.download_btn = PrimaryPushButton(FIF.DOWNLOAD, "Descargar", self)
        self.download_btn.setFixedHeight(38)
        self.download_btn.clicked.connect(self.configure_requested.emit)
        btn_layout.addWidget(self.download_btn)
        btn_layout.addStretch()

        layout.addLayout(btn_layout)

    def set_data(self, data: Dict[str, Any]):
        title = data.get("title", "Sin título")
        channel = data.get("channel", "YouTube")
        content_type = data.get("type", "video")
        thumbnail_url = data.get("thumbnail", "")
        duration = data.get("duration", 0)
        upload_date_raw = data.get("upload_date", "")
        is_playlist = data.get("is_playlist", False)
        item_count = data.get("item_count", 0)

        self.title_label.setText(title)
        self.channel_label.setText(f"👤 {channel}")

        chapters_count = data.get("chapters_count", 0)
        chapters_badge = f"  •  📑 {chapters_count} capítulos" if chapters_count > 0 else ""

        # Configurar badges y metadatos
        if content_type == "short":
            self.badge_label.setText("⚡ Short")
            self.badge_label.setStyleSheet("padding: 2px 8px; border-radius: 4px; background-color: #D83B01; color: white; font-weight: bold;")
            self.info_label.setText(f"⏱️ {format_seconds(duration)}")
        elif content_type == "channel":
            self.badge_label.setText("📢 Canal Completo")
            self.badge_label.setStyleSheet("padding: 2px 8px; border-radius: 4px; background-color: #881798; color: white; font-weight: bold;")
            self.info_label.setText("Se organizará por Año / Mes / Categoría")
        elif is_playlist or content_type == "playlist":
            self.badge_label.setText("📑 Playlist")
            self.badge_label.setStyleSheet("padding: 2px 8px; border-radius: 4px; background-color: #107C41; color: white; font-weight: bold;")
            self.info_label.setText(f"📁 {item_count} videos")
        else:
            self.badge_label.setText("🎬 Video")
            self.badge_label.setStyleSheet("padding: 2px 8px; border-radius: 4px; background-color: #0078D4; color: white; font-weight: bold;")
            iso_date, _, _ = parse_iso_date(upload_date_raw)
            date_info = f"  •  📅 {iso_date}" if upload_date_raw else ""
            self.info_label.setText(f"⏱️ {format_seconds(duration)}{date_info}{chapters_badge}")

        # Cargar miniatura
        self.thumb_label.clear()
        if thumbnail_url:
            if self.loader_thread and self.loader_thread.isRunning():
                self.loader_thread.cancel()
                try:
                    self.loader_thread.image_loaded.disconnect()
                except Exception:
                    pass
            self.loader_thread = ImageLoaderThread(thumbnail_url, self)
            self.loader_thread.finished.connect(self.loader_thread.deleteLater)
            self.loader_thread.image_loaded.connect(self._on_image_loaded)
            self.loader_thread.start()

    def _on_image_loaded(self, pixmap: QPixmap):
        scaled = pixmap.scaled(
            self.thumb_label.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.thumb_label.setPixmap(scaled)
