"""Script automatizado para compilar Downfry en un ejecutable .exe para Windows 11.
Ejecutar con: python build_exe.py
"""

import sys
import subprocess
from pathlib import Path


def build():
    print("=" * 60)
    print("Iniciando compilación de Downfry para Windows 11...")
    print("=" * 60)

    spec_file = Path("packaging") / "Downfry.spec"
    if not spec_file.exists():
        print(f"Error: No se encontró el archivo spec en {spec_file}")
        sys.exit(1)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        str(spec_file),
    ]

    print("Ejecutando PyInstaller...")
    res = subprocess.run(cmd)

    if res.returncode == 0:
        exe_path = Path("dist") / "Downfry" / "Downfry.exe"
        print("\n" + "=" * 60)
        print("¡COMPILACIÓN EXITOSA!")
        print(f"Ejecutable generado en: {exe_path.resolve()}")
        print("=" * 60)
    else:
        print("\nOcurrió un error durante la compilación.")
        sys.exit(res.returncode)


if __name__ == "__main__":
    build()
