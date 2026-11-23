import ctypes
import sys

from PySide6.QtCore import QObject, QTimer, Signal

# Windows 虚拟键码分组（仅抽象为左/右手区/双手，绝不记录或存储具体键名或字符）
LEFT_VKS = (
    # 左手字母区：Q W E R T / A S D F G / Z X C V B
    0x51, 0x57, 0x45, 0x52, 0x54,
    0x41, 0x53, 0x44, 0x46, 0x47,
    0x5A, 0x58, 0x43, 0x56, 0x42,
    # 左手数字区：1 2 3 4 5
    0x31, 0x32, 0x33, 0x34, 0x35,
    # Tab / CapsLock / Left Shift / Left Ctrl
    0x09, 0x14, 0xA0, 0xA2,
)

RIGHT_VKS = (
    # 右手字母区：Y U I O P / H J K L / N M
    0x59, 0x55, 0x49, 0x4F, 0x50,
    0x48, 0x4A, 0x4B, 0x4C,
    0x4E, 0x4D,
    # 右手数字区：6 7 8 9 0
    0x36, 0x37, 0x38, 0x39, 0x30,
    # Backspace / 常见标点符号 / Right Shift / 方向键
    0x08, 0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xDB, 0xDC, 0xDD, 0xDE,
    0xA1, 0x25, 0x26, 0x27, 0x28,
)

BOTH_VKS = (
    0x20,  # Space
    0x0D,  # Enter
)

ALL_TRACKED_VKS = LEFT_VKS + RIGHT_VKS + BOTH_VKS


class TypingMonitor(QObject):
    """
    隐私安全的轻量级全局打字感知器（仅限 Windows）。

    使用 GetAsyncKeyState 低开销轮询（35ms）检测按键由松开到按下的上升沿，
    只发出 "left" / "right" / "both" 三种匿名手部动作信号，绝不记录、存储或输出任何按键字符。
    """

    key_tapped = Signal(str)

    def __init__(self, parent: QObject | None = None, enabled: bool = True):
        super().__init__(parent)
        self._enabled = bool(enabled)
        self._prev_down: dict[int, bool] = {vk: False for vk in ALL_TRACKED_VKS}
        self._user32 = None

        if sys.platform == "win32":
            try:
                self._user32 = ctypes.windll.user32
            except Exception:
                self._user32 = None

        self._timer = QTimer(self)
        self._timer.setInterval(35)
        self._timer.timeout.connect(self._poll)

        if self._enabled:
            self.start()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def start(self):
        if self._user32 is None:
            return
        self._sync_initial_state()
        if not self._timer.isActive():
            self._timer.start()

    def stop(self):
        self._timer.stop()
        for vk in self._prev_down:
            self._prev_down[vk] = False

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        if self._enabled:
            self.start()
        else:
            self.stop()

    def _sync_initial_state(self):
        """启动时同步一次初始状态，避免将当前按住的修饰键误判成新敲击。"""
        if self._user32 is None:
            return
        try:
            for vk in ALL_TRACKED_VKS:
                self._prev_down[vk] = bool(self._user32.GetAsyncKeyState(vk) & 0x8000)
        except Exception:
            pass

    def _poll(self):
        if not self._enabled or self._user32 is None:
            return
        triggered_both = False
        triggered_left = False
        triggered_right = False

        try:
            get_state = self._user32.GetAsyncKeyState
            for vk in BOTH_VKS:
                down = bool(get_state(vk) & 0x8000)
                if down and not self._prev_down[vk]:
                    triggered_both = True
                self._prev_down[vk] = down

            for vk in LEFT_VKS:
                down = bool(get_state(vk) & 0x8000)
                if down and not self._prev_down[vk]:
                    triggered_left = True
                self._prev_down[vk] = down

            for vk in RIGHT_VKS:
                down = bool(get_state(vk) & 0x8000)
                if down and not self._prev_down[vk]:
                    triggered_right = True
                self._prev_down[vk] = down
        except Exception:
            return

        # 同一次轮询内合并最多 1~2 次手部动作信号，既反映连敲又防止信号风暴
        if triggered_both:
            self.key_tapped.emit("both")
        elif triggered_left and triggered_right:
            self.key_tapped.emit("left")
            self.key_tapped.emit("right")
        elif triggered_left:
            self.key_tapped.emit("left")
        elif triggered_right:
            self.key_tapped.emit("right")
