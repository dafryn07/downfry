import sys
import os
import ctypes
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from downfry.ui.main_window import MainWindow


def main():
    # 1. Configurar ID de aplicación en Windows 11 para icono y barra de tareas
    try:
        myappid = "Downfry.YouTubeDownloader.Windows11.1.0"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    # 2. Habilitar escalado High DPI para pantallas 2K/4K en Windows 11
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Downfry")
    app.setOrganizationName("Downfry")

    from PyQt6.QtGui import QIcon
    from downfry.config import get_resource_path
    icon_path = get_resource_path("packaging/app_icon.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # 3. Purgar papelera de reciclaje caducada
    try:
        from downfry.core.recycle_bin import RecycleBinManager
        RecycleBinManager.purge_expired()
    except Exception:
        pass

    # 4. Iniciar ventana principal
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
