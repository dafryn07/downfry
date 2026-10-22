import os
import sys
import subprocess
from pathlib import Path

def build_launcher():
    project_dir = Path(__file__).resolve().parent
    icon_path = project_dir / "packaging" / "app_icon.ico"
    output_exe = project_dir / "Downfry.exe"
    cs_file = project_dir / "Launcher.cs"

    cs_code = r"""using System;
using System.Diagnostics;
using System.IO;

namespace DownfryLauncher
{
    class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            string appDir = AppDomain.CurrentDomain.BaseDirectory;
            string runScript = Path.Combine(appDir, "run.py");
            
            string pythonw = "pythonw.exe";
            string venvPythonw = Path.Combine(appDir, ".venv", "Scripts", "pythonw.exe");
            if (File.Exists(venvPythonw))
            {
                pythonw = venvPythonw;
            }
            else
            {
                string venv2 = Path.Combine(appDir, "venv", "Scripts", "pythonw.exe");
                if (File.Exists(venv2))
                {
                    pythonw = venv2;
                }
            }

            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = pythonw;
            psi.Arguments = "\"" + runScript + "\"";
            psi.WorkingDirectory = appDir;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;

            try
            {
                Process.Start(psi);
            }
            catch
            {
                psi.FileName = "python.exe";
                try
                {
                    Process.Start(psi);
                }
                catch (Exception ex)
                {
                    System.Windows.Forms.MessageBox.Show(
                        "No se pudo iniciar Python para ejecutar Downfry:\n" + ex.Message,
                        "Downfry Launcher Error",
                        System.Windows.Forms.MessageBoxButtons.OK,
                        System.Windows.Forms.MessageBoxIcon.Error
                    );
                }
            }
        }
    }
}
"""
    cs_file.write_text(cs_code, encoding="utf-8")

    # Localizar csc.exe
    csc_candidates = [
        r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
        r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe",
    ]
    csc_exe = None
    for cand in csc_candidates:
        if os.path.exists(cand):
            csc_exe = cand
            break

    if not csc_exe:
        print("[ERROR] No se encontró csc.exe de .NET Framework.")
        return False

    cmd = [
        csc_exe,
        "/target:winexe",
        f"/out:{output_exe}",
        "/r:System.Windows.Forms.dll",
    ]
    if icon_path.exists():
        cmd.append(f"/win32icon:{icon_path}")
    cmd.append(str(cs_file))

    print(f"Compilando {output_exe.name}...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[ERROR] Error al compilar: {res.stderr or res.stdout}")
        return False

    if cs_file.exists():
        try:
            cs_file.unlink()
        except Exception:
            pass

    print(f"¡Lanzador creado con éxito en: {output_exe}!")

    # Crear acceso directo en el Menú Inicio de Windows
    start_menu_programs = Path(os.getenv("APPDATA")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    if start_menu_programs.exists():
        shortcut_path = start_menu_programs / "Downfry.lnk"
        ps_cmd = f"""
        $ws = New-Object -ComObject WScript.Shell
        $s = $ws.CreateShortcut('{str(shortcut_path)}')
        $s.TargetPath = '{str(output_exe)}'
        $s.WorkingDirectory = '{str(project_dir)}'
        $s.IconLocation = '{str(icon_path if icon_path.exists() else output_exe)}'
        $s.Description = 'Downfry - Descargador de YouTube y YouTube Music'
        $s.Save()
        """
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=True)
            print(f"¡Acceso directo creado en el Menú Inicio: {shortcut_path}!")
        except Exception as e:
            print(f"[Aviso] No se pudo crear el acceso directo en el Menú Inicio: {e}")

    return True

if __name__ == "__main__":
    success = build_launcher()
    sys.exit(0 if success else 1)
