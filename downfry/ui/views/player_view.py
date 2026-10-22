import os
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from PyQt6.QtCore import Qt, QUrl, QTimer, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QMouseEvent, QKeyEvent
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QStackedWidget,
    QScrollArea,
    QSlider,
    QToolTip,
    QDialog,
    QSizePolicy,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from qfluentwidgets import (
    FluentIcon as FIF,
    PushButton,
    TransparentToolButton,
    DropDownPushButton,
    RoundMenu,
    Action,
    Slider,
    BodyLabel,
    CaptionLabel,
    SubtitleLabel,
    StrongBodyLabel,
    SegmentedWidget,
    CardWidget,
    InfoBar,
    InfoBarPosition,
)

from downfry.core.library_manager import playback_progress_manager, offline_library_manager
from downfry.utils.formatting import format_seconds, format_bytes, open_file, open_in_explorer


class ChapterSlider(QSlider):
    """Barra de progreso de tono frío (#00A8E8 -> #00C896) con marcas de capítulos y salto al hacer clic."""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.chapters: List[Dict[str, Any]] = []
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()

    def _apply_style(self):
        self.setStyleSheet("""
            QSlider {
                min-height: 22px;
                background: transparent;
            }
            QSlider::groove:horizontal {
                border: none;
                height: 6px;
                background: rgba(255, 255, 255, 0.18);
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00A8E8, stop:1 #00C896);
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #FFFFFF;
                border: 2px solid #00C896;
                width: 14px;
                height: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover {
                background: #00E5AA;
                border: 2px solid #FFFFFF;
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
        """)

    def set_chapters(self, chapters: List[Dict[str, Any]]):
        self.chapters = chapters or []
        self.update()

    def get_chapter_at_sec(self, sec: float) -> Optional[Dict[str, Any]]:
        if not self.chapters:
            return None
        for i, ch in enumerate(self.chapters):
            start = ch.get("start_time", 0.0)
            end = ch.get("end_time", float("inf"))
            if i + 1 < len(self.chapters):
                next_start = self.chapters[i + 1].get("start_time", float("inf"))
                if start <= sec < next_start:
                    return ch
            elif start <= sec:
                return ch
        return None

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            w = self.width()
            if w > 0 and self.maximum() > 0:
                pos_ratio = max(0.0, min(1.0, event.position().x() / w))
                val = int(pos_ratio * self.maximum())
                self.setValue(val)
                self.sliderMoved.emit(val)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        w = self.width()
        if w > 0 and self.maximum() > 0:
            pos_ratio = max(0.0, min(1.0, event.position().x() / w))
            sec = pos_ratio * self.maximum()
            time_str = format_seconds(sec)
            ch = self.get_chapter_at_sec(sec)
            if ch:
                ch_title = ch.get("title", "")
                text = f"{time_str} • 📑 {ch_title}"
            else:
                text = time_str
            QToolTip.showText(event.globalPosition().toPoint(), text, self)
        super().mouseMoveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        # Dibujar marcas sutiles de inicio de capítulo
        if self.chapters and self.maximum() > 0:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(255, 255, 255, 220))
            pen.setWidth(2)
            painter.setPen(pen)

            w = self.width()
            h = self.height()
            max_val = float(self.maximum())
            for ch in self.chapters:
                st = ch.get("start_time", 0.0)
                if 0 < st < max_val:
                    x = int((st / max_val) * w)
                    # Dibujar línea vertical en el track
                    painter.drawLine(x, int(h / 2) - 4, x, int(h / 2) + 4)
            painter.end()


class FloatingVideoDialog(QDialog):
    """Ventana flotante / Pop-out siempre visible."""

    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Downfry - Reproductor Flotante")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.resize(640, 360)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


class PlayerView(QWidget):
    """Reproductor de video integrado con diseño YouTube/VLC, barra fría y panel derecho."""

    progress_updated = pyqtSignal(str, float, float)  # filepath, pos_sec, dur_sec

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PlayerView")

        self.current_item: Dict[str, Any] = {}
        self.current_filepath: str = ""
        self.current_video_id: str = ""
        self.current_title: str = ""
        self.queue: List[Dict[str, Any]] = []
        self.queue_index: int = -1
        self.chapters: List[Dict[str, Any]] = []
        self._is_floating: bool = False
        self._is_fullscreen: bool = False
        self._pending_resume_sec: float = 0.0

        self._init_player()
        self._init_ui()
        self._init_progress_timer()

    def _init_player(self):
        self.media_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.video_widget = QVideoWidget(self)
        self.video_widget.setStyleSheet("background-color: #000000; border-radius: 8px;")
        self.media_player.setVideoOutput(self.video_widget)

        self.media_player.positionChanged.connect(self._on_position_changed)
        self.media_player.durationChanged.connect(self._on_duration_changed)
        self.media_player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.media_player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.media_player.tracksChanged.connect(self._on_tracks_changed)

        self.floating_dialog: Optional[FloatingVideoDialog] = None

    def _init_progress_timer(self):
        # Guarda progreso cada 3 segundos en segundo plano
        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(3000)
        self.progress_timer.timeout.connect(self._save_current_progress)
        self.progress_timer.start()

    def _init_ui(self):
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(16, 16, 16, 16)
        self.main_layout.setSpacing(12)

        # ------------------ COLUMNA IZQUIERDA: VIDEO Y CONTROLES ------------------
        self.video_column = QWidget(self)
        self.video_col_layout = QVBoxLayout(self.video_column)
        self.video_col_layout.setContentsMargins(0, 0, 0, 0)
        self.video_col_layout.setSpacing(8)

        # Contenedor de video y banner de reanudación
        self.video_container = QWidget(self.video_column)
        self.video_container_layout = QVBoxLayout(self.video_container)
        self.video_container_layout.setContentsMargins(0, 0, 0, 0)
        self.video_container_layout.setSpacing(0)
        self.video_container_layout.addWidget(self.video_widget, stretch=1)

        # Banner flotante para aviso de reanudación estilo VLC
        self.resume_banner = QWidget(self.video_container)
        self.resume_banner.setStyleSheet("""
            QWidget {
                background: rgba(16, 24, 32, 0.88);
                border: 1px solid #00C896;
                border-radius: 6px;
            }
        """)
        rb_layout = QHBoxLayout(self.resume_banner)
        rb_layout.setContentsMargins(12, 6, 12, 6)
        rb_layout.setSpacing(10)
        self.resume_label = CaptionLabel("Reanudado en 00:00", self.resume_banner)
        self.resume_label.setStyleSheet("color: #FFFFFF; font-weight: bold;")
        self.restart_btn = PushButton("Desde el inicio", self.resume_banner)
        self.restart_btn.clicked.connect(self._restart_from_beginning)
        rb_layout.addWidget(self.resume_label)
        rb_layout.addWidget(self.restart_btn)
        rb_layout.addStretch()
        self.resume_banner.hide()
        self.video_container_layout.addWidget(self.resume_banner)

        self.video_col_layout.addWidget(self.video_container, stretch=1)

        # ------------------ BARRA INFERIOR DE CONTROLES ------------------
        self.controls_widget = CardWidget(self.video_column)
        controls_layout = QVBoxLayout(self.controls_widget)
        controls_layout.setContentsMargins(12, 8, 12, 8)
        controls_layout.setSpacing(6)

        # Fila 1: Barra de progreso en tonos fríos
        self.slider = ChapterSlider(self.controls_widget)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        controls_layout.addWidget(self.slider)

        # Fila 2: Botones y etiquetas
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        # Play / Pause
        self.play_btn = TransparentToolButton(FIF.PLAY, self.controls_widget)
        self.play_btn.setToolTip("Reproducir / Pausar (Espacio o K)")
        self.play_btn.clicked.connect(self._toggle_playback)
        btn_row.addWidget(self.play_btn)

        # Anterior / Siguiente
        self.prev_btn = TransparentToolButton(FIF.SKIP_BACK, self.controls_widget)
        self.prev_btn.setToolTip("Video anterior")
        self.prev_btn.clicked.connect(self._play_previous)
        btn_row.addWidget(self.prev_btn)

        self.next_btn = TransparentToolButton(FIF.SKIP_FORWARD, self.controls_widget)
        self.next_btn.setToolTip("Siguiente video")
        self.next_btn.clicked.connect(self._play_next)
        btn_row.addWidget(self.next_btn)

        # -10s / +10s
        self.rewind_btn = TransparentToolButton(FIF.HISTORY, self.controls_widget)
        self.rewind_btn.setToolTip("Retroceder 10s (J o ←)")
        self.rewind_btn.clicked.connect(lambda: self._seek_relative(-10))
        btn_row.addWidget(self.rewind_btn)

        self.forward_btn = TransparentToolButton(FIF.CHEVRON_RIGHT, self.controls_widget)
        self.forward_btn.setToolTip("Avanzar 10s (L o →)")
        self.forward_btn.clicked.connect(lambda: self._seek_relative(10))
        btn_row.addWidget(self.forward_btn)

        # Tiempo transcurrido / Total
        self.time_label = CaptionLabel("00:00 / 00:00", self.controls_widget)
        self.time_label.setStyleSheet("color: #D0D0D0; font-family: monospace; font-size: 13px;")
        btn_row.addWidget(self.time_label)

        # Título del capítulo actual
        self.chapter_label = CaptionLabel("", self.controls_widget)
        self.chapter_label.setStyleSheet("color: #00C896; font-weight: bold; margin-left: 8px;")
        btn_row.addWidget(self.chapter_label, stretch=1)

        # Control de Volumen
        self.mute_btn = TransparentToolButton(FIF.VOLUME, self.controls_widget)
        self.mute_btn.setToolTip("Silenciar (M)")
        self.mute_btn.clicked.connect(self._toggle_mute)
        btn_row.addWidget(self.mute_btn)

        self.volume_slider = Slider(Qt.Orientation.Horizontal, self.controls_widget)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.audio_output.setVolume(0.8)
        self.volume_slider.setFixedWidth(80)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        btn_row.addWidget(self.volume_slider)

        # Selector de Velocidad
        self.speed_btn = DropDownPushButton("1.0x", self.controls_widget)
        self.speed_btn.setFixedWidth(74)
        self.speed_menu = RoundMenu(parent=self.speed_btn)
        for sp in [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]:
            action = Action(f"{sp}x", self.speed_menu)
            action.triggered.connect(lambda checked, s=sp: self._set_playback_rate(s))
            self.speed_menu.addAction(action)
        self.speed_btn.setMenu(self.speed_menu)
        btn_row.addWidget(self.speed_btn)

        # Menú de Subtítulos y Pistas de Audio
        self.sub_btn = TransparentToolButton(FIF.CHAT, self.controls_widget)
        self.sub_btn.setToolTip("Subtítulos")
        self.sub_menu = RoundMenu(parent=self.sub_btn)
        self.sub_btn.clicked.connect(self._show_subtitles_menu)
        btn_row.addWidget(self.sub_btn)

        # Abrir en reproductor externo
        self.vlc_btn = TransparentToolButton(FIF.FOLDER, self.controls_widget)
        self.vlc_btn.setToolTip("Abrir en reproductor externo")
        self.vlc_btn.clicked.connect(self._open_in_external_player)
        btn_row.addWidget(self.vlc_btn)

        # Ventana flotante (Pop-out)
        self.popout_btn = TransparentToolButton(FIF.BACK_TO_WINDOW, self.controls_widget)
        self.popout_btn.setToolTip("Ventana flotante / Pop-out")
        self.popout_btn.clicked.connect(self._toggle_popout)
        btn_row.addWidget(self.popout_btn)

        # Pantalla completa
        self.fullscreen_btn = TransparentToolButton(FIF.FULL_SCREEN, self.controls_widget)
        self.fullscreen_btn.setToolTip("Pantalla completa (F)")
        self.fullscreen_btn.clicked.connect(self._toggle_fullscreen)
        btn_row.addWidget(self.fullscreen_btn)

        # Alternar panel lateral
        self.sidebar_toggle_btn = TransparentToolButton(FIF.MORE, self.controls_widget)
        self.sidebar_toggle_btn.setToolTip("Mostrar / Ocultar panel lateral")
        self.sidebar_toggle_btn.clicked.connect(self._toggle_sidebar)
        btn_row.addWidget(self.sidebar_toggle_btn)

        controls_layout.addLayout(btn_row)
        self.video_col_layout.addWidget(self.controls_widget)

        self.main_layout.addWidget(self.video_column, stretch=3)

        # ------------------ COLUMNA DERECHA: PANEL LATERAL YOUTUBE ------------------
        self.sidebar_widget = CardWidget(self)
        self.sidebar_widget.setFixedWidth(340)
        sidebar_layout = QVBoxLayout(self.sidebar_widget)
        sidebar_layout.setContentsMargins(10, 10, 10, 10)
        sidebar_layout.setSpacing(8)

        # Selector de pestañas
        self.tab_selector = SegmentedWidget(self.sidebar_widget)
        self.tab_selector.addItem("chapters", "📑 Capítulos")
        self.tab_selector.addItem("queue", "📋 Siguientes")
        self.tab_selector.addItem("info", "ℹ️ Información")
        self.tab_selector.setCurrentItem("chapters")
        self.tab_selector.currentItemChanged.connect(self._on_sidebar_tab_changed)
        sidebar_layout.addWidget(self.tab_selector)

        # Stack con las 3 vistas
        self.sidebar_stack = QStackedWidget(self.sidebar_widget)

        # Pestaña 1: Capítulos
        self.chapters_scroll = QScrollArea()
        self.chapters_scroll.setWidgetResizable(True)
        self.chapters_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.chapters_container = QWidget()
        self.chapters_layout = QVBoxLayout(self.chapters_container)
        self.chapters_layout.setContentsMargins(0, 4, 0, 4)
        self.chapters_layout.setSpacing(6)
        self.chapters_scroll.setWidget(self.chapters_container)
        self.sidebar_stack.addWidget(self.chapters_scroll)

        # Pestaña 2: Cola de videos ("Siguientes")
        self.queue_scroll = QScrollArea()
        self.queue_scroll.setWidgetResizable(True)
        self.queue_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.queue_container = QWidget()
        self.queue_layout = QVBoxLayout(self.queue_container)
        self.queue_layout.setContentsMargins(0, 4, 0, 4)
        self.queue_layout.setSpacing(6)
        self.queue_scroll.setWidget(self.queue_container)
        self.sidebar_stack.addWidget(self.queue_scroll)

        # Pestaña 3: Información y Descripción
        self.info_scroll = QScrollArea()
        self.info_scroll.setWidgetResizable(True)
        self.info_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.info_container = QWidget()
        self.info_layout = QVBoxLayout(self.info_container)
        self.info_layout.setContentsMargins(4, 4, 4, 4)
        self.info_layout.setSpacing(8)
        self.info_scroll.setWidget(self.info_container)
        self.sidebar_stack.addWidget(self.info_scroll)

        sidebar_layout.addWidget(self.sidebar_stack, stretch=1)
        self.main_layout.addWidget(self.sidebar_widget, stretch=1)

    # ------------------ MÉTODOS PÚBLICOS OBLIGATORIOS ------------------

    def load_and_play(
        self,
        video_item: Dict[str, Any],
        queue: Optional[List[Dict[str, Any]]] = None,
        resume: bool = True,
    ):
        """Carga y reproduce un video completo con su lista de capítulos, cola y progreso."""
        if not video_item:
            return

        self._save_current_progress()

        self.current_item = video_item
        self.current_filepath = video_item.get("filepath", "")
        self.current_video_id = video_item.get("video_id", "")
        self.current_title = video_item.get("title", "")
        self.chapters = video_item.get("chapters") or []
        if not self.chapters and self.current_filepath and os.path.isfile(self.current_filepath):
            try:
                probed = offline_library_manager.probe_media_details(self.current_filepath)
                if probed.get("chapters"):
                    self.chapters = probed["chapters"]
                    video_item["chapters"] = self.chapters
                if not video_item.get("description") and probed.get("description"):
                    video_item["description"] = probed["description"]
            except Exception as e:
                print(f"[PlayerView] Error extrayendo detalles multimedia: {e}")
        self.slider.set_chapters(self.chapters)

        # Configurar cola
        if queue is not None:
            self.queue = queue
            for idx, q_it in enumerate(self.queue):
                if q_it.get("filepath") == self.current_filepath:
                    self.queue_index = idx
                    break
        elif not self.queue:
            self.queue = [video_item]
            self.queue_index = 0

        # Actualizar pestañas del panel lateral
        self._populate_chapters()
        self._populate_queue()
        self._populate_info()

        # Detener reproducción anterior de forma segura antes de cambiar de archivo
        try:
            self.media_player.stop()
        except Exception:
            pass

        # Cargar archivo en QMediaPlayer
        if not self.current_filepath or not os.path.exists(self.current_filepath):
            InfoBar.warning(
                title="Archivo no encontrado",
                content="El video no existe en el disco o fue movido.",
                position=InfoBarPosition.TOP,
                duration=3500,
                parent=self.window(),
            )
            return

        # Memoria de reanudación diferida (espera a que el backend cargue el medio)
        saved = playback_progress_manager.get_progress(self.current_video_id, self.current_filepath)
        saved_sec = saved.get("position_sec", 0.0)
        is_completed = saved.get("completed", False)

        self._pending_resume_sec = saved_sec if (resume and saved_sec > 3.0 and not is_completed) else 0.0
        self.resume_banner.hide()

        try:
            url = QUrl.fromLocalFile(self.current_filepath)
            self.media_player.setSource(url)
            self.media_player.play()
            self.play_btn.setIcon(FIF.PAUSE)
        except Exception as e:
            print(f"[PlayerView] Error iniciando reproducción: {e}")

    def play_filepath(self, filepath: str, title: str = "", video_id: str = ""):
        """Reproduce directamente una ruta de archivo física."""
        item = {
            "filepath": filepath,
            "title": title or Path(filepath).stem,
            "video_id": video_id,
            "duration": 0,
            "chapters": [],
        }
        self.load_and_play(item)

    def pause_playback(self):
        """Pausa la reproducción y guarda inmediatamente el progreso actual."""
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
            self.play_btn.setIcon(FIF.PLAY)
            self._save_current_progress()

    # ------------------ EVENTOS DE TECLADO Y ATAJOS ------------------

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key in (Qt.Key.Key_Space, Qt.Key.Key_K):
            self._toggle_playback()
            event.accept()
        elif key in (Qt.Key.Key_J, Qt.Key.Key_Left):
            self._seek_relative(-10 if key == Qt.Key.Key_J else -5)
            event.accept()
        elif key in (Qt.Key.Key_L, Qt.Key.Key_Right):
            self._seek_relative(10 if key == Qt.Key.Key_L else 5)
            event.accept()
        elif key == Qt.Key.Key_Up:
            v = min(100, self.volume_slider.value() + 5)
            self.volume_slider.setValue(v)
            event.accept()
        elif key == Qt.Key.Key_Down:
            v = max(0, self.volume_slider.value() - 5)
            self.volume_slider.setValue(v)
            event.accept()
        elif key == Qt.Key.Key_M:
            self._toggle_mute()
            event.accept()
        elif key == Qt.Key.Key_F:
            self._toggle_fullscreen()
            event.accept()
        elif key == Qt.Key.Key_Escape and self._is_fullscreen:
            self._toggle_fullscreen()
            event.accept()
        else:
            super().keyPressEvent(event)

    # ------------------ CONTROL DE REPRODUCCIÓN ------------------

    def _toggle_playback(self):
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
            self.play_btn.setIcon(FIF.PLAY)
            self._save_current_progress()
        else:
            self.media_player.play()
            self.play_btn.setIcon(FIF.PAUSE)

    def _seek_relative(self, seconds: int):
        cur_pos = self.media_player.position()
        new_pos = max(0, cur_pos + (seconds * 1000))
        self.media_player.setPosition(new_pos)

    def _restart_from_beginning(self):
        self.media_player.setPosition(0)
        self.resume_banner.hide()

    def _on_slider_moved(self, val: int):
        self.media_player.setPosition(val * 1000)

    def _on_position_changed(self, pos_ms: int):
        sec = pos_ms / 1000.0
        dur_sec = self.media_player.duration() / 1000.0
        if not self.slider.isSliderDown():
            self.slider.setValue(int(sec))
        self.time_label.setText(f"{format_seconds(sec)} / {format_seconds(dur_sec)}")

        ch = self.slider.get_chapter_at_sec(sec)
        if ch:
            self.chapter_label.setText(f"• 📑 {ch.get('title', '')}")
        else:
            self.chapter_label.setText("")

    def _on_duration_changed(self, dur_ms: int):
        dur_sec = int(dur_ms / 1000.0)
        self.slider.setRange(0, dur_sec)

    def _on_playback_state_changed(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setIcon(FIF.PAUSE)
        else:
            self.play_btn.setIcon(FIF.PLAY)

    def _on_media_status_changed(self, status):
        # Aplicar reanudación cuando el medio esté listo
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            if getattr(self, "_pending_resume_sec", 0.0) > 0:
                try:
                    self.media_player.setPosition(int(self._pending_resume_sec * 1000))
                    self.resume_label.setText(f"Reanudado en {format_seconds(self._pending_resume_sec)}")
                    self.resume_banner.show()
                    QTimer.singleShot(6000, self.resume_banner.hide)
                except Exception as e:
                    print(f"[PlayerView] Error reanudando posición: {e}")
                self._pending_resume_sec = 0.0

        # Al finalizar el video, reproducir automáticamente el siguiente en la cola
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._save_current_progress(force_completed=True)
            self._play_next()

    def _on_volume_changed(self, val: int):
        vol = val / 100.0
        self.audio_output.setVolume(vol)
        if val == 0:
            self.mute_btn.setIcon(FIF.MUTE)
        else:
            self.mute_btn.setIcon(FIF.VOLUME)

    def _toggle_mute(self):
        muted = not self.audio_output.isMuted()
        self.audio_output.setMuted(muted)
        if muted:
            self.mute_btn.setIcon(FIF.MUTE)
        else:
            self.mute_btn.setIcon(FIF.VOLUME)

    def _set_playback_rate(self, rate: float):
        self.media_player.setPlaybackRate(rate)
        self.speed_btn.setText(f"{rate}x")

    def _play_previous(self):
        if self.queue and self.queue_index > 0:
            self.queue_index -= 1
            self.load_and_play(self.queue[self.queue_index], queue=self.queue)

    def _play_next(self):
        if self.queue and self.queue_index + 1 < len(self.queue):
            self.queue_index += 1
            self.load_and_play(self.queue[self.queue_index], queue=self.queue)

    def _save_current_progress(self, force_completed: bool = False):
        if not self.current_filepath:
            return
        pos_sec = self.media_player.position() / 1000.0
        dur_sec = self.media_player.duration() / 1000.0
        if dur_sec <= 0:
            dur_sec = float(self.current_item.get("duration") or 0.0)

        if pos_sec > 0 or force_completed:
            if force_completed:
                pos_sec = dur_sec
            playback_progress_manager.update_progress(
                video_id=self.current_video_id,
                filepath=self.current_filepath,
                position_sec=pos_sec,
                duration_sec=dur_sec,
            )
            self.progress_updated.emit(self.current_filepath, pos_sec, dur_sec)

    # ------------------ MENÚS DE SUBTÍTULOS Y AUDIO ------------------

    def _on_tracks_changed(self):
        pass

    def _show_subtitles_menu(self):
        menu = RoundMenu(parent=self.sub_btn)
        tracks = self.media_player.subtitleTracks()
        active = self.media_player.activeSubtitleTrack()

        # Opción desactivar subtítulos
        act_none = Action("Desactivados", menu)
        act_none.setCheckable(True)
        act_none.setChecked(active == -1)
        act_none.triggered.connect(lambda: self.media_player.setActiveSubtitleTrack(-1))
        menu.addAction(act_none)

        if tracks:
            menu.addSeparator()
            for idx, tr in enumerate(tracks):
                lang = tr.value(tr.Key.Language) or f"Pista {idx + 1}"
                act = Action(str(lang), menu)
                act.setCheckable(True)
                act.setChecked(idx == active)
                act.triggered.connect(lambda checked, i=idx: self.media_player.setActiveSubtitleTrack(i))
                menu.addAction(act)

        menu.exec(self.sub_btn.mapToGlobal(QPoint(0, -menu.sizeHint().height())))

    def _open_in_external_player(self):
        if self.current_filepath and os.path.exists(self.current_filepath):
            self.pause_playback()
            open_file(self.current_filepath)
        else:
            InfoBar.warning(
                title="Archivo no disponible",
                content="No se encuentra el archivo en disco.",
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self.window(),
            )

    # ------------------ VENTANA FLOTANTE Y PANTALLA COMPLETA ------------------

    def _toggle_popout(self):
        if not self._is_floating:
            # Crear y mostrar diálogo flotante
            self.floating_dialog = FloatingVideoDialog(self)
            self.video_container_layout.removeWidget(self.video_widget)
            self.floating_dialog.layout.addWidget(self.video_widget)
            self.floating_dialog.closed.connect(self._dock_back_video)
            self.floating_dialog.show()
            self._is_floating = True
            self.popout_btn.setStyleSheet("color: #00C896;")
        else:
            self._dock_back_video()

    def _dock_back_video(self):
        if self._is_floating and self.floating_dialog:
            self.floating_dialog.layout.removeWidget(self.video_widget)
            self.video_container_layout.insertWidget(0, self.video_widget, stretch=1)
            self.floating_dialog.deleteLater()
            self.floating_dialog = None
            self._is_floating = False
            self.popout_btn.setStyleSheet("")

    def _toggle_fullscreen(self):
        win = self.window()
        if not self._is_fullscreen:
            win.showFullScreen()
            self._is_fullscreen = True
            self.fullscreen_btn.setIcon(FIF.CANCEL)
        else:
            win.showNormal()
            self._is_fullscreen = False
            self.fullscreen_btn.setIcon(FIF.FULL_SCREEN)

    def _toggle_sidebar(self):
        self.sidebar_widget.setVisible(not self.sidebar_widget.isVisible())

    def _on_sidebar_tab_changed(self, tab_key: str):
        if tab_key == "chapters":
            self.sidebar_stack.setCurrentIndex(0)
        elif tab_key == "queue":
            self.sidebar_stack.setCurrentIndex(1)
        elif tab_key == "info":
            self.sidebar_stack.setCurrentIndex(2)

    # ------------------ POBLACIÓN DEL PANEL LATERAL ------------------

    def _populate_chapters(self):
        # Limpiar
        while self.chapters_layout.count() > 0:
            child = self.chapters_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not self.chapters:
            empty_lbl = CaptionLabel("No hay capítulos disponibles para este video.", self.chapters_container)
            empty_lbl.setStyleSheet("color: #888888; padding: 20px;")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.chapters_layout.addWidget(empty_lbl)
            self.chapters_layout.addStretch()
            return

        for ch in self.chapters:
            title = ch.get("title", "Capítulo")
            st = ch.get("start_time", 0.0)

            card = CardWidget(self.chapters_container)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            c_layout = QHBoxLayout(card)
            c_layout.setContentsMargins(10, 8, 10, 8)
            c_layout.setSpacing(10)

            time_badge = StrongBodyLabel(format_seconds(st), card)
            time_badge.setStyleSheet("color: #00C896; font-family: monospace;")
            title_lbl = BodyLabel(title, card)
            title_lbl.setWordWrap(True)

            c_layout.addWidget(time_badge)
            c_layout.addWidget(title_lbl, stretch=1)

            # Salto al hacer clic
            card.mousePressEvent = lambda e, sec=st: self.media_player.setPosition(int(sec * 1000))
            self.chapters_layout.addWidget(card)

        self.chapters_layout.addStretch()

    def _populate_queue(self):
        while self.queue_layout.count() > 0:
            child = self.queue_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not self.queue:
            empty_lbl = CaptionLabel("La cola de reproducción está vacía.", self.queue_container)
            empty_lbl.setStyleSheet("color: #888888; padding: 20px;")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.queue_layout.addWidget(empty_lbl)
            self.queue_layout.addStretch()
            return

        for idx, it in enumerate(self.queue):
            is_current = (idx == self.queue_index)
            card = CardWidget(self.queue_container)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            if is_current:
                card.setStyleSheet("CardWidget { border: 1.5px solid #00C896; background: rgba(0, 200, 150, 0.08); }")

            c_layout = QVBoxLayout(card)
            c_layout.setContentsMargins(10, 8, 10, 8)
            c_layout.setSpacing(4)

            top_row = QHBoxLayout()
            title_text = it.get("title") or Path(it.get("filepath", "")).stem
            title_lbl = BodyLabel(title_text, card)
            title_lbl.setStyleSheet("font-weight: bold;" if is_current else "")
            title_lbl.setWordWrap(True)
            top_row.addWidget(title_lbl, stretch=1)

            if is_current:
                badge = CaptionLabel("▶ Ahora", card)
                badge.setStyleSheet("color: #00C896; font-weight: bold;")
                top_row.addWidget(badge)

            c_layout.addLayout(top_row)

            sub_row = QHBoxLayout()
            channel_lbl = CaptionLabel(it.get("channel") or it.get("uploader") or "YouTube", card)
            channel_lbl.setStyleSheet("color: #888888;")
            dur_lbl = CaptionLabel(format_seconds(it.get("duration")), card)
            dur_lbl.setStyleSheet("color: #888888;")
            sub_row.addWidget(channel_lbl)
            sub_row.addStretch()
            sub_row.addWidget(dur_lbl)
            c_layout.addLayout(sub_row)

            card.mousePressEvent = lambda e, index=idx: self._select_queue_item(index)
            self.queue_layout.addWidget(card)

        self.queue_layout.addStretch()

    def _select_queue_item(self, index: int):
        if 0 <= index < len(self.queue):
            self.queue_index = index
            self.load_and_play(self.queue[index], queue=self.queue)

    def _populate_info(self):
        while self.info_layout.count() > 0:
            child = self.info_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        it = self.current_item or {}
        title_lbl = SubtitleLabel(it.get("title") or "Video", self.info_container)
        title_lbl.setWordWrap(True)
        self.info_layout.addWidget(title_lbl)

        # Metadatos en tarjeta
        meta_card = CardWidget(self.info_container)
        mc_layout = QVBoxLayout(meta_card)
        mc_layout.setContentsMargins(12, 10, 12, 10)
        mc_layout.setSpacing(6)

        channel_lbl = BodyLabel(f"Canal: {it.get('channel') or it.get('uploader') or 'YouTube'}", meta_card)
        channel_lbl.setStyleSheet("font-weight: bold;")
        date_lbl = CaptionLabel(f"Publicado: {it.get('iso_date') or it.get('upload_date') or '--'}", meta_card)
        quality_lbl = CaptionLabel(f"Calidad: {it.get('quality') or 'Auto'}  •  Tamaño: {it.get('size_str') or '--'}", meta_card)

        mc_layout.addWidget(channel_lbl)
        mc_layout.addWidget(date_lbl)
        mc_layout.addWidget(quality_lbl)

        # Botón para ver en explorador
        fp = it.get("filepath", "")
        if fp:
            open_folder_btn = PushButton(FIF.FOLDER, "Ver en explorador", meta_card)
            open_folder_btn.clicked.connect(lambda: open_in_explorer(fp))
            mc_layout.addWidget(open_folder_btn)

        self.info_layout.addWidget(meta_card)

        # Descripción
        desc = it.get("description", "").strip()
        if desc:
            desc_header = StrongBodyLabel("Descripción:", self.info_container)
            self.info_layout.addWidget(desc_header)

            desc_lbl = CaptionLabel(desc, self.info_container)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet("color: #CCCCCC; line-height: 1.4;")
            desc_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.info_layout.addWidget(desc_lbl)

        self.info_layout.addStretch()
