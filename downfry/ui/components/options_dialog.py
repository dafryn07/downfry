from typing import Dict, Any
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFileDialog,
    QStackedWidget,
)
from qfluentwidgets import (
    MessageBoxBase,
    SubtitleLabel,
    BodyLabel,
    CaptionLabel,
    SegmentedWidget,
    ComboBox,
    CheckBox,
    LineEdit,
    PushButton,
    CardWidget,
    FluentIcon as FIF,
)
from downfry.config import config_manager


class DownloadOptionsDialog(MessageBoxBase):
    """Diálogo estilo Seal con cálculo exacto por pestaña y selector Video Único vs Playlist."""

    def __init__(self, data: Dict[str, Any], parent=None):
        super().__init__(parent=parent)
        self.data = data
        self.content_type = data.get("type", "video")
        self.is_channel = self.content_type == "channel"
        self.is_playlist = data.get("is_playlist", False)
        self.has_playlist = data.get("has_playlist", False)
        self.available_resolutions = data.get("resolutions", [])
        self.tab_counts = data.get("tab_counts", {})
        self.tab_sizes = data.get("tab_sizes", {})
        self.detected_tab = data.get("detected_tab", "all")

        self.widget.setMinimumWidth(550)
        self.yesButton.setText("Iniciar Descarga")
        self.cancelButton.setText("Cancelar")
        self.current_mode = "video"

        self._init_ui()

    def _init_ui(self):
        title_label = SubtitleLabel("Opciones de Descarga", self)
        self.viewLayout.addWidget(title_label)

        # Opción estilo Seal cuando el enlace es un video dentro de una Playlist
        self.playlist_scope_combo = None
        if self.has_playlist and not self.is_playlist and not self.is_channel:
            scope_card = CardWidget(self)
            sc_l = QHBoxLayout(scope_card)
            sc_l.setContentsMargins(12, 8, 12, 8)
            sc_lbl = BodyLabel("📑 Este enlace incluye una Playlist:", scope_card)
            self.playlist_scope_combo = ComboBox(scope_card)
            self.playlist_scope_combo.addItem("🎬 Descargar solo este video", userData="single")
            self.playlist_scope_combo.addItem("📑 Descargar la Playlist completa", userData="playlist")
            sc_l.addWidget(sc_lbl)
            sc_l.addWidget(self.playlist_scope_combo, stretch=1)
            self.viewLayout.addWidget(scope_card)

        # Selector Video vs Audio
        self.mode_segmented = SegmentedWidget(self)
        self.mode_segmented.addItem("video", "🎬 Video (MP4)")
        self.mode_segmented.addItem("audio", "🎵 Solo Audio")
        self.mode_segmented.setCurrentItem("video")
        self.mode_segmented.currentItemChanged.connect(self._on_mode_changed)
        self.viewLayout.addWidget(self.mode_segmented)

        self.stack = QStackedWidget(self)

        # --- Página Video ---
        video_page = QWidget()
        v_layout = QVBoxLayout(video_page)
        v_layout.setContentsMargins(0, 8, 0, 8)
        v_layout.setSpacing(10)

        res_box = QHBoxLayout()
        res_label = BodyLabel("Calidad de video:", video_page)
        self.res_combo = ComboBox(video_page)

        max_res_hint = self.data.get("max_resolution", "")
        best_label = (
            f"Mejor calidad disponible (Auto {max_res_hint})"
            if max_res_hint
            else "Mejor calidad disponible (Automática 4K/1080p/720p)"
        )
        self.res_combo.addItem(best_label, userData="best")

        standard_res = [2160, 1440, 1080, 720, 480, 360, 240, 144]
        res_to_show = [r for r in standard_res if not self.available_resolutions or r in self.available_resolutions]
        if not res_to_show:
            res_to_show = standard_res

        for r in res_to_show:
            suffix = "(4K)" if r == 2160 else "(2K QHD)" if r == 1440 else "(Full HD)" if r == 1080 else "(HD)" if r == 720 else ""
            self.res_combo.addItem(f"Hasta {r}p {suffix}".strip(), userData=f"{r}p")

        default_q = config_manager.get("default_video_quality", "best")
        idx = self.res_combo.findData(default_q)
        if idx >= 0:
            self.res_combo.setCurrentIndex(idx)

        res_box.addWidget(res_label)
        res_box.addWidget(self.res_combo, stretch=1)
        v_layout.addLayout(res_box)

        self.subtitles_check = CheckBox("Incrustar subtítulos automáticos (Español / Inglés)", video_page)
        self.subtitles_check.setChecked(config_manager.get("embed_subtitles", True))
        v_layout.addWidget(self.subtitles_check)

        self.stack.addWidget(video_page)

        # --- Página Audio ---
        audio_page = QWidget()
        a_layout = QVBoxLayout(audio_page)
        a_layout.setContentsMargins(0, 8, 0, 8)
        a_layout.setSpacing(10)

        format_box = QHBoxLayout()
        fmt_label = BodyLabel("Formato:", audio_page)
        self.audio_format_combo = ComboBox(audio_page)
        for fmt in ["mp3", "m4a", "opus", "flac", "wav"]:
            self.audio_format_combo.addItem(fmt.upper(), userData=fmt)
        def_fmt = config_manager.get("default_audio_format", "mp3")
        idx_fmt = self.audio_format_combo.findData(def_fmt)
        if idx_fmt >= 0:
            self.audio_format_combo.setCurrentIndex(idx_fmt)
        format_box.addWidget(fmt_label)
        format_box.addWidget(self.audio_format_combo, stretch=1)
        a_layout.addLayout(format_box)

        bitrate_box = QHBoxLayout()
        bit_label = BodyLabel("Tasa de bits (Calidad):", audio_page)
        self.audio_bitrate_combo = ComboBox(audio_page)
        self.audio_bitrate_combo.addItem("320 kbps (Máxima calidad)", userData="320")
        self.audio_bitrate_combo.addItem("256 kbps (Muy alta)", userData="256")
        self.audio_bitrate_combo.addItem("192 kbps (Estándar recomendada)", userData="192")
        self.audio_bitrate_combo.addItem("128 kbps (Ligero)", userData="128")
        def_bit = config_manager.get("default_audio_bitrate", "320")
        idx_bit = self.audio_bitrate_combo.findData(def_bit)
        if idx_bit >= 0:
            self.audio_bitrate_combo.setCurrentIndex(idx_bit)
        bitrate_box.addWidget(bit_label)
        bitrate_box.addWidget(self.audio_bitrate_combo, stretch=1)
        a_layout.addLayout(bitrate_box)

        self.stack.addWidget(audio_page)
        self.viewLayout.addWidget(self.stack)

        self.thumb_check = CheckBox("Incrustar miniatura / carátula oficial", self)
        self.thumb_check.setChecked(config_manager.get("embed_thumbnail", True))
        self.viewLayout.addWidget(self.thumb_check)

        ch_count = self.data.get("chapters_count", 0)
        ch_label = f"Incrustar {ch_count} capítulos y metadatos (VLC / Reproductor)" if ch_count > 0 else "Incrustar capítulos y metadatos (Creador, fecha, VLC)"
        self.chk_chapters = CheckBox(ch_label, self)
        self.chk_chapters.setChecked(config_manager.get("embed_chapters", True) and config_manager.get("embed_metadata", True))
        self.viewLayout.addWidget(self.chk_chapters)

        speed_box = QHBoxLayout()
        speed_lbl = BodyLabel("Límite de velocidad:", self)
        self.speed_val_input = LineEdit(self)
        self.speed_val_input.setPlaceholderText("0 (Sin límite)")
        self.speed_val_input.setFixedWidth(120)
        curr_spd = config_manager.get("speed_limit_value", 0)
        self.speed_val_input.setText(str(curr_spd) if curr_spd else "")

        self.speed_unit_combo = ComboBox(self)
        self.speed_unit_combo.setFixedWidth(100)
        for u in ["KB/s", "MB/s", "KiB/s", "MiB/s"]:
            self.speed_unit_combo.addItem(u, userData=u)
        curr_unit = config_manager.get("speed_limit_unit", "MB/s")
        idx_u = self.speed_unit_combo.findData(curr_unit)
        if idx_u >= 0:
            self.speed_unit_combo.setCurrentIndex(idx_u)

        speed_box.addWidget(speed_lbl)
        speed_box.addWidget(self.speed_val_input)
        speed_box.addWidget(self.speed_unit_combo)
        speed_box.addStretch()
        self.viewLayout.addLayout(speed_box)

        # Sección de pestañas de Canal (Videos, Shorts, Directos)
        if self.is_channel:
            channel_card = CardWidget(self)
            cc_layout = QVBoxLayout(channel_card)
            cc_layout.setContentsMargins(14, 12, 14, 12)
            cc_layout.setSpacing(8)

            tab_header = BodyLabel("📺 Pestañas del canal a descargar (elige 1, 2 o las 3):", channel_card)
            tab_header.setStyleSheet("font-weight: bold;")
            cc_layout.addWidget(tab_header)

            info_org = CaptionLabel("📁 Se guardarán en: Canal / Año / Mes / [Videos | Shorts | Directos]", channel_card)
            info_org.setStyleSheet("color: #0078D4; font-weight: 500;")
            cc_layout.addWidget(info_org)

            v_count = self.tab_counts.get("videos", 0)
            s_count = self.tab_counts.get("shorts", 0)
            l_count = self.tab_counts.get("lives", 0)

            v_txt = f"🎬 Videos ({v_count})" if v_count else "🎬 Videos"
            s_txt = f"⚡ Shorts ({s_count})" if s_count else "⚡ Shorts"
            l_txt = f"🔴 Directos ({l_count})" if l_count else "🔴 Directos"

            filters_box = QHBoxLayout()
            self.ch_videos_check = CheckBox(v_txt, channel_card)
            self.ch_shorts_check = CheckBox(s_txt, channel_card)
            self.ch_lives_check = CheckBox(l_txt, channel_card)

            if self.detected_tab == "shorts":
                self.ch_videos_check.setChecked(False)
                self.ch_shorts_check.setChecked(True)
                self.ch_lives_check.setChecked(False)
            elif self.detected_tab in ("streams", "live"):
                self.ch_videos_check.setChecked(False)
                self.ch_shorts_check.setChecked(False)
                self.ch_lives_check.setChecked(True)
            elif self.detected_tab == "videos":
                self.ch_videos_check.setChecked(True)
                self.ch_shorts_check.setChecked(False)
                self.ch_lives_check.setChecked(False)
            else:
                self.ch_videos_check.setChecked(config_manager.get("channel_download_videos", True))
                self.ch_shorts_check.setChecked(config_manager.get("channel_download_shorts", True))
                self.ch_lives_check.setChecked(config_manager.get("channel_download_lives", True))

            filters_box.addWidget(self.ch_videos_check)
            filters_box.addWidget(self.ch_shorts_check)
            filters_box.addWidget(self.ch_lives_check)
            cc_layout.addLayout(filters_box)

            self.channel_warn_label = CaptionLabel("⚠️ Selecciona al menos una pestaña para iniciar.", channel_card)
            self.channel_warn_label.setStyleSheet("color: #D83B01; font-weight: bold;")
            self.channel_warn_label.setVisible(False)
            cc_layout.addWidget(self.channel_warn_label)

            self.viewLayout.addWidget(channel_card)

        # Carpeta de Destino
        dir_label = BodyLabel("Carpeta de destino:", self)
        self.viewLayout.addWidget(dir_label)

        dir_box = QHBoxLayout()
        self.dir_input = LineEdit(self)
        self.dir_input.setText(config_manager.get("download_dir", str(Path.home() / "Downloads" / "Downfry")))
        self.dir_input.setReadOnly(True)

        self.browse_btn = PushButton(FIF.FOLDER, "Examinar...", self)
        self.browse_btn.clicked.connect(self._on_browse_folder)

        dir_box.addWidget(self.dir_input, stretch=1)
        dir_box.addWidget(self.browse_btn)
        self.viewLayout.addLayout(dir_box)

        # Tarjeta de Tamaño Estimado
        self.size_card = CardWidget(self)
        sc_layout = QHBoxLayout(self.size_card)
        sc_layout.setContentsMargins(14, 10, 14, 10)

        left_size = QVBoxLayout()
        self.size_title = BodyLabel("💾 Tamaño estimado de descarga:", self.size_card)
        self.size_val = SubtitleLabel("Calculando...", self.size_card)
        self.size_val.setStyleSheet("color: #0078D4; font-weight: bold;")
        left_size.addWidget(self.size_title)
        left_size.addWidget(self.size_val)
        sc_layout.addLayout(left_size, stretch=1)

        right_disk = QVBoxLayout()
        self.disk_free_label = CaptionLabel("Espacio libre en disco: Calculando...", self.size_card)
        self.disk_free_label.setStyleSheet("color: #888888;")
        right_disk.addWidget(self.disk_free_label, alignment=Qt.AlignmentFlag.AlignRight)
        sc_layout.addLayout(right_disk)

        self.viewLayout.addWidget(self.size_card)

        self.res_combo.currentIndexChanged.connect(self._update_estimated_size)
        self.audio_bitrate_combo.currentIndexChanged.connect(self._update_estimated_size)
        if self.is_channel:
            self.ch_videos_check.stateChanged.connect(self._on_channel_tabs_changed)
            self.ch_shorts_check.stateChanged.connect(self._on_channel_tabs_changed)
            self.ch_lives_check.stateChanged.connect(self._on_channel_tabs_changed)

        self._update_estimated_size()

    def _on_channel_tabs_changed(self):
        any_selected = (
            self.ch_videos_check.isChecked()
            or self.ch_shorts_check.isChecked()
            or self.ch_lives_check.isChecked()
        )
        self.yesButton.setEnabled(any_selected)
        self.channel_warn_label.setVisible(not any_selected)
        self._update_estimated_size()

    def _update_estimated_size(self):
        """Calcula el peso sumando únicamente las bolsas de las pestañas seleccionadas."""
        import shutil
        from downfry.utils.formatting import format_bytes

        mode = self.current_mode
        est_sizes = self.data.get("estimated_sizes", {})
        duration = self.data.get("duration", 0)
        total_bytes = 0

        if self.is_channel:
            # Sumar únicamente los bytes reales estimados de cada categoría marcada
            base_total = 0
            if self.ch_videos_check.isChecked():
                base_total += self.tab_sizes.get("videos", 0)
            if self.ch_shorts_check.isChecked():
                base_total += self.tab_sizes.get("shorts", 0)
            if self.ch_lives_check.isChecked():
                base_total += self.tab_sizes.get("lives", 0)

            # Si el usuario pegó directamente /@canal/shorts y tab_sizes vino en 0, estimar suave
            if base_total == 0 and (self.ch_videos_check.isChecked() or self.ch_shorts_check.isChecked() or self.ch_lives_check.isChecked()):
                if self.ch_shorts_check.isChecked() and not self.ch_videos_check.isChecked() and not self.ch_lives_check.isChecked():
                    base_total = max(1, self.data.get("item_count", 8)) * (6 * 1024 * 1024)
                else:
                    base_total = est_sizes.get("best", 0)

            total_bytes = self._apply_quality_multiplier(base_total, mode)

        elif self.is_playlist:
            base_total = est_sizes.get("best", 0) or (self.data.get("item_count", 1) * 45 * 1024 * 1024)
            total_bytes = self._apply_quality_multiplier(base_total, mode)

        else:
            if mode == "audio":
                bitrate = int(self.audio_bitrate_combo.currentData() or 320)
                total_bytes = int(duration * bitrate * 1000 / 8) if duration else est_sizes.get("audio", 5 * 1024 * 1024)
            else:
                res_key = self.res_combo.currentData()
                if res_key in est_sizes:
                    total_bytes = est_sizes[res_key]
                elif "best" in est_sizes:
                    total_bytes = est_sizes["best"]
                else:
                    total_bytes = int(duration * 2200 * 1000 / 8) if duration else 20 * 1024 * 1024

        if total_bytes > 0:
            self.size_val.setText(f"~ {format_bytes(total_bytes)}")
        else:
            self.size_val.setText("0.0 MB" if self.is_channel else "Calculando...")

        try:
            target_path = Path(self.dir_input.text()).resolve()
            drive = target_path.anchor or str(target_path)
            usage = shutil.disk_usage(drive)
            self.disk_free_label.setText(f"Espacio libre en disco: {format_bytes(usage.free)}")
        except Exception:
            self.disk_free_label.setText("Espacio libre en disco: Disponible")

    def _apply_quality_multiplier(self, base_bytes: int, mode: str) -> int:
        if mode == "audio":
            bitrate = int(self.audio_bitrate_combo.currentData() or 320)
            return int(base_bytes * (bitrate / 320.0) * 0.14)
        res_key = self.res_combo.currentData()
        if res_key == "720p":
            return int(base_bytes * 0.6)
        if res_key == "480p":
            return int(base_bytes * 0.35)
        if res_key in ("360p", "240p", "144p"):
            return int(base_bytes * 0.2)
        if res_key in ("1440p", "2160p"):
            return int(base_bytes * 1.7)
        return base_bytes

    def _on_mode_changed(self, item_key: str):
        self.current_mode = str(item_key)
        self.stack.setCurrentIndex(0 if item_key == "video" else 1)
        self._update_estimated_size()

    def _on_browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de descarga", self.dir_input.text())
        if folder:
            self.dir_input.setText(folder)
            config_manager.set("download_dir", folder)
            self._update_estimated_size()

    def get_options(self) -> Dict[str, Any]:
        mode = self.current_mode
        options: Dict[str, Any] = {
            "mode": mode,
            "target_dir": self.dir_input.text(),
            "embed_thumbnail": self.thumb_check.isChecked(),
            "embed_chapters": self.chk_chapters.isChecked(),
            "embed_metadata": self.chk_chapters.isChecked(),
            "preserve_publish_date": config_manager.get("preserve_publish_date", True),
            "download_playlist_scope": (
                self.playlist_scope_combo.currentData() if self.playlist_scope_combo else "single"
            ),
        }
        try:
            sp_text = self.speed_val_input.text().strip().replace(",", ".")
            sp_val = float(sp_text) if sp_text else 0
            if sp_val < 0:
                sp_val = 0
        except ValueError:
            sp_val = 0
        sp_unit = self.speed_unit_combo.currentData() or "MB/s"
        options["speed_limit_value"] = sp_val
        options["speed_limit_unit"] = sp_unit

        config_manager.set("embed_chapters", self.chk_chapters.isChecked())
        config_manager.set("embed_metadata", self.chk_chapters.isChecked())
        config_manager.set("speed_limit_value", sp_val)
        config_manager.set("speed_limit_unit", sp_unit)

        if mode == "video":
            options["quality"] = self.res_combo.currentData() or "best"
            options["embed_subtitles"] = self.subtitles_check.isChecked()
            config_manager.set("default_video_quality", options["quality"])
        else:
            options["audio_format"] = self.audio_format_combo.currentData() or "mp3"
            options["audio_bitrate"] = self.audio_bitrate_combo.currentData() or "320"
            options["embed_subtitles"] = False
            config_manager.set("default_audio_format", options["audio_format"])
            config_manager.set("default_audio_bitrate", options["audio_bitrate"])

        if self.is_channel:
            inc_v = self.ch_videos_check.isChecked()
            inc_s = self.ch_shorts_check.isChecked()
            inc_l = self.ch_lives_check.isChecked()
            options["include_videos"] = inc_v
            options["include_shorts"] = inc_s
            options["include_lives"] = inc_l
            config_manager.set("channel_download_videos", inc_v)
            config_manager.set("channel_download_shorts", inc_s)
            config_manager.set("channel_download_lives", inc_l)
        else:
            options["include_videos"] = True
            options["include_shorts"] = True
            options["include_lives"] = True

        return options
