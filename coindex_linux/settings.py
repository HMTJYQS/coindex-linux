"""Connection and schedule editors; persistent state belongs to the backend."""
from copy import deepcopy
import shlex
from shiboken6 import isValid

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QTabWidget, QTimeEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from .desktop import autostart_enabled, launch_ssh_terminal, set_autostart_enabled


def _button(text, callback):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    return widget


class SSHDialog(QDialog):
    def __init__(self, client, profile=None, enabled=False, parent=None):
        super().__init__(parent)
        self.client = client
        self._closed = False
        self.setWindowTitle("编辑 SSH 来源" if profile else "添加 SSH 来源")
        self.resize(580, 640)
        self.fields = {}
        self._checked_profile = None
        self._previous_profile = deepcopy(profile or {})
        self._previous_enabled = enabled
        form = QFormLayout()
        self.alias = QComboBox()
        self.alias.setEditable(True)
        self.alias.addItem((profile or {}).get("id", ""))
        if profile:
            self.alias.setEnabled(False)
        form.addRow("SSH 别名 / 连接名称", self.alias)
        for key, label, placeholder in (
            ("name", "显示名称", "开发机"),
            ("hostname", "地址（使用 SSH 别名时可留空）", "server.example.com"),
            ("user", "用户名", ""), ("identity_file", "私钥文件路径", "沿用 SSH 配置"),
            ("codex_home", "远程 Codex 数据目录", "~/.codex"),
            ("python", "远程 Python", "python3"),
            ("codex_cli", "远程 Codex CLI", "自动发现"),
            ("host_id", "Codex 桌面主机 ID", "remote-ssh-discovered:<连接名称>"),
        ):
            field = QLineEdit((profile or {}).get(key, ""))
            field.setPlaceholderText(placeholder)
            self.fields[key] = field
            form.addRow(label, field)
            field.textChanged.connect(self.invalidate_check)
        self.port = QSpinBox()
        self.port.setRange(0, 65535)
        self.port.setSpecialValueText("使用 SSH 配置")
        self.port.setValue((profile or {}).get("port", 0))
        self.port.valueChanged.connect(self.invalidate_check)
        form.addRow("端口", self.port)
        self.alias.currentTextChanged.connect(self.invalidate_check)
        self.enabled = QCheckBox("启用该来源")
        self.enabled.setChecked(enabled)
        self.enabled.setEnabled(enabled)
        form.addRow(self.enabled)
        self.result = QLabel("首次连接请在终端核对主机指纹；后台读取需要免交互登录。")
        self.result.setWordWrap(True)
        actions = QHBoxLayout()
        self.test_button = _button("测试 SSH 与会话读取", self.check)
        actions.addWidget(self.test_button)
        actions.addWidget(_button("在终端连接", self.connect_terminal))
        actions.addWidget(_button("复制 SSH 命令", self.copy_command))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.result)
        layout.addLayout(actions)
        layout.addWidget(buttons)
        if not profile:
            client.request("ssh_aliases", success=self._aliases)

    def _aliases(self, result):
        if self._closed or not isValid(self):
            return
        current = self.alias.currentText()
        self.alias.addItems(result.get("aliases", []))
        self.alias.setCurrentText(current)

    @property
    def profile(self):
        result = {key: field.text().strip() for key, field in self.fields.items()}
        result.update(id=self.alias.currentText().strip(), port=self.port.value())
        result["name"] = result["name"] or result["id"]
        return result

    def invalidate_check(self, *_):
        if not hasattr(self, "enabled"):
            return
        # A result for old input cannot authorize collection from edited input.
        self._checked_profile = None
        unchanged = self.profile == self._previous_profile and self._previous_enabled
        self.enabled.setEnabled(unchanged)
        if not unchanged:
            self.enabled.setChecked(False)

    def check(self):
        profile = self.profile
        self.test_button.setEnabled(False)
        self.result.setText("正在测试连接…")

        def done(result):
            if self._closed or not isValid(self):
                return
            self.test_button.setEnabled(True)
            if self.profile != profile:
                self.result.setText("设置已变化，请重新测试。")
                return
            self.result.setText(result.get("detail", ""))
            self._checked_profile = profile if result.get("ok") else None
            self.enabled.setEnabled(bool(result.get("ok")))
            self.enabled.setChecked(bool(result.get("ok")))

        def failed(message):
            if self._closed or not isValid(self):
                return
            self.test_button.setEnabled(True)
            self.result.setText(message)

        self.client.request("check_connection", {"profile": profile}, done, failed,
                            timeout_ms=45000)

    def _command(self, callback):
        self.client.request("ssh_terminal_command", {"profile": self.profile},
                            lambda result: callback(result["command"]) if not self._closed and isValid(self) else None,
                            lambda message: self.result.setText(message) if not self._closed and isValid(self) else None)

    def connect_terminal(self):
        def launch(command):
            try:
                launch_ssh_terminal(shlex.split(command))
            except RuntimeError as error:
                self.result.setText(str(error))
        self._command(launch)

    def copy_command(self):
        self._command(lambda value: (QApplication.clipboard().setText(value),
                                     self.result.setText("SSH 命令已复制。")))

    def validate_and_accept(self):
        if not self.profile["id"]:
            self.result.setText("请填写连接名称。")
            return
        unchanged = self.profile == self._previous_profile and self._previous_enabled
        if self.enabled.isChecked() and not unchanged and self._checked_profile != self.profile:
            self.result.setText("请先测试当前设置，再启用来源。")
            return
        self.accept()

    def accept(self):
        self._closed = True
        super().accept()

    def reject(self):
        self._closed = True
        super().reject()


class SettingsDialog(QDialog):
    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self._closed = False
        self.original = deepcopy(client.snapshot.get("settings", {}))
        self.remotes = deepcopy(self.original.get("remote_hosts", []))
        self.enabled_hosts = set(self.original.get("enabled_hosts", ["mac"]))
        self.fields = {}
        self._check_serial = 0
        self._check_values = None
        self._checking = False
        self.setWindowTitle("设置与连接")
        self.resize(760, 690)
        tabs = self.tabs = QTabWidget()
        tabs.addTab(self._connections(), "Codex 与 SSH")
        tabs.addTab(self._schedule(), "自动整理与时间")
        tabs.addTab(self._desktop(), "桌面")
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        self.buttons.button(QDialogButtonBox.Save).setText("保存设置")
        self.buttons.button(QDialogButtonBox.Save).clicked.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(self.message)
        layout.addWidget(self.buttons)
        if client.is_demo:
            tabs.setEnabled(False)
            self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
            self.message.setText("演示模式只展示虚构数据，请退出演示后配置真实连接。")

    def _connections(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        for key, label, placeholder, directory in (
            ("codex_home", "Codex 数据目录", "~/.codex", True),
            ("codex_cli", "Codex CLI", "自动发现", False),
            ("codex_app", "Codex 桌面启动程序（可选）", "使用系统 codex:// 关联", False),
        ):
            field = QLineEdit(self.original.get(key, ""))
            field.setPlaceholderText(placeholder)
            field.setObjectName(key)
            self.fields[key] = field
            row = QHBoxLayout()
            row.addWidget(field)
            row.addWidget(_button("选择…", lambda _=False, f=field, d=directory: self._browse(f, d)))
            form.addRow(label, row)
        self.local_enabled = QCheckBox("读取本机会话")
        self.local_enabled.setChecked("mac" in self.enabled_hosts)
        form.addRow(self.local_enabled)
        self.check_button = _button("保存并检查本机连接", self.check_local)
        form.addRow(self.check_button)
        self.check_details = QLabel("检查分别确认 CLI、登录、会话读取与桌面连接。检查本身不调用模型。")
        self.check_details.setWordWrap(True)
        form.addRow(self.check_details)
        layout.addLayout(form)
        self.remote_list = QTreeWidget()
        self.remote_list.setHeaderLabels(["SSH 来源", "连接名称", "采集"])
        self.remote_list.setRootIsDecorated(False)
        self.remote_list.itemDoubleClicked.connect(lambda *_: self.edit_remote())
        layout.addWidget(self.remote_list)
        actions = QHBoxLayout()
        actions.addWidget(_button("添加 SSH 来源…", lambda: self.edit_remote(new=True)))
        actions.addWidget(_button("编辑…", self.edit_remote))
        actions.addWidget(_button("移除来源", self.remove_remote))
        actions.addStretch()
        layout.addLayout(actions)
        self._render_remotes()
        return page

    def _browse(self, field, directory):
        if directory:
            value = QFileDialog.getExistingDirectory(self, "选择 Codex 数据目录", field.text())
        else:
            value, _ = QFileDialog.getOpenFileName(self, "选择可执行文件", field.text())
        if value:
            field.setText(value)

    def _render_remotes(self):
        self.remote_list.clear()
        for profile in self.remotes:
            self.remote_list.addTopLevelItem(QTreeWidgetItem([
                profile.get("name", profile["id"]), profile["id"],
                "启用" if profile["id"] in self.enabled_hosts else "停用",
            ]))

    def edit_remote(self, new=False):
        selected = self.remote_list.currentItem()
        if not new and not selected:
            return
        profile = None if new else next(p for p in self.remotes if p["id"] == selected.text(1))
        dialog = SSHDialog(self.client, profile, bool(profile and profile["id"] in self.enabled_hosts), self)
        if dialog.exec() != QDialog.Accepted:
            return
        value = dialog.profile
        if new and any(p["id"] == value["id"] for p in self.remotes):
            self.message.setText("连接名称重复，请使用不同名称。")
            return
        self.remotes = [p for p in self.remotes if p["id"] != value["id"]] + [value]
        if dialog.enabled.isChecked():
            self.enabled_hosts.add(value["id"])
        else:
            self.enabled_hosts.discard(value["id"])
        self._render_remotes()
        self.message.setText("SSH 来源已编辑，点击保存设置后生效。")

    def remove_remote(self):
        selected = self.remote_list.currentItem()
        if not selected:
            return
        if QMessageBox.question(self, "移除来源", "移除后停止采集，已有任务和历史记录仍会保留。") != QMessageBox.Yes:
            return
        alias = selected.text(1)
        self.remotes = [p for p in self.remotes if p["id"] != alias]
        self.enabled_hosts.discard(alias)
        self._render_remotes()

    def _schedule(self):
        page = QWidget()
        form = QFormLayout(page)
        self.model = QLineEdit(self.original.get("analysis_model", "gpt-6-luna"))
        self.effort = QComboBox()
        self.effort.addItems(["minimal", "low", "medium", "high", "xhigh", "max", "ultra"])
        self.effort.setCurrentText(self.original.get("analysis_effort", "max"))
        form.addRow("分析模型", self.model)
        form.addRow("推理强度", self.effort)
        self.automatic = QCheckBox("定期整理发生变化的会话")
        self.automatic.setChecked(self.original.get("automatic", True))
        form.addRow(self.automatic)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.5, 60)
        self.interval.setDecimals(1)
        self.interval.setSingleStep(0.5)
        self.interval.setSuffix(" 分钟")
        self.interval.setValue(self.original.get("interval_seconds", 1800) / 60)
        form.addRow("检测间隔", self.interval)
        self.idle = QSpinBox()
        self.idle.setRange(1, 1440)
        self.idle.setSuffix(" 分钟")
        self.idle.setValue(self.original.get("idle_minutes", 10))
        form.addRow("会话空闲多久后整理", self.idle)
        self.history = QSpinBox()
        self.history.setRange(0, 36500)
        self.history.setSpecialValueText("全部历史")
        self.history.setSuffix(" 天")
        self.history.setValue(self.original.get("history_days", 0))
        form.addRow("历史范围", self.history)
        self.workdays = QCheckBox("只在中国大陆法定工作日检测")
        self.workdays.setChecked(self.original.get("workdays_only", True))
        form.addRow(self.workdays)
        self.work_hours = QCheckBox("限定检测时段（北京时间）")
        self.work_hours.setChecked(self.original.get("work_hours_enabled", False))
        form.addRow(self.work_hours)
        self.start_time = QTimeEdit()
        self.end_time = QTimeEdit()
        for field, value in ((self.start_time, self.original.get("work_start_minutes", 540)),
                             (self.end_time, self.original.get("work_end_minutes", 1080))):
            field.setDisplayFormat("HH:mm")
            field.setTime(QTime(value // 60, value % 60))
        form.addRow("开始", self.start_time)
        form.addRow("结束", self.end_time)
        refresh = _button("更新节假日数据", lambda: self.client.request(
            "refresh_calendar", success=lambda _: self.message.setText("正在更新节假日数据。"),
            failure=lambda error: self.message.setText(error)))
        form.addRow(refresh)
        note = QLabel("首次本机检查通过后才启用自动整理。实际分析使用你的 Codex 配额；暂停或退出应用可以停止后续检测。")
        note.setWordWrap(True)
        form.addRow(note)
        return page

    def _desktop(self):
        page = QWidget()
        form = QFormLayout(page)
        self.autostart = QCheckBox("登录桌面时启动 coindex Linux")
        self.autostart.setChecked(autostart_enabled())
        form.addRow(self.autostart)
        label = QLabel("托盘可用时，关闭主窗口会保留后台检测；没有托盘时，关闭窗口会退出应用。Wayland 下小猫保留在主窗口，X11 可选择浮窗。")
        label.setWordWrap(True)
        form.addRow(label)
        return page

    def values(self):
        values = {key: field.text().strip() for key, field in self.fields.items()}
        enabled = self.enabled_hosts - {"mac"}
        if self.local_enabled.isChecked():
            enabled.add("mac")
        values.update(
            remote_hosts=deepcopy(self.remotes), enabled_hosts=sorted(enabled),
            analysis_model=self.model.text().strip(), analysis_effort=self.effort.currentText(),
            automatic=self.automatic.isChecked(), interval_seconds=round(self.interval.value() * 60),
            idle_minutes=self.idle.value(), history_days=self.history.value(),
            workdays_only=self.workdays.isChecked(), work_hours_enabled=self.work_hours.isChecked(),
            work_start_minutes=self.start_time.time().hour() * 60 + self.start_time.time().minute(),
            work_end_minutes=self.end_time.time().hour() * 60 + self.end_time.time().minute(),
        )
        if any(values[key] != self.original.get(key, "") for key in self.fields):
            values["connection_setup_complete"] = False
        return values

    def _saved(self, _result=None):
        if self._closed or not isValid(self):
            return
        self.original = deepcopy(self.client.snapshot.get("settings", self.values()))
        for key, field in self.fields.items():
            field.setText(self.original.get(key, ""))
        self.model.setText(self.original.get("analysis_model", "gpt-6-luna"))
        self.effort.setCurrentText(self.original.get("analysis_effort", "max"))
        self.interval.setValue(self.original.get("interval_seconds", 1800) / 60)
        self.idle.setValue(self.original.get("idle_minutes", 10))
        self.history.setValue(self.original.get("history_days", 0))
        self.tabs.setEnabled(not self.client.is_demo)
        self.buttons.button(QDialogButtonBox.Save).setEnabled(True)

    def save(self):
        if self._checking:
            return
        self.tabs.setEnabled(False)
        self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
        wanted = self.autostart.isChecked()

        def saved(result):
            if self._closed or not isValid(self):
                return
            self._saved(result)
            try:
                if wanted != autostart_enabled():
                    set_autostart_enabled(wanted)
            except RuntimeError as error:
                self.message.setText("连接与整理设置已保存；" + str(error))
                return
            self.message.setText("设置已保存。")

        self.client.save_settings(self.values(), success=saved, failure=self._failed)

    def _failed(self, message):
        if self._closed or not isValid(self):
            return
        self._end_check()
        self.message.setText(message)

    def check_local(self):
        if self._checking:
            return
        self._check_serial += 1
        serial = self._check_serial
        self._checking = True
        self.tabs.setEnabled(False)
        self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
        self.check_button.setEnabled(False)
        values = self.values()
        self._check_values = {key: values[key] for key in self.fields}
        values["connection_setup_complete"] = False
        self.check_details.setText("正在保存并检查连接…")
        def saved(_):
            if serial == self._check_serial and not self._closed and isValid(self):
                self.client.request("check_connection",
                                    success=lambda result: self._local_checked(result, serial),
                                    failure=lambda message: self._check_failed(message, serial),
                                    timeout_ms=45000)
        self.client.save_settings(values, success=saved,
                                  failure=lambda message: self._check_failed(message, serial))

    def _check_failed(self, message, serial):
        if serial == self._check_serial:
            self._failed(message)

    def _end_check(self):
        self._checking = False
        self.tabs.setEnabled(not self.client.is_demo)
        self.buttons.button(QDialogButtonBox.Save).setEnabled(not self.client.is_demo)
        self.check_button.setEnabled(True)

    def _local_checked(self, result, serial):
        if serial != self._check_serial or self._closed or not isValid(self):
            return
        saved = self.client.snapshot.get("settings", {})
        matching = all(self.fields[key].text().strip() == value and saved.get(key, "") == value
                       for key, value in self._check_values.items())
        if not matching:
            self._end_check()
            self.message.setText("连接设置已变化，旧检查结果已失效，请重新检查。")
            return
        self.check_details.setText(result.get("detail", ""))
        enabled = saved.get("enabled_hosts", [])
        cli_ready = bool(result.get("version") and result.get("login_ready") and result.get("cli_compatible"))
        source_ready = bool(enabled) and ("mac" not in enabled or result.get("sessions_ready"))
        if cli_ready and source_ready:
            self.client.save_settings({"connection_setup_complete": True},
                                      success=lambda value: self._local_ready(value, serial),
                                      failure=lambda message: self._check_failed(message, serial))
        else:
            self._end_check()
            self.message.setText("配置已保存，连接尚未通过。请根据上方结果调整后重试。")

    def _local_ready(self, result, serial):
        if serial != self._check_serial or self._closed or not isValid(self):
            return
        self._saved(result)
        self._end_check()
        self.message.setText("本机连接检查通过；自动整理按你保存的设置运行。")

    def reject(self):
        self._closed = True
        self._check_serial += 1
        self._end_check()
        super().reject()
