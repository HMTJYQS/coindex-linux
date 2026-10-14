"""Explicit user-click reminders through the existing Codex desktop owner."""
import json
import os
import pathlib
import socket
import stat
import struct
import time
import uuid
from connections import codex_home, desktop_host_id, profile, normalize_remote
import platforms


class NudgeError(RuntimeError):
    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


def reminder(task):
    lines = ["用户通过 coindex 点击了一键催办。请结合本对话最新上下文核对当前进展，继续推进这项工作尚未完成的下一步。",
             "正在执行时沿现有任务继续，避免重复提交。等待外部结果时检查已有任务；已完成时汇报实际结果及核对依据。",
             "沿用本对话已有要求和授权；缺少选择、参数或审批时说明具体阻塞，不能替用户决定或绕过审批。",
             "以下是此前记录的待办摘要，仅用于定位工作，进度可能已经变化，请以当前会话和实际结果为准。",
             "任务：" + task["title"], "此前进度：" + task["progress"], "建议下一步：" + task["next_action"]]
    if task["artifact"]:
        lines.append("对应任务或产物：" + task["artifact"])
    return "\n".join(lines)


class DesktopIPC:
    def __init__(self, path=None):
        root = pathlib.Path(os.environ.get("CODEX_HOME") or pathlib.Path.home()/".codex")
        self.path = pathlib.Path(path) if path else root/"ipc/ipc.sock"
        self.socket = None
        self.client_id = None

    def connect(self):
        try:
            info = self.path.lstat()
            parent = self.path.parent.stat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or parent.st_uid != os.getuid() or parent.st_mode & 0o022:
                raise NudgeError("Codex 对话连接的权限不安全，请在桌面端检查")
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.socket.settimeout(3)
            self.socket.connect(str(self.path))
            response = self.request("initialize", {"clientType": "codex-todo"}, version=0)
            if response.get("resultType") != "success" or not response.get("handledByClientId"):
                raise NudgeError("Codex 桌面对话连接未就绪，请打开 Codex 后重试")
            self.client_id = response["handledByClientId"]
            return self
        except NudgeError:
            self.close()
            raise
        except (OSError, ValueError) as error:
            self.close()
            raise NudgeError("无法连接 Codex 桌面端，请打开 Codex 后重试") from error

    def close(self):
        if self.socket:
            self.socket.close()
            self.socket = None

    def write(self, value):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.socket.sendall(struct.pack("<I", len(data)) + data)

    def read(self, deadline):
        def exact(count):
            parts = bytearray()
            while len(parts) < count:
                self.socket.settimeout(max(0.01, deadline-time.monotonic()))
                data = self.socket.recv(count-len(parts))
                if not data:
                    raise ConnectionError("Codex 对话连接已断开")
                parts.extend(data)
            return parts
        size = struct.unpack("<I", exact(4))[0]
        if not 0 < size <= 32*1024*1024:
            raise ValueError("Codex 对话连接数据异常")
        message = json.loads(exact(size))
        if message.get("type") == "client-discovery-request":
            self.write({"type": "client-discovery-response", "requestId": message["requestId"], "response": {"canHandle": False}})
        return message

    def request(self, method, params, version=1, owner=None, host_id=None, timeout=12):
        request_id = str(uuid.uuid4())
        value = {"type": "request", "requestId": request_id, "sourceClientId": self.client_id,
                 "method": method, "params": params, "version": version,
                 "timeoutMs": int(timeout*1000)-250}
        if owner:
            value["targetClientId"] = owner
        if host_id and host_id != "local":
            value["hostId"] = host_id
            if method.startswith("thread-follower-"):
                value["version"] += 1
        self.write(value)
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            response = self.read(deadline)
            if response.get("type") == "response" and response.get("requestId") == request_id:
                return response
        raise TimeoutError("Codex 响应超时")

    def owner(self, host_id, thread_id):
        response = self.request("thread-owner-discovery", {"hostId": host_id, "conversationId": thread_id}, timeout=3)
        if response.get("resultType") == "success":
            return response.get("handledByClientId")
        if response.get("error") == "no-client-found":
            return None
        raise NudgeError("无法确认原对话的连接，请在 Codex 中打开该对话后重试")

    def state(self, host_id, thread_id, owner):
        params = {"hostId": host_id, "conversationId": thread_id, "following": True}
        message = {"type": "broadcast", "sourceClientId": self.client_id,
                   "method": "thread-stream-following-changed", "version": 1,
                   "targetClientIds": [owner], "params": params}
        self.write(message)
        deadline = time.monotonic()+6
        try:
            while time.monotonic() < deadline:
                event = self.read(deadline)
                p = event.get("params") or {}
                if event.get("type") == "broadcast" and event.get("method") == "thread-stream-state-changed" and event.get("version") == 11 and event.get("sourceClientId") == owner and p.get("hostId") == host_id and p.get("conversationId") == thread_id and p.get("change", {}).get("type") == "snapshot":
                    return p["change"]["conversationState"]
            raise TimeoutError("未取得原对话的当前状态")
        finally:
            params["following"] = False
            try:
                self.write(message)
            except OSError:
                pass


def dispatch_remote(task, action_id, rpc_factory=None, accepted=None, attention=None, settings=None):
    from remote_rpc import RemoteRPC
    rpc = rpc_factory(task["host"]) if rpc_factory else RemoteRPC(task["host"], profile=profile(settings, task["host"]) if settings is not None else None)
    rpc.on_attention = attention
    rpc.thread_id = task["thread_id"]
    attempted = False
    confirmed = None
    try:
        rpc.connect()
        thread_id = task["thread_id"]
        rpc.call("thread/resume", {"threadId": thread_id, "excludeTurns": True})
        thread = rpc.call("thread/read", {"threadId": thread_id, "includeTurns": False})["thread"]
        phase = (thread.get("status") or {}).get("type")
        if phase not in ("active", "idle"):
            raise NudgeError("原对话当前状态尚未就绪，请在 Codex 中打开后重试")
        inputs = [{"type": "text", "text": reminder(task)}]
        if phase == "active":
            page = rpc.call("thread/turns/list", {"threadId": thread_id, "limit": 1, "sortDirection": "desc", "itemsView": "full"})
            turn = next((t for t in page.get("data", []) if t.get("status") == "inProgress"), None)
            if not turn:
                raise NudgeError("原对话的执行状态已变化，请核对后重新催办")
            method = "turn/steer"
            params = {"threadId": thread_id, "expectedTurnId": turn["id"], "input": inputs}
        else:
            method = "turn/start"
            params = {"threadId": thread_id, "input": inputs, "clientUserMessageId": action_id}
        attempted = True
        result = rpc.call(method, params)
        turn_id = result.get("turnId") if phase == "active" else (result.get("turn") or {}).get("id")
        if not turn_id:
            raise NudgeError("催办送达状态未确认，请先核对原对话", uncertain=True)
        confirmed = {"delivery": "steered" if phase == "active" else "started", "turn_id": turn_id}
        if accepted:
            accepted(confirmed)
            rpc.follow(thread_id, turn_id)
        return confirmed
    except NudgeError:
        raise
    except Exception as error:
        if confirmed:
            return confirmed
        raise NudgeError("催办送达状态未确认，请先核对原对话" if attempted else "无法连接该机器的 Codex 对话服务，请检查 SSH 与 Codex 连接", uncertain=attempted) from error
    finally:
        rpc.close()


def dispatch(task, action_id, ipc_factory=DesktopIPC, open_thread=None, accepted=None, attention=None, settings=None):
    try:
        host_id = desktop_host_id(settings, task["host"]) if settings is not None else ("local" if task["host"] == "mac" else "remote-ssh-discovered:" + normalize_remote({"id": task["host"]})["id"])
    except ValueError as error:
        raise NudgeError("待办缺少有效的原对话来源") from error
    try:
        valid = str(uuid.UUID(task["thread_id"])) == task["thread_id"]
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not host_id or not valid:
        raise NudgeError("待办缺少有效的原对话来源")
    if task["host"] != "mac":
        return dispatch_remote(task, action_id, accepted=accepted, attention=attention, settings=settings)
    ipc = (DesktopIPC(codex_home(settings)/"ipc/ipc.sock") if settings is not None and ipc_factory is DesktopIPC else ipc_factory()).connect()
    attempted = False
    try:
        owner = ipc.owner(host_id, task["thread_id"])
        if not owner and open_thread:
            open_thread(task["thread_id"], host_id)
            deadline = time.monotonic()+15
            while not owner and time.monotonic() < deadline:
                time.sleep(0.3)
                owner = ipc.owner(host_id, task["thread_id"])
        if not owner:
            raise NudgeError("请在 Codex 中打开原对话，等待加载完成后再催办")
        state = ipc.state(host_id, task["thread_id"], owner)
        runtime = state.get("threadRuntimeStatus") or {}
        if runtime.get("type") not in ("active", "idle"):
            raise NudgeError("原对话当前状态尚未就绪，请在 Codex 中核对")
        text = reminder(task)
        inputs = [{"type": "text", "text": text}]
        active = runtime["type"] == "active"
        if active:
            method, version = "thread-follower-steer-turn", 1
            params = {"conversationId": task["thread_id"], "clientUserMessageId": action_id, "input": inputs, "attachments": [],
                      "restoreMessage": {"id": action_id, "text": text, "context": {"prompt": text, "addedFiles": [], "fileAttachments": [], "imageAttachments": [], "workspaceRoots": []}, "createdAt": int(time.time()*1000)}}
        else:
            method, version = "thread-follower-start-turn", 2
            params = {"conversationId": task["thread_id"], "turnStart": {
                "request": {"threadId": task["thread_id"], "input": inputs, "clientUserMessageId": action_id},
                "context": {"inheritThreadSettings": True}}}
        attempted = True
        response = ipc.request(method, params, version=version, owner=owner, host_id=host_id)
        if response.get("resultType") != "success":
            raise NudgeError("催办未获送达确认，请先打开原对话核对，避免重复发送", uncertain=True)
        result = (response.get("result") or {}).get("result")
        turn_id = (result or {}).get("turnId") if active else ((result or {}).get("turn") or {}).get("id")
        if not turn_id:
            raise NudgeError("催办送达状态未确认，请先核对原对话", uncertain=True)
        return {"delivery": "steered" if active else "started", "turn_id": turn_id}
    except NudgeError:
        raise
    except Exception as error:
        raise NudgeError("催办送达状态未确认，请先核对原对话" if attempted else "未能连接原对话，请打开 Codex 后重试", uncertain=attempted) from error
    finally:
        ipc.close()


def open_desktop_thread(thread_id, host_id, app=""):
    return platforms.open_desktop_thread(thread_id, host_id, app)


def run_nudge(folder, action_id):
    from store import Store
    from collector import redact
    store = Store(folder)
    record = store.nudge(action_id)
    if not record or record["status"] != "queued":
        store.db.close()
        return
    try:
        task = store.nudge_target(record["task_id"])
        settings = store.settings()
        store.finish_nudge(action_id, "sending")
        result = dispatch(task, action_id, settings=settings, open_thread=lambda thread, host: open_desktop_thread(thread, host, settings["codex_app"]),
                          accepted=lambda result: store.finish_nudge(action_id, "sent", result=result),
                          attention=lambda text: store.nudge_attention(action_id, text))
        store.finish_nudge(action_id, "sent", result=result)
    except Exception as error:
        store.finish_nudge(action_id, "unknown" if getattr(error, "uncertain", False) else "failed", error=redact(str(error))[:500])
    finally:
        store.db.close()
