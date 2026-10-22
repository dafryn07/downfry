from pathlib import Path
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFileDialog,
    QScrollArea,
    QFrame,
)
from qfluentwidgets import (
    TitleLabel,
    SubtitleLabel,
    BodyLabel,
    CaptionLabel,
    CardWidget,
    LineEdit,
    PushButton,
    PrimaryPushButton,
    ComboBox,
    CheckBox,
    SwitchButton,
    MessageBox,
    InfoBar,
    InfoBarPosition,
    setTheme,
    Theme,
    FluentIcon as FIF,
)
import yt_dlp
import subprocess
from downfry.config import config_manager


class UpdateYtDlpThread(QThread):
    finished_signal = pyqtSignal(bool, str)

    def run(self):
        import sys
        if getattr(sys, "frozen", False):
            self.finished_signal.emit(
                False,
                "En la versión ejecutable empaquetada, el motor yt-dlp viene integrado. Para actualizar, descarga la última versión de Downfry."
            )
            return

        try:
            res = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if res.returncode == 0:
                self.finished_signal.emit(True, "yt-dlp se ha actualizado correctamente a la última versión.")
            else:
                self.finished_signal.emit(False, res.stderr or "Error durante la actualización.")
        except Exception as e:
            self.finished_signal.emit(False, str(e))


class SettingsView(QWidget):
    """Vista de configuración general de Downfry."""

    trash_emptied = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsView")
        self.update_thread = None
        self._init_ui()

    def _init_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        container = QWidget(scroll)
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(16)

        # 1. Cabecera
        header = TitleLabel("Configuración", container)
        layout.addWidget(header)

        # 2. Carpeta de descargas por defecto
        dir_card = CardWidget(self)
        dc_layout = QVBoxLayout(dir_card)
        dc_layout.setContentsMargins(16, 14, 16, 14)
        dc_layout.setSpacing(8)

        dc_title = SubtitleLabel("Carpeta de descargas predeterminada", dir_card)
        dc_desc = CaptionLabel("Ubicación en tu disco donde se guardarán los videos, playlists y canales.", dir_card)
        dc_desc.setStyleSheet("color: #888888;")
        dc_layout.addWidget(dc_title)
        dc_layout.addWidget(dc_desc)

        path_box = QHBoxLayout()
        self.dir_input = LineEdit(dir_card)
        self.dir_input.setText(config_manager.get("download_dir", str(Path.home() / "Downloads" / "Downfry")))
        self.dir_input.setReadOnly(True)

        self.browse_btn = PushButton(FIF.FOLDER, "Examinar...", dir_card)
        self.browse_btn.setMinimumWidth(130)
        self.browse_btn.clicked.connect(self._on_browse_folder)

        path_box.addWidget(self.dir_input, stretch=1)
        path_box.addWidget(self.browse_btn)
        dc_layout.addLayout(path_box)

        layout.addWidget(dir_card)

        # 3. Tema de la aplicación
        theme_card = CardWidget(self)
        tc_layout = QHBoxLayout(theme_card)
        tc_layout.setContentsMargins(16, 14, 16, 14)

        t_info = QVBoxLayout()
        tc_title = SubtitleLabel("Tema de la aplicación", theme_card)
        tc_desc = CaptionLabel("Personaliza la apariencia con Fluent Design para Windows 11.", theme_card)
        tc_desc.setStyleSheet("color: #888888;")
        t_info.addWidget(tc_title)
        t_info.addWidget(tc_desc)
        tc_layout.addLayout(t_info, stretch=1)

        self.theme_combo = ComboBox(theme_card)
        self.theme_combo.addItem("Tema Claro", userData="Light")
        self.theme_combo.addItem("Tema Oscuro", userData="Dark")
        self.theme_combo.addItem("Sincronizar con Windows (Auto)", userData="Auto")

        saved_theme = config_manager.get("theme", "Auto")
        if saved_theme == "Dark":
            self.theme_combo.setCurrentIndex(1)
        elif saved_theme == "Light":
            self.theme_combo.setCurrentIndex(0)
        else:
            self.theme_combo.setCurrentIndex(2)

        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        tc_layout.addWidget(self.theme_combo)

        layout.addWidget(theme_card)

        # 4. Detección de duplicados
        dup_card = CardWidget(self)
        du_layout = QHBoxLayout(dup_card)
        du_layout.setContentsMargins(16, 14, 16, 14)

        du_info = QVBoxLayout()
        du_title = SubtitleLabel("Aviso de videos duplicados", dup_card)
        du_desc = CaptionLabel(
            "Preguntar antes de volver a descargar un video individual que ya existe en el disco o en el historial.",
            dup_card,
        )
        du_desc.setStyleSheet("color: #888888;")
        du_info.addWidget(du_title)
        du_info.addWidget(du_desc)
        du_layout.addLayout(du_info, stretch=1)

        self.dup_switch = SwitchButton(dup_card)
        self.dup_switch.setOnText("Activado")
        self.dup_switch.setOffText("Desactivado")
        self.dup_switch.setChecked(config_manager.get("check_duplicates", True))
        self.dup_switch.checkedChanged.connect(self._on_check_duplicates_changed)
        du_layout.addWidget(self.dup_switch)

        layout.addWidget(dup_card)

        # Metadatos y Organización de Archivos
        meta_card = CardWidget(self)
        mc_layout = QVBoxLayout(meta_card)
        mc_layout.setContentsMargins(16, 14, 16, 14)
        mc_layout.setSpacing(12)

        # Capítulos y Metadatos
        m1_layout = QHBoxLayout()
        m1_info = QVBoxLayout()
        m1_title = SubtitleLabel("Incrustar capítulos y metadatos (Creador, Fecha, Descripción)", meta_card)
        m1_desc = CaptionLabel(
            "Escribe en el archivo multimedia el autor/canal, fecha, etiquetas y capítulos interactivos para VLC y reproductores.",
            meta_card,
        )
        m1_desc.setStyleSheet("color: #888888;")
        m1_info.addWidget(m1_title)
        m1_info.addWidget(m1_desc)
        m1_layout.addLayout(m1_info, stretch=1)

        self.meta_switch = SwitchButton(meta_card)
        self.meta_switch.setOnText("Activado")
        self.meta_switch.setOffText("Desactivado")
        self.meta_switch.setChecked(config_manager.get("embed_metadata", True) and config_manager.get("embed_chapters", True))
        self.meta_switch.checkedChanged.connect(self._on_embed_metadata_changed)
        m1_layout.addWidget(self.meta_switch)
        mc_layout.addLayout(m1_layout)

        # Fecha de Publicación en Sistema de Archivos
        m2_layout = QHBoxLayout()
        m2_info = QVBoxLayout()
        m2_title = SubtitleLabel("Usar fecha de publicación como Fecha de Creación del archivo", meta_card)
        m2_desc = CaptionLabel(
            "Fija la Fecha de Creación y Modificación en Windows (NTFS) y Linux con la fecha exacta en que el video se publicó en YouTube.",
            meta_card,
        )
        m2_desc.setStyleSheet("color: #888888;")
        m2_info.addWidget(m2_title)
        m2_info.addWidget(m2_desc)
        m2_layout.addLayout(m2_info, stretch=1)

        self.pub_date_switch = SwitchButton(meta_card)
        self.pub_date_switch.setOnText("Activado")
        self.pub_date_switch.setOffText("Desactivado")
        self.pub_date_switch.setChecked(config_manager.get("preserve_publish_date", True))
        self.pub_date_switch.checkedChanged.connect(self._on_preserve_publish_date_changed)
        m2_layout.addWidget(self.pub_date_switch)
        mc_layout.addLayout(m2_layout)

        layout.addWidget(meta_card)

        # 5. Papelera de reciclaje y retención
        recycle_card = CardWidget(self)
        rc_layout = QVBoxLayout(recycle_card)
        rc_layout.setContentsMargins(16, 14, 16, 14)
        rc_layout.setSpacing(12)

        rc_top = QHBoxLayout()
        rc_info = QVBoxLayout()
        rc_title = SubtitleLabel("Papelera de reciclaje y retención", recycle_card)
        rc_desc = CaptionLabel(
            "Los videos eliminados del historial se conservan aquí antes de borrarse permanentemente del disco.",
            recycle_card,
        )
        rc_desc.setStyleSheet("color: #888888;")
        rc_info.addWidget(rc_title)
        rc_info.addWidget(rc_desc)
        rc_top.addLayout(rc_info, stretch=1)

        self.retention_combo = ComboBox(recycle_card)
        self.retention_combo.addItem("24 horas", userData="24h")
        self.retention_combo.addItem("3 días", userData="3d")
        self.retention_combo.addItem("1 semana (7 días)", userData="7d")
        self.retention_combo.addItem("2 semanas (14 días)", userData="14d")
        self.retention_combo.addItem("1 mes (30 días)", userData="30d")
        self.retention_combo.addItem("2 meses (60 días)", userData="60d")
        self.retention_combo.addItem("3 meses (90 días)", userData="90d")
        self.retention_combo.addItem("Nunca eliminar automáticamente", userData="never")

        saved_retention = config_manager.get("recycle_bin_retention", "7d")
        idx = 2
        for i in range(self.retention_combo.count()):
            if self.retention_combo.itemData(i) == saved_retention:
                idx = i
                break
        self.retention_combo.setCurrentIndex(idx)
        self.retention_combo.currentIndexChanged.connect(self._on_retention_changed)
        rc_top.addWidget(self.retention_combo)
        rc_layout.addLayout(rc_top)

        rc_bot = QHBoxLayout()
        from downfry.core.recycle_bin import RecycleBinManager
        count, size_str = RecycleBinManager.get_trash_stats()
        self.trash_stats_label = CaptionLabel(f"Estado actual: {count} archivos ({size_str}) en la papelera.", recycle_card)
        self.trash_stats_label.setStyleSheet("color: #888888;")
        self.empty_trash_btn = PushButton(FIF.DELETE, "Vaciar papelera ahora", recycle_card)
        self.empty_trash_btn.setMinimumWidth(180)
        self.empty_trash_btn.clicked.connect(self._on_empty_trash)

        rc_bot.addWidget(self.trash_stats_label, stretch=1)
        rc_bot.addWidget(self.empty_trash_btn)
        rc_layout.addLayout(rc_bot)

        layout.addWidget(recycle_card)

        # Límite de velocidad de descarga
        speed_card = CardWidget(container)
        sc_layout = QHBoxLayout(speed_card)
        sc_layout.setContentsMargins(16, 14, 16, 14)

        sc_info = QVBoxLayout()
        sc_title = SubtitleLabel("Límite de velocidad de descarga", speed_card)
        sc_desc = CaptionLabel(
            "Limita la tasa de transferencia por video para no saturar tu conexión (deja en 0 para velocidad ilimitada).",
            speed_card,
        )
        sc_desc.setStyleSheet("color: #888888;")
        sc_info.addWidget(sc_title)
        sc_info.addWidget(sc_desc)
        sc_layout.addLayout(sc_info, stretch=1)

        speed_box = QHBoxLayout()
        self.speed_input = LineEdit(speed_card)
        self.speed_input.setPlaceholderText("0 (Sin límite)")
        self.speed_input.setFixedWidth(120)
        curr_spd = config_manager.get("speed_limit_value", 0)
        self.speed_input.setText(str(curr_spd) if curr_spd else "")
        self.speed_input.textChanged.connect(self._on_speed_limit_changed)

        self.speed_unit_combo = ComboBox(speed_card)
        self.speed_unit_combo.setFixedWidth(100)
        for u in ["KB/s", "MB/s", "KiB/s", "MiB/s"]:
            self.speed_unit_combo.addItem(u, userData=u)
        curr_unit = config_manager.get("speed_limit_unit", "MB/s")
        idx_u = self.speed_unit_combo.findData(curr_unit)
        if idx_u >= 0:
            self.speed_unit_combo.setCurrentIndex(idx_u)
        self.speed_unit_combo.currentIndexChanged.connect(self._on_speed_unit_changed)

        speed_box.addWidget(self.speed_input)
        speed_box.addWidget(self.speed_unit_combo)
        sc_layout.addLayout(speed_box)

        layout.addWidget(speed_card)

        # 5. Motor yt-dlp y Actualizador
        ytdlp_card = CardWidget(self)
        yd_layout = QHBoxLayout(ytdlp_card)
        yd_layout.setContentsMargins(16, 14, 16, 14)

        yd_info = QVBoxLayout()
        yd_title = SubtitleLabel("Motor yt-dlp", ytdlp_card)
        try:
            ver = yt_dlp.version.__version__
        except Exception:
            ver = "Instalado"
        self.ver_label = CaptionLabel(f"Versión actual: {ver}", ytdlp_card)
        self.ver_label.setStyleSheet("color: #888888;")
        yd_info.addWidget(yd_title)
        yd_info.addWidget(self.ver_label)
        yd_layout.addLayout(yd_info, stretch=1)

        self.update_btn = PushButton(FIF.SYNC, "Actualizar motor", ytdlp_card)
        self.update_btn.setMinimumWidth(155)
        self.update_btn.clicked.connect(self._on_update_ytdlp)
        yd_layout.addWidget(self.update_btn)

        layout.addWidget(ytdlp_card)
        layout.addStretch()

        scroll.setWidget(container)
        outer_layout.addWidget(scroll)

    def _on_speed_limit_changed(self, text: str):
        try:
            val = float(text.strip().replace(",", ".")) if text.strip() else 0
            if val < 0:
                val = 0
        except ValueError:
            val = 0
        config_manager.set("speed_limit_value", val)

    def _on_speed_unit_changed(self, idx: int):
        val = self.speed_unit_combo.currentData()
        config_manager.set("speed_limit_unit", val)

    def _on_browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta por defecto", self.dir_input.text())
        if folder:
            self.dir_input.setText(folder)
            config_manager.set("download_dir", folder)
            InfoBar.success(
                title="Ajuste guardado",
                content="Carpeta de descargas actualizada.",
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self.window(),
            )

    def _on_theme_changed(self, idx: int):
        theme_val = self.theme_combo.currentData()
        config_manager.set("theme", theme_val)
        if theme_val == "Dark":
            setTheme(Theme.DARK)
        elif theme_val == "Light":
            setTheme(Theme.LIGHT)
        else:
            setTheme(Theme.AUTO)

    def _on_embed_metadata_changed(self, checked: bool):
        config_manager.set("embed_metadata", checked)
        config_manager.set("embed_chapters", checked)
        st = "activada" if checked else "desactivada"
        InfoBar.success(
            title="Ajuste guardado",
            content=f"Incrustación de metadatos y capítulos {st}.",
            position=InfoBarPosition.TOP,
            duration=2500,
            parent=self.window(),
        )

    def _on_preserve_publish_date_changed(self, checked: bool):
        config_manager.set("preserve_publish_date", checked)
        st = "activada" if checked else "desactivada"
        InfoBar.success(
            title="Ajuste guardado",
            content=f"Sincronización de fecha de publicación en disco {st}.",
            position=InfoBarPosition.TOP,
            duration=2500,
            parent=self.window(),
        )

    def _on_check_duplicates_changed(self, checked: bool):
        config_manager.set("check_duplicates", checked)
        status_txt = "activada" if checked else "desactivada"
        InfoBar.success(
            title="Ajuste guardado",
            content=f"La verificación de duplicados ha sido {status_txt}.",
            position=InfoBarPosition.TOP,
            duration=2500,
            parent=self.window(),
        )

    def _on_retention_changed(self, idx: int):
        val = self.retention_combo.currentData()
        config_manager.set("recycle_bin_retention", val)
        InfoBar.success(
            title="Ajuste guardado",
            content="Tiempo de retención de papelera actualizado.",
            position=InfoBarPosition.TOP,
            duration=2500,
            parent=self.window(),
        )

    def _on_empty_trash(self):
        from downfry.core.recycle_bin import RecycleBinManager
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
            self.refresh_trash_stats()
            self.trash_emptied.emit()
            InfoBar.success(
                title="Papelera vaciada",
                content=f"Se han eliminado permanentemente {c} archivos del disco.",
                position=InfoBarPosition.TOP,
                duration=3500,
                parent=self.window(),
            )

    def refresh_trash_stats(self):
        from downfry.core.recycle_bin import RecycleBinManager
        new_count, new_size = RecycleBinManager.get_trash_stats()
        self.trash_stats_label.setText(f"Estado actual: {new_count} archivos ({new_size}) en la papelera.")

    def _on_update_ytdlp(self):
        self.update_btn.setEnabled(False)
        self.update_btn.setText("Actualizando...")
        self.update_thread = UpdateYtDlpThread(self)
        self.update_thread.finished_signal.connect(self._on_update_finished)
        self.update_thread.start()

    def _on_update_finished(self, success: bool, msg: str):
        self.update_btn.setEnabled(True)
        self.update_btn.setText("Actualizar motor")
        if success:
            InfoBar.success(
                title="Actualización completada",
                content=msg,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self.window(),
            )
            try:
                import importlib
                importlib.reload(yt_dlp.version)
                self.ver_label.setText(f"Versión actual: {yt_dlp.version.__version__}")
            except Exception:
                pass
        else:
            InfoBar.error(
                title="Error al actualizar",
                content=msg,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self.window(),
            )
