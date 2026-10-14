"""Task workflow tests with snapshots and no Codex/network side effects."""

import copy
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError as error:
    raise unittest.SkipTest("Linux Qt dependencies unavailable") from error

from coindex_linux.rpc import BackendClient
from coindex_linux.app import default_data_directory
from coindex_linux.window import MainWindow, ManualTodoDialog, filtered_tasks, conversation_state


def fixture():
    task = {"id": "task-a", "conversation_id": "conversation-a", "title": "Example task",
            "kind": "review", "status": "open", "host": "mac", "thread_id": "thread-a",
            "progress": "An example result is ready", "detail": "Check the result", "next_action": "Verify the example",
            "evidence": "Example evidence", "priority": 2, "snoozed_until": 0,
            "conversation_title": "Example conversation", "confidence": .9, "updated_at": 100}
    return {"tasks": [task], "conversations": [{"id": "conversation-a", "host": "mac", "thread_id": "thread-a",
                                               "title": "Example conversation", "closed": 0, "archived": 0}],
            "hosts": [{"id": "mac", "name": "本机"}],
            "settings": {"connection_setup_complete": True, "automatic": False, "remote_hosts": []},
            "sync": {"running": False}, "schedule": {"due": False}, "nudges": [], "model": "fixture"}


class FakeClient(BackendClient):
    def __init__(self, folder):
        super().__init__(folder, demo=True, demo_data=fixture())
        self.is_demo = False
        self.calls = []

    @property
    def available(self):
        return True

    def request(self, method, values=None, success=None, failure=None, timeout_ms=30000):
        self.calls.append((method, values or {}))
        result = self.snapshot
        if method in {"rename_task", "save_manual"}:
            result = {"task_id": "task-a", "snapshot": self.snapshot}
        elif method == "sync":
            result = {"accepted": True}
        elif method == "nudge":
            result = copy.deepcopy(self.snapshot)
            result["nudges"] = [{"action_id": values["action_id"], "conversation_id": "conversation-a",
                                 "status": "queued", "updated_at": time.time()}]
        if success:
            success(result)
        return len(self.calls)


class WindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="coindex-window-test-")
        self.client = FakeClient(Path(self.temp.name))
        self.window = MainWindow(self.client)
        self.window.items.setCurrentRow(0)

    def tearDown(self):
        self.window.force_quit = True
        self.window.hide()
        self.window.deleteLater()
        self.client.shutdown()
        self.app.processEvents()
        self.temp.cleanup()

    def test_status_kind_and_snooze_are_independent(self):
        snap = fixture()
        original = snap["tasks"][0]
        snap["tasks"] += [{**original, "id": "done", "status": "completed"},
                          {**original, "id": "later", "snoozed_until": 2000},
                          {**original, "id": "manual", "kind": "manual"},
                          {**original, "id": "other", "host": "remote"}]
        self.assertEqual([entry["id"] for entry in filtered_tasks(snap, "review", host="mac", now=1000)], ["task-a"])
        self.assertEqual([entry["id"] for entry in filtered_tasks(snap, "completed", now=1000)], ["done"])
        self.assertEqual([entry["id"] for entry in filtered_tasks(snap, "snoozed", now=1000)], ["later"])
        self.assertEqual(len(filtered_tasks(snap, "review", now=3000)), 3)
        self.assertEqual(len(filtered_tasks(snap, search="verify", now=1000)), 3)

    def test_task_actions_and_details_use_upstream_contract(self):
        text = self.window.details.toPlainText()
        self.assertIn("Verify the example", text)
        self.assertIn("Example evidence", text)
        self.window.task_action("snooze", 60)
        self.assertEqual(self.client.calls[-1], ("act", {"action": "snooze", "entity_id": "task-a", "value": 60}))
        self.window.complete()
        self.assertEqual(self.client.calls[-1][1]["action"], "complete")
        with patch("coindex_linux.window.QInputDialog.getText", return_value=("Custom title", True)):
            self.window.rename()
        self.assertEqual(self.client.calls[-1], ("rename_task", {"entity_id": "task-a", "title": "Custom title"}))

    def test_unknown_nudge_requires_explicit_confirmed_retry(self):
        self.client.snapshot["nudges"] = [{"action_id": "old", "conversation_id": "conversation-a",
                                           "status": "unknown", "error": "fixture uncertain", "updated_at": 100}]
        self.window.render_detail()
        self.assertFalse(self.window.detail_buttons["nudge"].isEnabled())
        self.assertTrue(self.window.detail_buttons["retry"].isEnabled())
        self.window.nudge()
        self.assertEqual(self.client.calls, [])
        with patch("coindex_linux.window.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel):
            self.window.retry_nudge()
        self.assertEqual(self.client.calls, [])
        with patch("coindex_linux.window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            self.window.retry_nudge()
        self.assertEqual(self.client.calls[-1][0], "nudge")
        self.assertTrue(self.client.calls[-1][1]["retry_unknown"])
        self.assertFalse(self.window.detail_buttons["nudge"].isEnabled())

    def test_tracking_confirmation_and_archived_state(self):
        self.window.navigation.setCurrentRow(self.window.navigation.count() - 1)
        self.window.items.setCurrentRow(0)
        with patch("coindex_linux.window.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel):
            self.window.toggle_tracking()
        self.assertEqual(self.client.calls, [])
        with patch("coindex_linux.window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            self.window.toggle_tracking()
        self.assertEqual(self.client.calls[-1][1]["action"], "close_conversation")
        self.client.snapshot["conversations"][0]["closed"] = 1
        self.window.toggle_tracking()
        self.assertEqual(self.client.calls[-1][1]["action"], "reopen_conversation")
        self.assertEqual(conversation_state({"archived": 1, "closed": 1}), "已归档，不再跟踪")

    def test_manual_save_sends_plain_note_and_priority(self):
        dialog = ManualTodoDialog(self.client, parent=self.window)
        dialog.title_edit.setText("Manual example")
        dialog.note_edit.setPlainText("<b>literal note</b>")
        dialog.priority.setCurrentIndex(0)
        dialog.save()
        self.assertEqual(self.client.calls[-1], ("save_manual", {"title": "Manual example", "detail": "<b>literal note</b>", "priority": 1}))
        dialog.deleteLater()

    def test_auto_sync_needs_due_setup_and_not_off_duty(self):
        self.client.snapshot["schedule"]["due"] = True
        self.client.snapshot["settings"]["connection_setup_complete"] = False
        self.client.refresh(check_automatic=True)
        self.assertFalse(any(method == "sync" for method, values in self.client.calls))
        self.client.snapshot["settings"]["connection_setup_complete"] = True
        self.client.snapshot["schedule"]["off_duty"] = True
        self.client.refresh(check_automatic=True)
        self.assertFalse(any(method == "sync" for method, values in self.client.calls))
        self.client.snapshot["schedule"]["off_duty"] = False
        self.client.refresh(check_automatic=True)
        self.assertEqual([values for method, values in self.client.calls if method == "sync"], [{"force": False, "automatic": True}])

    def test_no_tray_close_exits_and_available_tray_hides(self):
        event = type("CloseEvent", (), {"accept": lambda self: setattr(self, "accepted", True),
                                       "ignore": lambda self: setattr(self, "accepted", False)})()
        with patch.object(QApplication.instance(), "quit") as quit_app:
            self.window.tray_available = False
            self.window.closeEvent(event)
            self.assertTrue(event.accepted)
            quit_app.assert_called_once()
        self.window.tray_available = True
        self.window.closeEvent(event)
        self.assertFalse(event.accepted)

    def test_app_delegates_empty_and_relative_xdg_to_platform_owner(self):
        for value in ("", "relative-data"):
            with self.subTest(value=value), patch("backend.platforms.sys.platform", "linux"), patch.dict(os.environ, {"XDG_DATA_HOME": value, "CODEX_TODO_DATA_DIR": ""}):
                self.assertEqual(default_data_directory(), Path.home() / ".local/share/coindex")
                self.assertTrue(default_data_directory().is_absolute())


if __name__ == "__main__":
    unittest.main()
