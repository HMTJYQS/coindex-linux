"""Asynchronous, single-owner transport for the upstream JSON-lines service.

Mutations are never replayed after timeout or process failure. The service owns
the database and all collector/model subprocesses; this client only owns serve.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid
from typing import Callable

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal


Callback = Callable[[object], None]
READ_METHODS = frozenset({"snapshot", "diagnostics", "ssh_aliases", "ssh_terminal_command", "check_connection"})


class BackendClient(QObject):
    snapshot_changed = Signal(dict)
    state_changed = Signal()
    error_changed = Signal(str)
    notification = Signal(str)

    def __init__(self, data_directory, *, demo=False, service_path=None,
                 python=None, demo_data=None, auto_start=True, parent=None):
        super().__init__(parent)
        self.data_directory = Path(data_directory).expanduser().absolute()
        self.is_demo = demo
        self.snapshot = {}
        self.error = ""
        self._service_path = Path(service_path) if service_path else None
        self._python = python
        self._process = None
        self._buffer = bytearray()
        self._stderr = bytearray()
        self._next_id = 0
        self._pending = {}
        self._refreshing = False
        self._awaiting_sync = False
        self._cancelling = False
        self._workday_pending = False
        self._stopping = False
        self._mutations = set()
        self._requesting_nudges = set()
        self._uncertain_nudges = {}
        self._poll = QTimer(self)
        self._poll.setInterval(3000)
        self._poll.timeout.connect(lambda: self.refresh(check_automatic=True))
        if demo:
            if demo_data is None:
                from .resources import demo_snapshot
                demo_data = demo_snapshot()
            self.snapshot = demo_data
        elif auto_start:
            QTimer.singleShot(0, self.start)

    @property
    def available(self):
        return bool(not self.is_demo and not self._stopping and self._process
                    and self._process.state() == QProcess.ProcessState.Running)

    @property
    def syncing(self):
        return bool(self._awaiting_sync or self._cancelling
                    or self.snapshot.get("sync", {}).get("running"))

    @property
    def off_duty(self):
        return self.snapshot.get("schedule", {}).get("off_duty", False)

    @property
    def workday_pending(self):
        return self._workday_pending

    @property
    def cancelling(self):
        return self._cancelling

    @property
    def update_disabled(self):
        return (not self.available or self.syncing or self.off_duty
                or self._workday_pending
                or not self.snapshot.get("settings", {}).get("connection_setup_complete", False))

    def set_error(self, message):
        self.error = str(message)
        self.error_changed.emit(self.error)

    def start(self):
        if self.is_demo or (self._process and self._process.state() != QProcess.ProcessState.NotRunning):
            return
        self._stopping = False
        self._buffer.clear()
        self._stderr.clear()
        self.set_error("")
        if self._service_path is None:
            from .resources import backend_script
            try:
                self._service_path = backend_script()
            except (FileNotFoundError, ImportError) as error:
                self.set_error("找不到后端服务，请重新安装 coindex。" + str(error))
                self.state_changed.emit()
                return
        if not self._service_path.is_file():
            self.set_error("找不到后端服务，请重新安装 coindex。")
            self.state_changed.emit()
            return
        python = self._python or os.environ.get("CODEX_TODO_PYTHON")
        if not python:
            python = shutil.which("python3") if getattr(sys, "frozen", False) else sys.executable
        if not python:
            self.set_error("找不到 Python 3，请安装后点击重新启动服务。")
            return
        process = QProcess(self)
        self._process = process
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUNBUFFERED", "1")
        environment.insert("PYTHONDONTWRITEBYTECODE", "1")
        process.setProcessEnvironment(environment)
        process.setProgram(str(python))
        process.setArguments([str(self._service_path), "--data-dir", str(self.data_directory), "serve"])
        process.readyReadStandardOutput.connect(lambda: self._read_stdout(process))
        process.readyReadStandardError.connect(lambda: self._read_stderr(process))
        process.started.connect(lambda: self._started(process))
        process.errorOccurred.connect(lambda error: self._process_error(process, error))
        process.finished.connect(lambda code, status: self._finished(process, code))
        process.start()
        self.state_changed.emit()

    def _started(self, process):
        if process is self._process and not self._stopping:
            self._poll.start()
            self.state_changed.emit()
            self.refresh()

    def _read_stderr(self, process):
        data = bytes(process.readAllStandardError())
        if process is self._process:
            self._stderr.extend(data)
            self._stderr = self._stderr[-8192:]

    def _read_stdout(self, process):
        data = bytes(process.readAllStandardOutput())
        if process is not self._process:
            return
        self._buffer.extend(data)
        if len(self._buffer) > 32 * 1024 * 1024:
            self.set_error("服务响应过大，已停止连接。请重新启动服务。")
            process.terminate()
            return
        while b"\n" in self._buffer:
            line, _, remaining = self._buffer.partition(b"\n")
            self._buffer = bytearray(remaining)
            if not line.strip():
                continue
            try:
                envelope = json.loads(line)
                if not isinstance(envelope, dict) or type(envelope.get("id")) is not int:
                    raise ValueError("missing request id")
                request_id = envelope["id"]
            except (ValueError, UnicodeError):
                self.set_error("服务返回了无效的数据，等待中的操作将超时；请核对状态。")
                continue
            pending = self._pending.pop(request_id, None)
            if pending is None:
                continue  # Expired requests must never invoke a late callback.
            method, success, failure, timer = pending
            timer.stop()
            timer.deleteLater()
            if "error" in envelope:
                message = str(envelope["error"])
                self.set_error(message)
                if failure:
                    failure(message)
            elif "result" not in envelope:
                message = "服务响应缺少结果，请刷新核对。"
                if method not in READ_METHODS:
                    message += "操作结果未确认，请核对后再操作。"
                self.set_error(message)
                if failure:
                    failure(message)
            elif success:
                success(envelope["result"])

    def _process_error(self, process, error):
        if process is not self._process or self._stopping:
            return
        if error == QProcess.ProcessError.FailedToStart:
            self._lost_connection("采集服务无法启动：" + process.errorString())
            self._process = None
            process.deleteLater()

    def _finished(self, process, code):
        if process is not self._process:
            process.deleteLater()
            return
        self._read_stderr(process)
        self._poll.stop()
        if self._stopping:
            self._fail_pending("服务已关闭；操作结果未确认，请重新打开后核对。")
        else:
            detail = self._stderr.decode("utf-8", errors="replace").strip()
            if "已有" in detail or "already running" in detail or "lock" in detail.lower():
                message = "此数据目录已有 coindex 服务运行。请使用已打开的窗口，或退出该实例后重试。"
            else:
                message = f"采集服务已停止（{code}）。点击重新启动服务可恢复。"
                if detail:
                    message += "\n" + detail[-1500:]
            self._lost_connection(message)
        self._process = None
        process.deleteLater()
        self.state_changed.emit()

    def _fail_pending(self, message):
        pending, self._pending = self._pending, {}
        for method, success, failure, timer in pending.values():
            timer.stop()
            timer.deleteLater()
            if failure:
                failure(message)
        self._refreshing = False
        self._awaiting_sync = False
        self._cancelling = False
        self._workday_pending = False
        self._mutations.clear()
        self._requesting_nudges.clear()

    def _lost_connection(self, message):
        self._poll.stop()
        self._fail_pending(message + " 操作结果未确认，请刷新核对后再操作。")
        if self.snapshot:
            self.snapshot = {**self.snapshot, "sync": {"running": False, "phase": "服务已停止"}}
            self.snapshot_changed.emit(self.snapshot)
        self.set_error(message)
        self.state_changed.emit()

    def request(self, method, values=None, success=None, failure=None, timeout_ms=30000):
        if self.is_demo or not self.available:
            message = "演示模式仅供预览。" if self.is_demo else "采集服务未运行，请点击重新启动服务。"
            if failure:
                failure(message)
            self.notification.emit(message)
            return 0
        self._next_id += 1
        request_id = self._next_id
        request = dict(values or {})
        request.update(id=request_id, method=method)
        try:
            encoded = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
        except (TypeError, ValueError) as error:
            if failure:
                failure(str(error))
            return 0
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._timeout(request_id))
        self._pending[request_id] = (method, success, failure, timer)
        timer.start(timeout_ms)
        if self._process.write(encoded) == -1:
            self._timeout(request_id, "请求写入失败")
        return request_id

    def _timeout(self, request_id, reason="服务请求超时"):
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        method, success, failure, timer = pending
        timer.stop()
        timer.deleteLater()
        message = f"{reason}（{method}）。"
        if method not in READ_METHODS:
            message += "操作结果未确认，请刷新核对后再操作。"
        self.set_error(message)
        if failure:
            failure(message)

    def apply_snapshot(self, snapshot):
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("tasks"), list) or not isinstance(snapshot.get("settings"), dict):
            self.set_error("服务返回的快照不完整，请刷新核对。")
            return False
        previous = {entry.get("action_id"): entry.get("status") for entry in self.snapshot.get("nudges", [])}
        for entry in snapshot.get("nudges", []):
            conversation = entry.get("conversation_id")
            unknown = self._uncertain_nudges.get(conversation)
            if unknown and entry.get("action_id") == unknown.get("action_id"):
                self._uncertain_nudges.pop(conversation, None)
            if previous and previous.get(entry.get("action_id")) != entry.get("status"):
                if entry.get("status") == "sent":
                    self.notification.emit("催办已送达原对话")
                elif entry.get("status") in {"unknown", "failed"}:
                    self.notification.emit(self.nudge_summary(entry))
        self.snapshot = snapshot
        self.snapshot_changed.emit(snapshot)
        self.state_changed.emit()
        return True

    def refresh(self, check_automatic=False):
        if self.is_demo or not self.available or self._refreshing:
            return
        self._refreshing = True

        def done(result):
            self._refreshing = False
            if self.apply_snapshot(result) and check_automatic:
                if self.snapshot.get("schedule", {}).get("due") and not self.update_disabled:
                    self.sync(automatic=True)

        def failed(message):
            self._refreshing = False

        self.request("snapshot", success=done, failure=failed, timeout_ms=10000)

    def save_settings(self, values, success=None, failure=None):
        def done(result):
            if self.apply_snapshot(result):
                if success:
                    success(result)
            elif failure:
                failure("设置状态读取失败，请刷新核对。")
        return self.request("settings", {"values": values}, done, failure)

    def sync(self, force=False, automatic=False):
        if self.update_disabled:
            return
        self._awaiting_sync = True
        self.state_changed.emit()

        def done(result):
            self._awaiting_sync = False
            if isinstance(result, dict) and result.get("accepted"):
                self.snapshot = {**self.snapshot, "sync": {"running": True, "phase": "正在启动更新"}}
            self.state_changed.emit()
            self.refresh()

        def failed(message):
            self._awaiting_sync = False
            self.state_changed.emit()
            self.refresh()

        self.request("sync", {"force": force, "automatic": automatic}, done, failed)

    def cancel_sync(self):
        if not self.available or self._cancelling:
            return
        self._cancelling = True
        self.state_changed.emit()
        self._state_operation("cancel_sync", "已中止更新，自动更新已暂停")

    def toggle_workday(self):
        if not self.available or self._workday_pending:
            return
        self._workday_pending = True
        self.state_changed.emit()
        method = "resume_workday" if self.off_duty else "finish_workday"
        self._state_operation(method, "已提前上班" if self.off_duty else "已下班，更新暂停")

    def _state_operation(self, method, message):
        def clear():
            self._cancelling = False
            self._workday_pending = False
            self._awaiting_sync = False
            self.state_changed.emit()

        def done(result):
            clear()
            if self.apply_snapshot(result):
                self.notification.emit(message)

        def failed(error):
            clear()
            self.notification.emit(error)
            self.refresh()

        self.request(method, success=done, failure=failed)

    def entity_pending(self, entity_id):
        return entity_id in self._mutations

    def act(self, action, entity_id, value=None):
        if not self.available or self.entity_pending(entity_id):
            return
        self._mutations.add(entity_id)
        self.state_changed.emit()
        values = {"action": action, "entity_id": entity_id}
        if value is not None:
            values["value"] = value

        def clear():
            self._mutations.discard(entity_id)
            self.state_changed.emit()

        def done(result):
            clear()
            if self.apply_snapshot(result):
                self.notification.emit("已保存")

        def failed(message):
            clear()
            self.notification.emit(message)

        self.request("act", values, done, failed)

    def latest_nudge(self, task):
        conversation = task.get("conversation_id")
        if conversation in self._uncertain_nudges:
            return self._uncertain_nudges[conversation]
        entries = [entry for entry in self.snapshot.get("nudges", []) if entry.get("conversation_id") == conversation]
        return max(entries, key=lambda entry: entry.get("updated_at", 0), default=None)

    @staticmethod
    def nudge_summary(record):
        status = record.get("status")
        if status in {"queued", "sending"}:
            return "正在发送催办…"
        if status == "sent":
            return "催办已送达" + (" · " + record["attention"] if record.get("attention") else "")
        if status == "unknown":
            return "送达未确认，请核对原对话"
        if status == "failed":
            return "催办未发送：" + record.get("error", "")
        return "已核对上次催办"

    def nudge_pending(self, task):
        return (task.get("conversation_id") in self._requesting_nudges
                or (self.latest_nudge(task) or {}).get("status") in {"queued", "sending"})

    def nudge_disabled(self, task, retry_unknown=False):
        if (not self.available or task.get("status") != "open"
                or task.get("kind") == "manual" or self.nudge_pending(task)):
            return True
        record = self.latest_nudge(task) or {}
        if record.get("status") == "unknown" and not retry_unknown:
            return True
        return record.get("status") == "sent" and time.time() - record.get("updated_at", 0) < 30

    def nudge(self, task, retry_unknown=False):
        if self.nudge_disabled(task, retry_unknown):
            return
        conversation = task.get("conversation_id")
        action_id = str(uuid.uuid4())
        self._requesting_nudges.add(conversation)
        self.state_changed.emit()

        def done(result):
            self._requesting_nudges.discard(conversation)
            self._uncertain_nudges.pop(conversation, None)
            if not self.apply_snapshot(result):
                failed("催办状态读取失败，结果未确认，请先核对原对话。")
            self.state_changed.emit()

        def failed(message):
            self._requesting_nudges.discard(conversation)
            if "结果未确认" in message:
                self._uncertain_nudges[conversation] = {
                    "action_id": action_id, "conversation_id": conversation,
                    "status": "unknown", "error": message, "updated_at": time.time(),
                }
            self.notification.emit(message)
            self.state_changed.emit()

        self.request("nudge", {"entity_id": task["id"], "action_id": action_id,
                               "retry_unknown": retry_unknown}, done, failed)

    def restart(self):
        if self.is_demo:
            return
        self.shutdown()
        self.start()

    def shutdown(self):
        self._stopping = True
        self._poll.stop()
        process = self._process
        if process and process.state() != QProcess.ProcessState.NotRunning:
            process.closeWriteChannel()
            if not process.waitForFinished(1500):
                process.terminate()
                if not process.waitForFinished(5000):
                    process.kill()
                    process.waitForFinished(1000)
        self._fail_pending("服务已关闭；操作结果未确认，请重新打开后核对。")
        self.state_changed.emit()
