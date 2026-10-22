import os
import subprocess
from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QStackedWidget,
)
from qfluentwidgets import (
    TitleLabel,
    SubtitleLabel,
    BodyLabel,
    CaptionLabel,
    CardWidget,
    PushButton,
    SegmentedWidget,
    LineEdit,
    MessageBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
)
from downfry.config import history_manager, config_manager


class HistoryItemCard(CardWidget):
    """Tarjeta individual que muestra un archivo completado en el historial."""

    file_deleted = pyqtSignal()
    play_internal_requested = pyqtSignal(dict)

    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self.entry = entry
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)

        # Información
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        title = self.entry.get("title", "Archivo descargado")
        self.title_label = BodyLabel(title, self)
        self.title_label.setStyleSheet("font-weight: bold;")
        self.title_label.setWordWrap(True)
        info_layout.addWidget(self.title_label)

        date_str = self.entry.get("date", "")
        size_str = self.entry.get("size_str", "")
        quality_str = self.entry.get("quality", "")
        mode_str = "🎬 Video" if self.entry.get("mode") == "video" else "🎵 Audio"

        meta_label = CaptionLabel(f"{mode_str} ({quality_str})  •  {size_str}  •  {date_str}", self)
        meta_label.setStyleSheet("color: #888888;")
        info_layout.addWidget(meta_label)

        layout.addLayout(info_layout, stretch=1)

        # Botones de acción
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.play_btn = PushButton(FIF.PLAY, "Reproducir", self)
        self.play_btn.setMinimumWidth(100)
        self.play_btn.clicked.connect(self._on_play_internal)
        btn_layout.addWidget(self.play_btn)

        self.vlc_btn = PushButton(FIF.APPLICATION, "Reproductor externo", self)
        self.vlc_btn.setMinimumWidth(140)
        self.vlc_btn.setToolTip("Abrir en el reproductor predeterminado del sistema")
        self.vlc_btn.clicked.connect(self._on_open_file)
        btn_layout.addWidget(self.vlc_btn)

        self.folder_btn = PushButton(FIF.FOLDER, "En Explorador", self)
        self.folder_btn.setMinimumWidth(125)
        self.folder_btn.clicked.connect(self._on_open_folder)
        btn_layout.addWidget(self.folder_btn)

        self.delete_btn = PushButton(FIF.DELETE, "Eliminar", self)
        self.delete_btn.setMinimumWidth(95)
        self.delete_btn.clicked.connect(self._on_delete_file)
        btn_layout.addWidget(self.delete_btn)

        layout.addLayout(btn_layout)

    def _on_play_internal(self):
        filepath = self.entry.get("filepath", "")
        if filepath and os.path.exists(filepath):
            self.play_internal_requested.emit(self.entry)
        else:
            self._on_open_file()

    def _on_open_file(self):
        filepath = self.entry.get("filepath", "")
        if filepath and os.path.exists(filepath):
            try:
                os.startfile(filepath)
            except Exception as e:
                InfoBar.error(
                    title="Error al abrir archivo",
                    content=str(e),
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=self.window(),
                )
        else:
            InfoBar.warning(
                title="Archivo no encontrado",
                content="El archivo fue movido o eliminado de su ubicación original.",
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self.window(),
            )

    def _on_open_folder(self):
        from downfry.utils.formatting import open_in_explorer
        filepath = self.entry.get("filepath", "")
        if filepath and open_in_explorer(filepath):
            return
        parent_dir = os.path.dirname(filepath) if filepath else ""
        if parent_dir and os.path.exists(parent_dir):
            os.startfile(parent_dir)
        else:
            InfoBar.warning(
                title="Carpeta no encontrada",
                content="La carpeta de descarga ya no existe.",
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self.window(),
            )

    def _on_delete_file(self):
        filepath = self.entry.get("filepath", "")
        title = self.entry.get("title", "este video")
        vid_id = self.entry.get("video_id", "")
        win = self.window()
        parent_for_infobar = win if win is not None else self
        file_exists = bool(filepath and os.path.exists(filepath))

        if file_exists:
            w = MessageBox(
                "¿Mover archivo a la papelera?",
                f"¿Deseas mover '{title}' a la papelera de reciclaje de Downfry?\n\nSe conservará temporalmente según el tiempo configurado y luego se eliminará automáticamente.",
                parent_for_infobar,
            )
            w.yesButton.setText("Mover a la papelera")
            w.cancelButton.setText("Cancelar")

            if not w.exec():
                return

            from downfry.core.recycle_bin import RecycleBinManager
            success = RecycleBinManager.move_to_trash(filepath, title, metadata=self.entry)
            if not success and os.path.exists(filepath):
                InfoBar.error(
                    title="Error al mover a la papelera",
                    content="No se pudo mover el archivo a la papelera.",
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=parent_for_infobar,
                )
                return

            self._remove_from_archive_files(filepath)
            InfoBar.success(
                title="Movido a la papelera",
                content=f"'{title}' se movió a la papelera y se eliminará según tu configuración.",
                position=InfoBarPosition.TOP,
                duration=3500,
                parent=parent_for_infobar,
            )
        else:
            w = MessageBox(
                "¿Eliminar entrada del historial?",
                f"El archivo físico de '{title}' no se encuentra en el disco.\n\n¿Deseas quitar esta entrada del historial?",
                parent_for_infobar,
            )
            w.yesButton.setText("Eliminar del historial")
            w.cancelButton.setText("Cancelar")

            if not w.exec():
                return

            history_manager.remove_entry(filepath, video_id=vid_id)
            self._remove_from_archive_files(filepath)
            InfoBar.success(
                title="Entrada eliminada",
                content=f"'{title}' se eliminó del historial.",
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=parent_for_infobar,
            )

        QTimer.singleShot(0, self.file_deleted.emit)

    def _remove_from_archive_files(self, filepath: str):
        try:
            from downfry.core.organizer import unblock_archive_id
            vid_id = self.entry.get("video_id")
            if not vid_id:
                thumb = self.entry.get("thumbnail", "")
                import re
                m = re.search(r"/vi/([a-zA-Z0-9_-]{11})/", thumb)
                if m:
                    vid_id = m.group(1)

            if vid_id:
                download_dir = config_manager.get("download_dir", str(Path.home() / "Downloads" / "Downfry"))
                unblock_archive_id(download_dir, vid_id)
                if filepath:
                    parent_dir = str(Path(filepath).parent)
                    if parent_dir != download_dir:
                        unblock_archive_id(parent_dir, vid_id)
        except Exception:
            pass


class ArchiveEntryCard(CardWidget):
    """Tarjeta para gestionar un elemento registrado en el archivo antiduplicados."""

    entry_cleared = pyqtSignal()

    def __init__(self, record_text: str, archive_path: Path, parent=None):
        super().__init__(parent)
        self.record_text = record_text
        self.archive_path = archive_path
        self._init_ui()

    def _init_ui(self):
        from downfry.config import get_archive_title
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)

        parts = self.record_text.strip().split()
        vid_id = parts[-1] if parts else self.record_text

        # Buscar título
        title = get_archive_title(vid_id)
        if not title:
            for h in history_manager.history:
                th = h.get("thumbnail", "")
                fp = h.get("filepath", "")
                if (vid_id in th) or (vid_id in fp):
                    title = h.get("title")
                    break

        if title:
            display_title = f"{title} [{vid_id}]"
        else:
            display_title = f"Video [{vid_id}]" if vid_id else f"Registro: {self.record_text}"

        info = QVBoxLayout()
        info.setSpacing(2)
        lbl = BodyLabel(f"🎬 {display_title}", self)
        lbl.setStyleSheet("font-weight: bold;")
        lbl.setWordWrap(True)
        caption = CaptionLabel(f"Identificador: {vid_id}  •  Archivo: {self.archive_path.name}", self)
        caption.setStyleSheet("color: #888888;")
        info.addWidget(lbl)
        info.addWidget(caption)
        layout.addLayout(info, stretch=1)

        self.clear_btn = PushButton(FIF.DELETE, "Permitir re-descargar", self)
        self.clear_btn.setToolTip("Elimina esta entrada del registro antiduplicados para poder descargarla nuevamente.")
        self.clear_btn.clicked.connect(self._on_clear_entry)
        layout.addWidget(self.clear_btn)

    def _on_clear_entry(self):
        win = self.window()
        parent_for_infobar = win if win is not None else self
        try:
            if self.archive_path.exists():
                lines = self.archive_path.read_text(encoding="utf-8").splitlines()
                lines = [l for l in lines if l.strip() != self.record_text.strip()]
                self.archive_path.write_text("\n".join(lines), encoding="utf-8")
            InfoBar.success(
                title="Registro liberado",
                content=f"Ahora puedes volver a descargar este video.",
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=parent_for_infobar,
            )
            QTimer.singleShot(0, self.entry_cleared.emit)
        except Exception as e:
            InfoBar.error(
                title="Error al modificar registro",
                content=str(e),
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=parent_for_infobar,
            )


class HistoryView(QWidget):
    """Vista de historial con pestaña de Archivos Descargados y Registro Antiduplicados."""

    file_deleted = pyqtSignal()
    play_internal_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HistoryView")
        self._init_ui()

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(30, 24, 30, 24)
        self.main_layout.setSpacing(16)

        # 1. Cabecera
        header_layout = QHBoxLayout()
        header = TitleLabel("Historial y Gestión", self)
        header_layout.addWidget(header)
        header_layout.addStretch()

        self.clear_all_btn = PushButton(FIF.DELETE, "Limpiar historial", self)
        self.clear_all_btn.clicked.connect(self._on_clear_history)
        header_layout.addWidget(self.clear_all_btn)

        self.main_layout.addLayout(header_layout)

        # 2. Selector de Pestañas
        self.tab_segmented = SegmentedWidget(self)
        self.tab_segmented.addItem("files", "📁 Archivos Descargados")
        self.tab_segmented.addItem("archive", "📋 Registro Antiduplicados")
        self.tab_segmented.setCurrentItem("files")
        self.tab_segmented.currentItemChanged.connect(self._on_tab_changed)
        self.main_layout.addWidget(self.tab_segmented)

        # 3. Stack con ambas vistas
        self.stack = QStackedWidget(self)

        # --- Página 1: Archivos Descargados ---
        self.files_page = QWidget()
        fp_layout = QVBoxLayout(self.files_page)
        fp_layout.setContentsMargins(0, 0, 0, 0)

        self.files_scroll = QScrollArea(self.files_page)
        self.files_scroll.setWidgetResizable(True)
        self.files_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.files_container = QWidget()
        self.files_items_layout = QVBoxLayout(self.files_container)
        self.files_items_layout.setContentsMargins(0, 0, 0, 0)
        self.files_items_layout.setSpacing(10)
        self.files_scroll.setWidget(self.files_container)
        fp_layout.addWidget(self.files_scroll)

        self.stack.addWidget(self.files_page)

        # --- Página 2: Registro Antiduplicados ---
        self.archive_page = QWidget()
        ap_layout = QVBoxLayout(self.archive_page)
        ap_layout.setContentsMargins(0, 0, 0, 0)
        ap_layout.setSpacing(10)

        search_box = QHBoxLayout()
        self.archive_search = LineEdit(self.archive_page)
        self.archive_search.setPlaceholderText("Buscar ID o entrada en el registro...")
        self.archive_search.setClearButtonEnabled(True)
        self.archive_search.textChanged.connect(self._filter_archive)
        search_box.addWidget(self.archive_search, stretch=1)

        self.reload_archive_btn = PushButton(FIF.SYNC, "Actualizar", self.archive_page)
        self.reload_archive_btn.clicked.connect(self.reload_archive)
        search_box.addWidget(self.reload_archive_btn)
        ap_layout.addLayout(search_box)

        self.archive_scroll = QScrollArea(self.archive_page)
        self.archive_scroll.setWidgetResizable(True)
        self.archive_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.archive_container = QWidget()
        self.archive_items_layout = QVBoxLayout(self.archive_container)
        self.archive_items_layout.setContentsMargins(0, 0, 0, 0)
        self.archive_items_layout.setSpacing(8)
        self.archive_scroll.setWidget(self.archive_container)
        ap_layout.addWidget(self.archive_scroll)

        self.stack.addWidget(self.archive_page)
        self.main_layout.addWidget(self.stack, stretch=1)

        self.reload_history()

    def _on_tab_changed(self, tab_key: str):
        if tab_key == "files":
            self.stack.setCurrentIndex(0)
            self.reload_history()
        else:
            self.stack.setCurrentIndex(1)
            self.reload_archive()

    def reload_history(self):
        """Recarga la lista de archivos descargados desde history_manager."""
        while self.files_items_layout.count() > 0:
            child = self.files_items_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        entries = history_manager.history
        if not entries:
            empty_card = CardWidget(self.files_container)
            el = QVBoxLayout(empty_card)
            el.setContentsMargins(40, 40, 40, 40)
            lbl = SubtitleLabel("No hay descargas en el historial", empty_card)
            el.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignCenter)
            self.files_items_layout.addWidget(empty_card)
            self.clear_all_btn.setEnabled(False)
        else:
            self.clear_all_btn.setEnabled(True)
            for entry in entries:
                card = HistoryItemCard(entry, self.files_container)
                card.file_deleted.connect(self.reload_history)
                card.file_deleted.connect(self.file_deleted.emit)
                card.play_internal_requested.connect(self.play_internal_requested.emit)
                self.files_items_layout.addWidget(card)

        self.files_items_layout.addStretch()

    def reload_archive(self):
        """Busca y carga todas las entradas de archivos download_archive.txt."""
        while self.archive_items_layout.count() > 0:
            child = self.archive_items_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        download_base = Path(config_manager.get("download_dir", str(Path.home() / "Downloads" / "Downfry")))
        archive_files = list(download_base.glob("**/download_archive.txt"))

        entries_found = []
        for af in archive_files:
            try:
                lines = af.read_text(encoding="utf-8").splitlines()
                for line in lines:
                    line_s = line.strip()
                    if line_s:
                        entries_found.append((line_s, af))
            except Exception:
                pass

        if not entries_found:
            empty_card = CardWidget(self.archive_container)
            el = QVBoxLayout(empty_card)
            el.setContentsMargins(40, 40, 40, 40)
            lbl = SubtitleLabel("El registro antiduplicados está vacío", empty_card)
            cap = CaptionLabel("Cuando descargues listas o canales, los IDs registrados aparecerán aquí para que puedas desbloquearlos si deseas descargarlos de nuevo.", empty_card)
            cap.setStyleSheet("color: #888888;")
            el.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignCenter)
            el.addWidget(cap, alignment=Qt.AlignmentFlag.AlignCenter)
            self.archive_items_layout.addWidget(empty_card)
        else:
            from downfry.config import get_archive_title
            search_query = self.archive_search.text().lower().strip()
            for rec, af in entries_found:
                parts = rec.strip().split()
                vid_id = parts[-1] if parts else rec
                title = get_archive_title(vid_id) or ""
                if search_query:
                    if (search_query not in rec.lower()) and (search_query not in title.lower()):
                        continue
                card = ArchiveEntryCard(rec, af, self.archive_container)
                card.entry_cleared.connect(self.reload_archive)
                self.archive_items_layout.addWidget(card)

        self.archive_items_layout.addStretch()

    def _filter_archive(self):
        self.reload_archive()

    def _on_clear_history(self):
        history_manager.clear()
        self.reload_history()
        InfoBar.success(
            title="Historial limpiado",
            content="Se ha borrado el historial de descargas.",
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self.window(),
        )
