"""Desktop integration and user data locations shared by the backend and UI."""
import os
import pathlib
import shutil
import subprocess
import sys
from urllib.parse import quote, urlencode


def default_data_dir():
    override = os.environ.get("CODEX_TODO_DATA_DIR")
    if override:
        return pathlib.Path(override).expanduser()
    if sys.platform == "darwin":
        return pathlib.Path.home() / "Library/Application Support/CodexTodo"
    # XDG requires an absolute path; ignore relative values instead of placing
    # user data inside whichever project happened to launch the application.
    configured = os.environ.get("XDG_DATA_HOME", "")
    root = pathlib.Path(configured) if configured else None
    if root is None or not root.is_absolute():
        root = pathlib.Path.home() / ".local/share"
    return root / "coindex"


def local_host_name():
    return "这台 Mac" if sys.platform == "darwin" else "本机"


def desktop_thread_url(thread_id, host_id):
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise ValueError("原对话 ID 无效")
    if not isinstance(host_id, str) or not host_id.strip():
        raise ValueError("原对话主机 ID 无效")
    return "codex://threads/" + quote(thread_id, safe="") + "?" + urlencode({"hostId": host_id})


def open_desktop_thread(thread_id, host_id, app=""):
    """Request the Codex desktop to open a thread; never fall back to the CLI."""
    url = desktop_thread_url(thread_id, host_id)
    explicit_gui = bool(app) and sys.platform != "darwin"
    if sys.platform == "darwin":
        command = ["/usr/bin/open"]
        if app:
            command += ["-a", str(pathlib.Path(app).expanduser())]
        command.append(url)
    elif explicit_gui:
        executable = pathlib.Path(app).expanduser()
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise RuntimeError("设置的 Codex 桌面程序无法执行，请选择 GUI 启动程序或清空该设置")
        command = [str(executable.resolve()), url]
    else:
        opener = shutil.which("xdg-open")
        if not opener:
            raise RuntimeError("找不到 xdg-open，请安装 xdg-utils 或设置 Codex 桌面程序路径")
        command = [opener, url]
    try:
        if explicit_gui:
            # A GUI can remain alive after accepting its URL. Requiring it to
            # exit would report successful launches as failures.
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       start_new_session=True)
            try:
                code = process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                return
            if code:
                raise RuntimeError("Codex 桌面程序启动失败，请检查所选 GUI 程序")
        else:
            subprocess.run(command, check=True, timeout=5, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           start_new_session=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("无法打开 Codex 原对话，请检查桌面程序及 codex:// 协议关联，或设置 GUI 程序路径") from error
