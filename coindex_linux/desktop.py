"""Linux desktop actions shared by the window and connection setup."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def open_thread(thread_id, host_id, app=""):
    from backend.platforms import open_desktop_thread
    open_desktop_thread(thread_id, host_id, app)


def open_data_directory(path):
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve()))):
        raise RuntimeError("无法打开数据目录，请在文件管理器中打开该路径。")


def launch_ssh_terminal(args):
    """Use argv rather than interpreting the SSH command in a shell."""
    for name, flag in (("gnome-terminal", "--"), ("konsole", "-e"),
                       ("xfce4-terminal", "-x"), ("x-terminal-emulator", "-e"),
                       ("xterm", "-e")):
        executable = shutil.which(name)
        if executable:
            try:
                subprocess.Popen([executable, flag, *args], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as error:
                raise RuntimeError("终端无法启动，请复制 SSH 命令到终端执行。") from error
            return
    raise RuntimeError("找不到终端，请复制 SSH 命令到终端执行。")


def _autostart_path():
    base = os.environ.get("XDG_CONFIG_HOME", "")
    root = Path(base) if base and Path(base).is_absolute() else Path.home() / ".config"
    return root / "autostart/coindex-linux.desktop"


def autostart_enabled():
    try:
        return "X-Coindex-Linux=true" in _autostart_path().read_text()
    except OSError:
        return False


def set_autostart_enabled(enabled):
    path = _autostart_path()
    if path.exists() and not autostart_enabled():
        raise RuntimeError("同名自启动文件由其他程序创建，请先在系统设置中核对。")
    if not enabled:
        if path.exists():
            path.unlink()
        return
    configured = os.environ.get("COINDEX_LINUX_LAUNCHER")
    found = configured or shutil.which("coindex-linux")
    launcher = Path(found) if found else Path(sys.executable).parent / "coindex-linux"
    if not launcher.is_file():
        raise RuntimeError("请先安装 coindex-linux，再启用登录自启动。")
    value = str(launcher.resolve())
    for before, after in (("\\", "\\\\"), ('"', '\\"'), ("$", "\\$"),
                          ("`", "\\`"), ("%", "%%")):
        value = value.replace(before, after)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[Desktop Entry]\nType=Application\nName=coindex Linux\n"
                    f'Exec="{value}"\n'
                    "Terminal=false\nX-Coindex-Linux=true\n"
                    "X-GNOME-Autostart-enabled=true\n", encoding="utf-8")
