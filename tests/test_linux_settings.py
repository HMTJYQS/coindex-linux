"""Connection activation must use a successful check of the saved inputs."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    raise unittest.SkipTest("Linux Qt dependencies are not installed")

from coindex_linux.settings import SettingsDialog, SSHDialog
from coindex_linux import desktop
from coindex_linux.app import check_desktop_environment


class FakeClient:
    is_demo = False

    def __init__(self):
        self.snapshot = {"settings": {"codex_home": "", "codex_cli": "", "codex_app": "",
                                     "enabled_hosts": ["mac"], "remote_hosts": [],
                                     "connection_setup_complete": False}}
        self.requests = []
        self.writes = []

    def save_settings(self, values, success=None, failure=None):
        self.writes.append(copy.deepcopy(values))
        self.snapshot["settings"].update(copy.deepcopy(values))
        if success:
            success(self.snapshot)

    def request(self, method, values=None, success=None, failure=None, timeout_ms=30000):
        self.requests.append((method, values, success, failure))
        return len(self.requests)

    def finish_check(self, **updates):
        result = {"ok": True, "detail": "fake check", "version": "Codex fixture",
                  "login_ready": True, "cli_compatible": True, "sessions_ready": True}
        result.update(updates)
        next(item[2] for item in reversed(self.requests) if item[0] == "check_connection")(result)


class SettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.environment = patch.dict(os.environ, {"XDG_CONFIG_HOME": self.temporary.name})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.client = FakeClient()

    def dialog(self):
        dialog = SettingsDialog(self.client)
        self.addCleanup(dialog.close)
        return dialog

    def test_successful_saved_configuration_can_enable_automatic_collection(self):
        dialog = self.dialog()
        dialog.check_local()
        self.assertFalse(dialog.tabs.isEnabled())
        self.client.finish_check()
        self.assertTrue(self.client.snapshot["settings"]["connection_setup_complete"])
        self.assertTrue(dialog.tabs.isEnabled())

    def test_old_check_cannot_activate_new_saved_configuration(self):
        dialog = self.dialog()
        dialog.fields["codex_cli"].setText("/workspace/cli-a")
        dialog.check_local()
        dialog.fields["codex_cli"].setText("/workspace/cli-b")
        self.client.save_settings({"codex_cli": "/workspace/cli-b"})
        self.client.finish_check()
        self.assertFalse(self.client.snapshot["settings"]["connection_setup_complete"])
        self.assertIn("失效", dialog.message.text())

    def test_closing_check_dialog_does_not_enable_collection_later(self):
        dialog = self.dialog()
        dialog.check_local()
        dialog.reject()
        self.client.finish_check()
        self.assertFalse(self.client.snapshot["settings"]["connection_setup_complete"])

    def test_ssh_only_setup_does_not_require_local_sessions(self):
        self.client.snapshot["settings"].update(
            enabled_hosts=["dev-fixture"],
            remote_hosts=[{"id": "dev-fixture", "name": "测试来源"}],
        )
        dialog = self.dialog()
        dialog.check_local()
        self.client.finish_check(ok=False, sessions_ready=False)
        self.assertTrue(self.client.snapshot["settings"]["connection_setup_complete"])

    def test_ssh_only_setup_still_requires_local_cli_login(self):
        self.client.snapshot["settings"].update(enabled_hosts=["dev-fixture"])
        dialog = self.dialog()
        dialog.check_local()
        self.client.finish_check(ok=False, sessions_ready=False, login_ready=False)
        self.assertFalse(self.client.snapshot["settings"]["connection_setup_complete"])

    def test_detection_controls_preserve_backend_time_limits(self):
        self.client.snapshot["settings"].update(interval_seconds=30, idle_minutes=1)
        dialog = self.dialog()
        self.assertEqual(dialog.values()["interval_seconds"], 30)
        dialog.interval.setValue(1440)
        dialog.idle.setValue(0)
        self.assertEqual(dialog.values()["interval_seconds"], 3600)
        self.assertEqual(dialog.values()["idle_minutes"], 1)

    def test_edited_remote_cannot_reuse_a_prior_success(self):
        profile = {"id": "dev-fixture", "name": "测试来源", "hostname": "",
                   "user": "", "port": 0, "identity_file": "", "codex_home": "",
                   "python": "", "codex_cli": "", "host_id": ""}
        dialog = SSHDialog(self.client, profile, enabled=True)
        self.addCleanup(dialog.close)
        self.assertTrue(dialog.enabled.isChecked())
        dialog.fields["user"].setText("developer")
        self.assertFalse(dialog.enabled.isChecked())
        self.assertFalse(dialog.enabled.isEnabled())

    def test_autostart_uses_stable_launcher_and_preserves_unowned_file(self):
        launcher = Path(self.temporary.name) / "bin/coindex-linux"
        launcher.parent.mkdir()
        launcher.write_text("#!/bin/sh\n")
        with patch.dict(os.environ, {"COINDEX_LINUX_LAUNCHER": str(launcher)}):
            desktop.set_autostart_enabled(True)
            text = desktop._autostart_path().read_text()
            self.assertIn(str(launcher), text)
            self.assertTrue(desktop.autostart_enabled())
            desktop.set_autostart_enabled(False)
            self.assertFalse(desktop._autostart_path().exists())
            desktop._autostart_path().write_text("[Desktop Entry]\nName=Other app\n")
            with self.assertRaises(RuntimeError):
                desktop.set_autostart_enabled(True)
            self.assertIn("Other app", desktop._autostart_path().read_text())

    def test_missing_xcb_dependency_reports_an_actionable_error(self):
        with patch.dict(os.environ, {"QT_QPA_PLATFORM": "xcb", "DISPLAY": ":1"}), \
                patch("coindex_linux.app.ctypes.CDLL", side_effect=OSError("missing library")):
            with self.assertRaisesRegex(RuntimeError, "libxcb-cursor0"):
                check_desktop_environment()

    def test_offscreen_verification_does_not_require_an_x11_server(self):
        with patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}), \
                patch("coindex_linux.app.ctypes.CDLL") as loader:
            check_desktop_environment()
            loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
