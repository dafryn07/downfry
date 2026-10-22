import os
from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
)
from qfluentwidgets import (
    TitleLabel,
    SubtitleLabel,
    BodyLabel,
    CaptionLabel,
    CardWidget,
    PushButton,
    LineEdit,
    MessageBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
)
from downfry.core.recycle_bin import RecycleBinManager
from downfry.utils.formatting import open_file, open_in_explorer
from downfry.config import config_manager


class RecycleBinItemCard(CardWidget):
    """Tarjeta individual para un archivo en la papelera de reciclaje."""

    item_action = pyqtSignal()

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.item = item
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        title = self.item.get("title", "Archivo en papelera")
        self.title_label = BodyLabel(f"🗑️ {title}", self)
        self.title_label.setStyleSheet("font-weight: bold;")
        self.title_label.setWordWrap(True)
        info_layout.addWidget(self.title_label)

        date_str = self.item.get("date_str", "")
        size_str = self.item.get("size_str", "")
        orig = self.item.get("original_path", "")
        orig_folder = Path(orig).parent.name if orig else "Descargas"

        meta_label = CaptionLabel(f"Eliminado: {date_str}  •  {size_str}  •  Carpeta: {orig_folder}", self)
        meta_label.setStyleSheet("color: #888888;")
        meta_label.setToolTip(f"Ubicación original: {orig}")
        info_layout.addWidget(meta_label)

        layout.addLayout(info_layout, stretch=1)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.play_btn = PushButton(FIF.PLAY, "Abrir", self)
        self.play_btn.setMinimumWidth(85)
        self.play_btn.clicked.connect(self._on_play)
        btn_layout.addWidget(self.play_btn)

        self.restore_btn = PushButton(FIF.SYNC, "Restaurar", self)
        self.restore_btn.setMinimumWidth(110)
        self.restore_btn.clicked.connect(self._on_restore)
        btn_layout.addWidget(self.restore_btn)

        self.delete_btn = PushButton(FIF.DELETE, "Eliminar", self)
        self.delete_btn.setMinimumWidth(100)
        self.delete_btn.clicked.connect(self._on_delete)
        btn_layout.addWidget(self.delete_btn)

        layout.addLayout(btn_layout)

    def _on_play(self):
        trash_path = self.item.get("trash_path", "")
        if trash_path and os.path.exists(trash_path):
            open_file(trash_path)
        else:
            InfoBar.warning(
                title="Archivo no disponible",
                content="El archivo físico ya no se encuentra en la papelera.",
                position=InfoBarPosition.TOP,
                duration=2500,
                parent=self.window(),
            )

    def _on_restore(self):
        win = self.window()
        parent_for_infobar = win if win is not None else self
        filename = self.item.get("trash_filename", "")
        title = self.item.get("title", "Archivo")
        success = RecycleBinManager.restore_item(filename)
        if success:
            InfoBar.success(
                title="Archivo restaurado",
                content=f"'{title}' ha sido restaurado en tu carpeta de descargas e historial.",
                position=InfoBarPosition.TOP,
                duration=3500,
                parent=parent_for_infobar,
            )
            QTimer.singleShot(0, self.item_action.emit)
        else:
            InfoBar.error(
                title="Error al restaurar",
                content="No se pudo restaurar el archivo.",
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=parent_for_infobar,
            )

    def _on_delete(self):
        win = self.window()
        parent_for_infobar = win if win is not None else self
        filename = self.item.get("trash_filename", "")
        title = self.item.get("title", "este archivo")
        w = MessageBox(
            "¿Eliminar definitivamente?",
            f"¿Estás seguro de que deseas eliminar permanentemente '{title}'?\n\nEsta acción no se puede deshacer.",
            parent_for_infobar,
        )
        w.yesButton.setText("Sí, eliminar")
        w.cancelButton.setText("Cancelar")
        if w.exec():
            RecycleBinManager.delete_item(filename)
            InfoBar.success(
                title="Archivo eliminado",
                content=f"'{title}' ha sido eliminado definitivamente.",
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=parent_for_infobar,
            )
            QTimer.singleShot(0, self.item_action.emit)


class RecycleBinView(QWidget):
    """Pestaña de la aplicación para gestionar la papelera de reciclaje."""

    item_restored = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RecycleBinView")
        self._init_ui()
        self.reload_trash()

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(30, 24, 30, 24)
        self.main_layout.setSpacing(16)

        # 1. Cabecera
        header_layout = QHBoxLayout()
        header = TitleLabel("Papelera de Reciclaje", self)
        header_layout.addWidget(header)
        header_layout.addStretch()

        self.open_folder_btn = PushButton(FIF.FOLDER, "Abrir carpeta en Explorador", self)
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        header_layout.addWidget(self.open_folder_btn)

        self.empty_trash_btn = PushButton(FIF.DELETE, "Vaciar papelera", self)
        self.empty_trash_btn.clicked.connect(self._on_empty_trash)
        header_layout.addWidget(self.empty_trash_btn)

        self.main_layout.addLayout(header_layout)

        # 2. Barra de información y búsqueda
        filter_layout = QHBoxLayout()
        self.info_caption = CaptionLabel("", self)
        self.info_caption.setStyleSheet("color: #888888;")
        filter_layout.addWidget(self.info_caption)
        filter_layout.addStretch()

        self.search_input = LineEdit(self)
        self.search_input.setPlaceholderText("Buscar en la papelera...")
        self.search_input.setFixedWidth(260)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        filter_layout.addWidget(self.search_input)

        self.main_layout.addLayout(filter_layout)

        # 3. Lista de elementos
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.container = QWidget()
        self.items_layout = QVBoxLayout(self.container)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(10)

        self.scroll.setWidget(self.container)
        self.main_layout.addWidget(self.scroll)

    def reload_trash(self):
        while self.items_layout.count():
            item = self.items_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        items = RecycleBinManager.get_items()
        count = len(items)
        _, size_str = RecycleBinManager.get_trash_stats()
        retention = config_manager.get("recycle_bin_retention", "7d")

        retention_text_map = {
            "24h": "24 horas",
            "3d": "3 días",
            "7d": "1 semana",
            "14d": "2 semanas",
            "30d": "1 mes",
            "60d": "2 meses",
            "90d": "3 meses",
            "never": "Nunca",
        }
        ret_label = retention_text_map.get(retention, retention)
        self.info_caption.setText(f"{count} archivos ({size_str})  •  Retención: {ret_label}  •  Carpeta oculta en disco")

        query = self.search_input.text().strip().lower()
        visible_count = 0
        for it in items:
            title = it.get("title", "").lower()
            orig = it.get("original_path", "").lower()
            if query and query not in title and query not in orig:
                continue

            card = RecycleBinItemCard(it, self.container)
            card.item_action.connect(self._on_item_action)
            self.items_layout.addWidget(card)
            visible_count += 1

        if visible_count == 0:
            empty_widget = QWidget(self.container)
            ew_layout = QVBoxLayout(empty_widget)
            ew_layout.setContentsMargins(0, 60, 0, 60)
            ew_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            empty_title = SubtitleLabel("La papelera de reciclaje está vacía", empty_widget)
            empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_desc = CaptionLabel(
                "Los videos eliminados del historial se conservan aquí antes de borrarse permanentemente.",
                empty_widget,
            )
            empty_desc.setStyleSheet("color: #888888;")
            empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)

            ew_layout.addWidget(empty_title)
            ew_layout.addWidget(empty_desc)
            self.items_layout.addWidget(empty_widget)

        self.items_layout.addStretch()

    def _on_search_changed(self, text: str):
        self.reload_trash()

    def _on_item_action(self):
        self.reload_trash()
        self.item_restored.emit()

    def _on_open_folder(self):
        bin_dir = RecycleBinManager.get_bin_dir()
        if bin_dir.exists():
            open_in_explorer(str(bin_dir))
        else:
            InfoBar.warning(
                title="Carpeta no encontrada",
                content="La carpeta de la papelera aún no se ha creado.",
                position=InfoBarPosition.TOP,
                duration=2500,
                parent=self.window(),
            )

    def _on_empty_trash(self):
        count, size_str = RecycleBinManager.get_trash_stats()
        if count == 0:
            InfoBar.info(
                title="Papelera vacía",
                content="No hay archivos en la papelera de reciclaje.",
                position=InfoBarPosition.TOP,
                duration=2500,
                parent=self.window(),
            )
            return

        w = MessageBox(
            "¿Vaciar papelera de reciclaje?",
            f"Se eliminarán permanentemente {count} archivos ({size_str}) del disco. Esta acción no se puede deshacer.",
            self.window(),
        )
        w.yesButton.setText("Sí, vaciar ahora")
        w.cancelButton.setText("Cancelar")
        if w.exec():
            c, total_bytes = RecycleBinManager.empty_trash()
            self.reload_trash()
            InfoBar.success(
                title="Papelera vaciada",
                content=f"Se han eliminado permanentemente {c} archivos del disco.",
                position=InfoBarPosition.TOP,
                duration=3500,
                parent=self.window(),
            )
