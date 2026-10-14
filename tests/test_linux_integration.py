"""Qt transport against the real backend, with an empty isolated Codex home."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
except ImportError:
    raise unittest.SkipTest("Linux Qt dependencies are not installed")

from coindex_linux.rpc import BackendClient


class BackendIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_until(self, condition, seconds=5):
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertTrue(condition(), self.client.error)

    def test_manual_task_state_persists_through_process_restart(self):
        with tempfile.TemporaryDirectory(prefix="coindex-integration-") as temporary:
            root = Path(temporary)
            with patch.dict(os.environ, {"HOME": str(root), "CODEX_HOME": str(root / "empty-codex"),
                                         "XDG_CONFIG_HOME": str(root / "config"),
                                         "CODEX_TODO_CODEX": "/usr/bin/true"}):
                self.client = BackendClient(root / "data", auto_start=False)
                try:
                    self.client.start()
                    self.wait_until(lambda: bool(self.client.snapshot))
                    self.assertFalse(self.client.snapshot["settings"]["connection_setup_complete"])
                    saved = []
                    self.client.request("save_manual", {"title": "测试安装后的跟进事项", "detail": "隔离数据",
                                                        "priority": 2},
                                        success=lambda result: (self.client.apply_snapshot(result["snapshot"]),
                                                                saved.append(result["task_id"])))
                    self.wait_until(lambda: bool(saved))
                    task_id = saved[0]
                    self.client.act("complete", task_id)
                    self.wait_until(lambda: any(t["id"] == task_id and t["status"] == "done"
                                               for t in self.client.snapshot["tasks"]))
                    self.client.shutdown()
                    self.assertFalse(self.client.available)
                    self.client.snapshot = {}
                    self.client.start()
                    self.wait_until(lambda: bool(self.client.snapshot))
                    self.assertTrue(any(t["id"] == task_id and t["status"] == "done"
                                        for t in self.client.snapshot["tasks"]))
                    self.client.act("reopen", task_id)
                    self.wait_until(lambda: any(t["id"] == task_id and t["status"] == "open"
                                               for t in self.client.snapshot["tasks"]))
                    self.assertTrue(self.client.update_disabled)
                finally:
                    self.client.shutdown()


if __name__ == "__main__":
    unittest.main()
