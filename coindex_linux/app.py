"""Launch coindex for Linux with optional tray integration."""

from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from . import __version__
from .rpc import BackendClient
from .window import MainWindow, filtered_tasks


def default_data_directory():
    from backend.platforms import default_data_dir
    return default_data_dir()


def check_desktop_environment():
    """Report the known X11 runtime prerequisite before Qt can abort."""
    platform = os.environ.get("QT_QPA_PLATFORM", "").split(":", 1)[0]
    if platform in ("offscreen", "minimal", "wayland", "wayland-egl"):
        return
    if not platform and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise RuntimeError("未检测到图形桌面。请在 X11 或 Wayland 桌面中启动 coindex Linux。")
    uses_xcb = platform == "xcb" or (not platform and not os.environ.get("WAYLAND_DISPLAY"))
    if uses_xcb:
        try:
            ctypes.CDLL("libxcb-cursor.so.0")
        except OSError as error:
            raise RuntimeError("缺少 Qt 的 X11 运行库 libxcb-cursor0。Ubuntu/Debian 请在终端运行：sudo apt-get install -y libxcb-cursor0") from error


class TrayController:
    def __init__(self, app, window, client):
        self.app, self.window, self.client = app, window, client
        self.icon = QSystemTrayIcon(window)
        self.menu = QMenu(window)
        self.icon.setContextMenu(self.menu)
        self.icon.setIcon(app.windowIcon())
        self.icon.activated.connect(self._activated)
        self.icon.show()
        client.snapshot_changed.connect(lambda snapshot: self.refresh())
        client.state_changed.connect(self.refresh)
        window.closed_to_tray.connect(lambda: self.icon.showMessage("coindex", "主窗口已隐藏；托盘菜单可以重新打开。"))
        self.timer = QTimer(window)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh_availability)
        self.timer.start()
        self.refresh_availability()
        self.refresh()

    def refresh_availability(self):
        available = QSystemTrayIcon.isSystemTrayAvailable()
        was_available = self.window.tray_available
        self.window.tray_available = available
        if was_available and not available and not self.window.isVisible():
            self.window.show_main()

    def _activated(self, reason):
        if reason in {QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick}:
            self.window.show_main()

    def refresh(self):
        self.menu.clear()
        tasks = filtered_tasks(self.client.snapshot)
        self.icon.setToolTip(f"coindex · {len(tasks)} 项待办")
        self.menu.addAction(f"coindex · {len(tasks)} 项待办").setEnabled(False)
        for task in tasks[:5]:
            self.menu.addAction(task.get("title", "待办")[:60], lambda checked=False, task_id=task["id"]: self._select_task(task_id))
        self.menu.addSeparator()
        self.menu.addAction("打开 coindex", self.window.show_main)
        self.menu.addAction("新建待办", self.window.edit_manual).setEnabled(self.client.available)
        self.menu.addAction("立即更新", lambda: self.client.sync()).setEnabled(not self.client.update_disabled)
        if self.client.syncing:
            self.menu.addAction("中止更新", self.client.cancel_sync).setEnabled(not self.client.cancelling)
        self.menu.addAction("提前上班" if self.client.off_duty else "下班", self.client.toggle_workday).setEnabled(self.client.available and not self.client.workday_pending)
        automatic = self.client.snapshot.get("settings", {}).get("automatic", False)
        self.menu.addAction("暂停自动整理" if automatic else "恢复自动整理",
                            lambda: self.client.save_settings({"automatic": not automatic})).setEnabled(self.client.available)
        self.menu.addSeparator()
        self.menu.addAction("设置", self.window.open_settings)
        self.menu.addAction("退出 coindex", self.app.quit)

    def _select_task(self, task_id):
        self.window.navigation.setCurrentRow(0)
        self.window.host_combo.setCurrentIndex(0)
        self.window.search.clear()
        self.window.selected_id = task_id
        self.window.render_list()
        self.window.show_main()


def main(argv=None):
    parser = argparse.ArgumentParser(description="coindex Linux desktop")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--demo", action="store_true", help="Preview bundled example data without starting any backend")
    parser.add_argument("--smoke-test", action="store_true", help="Show the demo briefly and exit; requires --demo")
    parser.add_argument("--screenshot", type=Path, help="Save a screenshot of the main window after showing it")
    parser.add_argument("--data-dir", type=Path, default=default_data_directory())
    args = parser.parse_args(argv)
    if args.smoke_test and not args.demo:
        parser.error("--smoke-test requires --demo so it cannot start real analysis")
    try:
        check_desktop_environment()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("coindex-linux")
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("coindex-linux")
    app.setQuitOnLastWindowClosed(False)
    from .resources import backend_script, resource_path
    if args.smoke_test and not backend_script().is_file():
        parser.error("Bundled backend service is missing")
    icon_path = resource_path("Brand/AppIcon.png")
    app.setWindowIcon(QIcon(str(icon_path)) if icon_path.is_file()
                      else app.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
    client = BackendClient(args.data_dir, demo=args.demo, auto_start=False)
    window = MainWindow(client)
    tray = TrayController(app, window, client)
    app.aboutToQuit.connect(client.shutdown)
    app.aboutToQuit.connect(window.pet_widget.shutdown)
    window.show()
    if args.smoke_test or args.screenshot:
        def capture():
            if args.screenshot:
                try:
                    args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                    saved = window.grab().save(str(args.screenshot))
                except OSError as error:
                    print(f"Cannot save screenshot: {error}", file=sys.stderr)
                    saved = False
                if not saved:
                    app.exit(1)
                    return
            if args.smoke_test:
                app.exit(0)
        QTimer.singleShot(600, capture)
    if not args.demo:
        QTimer.singleShot(0, client.start)
    try:
        return app.exec()
    finally:
        client.shutdown()
        tray.icon.hide()


if __name__ == "__main__":
    raise SystemExit(main())
