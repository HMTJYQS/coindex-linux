"""Real QProcess transport tests using an isolated, stdlib-only service."""

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except ImportError as error:
    raise unittest.SkipTest("Linux Qt dependencies unavailable") from error

from coindex_linux.rpc import BackendClient


def snapshot():
    return {"tasks": [], "conversations": [], "hosts": [],
            "settings": {"connection_setup_complete": True, "automatic": False},
            "sync": {"running": False}, "schedule": {"due": False}, "nudges": []}


FIXTURE = r'''
import json, os, pathlib, sys, threading, time
lock = threading.Lock()
folder = pathlib.Path(__file__).parent
snapshot = SNAPSHOT
mode = MODE
if mode == 'locked':
    sys.stderr.write('已有 coindex 服务运行，无法获取 service.lock\n')
    sys.exit(3)
def emit(request):
    method = request['method']
    if method == 'slow': time.sleep(.12)
    if method == 'hold': return
    result = snapshot if method == 'snapshot' else {'method': method, 'value': request.get('value')}
    envelope = {'id': request['id'], 'result': result}
    if method == 'error': envelope = {'id': request['id'], 'error': 'fixture denied'}
    if mode == 'missing_nudge' and method == 'nudge': envelope = {'id': request['id']}
    with lock:
        if method == 'malformed':
            sys.stdout.write('not-json\n')
        line = json.dumps(envelope) + '\n'
        if method == 'split':
            middle = len(line)//2
            sys.stdout.write(line[:middle]); sys.stdout.flush(); time.sleep(.02)
            sys.stdout.write(line[middle:]); sys.stdout.flush()
        else:
            sys.stdout.write(line); sys.stdout.flush()
for line in sys.stdin:
    request = json.loads(line)
    with (folder/'calls.jsonl').open('a') as log:
        log.write(json.dumps(request)+'\n')
    if request['method'] == 'exit' or mode == 'crash_sync' and request['method'] == 'sync':
        os._exit(7)
    threading.Thread(target=emit, args=(request,), daemon=True).start()
(folder/'closed').write_text('stdin closed')
'''


class RpcTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="coindex-rpc-test-")
        self.folder = Path(self.temp.name)
        self.clients = []

    def tearDown(self):
        for client in self.clients:
            client.shutdown()
        self.app.processEvents()
        self.temp.cleanup()

    def pump(self, condition, seconds=3):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return
            time.sleep(.005)
        self.fail("timed out waiting for Qt event")

    def client(self, mode="normal"):
        service = self.folder / "service.py"
        service.write_text(FIXTURE.replace("SNAPSHOT", repr(snapshot())).replace("MODE", repr(mode)), encoding="utf-8")
        client = BackendClient(self.folder / "data", service_path=service, python=sys.executable, auto_start=False)
        self.clients.append(client)
        client.start()
        if mode != "locked":
            self.pump(lambda: bool(client.snapshot))
            client._poll.stop()
        return client

    def test_split_lines_and_out_of_order_replies_route_by_id(self):
        client = self.client()
        results = []
        client.request("slow", {"value": 1}, lambda value: results.append(value))
        client.request("split", {"value": 2}, lambda value: results.append(value))
        self.pump(lambda: len(results) == 2)
        self.assertEqual([result["value"] for result in results], [2, 1])
        self.assertFalse(client._pending)

    def test_error_and_malformed_line_do_not_orphan_callbacks(self):
        client = self.client()
        errors, results = [], []
        client.request("error", failure=errors.append)
        client.request("malformed", success=results.append)
        self.pump(lambda: errors and results)
        self.assertEqual(errors, ["fixture denied"])
        self.assertEqual(results[0]["method"], "malformed")
        self.assertFalse(client._pending)

    def test_timeout_reports_unknown_mutation_and_discards_late_reply(self):
        client = self.client()
        errors, results = [], []
        client.request("slow", success=results.append, failure=errors.append, timeout_ms=20)
        self.pump(lambda: bool(errors))
        self.assertIn("结果未确认", errors[0])
        marker = []
        client.request("slow", success=marker.append)
        self.pump(lambda: bool(marker))
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 1)

    def test_crash_clears_busy_and_restart_does_not_replay_sync(self):
        client = self.client("crash_sync")
        client.sync()
        self.assertTrue(client.syncing)
        self.pump(lambda: not client.available and bool(client.error))
        self.assertFalse(client.syncing)
        self.assertFalse(client._pending)
        client.restart()
        self.pump(lambda: client.available and not client._refreshing)
        calls = [json.loads(line)["method"] for line in (self.folder / "calls.jsonl").read_text().splitlines()]
        self.assertEqual(calls.count("sync"), 1)

    def test_shutdown_closes_stdin_to_allow_backend_cleanup(self):
        client = self.client()
        client.shutdown()
        self.assertTrue((self.folder / "closed").is_file())
        self.assertFalse(client.available)

    def test_second_instance_lock_has_actionable_message(self):
        client = self.client("locked")
        self.pump(lambda: bool(client.error))
        self.assertIn("已有 coindex 服务", client.error)

    def test_demo_never_starts_process_or_sends(self):
        client = BackendClient(self.folder / "demo", demo=True, demo_data=snapshot())
        self.clients.append(client)
        failed = []
        client.start()
        client.request("nudge", failure=failed.append)
        self.assertIsNone(client._process)
        self.assertFalse((self.folder / "demo").exists())
        self.assertIn("演示模式", failed[0])

    def test_missing_nudge_result_stays_unknown_until_matching_receipt(self):
        client = self.client("missing_nudge")
        task = {"id": "fixture-task", "conversation_id": "fixture-conversation", "kind": "review", "status": "open"}
        client.nudge(task)
        self.pump(lambda: (client.latest_nudge(task) or {}).get("status") == "unknown")
        self.assertTrue(client.nudge_disabled(task))
        client.nudge(task)
        calls = [json.loads(line)["method"] for line in (self.folder / "calls.jsonl").read_text().splitlines()]
        self.assertEqual(calls.count("nudge"), 1)
        confirmed = snapshot()
        confirmed["nudges"] = [{**client.latest_nudge(task), "status": "sent"}]
        client.apply_snapshot(confirmed)
        self.assertEqual(client.latest_nudge(task)["status"], "sent")
        self.assertFalse(client._uncertain_nudges)


if __name__ == "__main__":
    unittest.main()
