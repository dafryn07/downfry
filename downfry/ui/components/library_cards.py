"""Componentes visuales estilo YouTube para la Biblioteca Offline de Downfry."""

import os
import hashlib
from typing import Dict, Any, Optional
from PyQt6.QtCore import Qt, QRect, QRectF, QSize, QPoint, pyqtSignal, QThread
from PyQt6.QtGui import (
    QPainter,
    QColor,
    QLinearGradient,
    QPixmap,
    QImage,
    QFont,
    QFontMetrics,
    QPainterPath,
    QBrush,
    QCursor,
    QMouseEvent,
)
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
)
from qfluentwidgets import (
    CardWidget,
    CaptionLabel,
    TransparentToolButton,
    RoundMenu,
    Action,
    FluentIcon as FIF,
)
from downfry.utils.formatting import open_file, open_in_explorer, format_seconds

_PIXMAP_CACHE: Dict[str, QPixmap] = {}

# Paleta armónica y elegante de colores para avatares de canales
AVATAR_PALETTE = [
    "#1E88E5",  # Azul
    "#43A047",  # Verde
    "#8E24AA",  # Púrpura
    "#FB8C00",  # Naranja
    "#00ACC1",  # Cian oscuro
    "#3949AB",  # Índigo
    "#D81B60",  # Rosa
    "#00897B",  # Verde azulado
    "#5E35B1",  # Violeta profundo
]


def _get_channel_color(name: str) -> str:
    """Calcula un color consistente a partir del nombre del canal."""
    if not name:
        return AVATAR_PALETTE[0]
    idx = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16) % len(AVATAR_PALETTE)
    return AVATAR_PALETTE[idx]


def _get_channel_initials(name: str) -> str:
    """Extrae 1 o 2 iniciales representativas del nombre del canal."""
    if not name:
        return "Y"
    words = [w for w in name.strip().split() if w]
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    return name[:2].upper() if len(name) >= 2 else name[:1].upper()


def _format_date_ddmmyyyy(date_str: str) -> str:
    """Convierte fechas ISO (YYYY-MM-DD o YYYYMMDD) al formato DD/MM/AAAA."""
    if not date_str:
        return ""
    s = str(date_str).strip()
    if "-" in s:
        parts = s.split("-")
        if len(parts) >= 3 and len(parts[0]) == 4:
            return f"{parts[2][:2]}/{parts[1]}/{parts[0]}"
    if len(s) == 8 and s.isdigit():
        return f"{s[6:8]}/{s[4:6]}/{s[0:4]}"
    return s


class ThumbnailLoaderThread(QThread):
    """Carga miniaturas en segundo plano (disco local o web) sin bloquear la interfaz."""

    pixmap_ready = pyqtSignal(QPixmap)

    def __init__(self, item: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.item = item
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return

        # 1. Intentar con miniatura local ya establecida
        local_thumb = self.item.get("local_thumbnail")
        if local_thumb and os.path.isfile(local_thumb):
            pix = self._load_file(local_thumb)
            if pix and not self._cancelled:
                self.pixmap_ready.emit(pix)
                return

        # 2. Intentar con ruta 'thumbnail' si es un archivo existente en disco
        thumb_val = self.item.get("thumbnail") or ""
        if thumb_val and os.path.isfile(thumb_val):
            pix = self._load_file(thumb_val)
            if pix and not self._cancelled:
                self.pixmap_ready.emit(pix)
                return

        # 3. Intentar generar o localizar vía offline_library_manager si está disponible
        filepath = self.item.get("filepath") or ""
        vid_id = self.item.get("video_id") or ""
        try:
            from downfry.core.library_manager import offline_library_manager
            ensured = offline_library_manager.ensure_local_thumbnail(filepath, vid_id)
            if ensured and os.path.isfile(ensured):
                pix = self._load_file(ensured)
                if pix and not self._cancelled:
                    self.pixmap_ready.emit(pix)
                    return
        except Exception:
            pass

        # 4. Comprobar si existe un archivo .jpg o .webp con el mismo nombre base que el video
        if filepath and os.path.isfile(filepath):
            base, _ = os.path.splitext(filepath)
            for ext in [".jpg", ".jpeg", ".png", ".webp"]:
                candidate = base + ext
                if os.path.isfile(candidate):
                    pix = self._load_file(candidate)
                    if pix and not self._cancelled:
                        self.pixmap_ready.emit(pix)
                        return

        # 5. Si la miniatura es una URL web http/https, descargarla
        if thumb_val and (thumb_val.startswith("http://") or thumb_val.startswith("https://")):
            if thumb_val in _PIXMAP_CACHE:
                if not self._cancelled:
                    self.pixmap_ready.emit(_PIXMAP_CACHE[thumb_val])
                return

            try:
                import requests
                resp = requests.get(thumb_val, timeout=6)
                if not self._cancelled and resp.status_code == 200:
                    img = QImage()
                    if img.loadFromData(resp.content):
                        pix = QPixmap.fromImage(img)
                        if len(_PIXMAP_CACHE) > 100:
                            _PIXMAP_CACHE.pop(next(iter(_PIXMAP_CACHE)))
                        _PIXMAP_CACHE[thumb_val] = pix
                        self.pixmap_ready.emit(pix)
            except Exception:
                pass

    def _load_file(self, path: str) -> Optional[QPixmap]:
        if path in _PIXMAP_CACHE:
            return _PIXMAP_CACHE[path]
        try:
            pix = QPixmap(path)
            if not pix.isNull():
                if len(_PIXMAP_CACHE) > 100:
                    _PIXMAP_CACHE.pop(next(iter(_PIXMAP_CACHE)))
                _PIXMAP_CACHE[path] = pix
                return pix
        except Exception:
            pass
        return None


class ThumbnailWidget(QWidget):
    """Lienzo de miniatura 16:9 con badges, hover animado y barra inferior de progreso en tonos fríos."""

    clicked = pyqtSignal()

    def __init__(self, width: int = 225, height: int = 126, parent=None):
        super().__init__(parent)
        self.setFixedSize(width, height)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self.pixmap: Optional[QPixmap] = None
        self.duration_str: str = ""
        self.quality_str: str = ""
        self.progress_ratio: float = 0.0
        self.is_completed: bool = False
        self.is_hovered: bool = False

    def set_data(
        self,
        pixmap: Optional[QPixmap] = None,
        duration_str: str = "",
        quality_str: str = "",
        progress_ratio: float = 0.0,
        is_completed: bool = False,
    ):
        self.pixmap = pixmap
        self.duration_str = duration_str
        self.quality_str = quality_str
        self.progress_ratio = max(0.0, min(1.0, progress_ratio))
        self.is_completed = is_completed
        self.update()

    def set_pixmap(self, pixmap: QPixmap):
        self.pixmap = pixmap
        self.update()

    def set_progress(self, ratio: float, completed: bool = False):
        self.progress_ratio = max(0.0, min(1.0, ratio))
        self.is_completed = completed
        self.update()

    def enterEvent(self, event):
        self.is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        w = self.width()
        h = self.height()
        radius = 6.0

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Recorte con esquinas redondeadas
        clip_path = QPainterPath()
        clip_path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
        painter.setClipPath(clip_path)

        # Fondo base
        if self.pixmap and not self.pixmap.isNull():
            scaled = self.pixmap.scaled(
                QSize(w, h),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x_off = (scaled.width() - w) // 2
            y_off = (scaled.height() - h) // 2
            painter.drawPixmap(0, 0, scaled, x_off, y_off, w, h)
        else:
            painter.fillRect(QRect(0, 0, w, h), QColor("#1e222b"))
            painter.setPen(QColor("#4f5869"))
            painter.setFont(QFont("Segoe UI", 16))
            painter.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "🎬")

        # Overlay tenue de hover + botón de play central
        if self.is_hovered:
            painter.fillRect(QRect(0, 0, w, h), QColor(0, 0, 0, 75))
            cx, cy = w // 2, h // 2
            r = 18
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 160))
            painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)

            play_path = QPainterPath()
            play_path.moveTo(cx - 4, cy - 7)
            play_path.lineTo(cx + 7, cy)
            play_path.lineTo(cx - 4, cy + 7)
            play_path.closeSubpath()
            painter.setBrush(QColor(255, 255, 255, 230))
            painter.drawPath(play_path)

        # 1. Badge de calidad (esquina superior izquierda)
        if self.quality_str:
            q_text = self.quality_str.upper()
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(q_text)
            th = fm.height()
            bw = tw + 8
            bh = th + 3
            bx = 6
            by = 6
            b_path = QPainterPath()
            b_path.addRoundedRect(QRectF(bx, by, bw, bh), 3.0, 3.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 180))
            painter.drawPath(b_path)
            painter.setPen(QColor(255, 255, 255, 230))
            painter.drawText(QRect(bx, by, bw, bh), Qt.AlignmentFlag.AlignCenter, q_text)

        # 2. Badge de duración (esquina inferior derecha)
        if self.duration_str:
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(self.duration_str)
            th = fm.height()
            bw = tw + 8
            bh = th + 3
            bx = w - bw - 6
            by = h - bh - (7 if self.progress_ratio > 0 else 6)
            b_path = QPainterPath()
            b_path.addRoundedRect(QRectF(bx, by, bw, bh), 3.0, 3.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 190))
            painter.drawPath(b_path)
            painter.setPen(QColor(255, 255, 255, 240))
            painter.drawText(QRect(bx, by, bw, bh), Qt.AlignmentFlag.AlignCenter, self.duration_str)

        # 3. BARRA INFERIOR DE PROGRESO VISTO (COLORES FRÍOS: CIAN #00A8E8 A VERDE ESMERALDA #00C896 - NUNCA ROJO)
        if self.progress_ratio > 0:
            bar_height = 4
            bar_y = h - bar_height

            painter.fillRect(QRect(0, bar_y, w, bar_height), QColor(40, 40, 40, 190))
            prog_w = max(4, int(w * self.progress_ratio))

            if self.is_completed:
                fill_brush = QBrush(QColor("#00C896"))
            else:
                grad = QLinearGradient(0, bar_y, max(w, prog_w), bar_y)
                grad.setColorAt(0.0, QColor("#00A8E8"))
                grad.setColorAt(1.0, QColor("#00C896"))
                fill_brush = QBrush(grad)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill_brush)
            painter.fillRect(QRect(0, bar_y, prog_w, bar_height))

        painter.end()


class YouTubeVideoCard(CardWidget):
    """Tarjeta individual estilo YouTube limpia y compacta con menú desplegable ⋮ y sin botones inferiores."""

    play_clicked = pyqtSignal(dict)
    channel_clicked = pyqtSignal(str)
    open_folder_clicked = pyqtSignal(str)

    def __init__(self, item: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.item = item
        self.loader_thread: Optional[ThumbnailLoaderThread] = None

        # Tamaño compacto y proporcionado para múltiples columnas
        self.setFixedSize(245, 222)
        self._init_ui()
        self._load_thumbnail()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)

        # 1. Miniatura 16:9 con barra fría integrada
        self.thumb_widget = ThumbnailWidget(width=225, height=126, parent=self)
        self.thumb_widget.clicked.connect(self._on_play)

        # Duración y calidad
        dur = self.item.get("duration")
        dur_str = self.item.get("duration_str") or (format_seconds(dur) if dur else "")
        quality_str = self.item.get("quality", "")
        if not quality_str:
            category = self.item.get("category", "")
            if category in ["Shorts", "Audio"]:
                quality_str = category

        # Progreso
        prog = self.item.get("progress") or {}
        ratio = float(prog.get("ratio", 0.0))
        completed = bool(prog.get("completed", False))

        self.thumb_widget.set_data(
            pixmap=None,
            duration_str=dur_str,
            quality_str=quality_str,
            progress_ratio=ratio,
            is_completed=completed,
        )
        layout.addWidget(self.thumb_widget, alignment=Qt.AlignmentFlag.AlignCenter)

        # 2. Fila de Título y Botón de 3 puntitos verticales (⋮)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 2, 0, 0)
        title_row.setSpacing(4)

        title_text = self.item.get("title", "Video descargado")
        self.title_label = QLabel(self)
        self.title_label.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        self.title_label.setToolTip(title_text)
        self.title_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.title_label.setStyleSheet("color: palette(text); line-height: 1.2;")

        # Elidir texto en 2 líneas
        fm = QFontMetrics(self.title_label.font())
        elided = fm.elidedText(title_text, Qt.TextElideMode.ElideRight, 195 * 2 - 8)
        self.title_label.setText(elided)
        self.title_label.setWordWrap(True)
        self.title_label.setFixedHeight(34)
        self.title_label.mousePressEvent = self._on_title_mouse_press
        title_row.addWidget(self.title_label, stretch=1)

        # Botón de 3 puntitos estilo YouTube
        self.more_btn = TransparentToolButton(FIF.MORE, self)
        self.more_btn.setFixedSize(24, 24)
        self.more_btn.setToolTip("Más opciones")
        self.more_btn.clicked.connect(self._on_more_clicked)
        title_row.addWidget(self.more_btn, alignment=Qt.AlignmentFlag.AlignTop)

        layout.addLayout(title_row)

        # 3. Fila de Canal
        channel_name = self.item.get("uploader") or self.item.get("channel") or "YouTube"
        self.channel_btn = QLabel(channel_name, self)
        self.channel_btn.setFont(QFont("Segoe UI", 8))
        self.channel_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.channel_btn.setStyleSheet("color: #888888; text-decoration: none;")
        self.channel_btn.mousePressEvent = lambda e: self.channel_clicked.emit(channel_name)
        layout.addWidget(self.channel_btn)

        # 4. Fila de Duración y Fecha (DD/MM/AAAA - sin peso en MB)
        raw_date = self.item.get("upload_date") or self.item.get("iso_date") or ""
        date_formatted = _format_date_ddmmyyyy(raw_date)

        if dur_str and date_formatted:
            info_sub = f"{dur_str}  •  {date_formatted}"
        elif dur_str:
            info_sub = dur_str
        else:
            info_sub = date_formatted

        self.meta_label = CaptionLabel(info_sub, self)
        self.meta_label.setStyleSheet("color: #777777;")
        layout.addWidget(self.meta_label)

    def _on_title_mouse_press(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_play()
        else:
            super(QLabel, self.title_label).mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_play()
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        """Despliega el menú contextual al hacer clic derecho en cualquier parte de la tarjeta."""
        self._show_context_menu(event.globalPos())

    def _on_more_clicked(self):
        """Despliega el menú contextual justo debajo del botón de 3 puntitos."""
        pos = self.more_btn.mapToGlobal(QPoint(0, self.more_btn.height()))
        self._show_context_menu(pos)

    def _show_context_menu(self, pos: QPoint):
        menu = RoundMenu(parent=self)

        act_play = Action(FIF.PLAY, "Reproducir", parent=menu)
        act_play.triggered.connect(self._on_play)
        menu.addAction(act_play)

        act_ext = Action(FIF.APPLICATION, "Abrir en reproductor externo", parent=menu)
        act_ext.triggered.connect(self._on_open_external)
        menu.addAction(act_ext)

        act_folder = Action(FIF.FOLDER, "Mostrar en carpeta", parent=menu)
        act_folder.triggered.connect(self._on_open_folder)
        menu.addAction(act_folder)

        menu.exec(pos)

    def _load_thumbnail(self):
        self.loader_thread = ThumbnailLoaderThread(self.item, parent=None)
        self.loader_thread.pixmap_ready.connect(self._on_pixmap_ready)
        self.loader_thread.finished.connect(self.loader_thread.deleteLater)
        self.loader_thread.start()

    def _on_pixmap_ready(self, pixmap: QPixmap):
        if hasattr(self, "thumb_widget") and self.thumb_widget is not None:
            self.thumb_widget.set_pixmap(pixmap)

    def _stop_loader(self):
        """Detiene el hilo de carga de miniatura de forma segura."""
        if self.loader_thread is not None:
            try:
                self.loader_thread.cancel()
                if self.loader_thread.isRunning():
                    self.loader_thread.quit()
                    self.loader_thread.wait(150)
            except Exception:
                pass

    def closeEvent(self, event):
        self._stop_loader()
        super().closeEvent(event)

    def update_progress(self, ratio: float, completed: bool = False):
        """Actualiza dinámicamente la barra de progreso sin recargar toda la tarjeta."""
        self.thumb_widget.set_progress(ratio, completed)

    def _on_play(self):
        self.play_clicked.emit(self.item)

    def _on_open_external(self):
        filepath = self.item.get("filepath", "")
        if filepath and os.path.isfile(filepath):
            open_file(filepath)

    def _on_open_folder(self):
        filepath = self.item.get("filepath", "")
        if filepath:
            open_in_explorer(filepath)
            self.open_folder_clicked.emit(filepath)


class ChannelSidebarItem(QWidget):
    """Elemento interactivo para un Canal o Playlist en el panel lateral."""

    clicked = pyqtSignal(str)

    def __init__(self, name: str, count: int = 0, is_playlist: bool = False, parent=None):
        super().__init__(parent)
        self.name = name
        self.count = count
        self.is_playlist = is_playlist
        self.is_selected: bool = False
        self.is_hovered: bool = False

        self.setFixedHeight(36)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(8)

        # Avatar circular o icono
        self.avatar_label = QLabel(self)
        self.avatar_label.setFixedSize(26, 26)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if self.is_playlist:
            self.avatar_label.setText("📁")
            self.avatar_label.setStyleSheet("background-color: #2b3b4d; border-radius: 13px; font-size: 12px;")
        else:
            initials = _get_channel_initials(self.name)
            bg_color = _get_channel_color(self.name)
            self.avatar_label.setText(initials)
            self.avatar_label.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            self.avatar_label.setStyleSheet(
                f"background-color: {bg_color}; color: white; border-radius: 13px;"
            )
        layout.addWidget(self.avatar_label)

        # Nombre del canal / playlist
        self.name_label = QLabel(self.name, self)
        self.name_label.setFont(QFont("Segoe UI", 9))
        self.name_label.setToolTip(self.name)
        layout.addWidget(self.name_label, stretch=1)

        # Contador de videos
        if self.count > 0:
            self.count_badge = CaptionLabel(str(self.count), self)
            self.count_badge.setStyleSheet(
                "padding: 1px 5px; border-radius: 7px; background-color: rgba(128, 128, 128, 0.18); color: #888888;"
            )
            layout.addWidget(self.count_badge)

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self.update()

    def enterEvent(self, event):
        self.is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.name)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        if self.is_selected:
            painter.fillRect(QRect(0, 0, w, h), QColor(0, 120, 212, 35))
            painter.fillRect(QRect(0, 4, 3, h - 8), QColor("#0078D4"))
        elif self.is_hovered:
            painter.fillRect(QRect(0, 0, w, h), QColor(128, 128, 128, 25))

        painter.end()


class SidebarNavButton(QWidget):
    """Botón de navegación superior de la barra lateral (ej. 'Todos los videos', 'Continuar viendo')."""

    clicked = pyqtSignal(str)

    def __init__(self, key: str, title: str, icon_symbol: str = "🎬", count: int = 0, parent=None):
        super().__init__(parent)
        self.key = key
        self.title = title
        self.count = count
        self.is_selected: bool = False
        self.is_hovered: bool = False

        self.setFixedHeight(34)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._init_ui(icon_symbol)

    def _init_ui(self, icon_symbol: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 10, 3)
        layout.setSpacing(8)

        icon_label = QLabel(icon_symbol, self)
        icon_label.setFont(QFont("Segoe UI", 11))
        layout.addWidget(icon_label)

        self.title_label = QLabel(self.title, self)
        self.title_label.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        layout.addWidget(self.title_label, stretch=1)

        self.count_badge = CaptionLabel("" if self.count == 0 else str(self.count), self)
        self.count_badge.setStyleSheet(
            "padding: 1px 5px; border-radius: 7px; background-color: rgba(128, 128, 128, 0.18); color: #888888;"
        )
        layout.addWidget(self.count_badge)

    def update_count(self, count: int):
        self.count = count
        self.count_badge.setText("" if count == 0 else str(count))

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self.update()

    def enterEvent(self, event):
        self.is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        if self.is_selected:
            painter.fillRect(QRect(0, 0, w, h), QColor(0, 120, 212, 35))
            painter.fillRect(QRect(0, 4, 3, h - 8), QColor("#0078D4"))
        elif self.is_hovered:
            painter.fillRect(QRect(0, 0, w, h), QColor(128, 128, 128, 25))

        painter.end()
