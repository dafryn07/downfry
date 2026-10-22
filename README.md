# 🍟 Downfry — YouTube Media Suite & Offline Player para Windows 11

[![GitHub Release](https://img.shields.io/github/v/release/your-repo/downfry?style=flat-square&color=00C896)](https://github.com/your-repo/downfry/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-00A8E8.svg?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011%20(64--bit)-blue?style=flat-square)](#)
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-blue?style=flat-square)](#)

Una aplicación de escritorio moderna y fluida para **Windows 10 y Windows 11** diseñada con **Fluent Design 2** (Mica, acrílico, temas claro/oscuro) e inspirada en la elegancia y potencia de **Seal (Android)**.

Downfry no solo descarga contenido de YouTube con orden cronológico perfecto, sino que se convierte en tu **reproductor y biblioteca personal offline estilo YouTube**, permitiéndote revivir tus videos, shorts, playlists y canales favoritos sin conexión a internet y sin anuncios.

---

## ✨ Características Principales

### 🎬 Descarga Multimedia Potente y Flexible
- **Formatos de Video**: Descargas en MP4 hasta 4K UHD (2160p), 2K (1440p), 1080p Full HD, 720p HD, 480p y 360p.
- **Extracción de Audio de Alta Fidelidad**: MP3, M4A (AAC), OPUS, FLAC o WAV a 320 kbps, 256 kbps, 192 kbps o 128 kbps con carátula original incrustada.
- **Incrustación de Metadatos y Capítulos**: Etiquetas ID3/MP4 completas con título, artista/canal, miniatura original en alta resolución y marcas de capítulos interactivos.
- **Subtítulos y Traducción**: Subtítulos automáticos o manuales en español e inglés integrados directamente en el contenedor del video.
- **Timestamps NTFS Reales**: Conserva la fecha y hora original de publicación del video en los metadatos del archivo de Windows.

### 📅 Nombres con Fecha Cronológica Estricta (`YYYY-MM-DD`)
Todos los archivos se nombran con el estándar:
```text
YYYY-MM-DD - [Título del video] - [Canal].[ext]
```
*Ejemplo:* `2024-05-18 - Análisis Gran Premio de Mónaco [1080p] - F1.mp4`  
Al iniciar con la fecha ISO, cualquier explorador de archivos (Windows Explorer, Android, Smart TVs, NAS o discos externos) los ordenará en secuencia cronológica exacta.

### 📢 Descarga Inteligente de Canales Completos (Función Estrella)
Organiza los videos automáticamente en carpetas estructuradas por **Año**, **Mes en español** y **Categoría**:
```text
<Carpeta de Descargas>/<Nombre del Canal>/
    ├── 2024/
    │   ├── 01 - Enero/
    │   │   ├── Videos/
    │   │   │   └── 2024-01-15 - Video normal [1080p] - Canal.mp4
    │   │   ├── Shorts/
    │   │   │   └── 2024-01-20 - Mi short viral [1080p] - Canal.mp4
    │   │   └── Directos/
    │   │       └── 2024-01-28 - Transmisión en vivo [1080p] - Canal.mp4
    │   └── 02 - Febrero/
    └── download_archive.txt
```
- **Detección Dinámica en Disco**: Si borras o mueves un video fuera de la app, Downfry detecta la ausencia física y lo vuelve a descargar cuando actualices el canal.
- **Filtros por categoría**: Elige descargar solo videos largos, solo shorts, directos o todo el canal en simultáneo.

### 📺 Reproductor de Video Integrado (Estilo YouTube + VLC)
- **Barra de Progreso en Tonos Fríos (`ChapterSlider`)**:
  - Gradiente relajante en azul cian (`#00A8E8`) a verde esmeralda (`#00C896`).
  - Marcas divisorias de **Capítulos** con tooltip al pasar el cursor y nombre del capítulo actual junto al contador de tiempo (`04:15 / 22:10 • 📑 Introducción`).
- **Memoria de Posición Automática (Estilo VLC)**:
  - Guarda la posición exacta cada 3 segundos y al pausar o salir.
  - Al reanudar un video, salta automáticamente al minuto exacto con un aviso sutil y opción de volver al inicio con un clic.
- **Atajos de Teclado Universales**:
  - `Espacio` o `K`: Reproducir / Pausar
  - `J` o `←`: Retroceder 10s / 5s
  - `L` o `→`: Avanzar 10s / 5s
  - `↑` / `↓`: Subir / Bajar volumen
  - `M`: Silenciar / Desactivar silencio
  - `F`: Pantalla completa
- **Panel Lateral Derecho Colapsable**:
  - **📑 Capítulos**: Lista interactiva de capítulos del video; salta al instante al hacer clic en uno.
  - **📋 Siguientes ("Cola")**: Lista de reproducción del canal o playlist con reproducción continua automática.
  - **ℹ️ Información y Descripción**: Metadatos completos, fecha de publicación, canal y descripción original.
- **Controles Avanzados**:
  - Selector de velocidad de reproducción (`0.25x` a `2.0x`).
  - Selector de pistas de audio y subtítulos incrustados.
  - **Ventana Flotante (Pop-out)** para seguir viendo mientras trabajas en otras aplicaciones.
  - Botón directo para abrir en reproductor externo (VLC / Media Player).

### 📚 Navegador de Biblioteca Offline Estilo YouTube
- Explora tus canales descargados con interfaz de tarjetas con vista previa 16:9, duración, calidad y **barra inferior de progreso en color frío**.
- Filtra por **Canal**, **Playlist**, **Año**, **Mes** o categorías (**Videos**, **Shorts**, **Directos**, **Audio**).
- Búsqueda en tiempo real instantánea por título o identificador.

---

## 🚀 Instalación y Uso

### Opción 1: Versión Portable (Recomendada para Usuarios)
1. Descarga el archivo `Downfry-Windows-Portable.zip` desde la sección de [Releases](https://github.com/your-repo/downfry/releases).
2. Descomprímelo en cualquier carpeta de tu disco.
3. Ejecuta `Downfry.exe` y comienza a disfrutar. No requiere instalación de Python.

---

### Opción 2: Ejecución desde Código Fuente (Desarrolladores)

#### Requisitos del Sistema:
- **Sistema Operativo**: Windows 10 u 11 (64-bit) o distribuciones Linux recientes.
- **Python**: Versión 3.10 o superior (recomendado 3.12).
- **FFmpeg**: Se descarga automáticamente o se utiliza el presente en el sistema.

#### Pasos:
1. Clona el repositorio:
   ```bash
   git clone https://github.com/your-repo/downfry.git
   cd downfry
   ```

2. Crea y activa un entorno virtual (opcional pero recomendado):
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```

4. Inicia la aplicación:
   ```bash
   python run.py
   ```

---

## 🧪 Pruebas Automatizadas

Downfry incluye una suite integral de pruebas unitarias que validan la sanitización de nombres, detección de resoluciones, cadenas anti-bloqueo y memoria de biblioteca:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

---

## 📦 Compilación de Versión Portable `.exe`

Para empaquetar Downfry como ejecutable independiente para Windows:

```bash
python build_exe.py
```
El ejecutable y sus recursos asociados se generarán en la carpeta `dist/Downfry/`.

---

## 🛠️ Tecnologías Utilizadas

- **Interfaz Gráfica**: [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) + [PyQt6-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)
- **Motor de Descarga**: [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- **Multimedia y Reproducción**: `PyQt6.QtMultimedia`, `PyQt6.QtMultimediaWidgets` y `FFmpeg`
- **Integración de Sistema**: Windows Mica/Acrylic material, compatibilidad con temas claro/oscuro de Windows 11.

---

## 📄 Licencia

Este proyecto está bajo la Licencia **MIT**. Consulta el archivo [LICENSE](LICENSE) para más detalles.
