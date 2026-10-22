from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout
from qfluentwidgets import (
    MessageBoxBase,
    SubtitleLabel,
    BodyLabel,
    CaptionLabel,
    CardWidget,
    PushButton,
    FluentIcon as FIF,
)


class DuplicateWarningDialog(MessageBoxBase):
    """Diálogo interactivo de advertencia cuando un video ya fue descargado previamente."""

    def __init__(self, title: str, match_type: str = "Disco", match_loc: str = "", parent=None):
        if parent is None:
            from PyQt6.QtWidgets import QApplication
            parent = QApplication.activeWindow()
        super().__init__(parent=parent)
        self.title_str = title
        if not match_loc and "\n" in match_type:
            parts = match_type.split("\n", 1)
            self.match_type = parts[0].replace("Detectado en:", "").strip()
            self.filepath = parts[1].strip()
        else:
            self.match_type = match_type.replace("Detectado en:", "").strip()
            self.filepath = match_loc.strip()

        self.widget.setMinimumWidth(480)
        self.yesButton.setText("🔄 Volver a descargar (Nueva copia)")
        self.cancelButton.setText("❌ Cancelar")

        self._init_ui()

    def _init_ui(self):
        title_label = SubtitleLabel("⚠️ Este video ya fue descargado", self)
        title_label.setStyleSheet("color: #D83B01; font-weight: bold;")
        self.viewLayout.addWidget(title_label)

        card = CardWidget(self)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(14, 12, 14, 12)
        c_layout.setSpacing(10)

        msg = BodyLabel(f"El video '{self.title_str}' ya existe en tu disco o se encuentra registrado en el historial.", card)
        msg.setWordWrap(True)
        c_layout.addWidget(msg)

        row_layout = QHBoxLayout()
        type_lbl = CaptionLabel(f"Estado: Detectado en {self.match_type}", card)
        type_lbl.setStyleSheet("color: #888888; font-weight: bold;")
        row_layout.addWidget(type_lbl, stretch=1)

        if self.filepath:
            from downfry.utils.formatting import open_in_explorer
            clean_fp = self.filepath.rsplit(" [", 1)[0] if self.filepath.endswith("]") and " [" in self.filepath else self.filepath
            self.explorer_btn = PushButton(FIF.FOLDER, "Ver en explorador", card)
            self.explorer_btn.setToolTip("Abrir el explorador de Windows y resaltar el archivo existente")
            self.explorer_btn.clicked.connect(lambda: open_in_explorer(clean_fp))
            row_layout.addWidget(self.explorer_btn)

        c_layout.addLayout(row_layout)
        self.viewLayout.addWidget(card)

        info_lbl = CaptionLabel("Si decides volver a descargarlo, se conservará el archivo existente intacto y la nueva descarga se guardará automáticamente como copia numerada (2), (3).", self)
        info_lbl.setStyleSheet("color: #888888;")
        self.viewLayout.addWidget(info_lbl)
