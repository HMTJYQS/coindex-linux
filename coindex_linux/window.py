"""The Linux task workbench; backend snapshots remain the source of truth."""

from __future__ import annotations

from datetime import datetime
import html
import re
import time
from zoneinfo import ZoneInfo

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QKeySequence, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QSplitter, QTextBrowser, QTextEdit,
    QVBoxLayout, QWidget,
)

from .desktop import open_data_directory, open_thread


KINDS = {"running": "进行中", "review": "结果校对", "continue": "继续推进",
         "wait": "等待结果", "decision": "需要决定", "manual": "手动待办"}
FILTERS = [("all", "全部待办"), *KINDS.items(), ("snoozed", "稍后处理"),
           ("completed", "已完成 / 已忽略"), ("conversations", "所有对话")]


def filtered_tasks(snapshot, category="all", host="all", search="", now=None):
    """Match status separately from kind, including expiration of snoozes."""
    now = time.time() if now is None else now
    result = []
    for task in snapshot.get("tasks", []):
        opened = task.get("status") == "open"
        snoozed = task.get("snoozed_until", 0) > now
        if category == "completed":
            matches = not opened
        elif category == "snoozed":
            matches = opened and snoozed
        else:
            matches = opened and not snoozed and (category == "all" or task.get("kind") == category)
        text = " ".join(str(task.get(key) or "") for key in
                        ("title", "detail", "conversation_title", "artifact", "progress", "next_action"))
        if matches and (host == "all" or task.get("host") == host) and search.casefold() in text.casefold():
            result.append(task)
    return result


def relative_time(stamp):
    if not stamp:
        return "尚未同步"
    seconds = max(0, int(time.time() - stamp))
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{seconds // 60} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    return f"{seconds // 86400} 天前"


def schedule_time(stamp):
    if not stamp:
        return "等待日程数据"
    return datetime.fromtimestamp(stamp, ZoneInfo("Asia/Shanghai")).strftime("%m月%d日 %H:%M") + " 北京时间"


def conversation_state(conversation):
    if conversation.get("archived"):
        return "已归档，不再跟踪"
    if conversation.get("closed"):
        return "手动结束"
    if conversation.get("execution_state") == "running":
        return "进行中 · 待整理" if conversation.get("needs_analysis") else "进行中"
    if conversation.get("needs_analysis"):
        return "待整理最新进度"
    return {"running": "进行中", "submitted": "已提交", "unfinished": "未完成",
            "waiting": "等待中", "completed": "已完成", "informational": "已处理",
            "uncertain": "需确认"}.get(conversation.get("analysis_state"), "待分析")


def rich_text(value):
    # Links in model output are data. Only explicit HTTP(S) links are active.
    escaped = html.escape(str(value or ""))
    escaped = re.sub(r"https?://[^\s<>]+", lambda match: '<a href="' + match[0] + '">' + match[0] + '</a>', escaped)
    return escaped.replace("\n", "<br>")


class ManualTodoDialog(QDialog):
    def __init__(self, client, task=None, parent=None):
        super().__init__(parent)
        self.client = client
        self.task = task or {}
        self.setWindowTitle("编辑待办" if task else "新建待办")
        self.resize(520, 360)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.title_edit = QLineEdit(self.task.get("title", ""))
        self.title_edit.setObjectName("manualTitle")
        self.title_edit.setMaxLength(100)
        self.note_edit = QTextEdit()
        self.note_edit.setAcceptRichText(False)
        self.note_edit.setPlainText(self.task.get("detail", ""))
        self.priority = QComboBox()
        for value, label in [(1, "优先处理"), (2, "一般"), (3, "低优先")]:
            self.priority.addItem(label, value)
        self.priority.setCurrentIndex(max(0, min(2, self.task.get("priority", 2) - 1)))
        form.addRow("要做什么", self.title_edit)
        form.addRow("备注", self.note_edit)
        form.addRow("优先级", self.priority)
        layout.addLayout(form)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #af4436")
        layout.addWidget(self.error_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.title_edit.textChanged.connect(self._validate)
        self._validate()

    def _validate(self):
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(bool(self.title_edit.text().strip()) and self.client.available)

    def save(self):
        if not self.title_edit.text().strip() or not self.client.available:
            return
        self.buttons.setEnabled(False)
        values = {"title": self.title_edit.text().strip(), "detail": self.note_edit.toPlainText(),
                  "priority": self.priority.currentData()}
        if self.task.get("id"):
            values["entity_id"] = self.task["id"]

        def done(result):
            if isinstance(result, dict) and self.client.apply_snapshot(result.get("snapshot")):
                self.accept()
            else:
                failed("保存结果读取失败，请关闭窗口后刷新核对。")

        def failed(message):
            self.error_label.setText(message)
            self.buttons.setEnabled(True)
            self._validate()

        self.client.request("save_manual", values, done, failed)


class MainWindow(QMainWindow):
    closed_to_tray = Signal()

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self.category = "all"
        self.selected_id = None
        self.tray_available = False
        self.force_quit = False
        self._setup_offered = False
        self._settings_dialog = None
        self._rendering = False
        self._setup_timer = QTimer(self)
        self._setup_timer.setSingleShot(True)
        self._setup_timer.timeout.connect(self.open_settings)
        self.setWindowTitle("coindex · Linux" + (" · 演示" if client.is_demo else ""))
        self.resize(1250, 820)
        self.setMinimumSize(980, 660)
        self.setStyleSheet("""
            QMainWindow, QDialog { background: #f4f5f2; color: #24352c; }
            QLabel { color: #24352c; }
            QPushButton { background: #ffffff; border: 1px solid #d5ddd6; border-radius: 6px;
                          padding: 7px 11px; color: #294c3b; }
            QPushButton:hover { background: #e8eee8; }
            QPushButton:disabled { color: #929b95; background: #f1f2f0; }
            QPushButton#primary { color: white; background: #356448; border-color: #356448; }
            QPushButton#primary:disabled { color: #edf1ed; background: #aab8ae; border-color: #aab8ae; }
            QLineEdit, QComboBox { background: white; border: 1px solid #d5ddd6;
                                   border-radius: 6px; padding: 7px; }
            QListWidget { background: #f4f5f2; border: 0; outline: 0; }
            QListWidget::item { padding: 12px; margin: 4px 0; background: white;
                               border: 1px solid #e0e5df; border-radius: 8px; }
            QListWidget::item:selected { background: #e5eee5; color: #24352c; border-color: #64806a; }
            QListWidget#navigation::item { background: transparent; border: 0; padding: 10px; margin: 1px; }
            QListWidget#navigation::item:selected { background: #dfe9df; color: #294c3b; }
            QTextBrowser { background: white; border: 1px solid #e0e5df; border-radius: 8px; padding: 10px; }
            QStatusBar { background: #e9eee8; color: #46564c; }
        """)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 18, 18, 8)
        header = QHBoxLayout()
        brand = QLabel("coindex")
        brand.setStyleSheet("font-size: 26px; font-weight: 700; color: #294c3b")
        header.addWidget(brand)
        header.addWidget(QLabel("让每件事有下一步"))
        header.addStretch()
        self.workday_button = self._button("下班", client.toggle_workday)
        self.cancel_button = self._button("中止更新", client.cancel_sync)
        self.sync_button = self._button("立即更新", lambda: client.sync())
        self.sync_button.setObjectName("primary")
        self.manual_button = self._button("＋ 新建待办", lambda: self.edit_manual())
        self.settings_button = self._button("设置", self.open_settings)
        for widget in (self.workday_button, self.cancel_button, self.sync_button, self.manual_button, self.settings_button):
            header.addWidget(widget)
        layout.addLayout(header)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error_label.setStyleSheet("background: #fff1da; color: #855717; padding: 10px; border-radius: 6px;")
        error_row = QHBoxLayout()
        error_row.addWidget(self.error_label, 1)
        self.restart_button = self._button("重新启动服务", client.restart)
        error_row.addWidget(self.restart_button)
        layout.addLayout(error_row)
        splitter = QSplitter()
        layout.addWidget(splitter, 1)
        sidebar = QWidget()
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 8, 8, 0)
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setAccessibleName("待办分类")
        for key, label in FILTERS:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.navigation.addItem(item)
        self.navigation.setCurrentRow(0)
        self.navigation.currentItemChanged.connect(self._category_changed)
        side.addWidget(self.navigation, 1)
        side.addWidget(QLabel("会话来源"))
        self.host_combo = QComboBox()
        self.host_combo.setAccessibleName("按主机筛选")
        self.host_combo.addItem("所有机器", "all")
        self.host_combo.currentIndexChanged.connect(self.render_list)
        side.addWidget(self.host_combo)
        from .pets import PetWidget
        self.pet_widget = PetWidget(client.snapshot, self)
        self.pet_widget.motion.setEnabled(not client.is_demo)
        self.pet_widget.float_button.setEnabled(not client.is_demo)
        side.addWidget(self.pet_widget)
        self.model_label = QLabel()
        self.model_label.setWordWrap(True)
        side.addWidget(self.model_label)
        splitter.addWidget(sidebar)
        center = QWidget()
        middle = QVBoxLayout(center)
        middle.setContentsMargins(8, 8, 8, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索待办、进度或对话")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.render_list)
        middle.addWidget(self.search)
        self.list_heading = QLabel("全部待办")
        self.list_heading.setStyleSheet("font-size: 18px; font-weight: 600; padding: 8px 0")
        middle.addWidget(self.list_heading)
        self.items = QListWidget()
        self.items.setObjectName("taskList")
        self.items.setWordWrap(True)
        self.items.setSpacing(3)
        self.items.currentItemChanged.connect(self._selected)
        middle.addWidget(self.items, 1)
        self.empty_label = QLabel("暂无待办\n点击更新，或新建一项手动待办。")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #77817a; font-size: 16px; padding: 36px")
        middle.addWidget(self.empty_label)
        splitter.addWidget(center)
        details = QWidget()
        right = QVBoxLayout(details)
        right.setContentsMargins(8, 8, 0, 0)
        self.details = QTextBrowser()
        self.details.setObjectName("taskDetails")
        self.details.setOpenExternalLinks(False)
        self.details.setOpenLinks(False)
        self.details.anchorClicked.connect(self._open_link)
        right.addWidget(self.details, 1)
        self.nudge_receipt = QLabel()
        self.nudge_receipt.setWordWrap(True)
        self.nudge_receipt.setTextFormat(Qt.TextFormat.PlainText)
        self.nudge_receipt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right.addWidget(self.nudge_receipt)
        self.detail_buttons = {}
        for row in [[("complete", "完成", self.complete), ("snooze", "稍后一小时", lambda: self.task_action("snooze", 60)), ("dismiss", "忽略", lambda: self.task_action("dismiss"))],
                    [("rename", "修改标题", self.rename), ("edit", "编辑待办", lambda: self.edit_manual(self.selected_task()))],
                    [("nudge", "一键催办", self.nudge), ("retry", "确认未送达后重试", self.retry_nudge)],
                    [("open", "打开 Codex", self.open_conversation), ("copy", "复制下一步", self.copy_next)],
                    [("source", "复制来源", self.copy_source), ("tracking", "结束跟踪", self.toggle_tracking)]]:
            buttons = QHBoxLayout()
            for key, label, callback in row:
                button = self._button(label, callback)
                button.setObjectName(key + "Button")
                self.detail_buttons[key] = button
                buttons.addWidget(button)
            right.addLayout(buttons)
        splitter.addWidget(details)
        splitter.setSizes([195, 565, 400])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 1)
        self.status_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_label, 1)
        operations = self.menuBar().addMenu("操作")
        operations.addAction("重新读取状态", lambda: client.refresh())
        self.force_sync_action = operations.addAction("重新分析未结束对话", lambda: client.sync(force=True))
        operations.addAction("打开数据文件夹", self.open_data)
        self._add_shortcut("新建待办", "Ctrl+N", lambda: self.edit_manual())
        self._add_shortcut("立即更新", "Ctrl+R", lambda: client.sync())
        self._add_shortcut("搜索", "Ctrl+F", self.search.setFocus)
        self._add_shortcut("设置", "Ctrl+,", self.open_settings)
        self._add_shortcut("退出", "Ctrl+Q", QApplication.instance().quit)
        client.snapshot_changed.connect(self.apply_snapshot)
        client.state_changed.connect(self.update_state)
        client.error_changed.connect(lambda message: self.update_state())
        client.notification.connect(lambda message: self.statusBar().showMessage(message, 8000))
        self.apply_snapshot(client.snapshot)

    @staticmethod
    def _button(text, callback):
        button = QPushButton(text)
        button.clicked.connect(lambda checked=False: callback())
        return button

    def _add_shortcut(self, title, shortcut, callback):
        action = QAction(title, self)
        action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(lambda checked=False: callback())
        self.addAction(action)

    def _category_changed(self, current, previous):
        if current:
            self.category = current.data(Qt.ItemDataRole.UserRole)
            self.selected_id = None
            self.render_list()

    def host_name(self, host_id):
        for host in self.client.snapshot.get("hosts", []):
            if host.get("id") == host_id:
                return host.get("name") or ("本机" if host_id in {"mac", "local"} else host_id)
        return {"mac": "本机", "local": "本机", "manual": "手动添加"}.get(host_id, host_id or "")

    def apply_snapshot(self, snapshot):
        selected_host = self.host_combo.currentData() or "all"
        self.host_combo.blockSignals(True)
        self.host_combo.clear()
        self.host_combo.addItem("所有机器", "all")
        for host in snapshot.get("hosts", []):
            self.host_combo.addItem(self.host_name(host["id"]), host["id"])
        index = self.host_combo.findData(selected_host)
        self.host_combo.setCurrentIndex(index if index >= 0 else 0)
        self.host_combo.blockSignals(False)
        for row, (key, label) in enumerate(FILTERS):
            count = len(snapshot.get("conversations", [])) if key == "conversations" else len(filtered_tasks(snapshot, key))
            self.navigation.item(row).setText(f"{label}  {count}")
        self.pet_widget.set_snapshot(snapshot)
        self.render_list()
        self.update_state()
        if (snapshot and not self.client.is_demo and not self._setup_offered
                and snapshot.get("settings", {}).get("connection_setup_complete") is False):
            self._setup_offered = True
            self._setup_timer.start(0)

    def render_list(self, *_):
        if self._rendering:
            return
        self._rendering = True
        scroll = self.items.verticalScrollBar().value()
        self.items.blockSignals(True)
        self.items.clear()
        snapshot = self.client.snapshot
        host, search = self.host_combo.currentData() or "all", self.search.text()
        if self.category == "conversations":
            entries = [entry for entry in snapshot.get("conversations", [])
                       if (host == "all" or entry.get("host") == host)
                       and search.casefold() in (entry.get("title", "") + " " + entry.get("summary", "")).casefold()]
        else:
            entries = filtered_tasks(snapshot, self.category, host, search)
        selected = None
        for entry in entries:
            if self.category == "conversations":
                label = (f"{conversation_state(entry)} · {self.host_name(entry.get('host'))}\n"
                         f"{entry.get('title', '')}\n{entry.get('summary') or '等待分析最近记录'}")
            else:
                state = KINDS.get(entry.get("kind"), entry.get("kind", ""))
                progress = entry.get("detail", "") if entry.get("kind") == "manual" else entry.get("progress") or "停止位置待整理"
                label = (f"{state} · {self.host_name(entry.get('host'))} · P{entry.get('priority', 2)}\n"
                         f"{entry.get('title', '')}\n{progress[:180]}")
                if entry.get("kind") != "manual":
                    label += "\n下一步：" + entry.get("next_action", "")[:140]
                if entry.get("title_override"):
                    label += "\n✎ 手动标题"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, entry["id"])
            self.items.addItem(item)
            if entry["id"] == self.selected_id:
                selected = item
        if selected:
            self.items.setCurrentItem(selected)
        else:
            self.selected_id = None
        self.items.blockSignals(False)
        self.items.verticalScrollBar().setValue(scroll)
        self.list_heading.setText(dict(FILTERS)[self.category] + f" · {len(entries)}")
        self.empty_label.setVisible(not entries)
        self.items.setVisible(bool(entries))
        self.empty_label.setText("没有匹配的记录，试试其他关键词。" if search else
                                 "暂无记录\n可以新建待办，或在连接就绪后更新。")
        self._rendering = False
        self.render_detail()

    def _selected(self, current, previous):
        self.selected_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.render_detail()

    def selected_task(self):
        if self.category == "conversations":
            return None
        return next((task for task in self.client.snapshot.get("tasks", []) if task.get("id") == self.selected_id), None)

    def selected_conversation(self):
        if self.category != "conversations":
            return None
        return next((entry for entry in self.client.snapshot.get("conversations", []) if entry.get("id") == self.selected_id), None)

    def render_detail(self):
        task, conversation = self.selected_task(), self.selected_conversation()
        for button in self.detail_buttons.values():
            button.hide()
        self.nudge_receipt.hide()
        if not task and not conversation:
            self.details.setHtml("<h2>每件事，都有下一步。</h2><p>选择一项待办，查看进度、下一步和原始依据。</p>")
            return
        entry = task or conversation
        body = "<h2>" + html.escape(entry.get("title", "")) + "</h2>"
        if conversation:
            body += "<p>" + conversation_state(conversation) + " · " + html.escape(self.host_name(conversation.get("host"))) + "</p>"
            body += "<p>" + rich_text(conversation.get("summary")) + "</p>"
            visible = ["open", "source"]
            if not conversation.get("archived"):
                visible.append("tracking")
                self.detail_buttons["tracking"].setText("恢复跟踪" if conversation.get("closed") else "结束跟踪")
        else:
            body += "<p>" + html.escape(KINDS.get(task.get("kind"), "待办")) + " · " + html.escape(self.host_name(task.get("host"))) + "</p>"
            if task.get("snoozed_until", 0) > time.time():
                body += "<p>稍后至：" + schedule_time(task["snoozed_until"]) + "</p>"
            body += "<p>" + rich_text(task.get("detail")) + "</p>"
            visible = ["complete", "rename"]
            opened, manual = task.get("status") == "open", task.get("kind") == "manual"
            self.detail_buttons["complete"].setText("完成" if opened else "恢复待办")
            if opened:
                visible += ["snooze", "dismiss"]
            if manual:
                visible += ["edit"]
            else:
                for heading, value in [("当前进度" if task.get("kind") == "running" else "停住位置", task.get("progress") or "停止位置待整理"),
                                       ("下一步", task.get("next_action")), ("对应结果", task.get("artifact")),
                                       ("原文依据", task.get("evidence"))]:
                    if value:
                        body += "<h3>" + heading + "</h3><p>" + rich_text(value) + "</p>"
                confidence = task.get("confidence", 0)
                body += f"<p>判断把握 {int(confidence * 100)}% · 来源于对话最后记录</p>"
                if task.get("title_override"):
                    body += "<p>✎ 手动标题：自动更新不会覆盖</p>"
                visible += ["open", "copy", "source"]
                if opened:
                    visible += ["nudge"]
                record = self.client.latest_nudge(task)
                if record:
                    receipt = self.client.nudge_summary(record)
                    if record.get("error"):
                        receipt += "\n" + record["error"]
                    self.nudge_receipt.setText(receipt)
                    self.nudge_receipt.show()
                    if record.get("status") == "unknown" and opened:
                        visible += ["retry"]
            body += "<p>最近更新：" + relative_time(task.get("conversation_updated_at") or task.get("updated_at", 0)) + "</p>"
        if entry.get("cwd"):
            body += "<h3>原始对话</h3><p>" + rich_text(entry.get("conversation_title") or entry.get("title")) + "</p><p>" + rich_text(entry["cwd"]) + "</p>"
        if entry.get("thread_id"):
            body += "<p>" + html.escape(entry["thread_id"]) + "</p>"
        scroll = self.details.verticalScrollBar().value()
        self.details.setHtml('<style>body {color:#283b30;font-size:13px;} h2 {font-size:21px;} h3 {font-size:13px;color:#477150;margin-top:22px;} a {color:#326d51;} p {line-height:1.6;}</style>' + body)
        self.details.verticalScrollBar().setValue(scroll)
        for key in visible:
            self.detail_buttons[key].show()
        self._update_detail_state()

    def _update_detail_state(self):
        task, conversation = self.selected_task(), self.selected_conversation()
        entry = task or conversation
        for key, button in self.detail_buttons.items():
            button.setEnabled(bool(entry) and (key in {"open", "copy", "source"} or
                              (self.client.available and not self.client.entity_pending(entry["id"])) ))
        if task:
            self.detail_buttons["nudge"].setEnabled(not self.client.nudge_disabled(task))
            self.detail_buttons["nudge"].setText("发送中…" if self.client.nudge_pending(task) else "一键催办")
            self.detail_buttons["retry"].setEnabled(not self.client.nudge_disabled(task, retry_unknown=True))

    def update_state(self):
        client, snapshot = self.client, self.client.snapshot
        self.sync_button.setEnabled(not client.update_disabled)
        self.force_sync_action.setEnabled(not client.update_disabled)
        self.sync_button.setText("更新中…" if client.syncing else "立即更新")
        self.cancel_button.setVisible(client.syncing)
        self.cancel_button.setEnabled(client.available and not client.cancelling)
        self.workday_button.setText("提前上班" if client.off_duty else "下班")
        self.workday_button.setEnabled(client.available and not client.workday_pending)
        self.manual_button.setEnabled(client.available)
        self.restart_button.setVisible(not client.available and not client.is_demo)
        model_error = snapshot.get("model_error", "")
        error = "\n".join(value for value in (client.error, model_error) if value)
        if client.is_demo:
            error = "演示模式：仅预览固定数据，分析、发送和保存均已禁用。"
        elif snapshot and not snapshot.get("settings", {}).get("connection_setup_complete", False):
            error = "请先在设置中保存并检查 Codex 连接，再开始整理。" + ("\n" + error if error else "")
        self.error_label.setText(error)
        self.error_label.setVisible(bool(error))
        self.model_label.setText(f"{snapshot.get('model', '')}\n{snapshot.get('effort', '')} · " +
                                 ("已下班" if client.off_duty else "自动更新" if snapshot.get("settings", {}).get("automatic") else "自动更新暂停"))
        if client.off_duty:
            status = "已下班 · " + schedule_time(snapshot.get("schedule", {}).get("off_duty_until")) + " 恢复"
        elif client.syncing:
            status = "正在中止…" if client.cancelling else snapshot.get("sync", {}).get("phase", "正在更新…")
        else:
            status = "上次更新：" + relative_time(snapshot.get("last_sync", 0))
            if snapshot.get("settings", {}).get("automatic"):
                status += " · 下次：" + schedule_time(snapshot.get("schedule", {}).get("next_at"))
        pending = snapshot.get("pending_analysis", 0)
        backlog = sum(host.get("remaining_files", 0) for host in snapshot.get("hosts", []))
        if pending:
            status += f" · 待分析 {pending}"
        if backlog:
            status += f" · 历史回填 {backlog} 个文件"
        self.status_label.setText(status)
        self.render_detail()

    def task_action(self, action, value=None):
        task = self.selected_task()
        if task:
            self.client.act(action, task["id"], value)

    def complete(self):
        task = self.selected_task()
        if task:
            self.task_action("complete" if task.get("status") == "open" else "reopen")

    def edit_manual(self, task=None):
        if not self.client.available:
            return
        dialog = ManualTodoDialog(self.client, task, self)
        dialog.exec()

    def rename(self):
        task = self.selected_task()
        if not task or not self.client.available:
            return
        title, accepted = QInputDialog.getText(self, "修改标题", "标题（最多 100 字，自动更新不会覆盖）", text=task.get("title", ""))
        if not accepted:
            return
        title = title.strip()
        if not title or len(title) > 100:
            self.client.notification.emit("标题不能为空且不能超过 100 字。")
            return

        def done(result):
            if isinstance(result, dict):
                self.client.apply_snapshot(result.get("snapshot"))
                self.client.notification.emit("标题已保存")

        self.client.request("rename_task", {"entity_id": task["id"], "title": title}, done,
                            lambda message: self.client.notification.emit(message))

    def nudge(self):
        task = self.selected_task()
        if task:
            self.client.nudge(task)

    def retry_nudge(self):
        task = self.selected_task()
        if not task:
            return
        answer = QMessageBox.question(self, "确认重试催办", "请先打开原对话核对消息。\n确认上一条催办没有送达后，再发送一次？",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self.client.nudge(task, retry_unknown=True)

    def toggle_tracking(self):
        conversation = self.selected_conversation()
        if not conversation or conversation.get("archived"):
            return
        if conversation.get("closed"):
            self.client.act("reopen_conversation", conversation["id"])
        elif QMessageBox.question(self, "结束这段对话的任务？",
                                  "本对话的所有待办会结束，之后自动扫描也会跳过它。可以在所有对话中恢复跟踪。",
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                  QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes:
            self.client.act("close_conversation", conversation["id"])

    def open_conversation(self):
        entry = self.selected_task() or self.selected_conversation()
        if not entry or not entry.get("thread_id"):
            return
        host = entry.get("host", "mac")
        settings = self.client.snapshot.get("settings", {})
        connection = next((connection for connection in settings.get("remote_hosts", []) if connection.get("id") == host), {})
        host_id = "local" if host in {"mac", "local"} else connection.get("host_id") or "remote-ssh-discovered:" + host
        try:
            open_thread(entry["thread_id"], host_id, settings.get("codex_app", ""))
        except (RuntimeError, OSError, ValueError) as error:
            QApplication.clipboard().setText(entry["thread_id"])
            self.client.notification.emit(str(error) + "；对话 ID 已复制。")

    def copy_next(self):
        task = self.selected_task()
        if task:
            QApplication.clipboard().setText(task.get("next_action", ""))
            self.client.notification.emit("下一步已复制")

    def copy_source(self):
        entry = self.selected_task() or self.selected_conversation()
        if entry:
            QApplication.clipboard().setText(f"主机: {entry.get('host', '')}\n对话: {entry.get('thread_id', '')}\n文件: {entry.get('path', '')}")
            self.client.notification.emit("来源已复制")

    def _open_link(self, url):
        if url.scheme() in {"http", "https"}:
            if not QDesktopServices.openUrl(url):
                self.client.notification.emit("无法打开链接")

    def open_data(self):
        if self.client.is_demo:
            self.client.notification.emit("演示模式不创建或打开实际数据目录。")
            return
        try:
            open_data_directory(self.client.data_directory)
        except (RuntimeError, OSError) as error:
            self.client.notification.emit(str(error))

    def open_settings(self):
        if self._settings_dialog is not None:
            self._settings_dialog.show()
            self._settings_dialog.raise_()
            return
        from .settings import SettingsDialog
        dialog = SettingsDialog(self.client, self)
        self._settings_dialog = dialog
        dialog.finished.connect(lambda result: setattr(self, "_settings_dialog", None))
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()

    def show_main(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self.tray_available and not self.force_quit:
            self.hide()
            event.ignore()
            self.closed_to_tray.emit()
        else:
            event.accept()
            QApplication.instance().quit()
