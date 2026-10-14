"""Original coindex cat animation with optional X11 floating window."""
import time

from PySide6.QtCore import QPoint, QSettings, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .resources import resource_path


def pet_state(snapshot):
    if snapshot.get("model_error") or any(h.get("status") == "error" for h in snapshot.get("hosts", [])):
        return "failed"
    tasks = [t for t in snapshot.get("tasks", [])
             if t.get("status") == "open" and t.get("snoozed_until", 0) <= time.time()]
    if any(t.get("kind") in ("decision", "wait") for t in tasks):
        return "waiting"
    if any(t.get("kind") == "review" for t in tasks):
        return "review"
    if snapshot.get("sync", {}).get("running") or any(t.get("kind") == "running" for t in tasks):
        return "running"
    return "idle"


class CatSprite(QLabel):
    ROWS = {"idle": (0, 6, 800), "failed": (5, 8, 140),
            "waiting": (6, 6, 150), "running": (7, 6, 120), "review": (8, 6, 150)}

    def __init__(self, parent=None, size=116):
        super().__init__(parent)
        self.atlas = QPixmap(str(resource_path("CustomPets/coindex-cat/spritesheet.png")))
        self.state = "idle"
        self.frame = 0
        self.reduced_motion = False
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(size, round(size * 208 / 192))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.draw_frame()
        self.timer.start(800)

    def set_state(self, state, reduced_motion=False):
        if state != self.state or reduced_motion != self.reduced_motion:
            self.state = state
            self.frame = 0
            self.reduced_motion = reduced_motion
            self.draw_frame()
        if reduced_motion:
            self.timer.stop()
        else:
            self.timer.start(self.ROWS[self.state][2])

    def draw_frame(self):
        if self.atlas.isNull():
            self.setText("🐈")
            return
        row, _, _ = self.ROWS[self.state]
        frame = self.atlas.copy(self.frame * 192, row * 208, 192, 208)
        self.setPixmap(frame.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def advance(self):
        self.frame = (self.frame + 1) % self.ROWS[self.state][1]
        self.draw_frame()


class FloatingCat(QWidget):
    def __init__(self, owner):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.owner = owner
        self.drag_offset = None
        self.setWindowTitle("coindex 小猫")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.sprite = CatSprite(self, size=144)
        self.sprite.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.sprite)
        self.setToolTip("拖动移动；双击返回工作台；右键关闭浮窗。")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.pos()
        elif event.button() == Qt.RightButton:
            self.close()

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_offset)

    def mouseReleaseEvent(self, _event):
        self.drag_offset = None
        self.owner.preferences.setValue("pet/position", self.pos())

    def mouseDoubleClickEvent(self, _event):
        window = self.owner.window()
        window.showNormal()
        window.raise_()
        window.activateWindow()

    def closeEvent(self, event):
        self.sprite.timer.stop()
        self.owner.floating = None
        self.owner.float_button.setText("显示 X11 浮窗")
        event.accept()


class PetWidget(QWidget):
    def __init__(self, snapshot=None, parent=None):
        super().__init__(parent)
        self.preferences = QSettings("coindex-linux", "desktop")
        self.floating = None
        self.sprite = CatSprite(self)
        self.state_label = QLabel("小猫陪你跟进工作")
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setWordWrap(True)
        self.motion = QCheckBox("减少动画")
        self.motion.setChecked(str(self.preferences.value("pet/reduced_motion", "false")).lower() == "true")
        self.motion.toggled.connect(self.motion_changed)
        self.float_button = QPushButton("显示 X11 浮窗")
        self.float_button.clicked.connect(self.toggle_float)
        self.float_button.setVisible(QGuiApplication.platformName() == "xcb")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.sprite, alignment=Qt.AlignHCenter)
        layout.addWidget(self.state_label)
        controls = QHBoxLayout()
        controls.addWidget(self.motion)
        controls.addStretch()
        layout.addLayout(controls)
        layout.addWidget(self.float_button)
        self.snapshot = snapshot or {}
        self.set_snapshot(self.snapshot)

    def motion_changed(self, value):
        self.preferences.setValue("pet/reduced_motion", value)
        self.set_snapshot(self.snapshot)

    def set_snapshot(self, snapshot):
        self.snapshot = snapshot
        state = pet_state(snapshot)
        self.sprite.set_state(state, self.motion.isChecked())
        text = {"idle": "小猫陪你跟进工作", "failed": "有连接或分析需要检查",
                "waiting": "有工作等待结果或你的决定", "running": "工作正在推进",
                "review": "有结果等待校对"}[state]
        self.state_label.setText(text)
        if self.floating:
            self.floating.sprite.set_state(state, self.motion.isChecked())
            self.floating.setToolTip(text + "\n拖动移动；双击返回工作台；右键关闭。")

    def toggle_float(self):
        if self.floating:
            self.floating.close()
            return
        if QGuiApplication.platformName() != "xcb":
            return
        self.floating = FloatingCat(self)
        position = self.preferences.value("pet/position")
        if isinstance(position, QPoint) and any(screen.availableGeometry().contains(position)
                                                for screen in QGuiApplication.screens()):
            self.floating.move(position)
        self.set_snapshot(self.snapshot)
        self.floating.show()
        self.float_button.setText("关闭浮窗")

    def shutdown(self):
        self.sprite.timer.stop()
        if self.floating:
            self.floating.close()
