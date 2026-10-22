import os
import subprocess
from typing import Optional
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QSizePolicy
from qfluentwidgets import (
    CardWidget,
    ProgressBar,
    BodyLabel,
    CaptionLabel,
    PushButton,
    TransparentToolButton,
    FluentIcon as FIF,
)


class DownloadItemCard(CardWidget):
    """Tarjeta individual que representa una descarga activa en la cola con acceso rápido a la carpeta."""

    cancel_requested = pyqtSignal()

    def __init__(self, title: str, target_dir: str = "", parent=None):
        super().__init__(parent)
        self.title = title
        self.target_dir = target_dir
        self.last_filepath: Optional[str] = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        top_layout = QHBoxLayout()
        self.title_label = BodyLabel(self.title, self)
        self.title_label.setStyleSheet("font-weight: bold;")
        self.title_label.setWordWrap(True)
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        top_layout.addWidget(self.title_label, stretch=1)

        self.play_btn = PushButton(FIF.PLAY, "Abrir", self)
        self.play_btn.setVisible(False)
        self.play_btn.clicked.connect(self._on_open_file)
        top_layout.addWidget(self.play_btn)

        self.open_folder_btn = PushButton(FIF.FOLDER, "En Explorador", self)
        self.open_folder_btn.setVisible(False)
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        top_layout.addWidget(self.open_folder_btn)

        self.cancel_btn = TransparentToolButton(FIF.CLOSE, self)
        self.cancel_btn.setToolTip("Cancelar descarga")
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        top_layout.addWidget(self.cancel_btn)

        layout.addLayout(top_layout)

        self.progress_bar = ProgressBar(self)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(6)
        layout.addWidget(self.progress_bar)

        bottom_layout = QHBoxLayout()
        self.status_label = CaptionLabel("", self)
        self.status_label.setStyleSheet("color: #888888;")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumWidth(0)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bottom_layout.addWidget(self.status_label, stretch=1)

        self.stats_label = CaptionLabel("Iniciando descarga...", self)
        self.stats_label.setStyleSheet("color: #0078D4; font-weight: 500;")
        bottom_layout.addWidget(self.stats_label)

        layout.addLayout(bottom_layout)

    def _on_open_file(self):
        from downfry.utils.formatting import open_file
        if self.last_filepath:
            open_file(self.last_filepath)

    def _on_open_folder(self):
        from downfry.utils.formatting import open_in_explorer
        target = self.last_filepath or self.target_dir
        if target:
            open_in_explorer(target)

    def update_progress(self, percent: float, speed_str: str, eta_str: str, size_str: str):
        self.progress_bar.setValue(int(percent))
        self.status_label.setText("")
        self.stats_label.setText(f"{percent:.1f}%  •  {speed_str}  •  ETA: {eta_str}  •  {size_str}")

    def update_batch_progress(self, current: int, total: int, title: str):
        pct = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.status_label.setText(f"Descargando [{current}/{total}]: {title}")
        self.stats_label.setText(f"{current} / {total} ({pct}%)")

    def update_status(self, status: str):
        if status.startswith("Descargando"):
            self.status_label.setText("")
        elif "Guardado en:" in status:
            self.status_label.setText("✅ Descarga completada")
            self.status_label.setStyleSheet("color: #107C41; font-weight: bold;")
            self.stats_label.setText("Completado")
        else:
            self.stats_label.setText(status)

    def set_completed(self, filepath: str):
        self.last_filepath = filepath
        self.progress_bar.setValue(100)
        self.status_label.setText("✅ Descarga completada")
        self.status_label.setStyleSheet("color: #107C41; font-weight: bold;")
        self.stats_label.setText("Completado")
        self.setToolTip(f"Ubicación: {filepath}")
        self.play_btn.setVisible(True)
        self.open_folder_btn.setVisible(True)
        self.cancel_btn.setVisible(False)

    def set_error(self, err_msg: str):
        self.status_label.setText("❌ Error en la descarga")
        self.status_label.setStyleSheet("color: #D83B01; font-weight: bold;")
        self.stats_label.setText(err_msg)
        self.cancel_btn.setVisible(False)
