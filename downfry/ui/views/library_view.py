"""Vista principal de la Biblioteca Offline estilo YouTube para Downfry."""

import os
from typing import Dict, Any, List, Optional
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QSize
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QScrollArea,
    QLabel,
)
from qfluentwidgets import (
    SubtitleLabel,
    BodyLabel,
    CaptionLabel,
    CardWidget,
    PushButton,
    PrimaryPushButton,
    LineEdit,
    ComboBox,
    SegmentedWidget,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
)
from downfry.config import config_manager
from downfry.ui.components.library_cards import (
    YouTubeVideoCard,
    ChannelSidebarItem,
    SidebarNavButton,
)
from downfry.core.library_manager import (
    offline_library_manager,
    playback_progress_manager,
)


class LibraryScanWorker(QThread):
    """Hilo para escanear archivos y metadatos de la biblioteca en segundo plano."""

    scan_finished = pyqtSignal(list, list, list)

    def __init__(self, download_dir: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.download_dir = download_dir

    def run(self):
        try:
            items = offline_library_manager.scan_library(self.download_dir)
            channels = offline_library_manager.get_channels(items)
            playlists = offline_library_manager.get_playlists(items)
            self.scan_finished.emit(items, channels, playlists)
        except Exception as e:
            print(f"[LibraryScanWorker] Error escaneando: {e}")
            self.scan_finished.emit([], [], [])


class LibraryView(QWidget):
    """Navegador offline de videos estilo YouTube con panel lateral, filtros y cuadrícula responsiva."""

    # Señal emitida cuando el usuario desea reproducir un video (item seleccionado, cola completa)
    play_video_requested = pyqtSignal(dict, list)

    def __init__(self, parent=None, auto_load: bool = True):
        super().__init__(parent)
        self.setObjectName("library_view")

        # Datos
        self.all_items: List[Dict[str, Any]] = []
        self.channels_data: List[Dict[str, Any]] = []
        self.playlists_data: List[Dict[str, Any]] = []
        self.filtered_items: List[Dict[str, Any]] = []

        # Estado actual de navegación y filtros
        self.current_scope_type: str = "all"  # "all", "continue", "channel", "playlist"
        self.current_scope_name: str = ""
        self.current_category: str = "all"
        self.current_year: str = "all"
        self.current_month: str = "all"
        self.current_search: str = ""

        # Mapeo de tarjetas visuales activas
        self.card_widgets: List[YouTubeVideoCard] = []

        self._init_ui()
        if auto_load:
            self.reload_library()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # =========================================================================
        # 1. PANEL LATERAL IZQUIERDO (Canales, Playlists y Secciones fijas)
        # =========================================================================
        sidebar_frame = CardWidget(self)
        sidebar_frame.setFixedWidth(205)
        sidebar_layout = QVBoxLayout(sidebar_frame)
        sidebar_layout.setContentsMargins(6, 10, 6, 10)
        sidebar_layout.setSpacing(5)

        # Botones fijos superiores
        self.nav_all_btn = SidebarNavButton("all", "Todos los videos", "🎬", count=0, parent=sidebar_frame)
        self.nav_all_btn.clicked.connect(self._on_nav_all_clicked)
        self.nav_all_btn.set_selected(True)
        sidebar_layout.addWidget(self.nav_all_btn)

        self.nav_continue_btn = SidebarNavButton(
            "continue", "Continuar viendo", "⏱️", count=0, parent=sidebar_frame
        )
        self.nav_continue_btn.clicked.connect(self._on_nav_continue_clicked)
        sidebar_layout.addWidget(self.nav_continue_btn)

        # Scroll área interna para Canales y Playlists
        sidebar_scroll = QScrollArea(sidebar_frame)
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.sidebar_content = QWidget()
        self.sidebar_content_layout = QVBoxLayout(self.sidebar_content)
        self.sidebar_content_layout.setContentsMargins(0, 6, 0, 0)
        self.sidebar_content_layout.setSpacing(4)

        # Título sección Canales
        self.channels_header = CaptionLabel("CANALES DESCARGADOS", self.sidebar_content)
        self.channels_header.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.channels_header.setStyleSheet("color: #888888; padding-left: 8px; margin-top: 8px;")
        self.sidebar_content_layout.addWidget(self.channels_header)

        self.channels_list_layout = QVBoxLayout()
        self.channels_list_layout.setContentsMargins(0, 0, 0, 0)
        self.channels_list_layout.setSpacing(2)
        self.sidebar_content_layout.addLayout(self.channels_list_layout)

        # Título sección Playlists
        self.playlists_header = CaptionLabel("PLAYLISTS DESCARGADAS", self.sidebar_content)
        self.playlists_header.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.playlists_header.setStyleSheet("color: #888888; padding-left: 8px; margin-top: 12px;")
        self.sidebar_content_layout.addWidget(self.playlists_header)

        self.playlists_list_layout = QVBoxLayout()
        self.playlists_list_layout.setContentsMargins(0, 0, 0, 0)
        self.playlists_list_layout.setSpacing(2)
        self.sidebar_content_layout.addLayout(self.playlists_list_layout)

        self.sidebar_content_layout.addStretch()
        sidebar_scroll.setWidget(self.sidebar_content)
        sidebar_layout.addWidget(sidebar_scroll, stretch=1)

        main_layout.addWidget(sidebar_frame)

        # =========================================================================
        # 2. PANEL DERECHO PRINCIPAL (Cabecera, Filtros y Cuadrícula de Videos)
        # =========================================================================
        right_panel = QVBoxLayout()
        right_panel.setContentsMargins(0, 0, 0, 0)
        right_panel.setSpacing(10)

        # Cabecera dinámica (Título + Controles)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(4, 2, 4, 0)
        header_layout.setSpacing(10)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.view_title = SubtitleLabel("Todos los videos", self)
        self.view_subtitle = CaptionLabel("Explora tus videos descargados sin conexión", self)
        self.view_subtitle.setStyleSheet("color: #888888;")
        title_box.addWidget(self.view_title)
        title_box.addWidget(self.view_subtitle)
        header_layout.addLayout(title_box, stretch=1)

        # Botón "Reproducir todo"
        self.play_all_btn = PrimaryPushButton(FIF.PLAY, "Reproducir todo", self)
        self.play_all_btn.setMinimumWidth(130)
        self.play_all_btn.clicked.connect(self._on_play_all_clicked)
        header_layout.addWidget(self.play_all_btn)

        # Botón "Actualizar"
        self.reload_btn = PushButton(FIF.SYNC, "Actualizar", self)
        self.reload_btn.setMinimumWidth(100)
        self.reload_btn.clicked.connect(self.reload_library)
        header_layout.addWidget(self.reload_btn)

        right_panel.addLayout(header_layout)

        # FILA 1 DE FILTROS: Buscador + Filtros de Año y Mes + Ordenación
        filter_bar_1 = QHBoxLayout()
        filter_bar_1.setContentsMargins(4, 0, 4, 0)
        filter_bar_1.setSpacing(8)

        self.search_input = LineEdit(self)
        self.search_input.setPlaceholderText("Buscar por título, canal o playlist...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        filter_bar_1.addWidget(self.search_input, stretch=1)

        # Filtro de Año
        self.year_combo = ComboBox(self)
        self.year_combo.addItem("Todos los años", userData="all")
        self.year_combo.currentIndexChanged.connect(self._on_filter_changed)
        self.year_combo.setMinimumWidth(115)
        filter_bar_1.addWidget(self.year_combo)

        # Filtro de Mes
        self.month_combo = ComboBox(self)
        self.month_combo.addItem("Todos los meses", userData="all")
        self.month_combo.currentIndexChanged.connect(self._on_filter_changed)
        self.month_combo.setMinimumWidth(125)
        filter_bar_1.addWidget(self.month_combo)

        # Ordenamiento
        self.sort_combo = ComboBox(self)
        self.sort_combo.addItems([
            "Fecha (más reciente)",
            "Fecha (más antigua)",
            "Título (A-Z)",
            "Duración (mayor primero)",
            "Tamaño (mayor primero)",
        ])
        self.sort_combo.setCurrentIndex(0)
        self.sort_combo.currentIndexChanged.connect(self._on_filter_changed)
        self.sort_combo.setMinimumWidth(160)
        filter_bar_1.addWidget(self.sort_combo)

        right_panel.addLayout(filter_bar_1)

        # FILA 2 DE FILTROS: Chips de Categorías estilo YouTube (dedicado sin solapamiento)
        filter_bar_2 = QHBoxLayout()
        filter_bar_2.setContentsMargins(4, 0, 4, 0)
        filter_bar_2.setSpacing(8)

        self.category_seg = SegmentedWidget(self)
        self.category_seg.addItem("all", "Todos")
        self.category_seg.addItem("continue", "Continuar viendo")
        self.category_seg.addItem("Videos", "Videos")
        self.category_seg.addItem("Shorts", "Shorts")
        self.category_seg.addItem("Directos", "Directos")
        self.category_seg.addItem("Audio", "Audio")
        self.category_seg.setCurrentItem("all")
        self.category_seg.currentItemChanged.connect(self._on_category_chip_changed)
        filter_bar_2.addWidget(self.category_seg)

        filter_bar_2.addStretch(1)

        right_panel.addLayout(filter_bar_2)

        # Área de Desplazamiento y Cuadrícula de Videos
        self.grid_scroll = QScrollArea(self)
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(6, 6, 6, 6)
        self.grid_layout.setSpacing(14)
        self.grid_scroll.setWidget(self.grid_container)

        right_panel.addWidget(self.grid_scroll, stretch=1)
        main_layout.addLayout(right_panel, stretch=1)

    def reload_library(self):
        """Dispara el escaneo asíncrono de la biblioteca en segundo plano."""
        if hasattr(self, "worker") and self.worker is not None and self.worker.isRunning():
            try:
                self.worker.scan_finished.disconnect(self._on_scan_completed)
            except Exception:
                pass
            self.worker.wait(1000)

        self.reload_btn.setEnabled(False)
        download_dir = config_manager.get("download_dir", None)
        self.worker = LibraryScanWorker(download_dir=download_dir, parent=self)
        self.worker.scan_finished.connect(self._on_scan_completed)
        self.worker.start()

    def closeEvent(self, event):
        if hasattr(self, "worker") and self.worker is not None and self.worker.isRunning():
            try:
                self.worker.scan_finished.disconnect(self._on_scan_completed)
            except Exception:
                pass
            self.worker.terminate()
            self.worker.wait(500)
        super().closeEvent(event)

    def _on_scan_completed(self, items: list, channels: list, playlists: list):
        self.reload_btn.setEnabled(True)
        self.all_items = items
        self.channels_data = channels
        self.playlists_data = playlists

        # Actualizar contadores de navegación principal
        in_progress_count = sum(
            1 for it in items
            if float((it.get("progress") or {}).get("ratio", 0.0)) > 0
            and not (it.get("progress") or {}).get("completed", False)
        )
        self.nav_all_btn.update_count(len(items))
        self.nav_continue_btn.update_count(in_progress_count)

        # Actualizar selectores de Años y Meses disponibles (con meses limpios)
        self._populate_date_filters()

        # Actualizar lista lateral de canales y playlists
        self._populate_sidebar()

        # Filtrar y renderizar cuadrícula
        self._apply_filters_and_render()

    def _populate_date_filters(self):
        """Extrae los años y meses disponibles en la biblioteca con nombres limpios de mes."""
        current_year_val = self.year_combo.currentData() or "all"
        current_month_val = self.month_combo.currentData() or "all"

        self.year_combo.blockSignals(True)
        self.month_combo.blockSignals(True)

        self.year_combo.clear()
        self.year_combo.addItem("Todos los años", userData="all")

        years = sorted(
            list({str(it.get("year")) for it in self.all_items if it.get("year")}),
            reverse=True,
        )
        for y in years:
            self.year_combo.addItem(y, userData=y)

        self.month_combo.clear()
        self.month_combo.addItem("Todos los meses", userData="all")
        raw_months = sorted(
            list({str(it.get("month_folder")) for it in self.all_items if it.get("month_folder")})
        )
        for m in raw_months:
            # Quitar prefijo numérico para mostrar únicamente el nombre limpio ("07 - Julio" -> "Julio")
            display_m = m.split(" - ", 1)[-1].strip() if " - " in m else m
            self.month_combo.addItem(display_m, userData=m)

        # Restaurar selecciones si aún son válidas
        idx_y = self.year_combo.findData(current_year_val)
        if idx_y >= 0:
            self.year_combo.setCurrentIndex(idx_y)
        idx_m = self.month_combo.findData(current_month_val)
        if idx_m >= 0:
            self.month_combo.setCurrentIndex(idx_m)

        self.year_combo.blockSignals(False)
        self.month_combo.blockSignals(False)

    def _populate_sidebar(self):
        """Rellena la lista lateral de canales y playlists."""
        # Limpiar canales previos
        while self.channels_list_layout.count() > 0:
            child = self.channels_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Limpiar playlists previas
        while self.playlists_list_layout.count() > 0:
            child = self.playlists_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Rellenar Canales
        if not self.channels_data:
            empty_ch = CaptionLabel("No hay canales", self.sidebar_content)
            empty_ch.setStyleSheet("color: #666666; padding-left: 10px;")
            self.channels_list_layout.addWidget(empty_ch)
        else:
            for ch in self.channels_data:
                item_widget = ChannelSidebarItem(
                    name=ch["name"],
                    count=ch["count"],
                    is_playlist=False,
                    parent=self.sidebar_content,
                )
                if self.current_scope_type == "channel" and self.current_scope_name == ch["name"]:
                    item_widget.set_selected(True)
                item_widget.clicked.connect(self._on_channel_selected)
                self.channels_list_layout.addWidget(item_widget)

        # Rellenar Playlists
        if not self.playlists_data:
            empty_pl = CaptionLabel("No hay playlists", self.sidebar_content)
            empty_pl.setStyleSheet("color: #666666; padding-left: 10px;")
            self.playlists_list_layout.addWidget(empty_pl)
        else:
            for pl in self.playlists_data:
                item_widget = ChannelSidebarItem(
                    name=pl["name"],
                    count=pl["count"],
                    is_playlist=True,
                    parent=self.sidebar_content,
                )
                if self.current_scope_type == "playlist" and self.current_scope_name == pl["name"]:
                    item_widget.set_selected(True)
                item_widget.clicked.connect(self._on_playlist_selected)
                self.playlists_list_layout.addWidget(item_widget)

    def _on_nav_all_clicked(self):
        self.current_scope_type = "all"
        self.current_scope_name = ""
        self.nav_all_btn.set_selected(True)
        self.nav_continue_btn.set_selected(False)
        self._unselect_sidebar_items()
        self.view_title.setText("Todos los videos")
        self.view_subtitle.setText("Explora todos los videos descargados en tu equipo")
        self._apply_filters_and_render()

    def _on_nav_continue_clicked(self):
        self.current_scope_type = "continue"
        self.current_scope_name = ""
        self.nav_all_btn.set_selected(False)
        self.nav_continue_btn.set_selected(True)
        self._unselect_sidebar_items()
        self.view_title.setText("Continuar viendo")
        self.view_subtitle.setText("Videos que empezaste y dejaste a mitad")
        self._apply_filters_and_render()

    def _on_channel_selected(self, channel_name: str):
        self.current_scope_type = "channel"
        self.current_scope_name = channel_name
        self.nav_all_btn.set_selected(False)
        self.nav_continue_btn.set_selected(False)
        self._unselect_sidebar_items(active_channel=channel_name)
        self.view_title.setText(f"Canal: {channel_name}")
        self.view_subtitle.setText(f"Videos descargados del canal {channel_name}")
        self._apply_filters_and_render()

    def _on_playlist_selected(self, playlist_name: str):
        self.current_scope_type = "playlist"
        self.current_scope_name = playlist_name
        self.nav_all_btn.set_selected(False)
        self.nav_continue_btn.set_selected(False)
        self._unselect_sidebar_items(active_playlist=playlist_name)
        self.view_title.setText(f"Playlist: {playlist_name}")
        self.view_subtitle.setText(f"Videos descargados de la lista {playlist_name}")
        self._apply_filters_and_render()

    def _unselect_sidebar_items(self, active_channel: str = "", active_playlist: str = ""):
        for i in range(self.channels_list_layout.count()):
            w = self.channels_list_layout.itemAt(i).widget()
            if isinstance(w, ChannelSidebarItem):
                w.set_selected(w.name == active_channel)

        for i in range(self.playlists_list_layout.count()):
            w = self.playlists_list_layout.itemAt(i).widget()
            if isinstance(w, ChannelSidebarItem):
                w.set_selected(w.name == active_playlist)

    def _on_category_chip_changed(self, key: str):
        self.current_category = key
        self._apply_filters_and_render()

    def _on_search_text_changed(self, text: str):
        self.current_search = text.strip().lower()
        self._apply_filters_and_render()

    def _on_filter_changed(self):
        self._apply_filters_and_render()

    def _apply_filters_and_render(self):
        """Filtra y ordena la lista de elementos en base al estado activo y reconstruye la cuadrícula."""
        items = list(self.all_items)

        # 1. Filtro de Ámbito lateral
        if self.current_scope_type == "continue":
            items = [
                it for it in items
                if float((it.get("progress") or {}).get("ratio", 0.0)) > 0
                and not (it.get("progress") or {}).get("completed", False)
            ]
        elif self.current_scope_type == "channel":
            items = [
                it for it in items
                if (it.get("channel") or it.get("uploader") or "").strip().lower() == self.current_scope_name.lower()
            ]
        elif self.current_scope_type == "playlist":
            items = [
                it for it in items
                if (it.get("playlist") or "").strip().lower() == self.current_scope_name.lower()
            ]

        # 2. Filtro de Categoría (Chips)
        if self.current_category == "continue":
            items = [
                it for it in items
                if float((it.get("progress") or {}).get("ratio", 0.0)) > 0
                and not (it.get("progress") or {}).get("completed", False)
            ]
        elif self.current_category not in ("all", ""):
            items = [
                it for it in items
                if it.get("category") == self.current_category
            ]

        # 3. Filtro de Año
        selected_year = self.year_combo.currentData()
        if selected_year and selected_year != "all":
            items = [it for it in items if str(it.get("year")) == selected_year]

        # 4. Filtro de Mes
        selected_month = self.month_combo.currentData()
        if selected_month and selected_month != "all":
            items = [it for it in items if str(it.get("month_folder")) == selected_month]

        # 5. Búsqueda en tiempo real
        if self.current_search:
            q = self.current_search
            items = [
                it for it in items
                if (q in (it.get("title") or "").lower())
                or (q in (it.get("channel") or "").lower())
                or (q in (it.get("uploader") or "").lower())
                or (q in (it.get("playlist") or "").lower())
                or (q in (it.get("iso_date") or "").lower())
            ]

        # 6. Ordenamiento
        sort_mode = self.sort_combo.currentIndex()
        if sort_mode == 0:  # Fecha de subida más reciente
            items.sort(key=lambda x: (x.get("iso_date") or "", x.get("upload_date") or ""), reverse=True)
        elif sort_mode == 1:  # Fecha de subida más antigua
            items.sort(key=lambda x: (x.get("iso_date") or "9999", x.get("upload_date") or "9999"))
        elif sort_mode == 2:  # Título A-Z
            items.sort(key=lambda x: (x.get("title") or "").lower())
        elif sort_mode == 3:  # Duración mayor primero
            items.sort(key=lambda x: float(x.get("duration") or 0), reverse=True)
        elif sort_mode == 4:  # Tamaño mayor primero
            items.sort(key=lambda x: int(x.get("size") or 0), reverse=True)

        self.filtered_items = items
        self.play_all_btn.setEnabled(len(self.filtered_items) > 0)

        count_str = f"({len(self.filtered_items)} video{'s' if len(self.filtered_items) != 1 else ''})"
        base_sub = self.view_subtitle.text().split("(")[0].strip()
        self.view_subtitle.setText(f"{base_sub} {count_str}")

        self._render_grid()

    def _calculate_columns(self) -> int:
        """Calcula el número óptimo de columnas asegurando al menos 2-3 en ventanas estándar."""
        viewport_width = self.grid_scroll.viewport().width()
        if viewport_width < 300:
            viewport_width = max(520, self.width() - 225)
        card_width = 245
        spacing = 14
        return max(1, (viewport_width - 16) // (card_width + spacing))

    def _render_grid(self):
        """Limpia y construye las tarjetas en la cuadrícula de forma responsiva."""
        for card in self.card_widgets:
            if hasattr(card, "_stop_loader"):
                card._stop_loader()

        while self.grid_layout.count() > 0:
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.card_widgets.clear()

        if not self.filtered_items:
            empty_card = CardWidget(self.grid_container)
            el = QVBoxLayout(empty_card)
            el.setContentsMargins(40, 50, 40, 50)
            el.setSpacing(10)

            title_lbl = SubtitleLabel("No se encontraron videos descargados", empty_card)
            title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            el.addWidget(title_lbl)

            msg_lbl = BodyLabel(
                "Verifica los filtros seleccionados o añade nuevas descargas desde la pestaña de Inicio.",
                empty_card,
            )
            msg_lbl.setStyleSheet("color: #888888;")
            msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            el.addWidget(msg_lbl)

            rescan_btn = PushButton(FIF.SYNC, "Volver a escanear biblioteca", empty_card)
            rescan_btn.setMinimumWidth(180)
            rescan_btn.clicked.connect(self.reload_library)
            el.addWidget(rescan_btn, alignment=Qt.AlignmentFlag.AlignCenter)

            self.grid_layout.addWidget(empty_card, 0, 0, 1, 3)
            return

        columns = self._calculate_columns()

        for idx, item in enumerate(self.filtered_items):
            row = idx // columns
            col = idx % columns

            card = YouTubeVideoCard(item, parent=self.grid_container)
            card.play_clicked.connect(self._on_card_play_clicked)
            card.channel_clicked.connect(self._on_channel_selected)
            self.card_widgets.append(card)

            self.grid_layout.addWidget(card, row, col, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

    def _relayout_grid(self):
        """Reubica las tarjetas existentes según el nuevo número de columnas sin recrearlas."""
        if not self.card_widgets or not self.filtered_items:
            return
        columns = self._calculate_columns()
        for idx, card in enumerate(self.card_widgets):
            row = idx // columns
            col = idx % columns
            self.grid_layout.addWidget(card, row, col, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

    def showEvent(self, event):
        """Garantiza el cálculo exacto del ancho de cuadrícula cuando la pestaña se hace visible."""
        super().showEvent(event)
        QTimer.singleShot(50, self._relayout_grid)

    def resizeEvent(self, event):
        """Adapta la cuadrícula dinámicamente cuando el usuario cambia el tamaño de la ventana."""
        super().resizeEvent(event)
        self._relayout_grid()

    def _on_card_play_clicked(self, item: dict):
        """Reproduce el video individual enviando la lista filtrada como cola de reproducción."""
        self.play_video_requested.emit(item, self.filtered_items)

    def _on_play_all_clicked(self):
        """Reproduce la lista completa filtrada desde el primer elemento."""
        if self.filtered_items:
            first_item = self.filtered_items[0]
            self.play_video_requested.emit(first_item, self.filtered_items)

    def update_card_progress(self, video_id: str, filepath: str, ratio: float, completed: bool = False):
        """Actualiza la barra de progreso en vivo de la tarjeta correspondiente sin redibujar todo."""
        norm_fp = os.path.normpath(str(filepath)).lower() if filepath else ""
        vid = str(video_id or "").strip()

        for card in self.card_widgets:
            card_vid = str(card.item.get("video_id") or "").strip()
            card_fp = os.path.normpath(str(card.item.get("filepath") or "")).lower()

            if (vid and card_vid == vid) or (norm_fp and card_fp == norm_fp):
                card.update_progress(ratio, completed)
                if "progress" not in card.item:
                    card.item["progress"] = {}
                card.item["progress"]["ratio"] = ratio
                card.item["progress"]["completed"] = completed
                break
