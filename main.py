import ctypes
import ctypes.wintypes
import math
import os
import random
import sys
import time
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QBrush,
    QColor,
    QCursor,
    QFont,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QTransform,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from config_store import (
    PetConfig,
    get_affinity_level,
    is_autostart_enabled,
    load_config,
    save_config,
    set_autostart,
)
from live2d_rig import Live2DController, Live2DMeshWarper
from motion import ActionQueue, ActionStep, PoseRig, SpringValue
from sound_fx import SoundManager
from typing_monitor import TypingMonitor
from widgets import BubbleWidget, LaserToyWidget, StatusDialog

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SPRITE_DIR = os.path.join(BASE_DIR, "assets", "sprites")
SINGLE_INSTANCE_KEY = "AntigravityStarryCatgirlPet_v2"
WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1
HIT_GRID_SIZE = 96

SPRITE_NAMES = (
    "idle",
    "happy",
    "sleep",
    "dragged",
    "overload",
    "walk_a",
    "walk_b",
    "sit",
    "eat",
    "shy",
    "typing_body",
)

SPRITE_FALLBACKS = {
    "walk_a": "idle",
    "walk_b": "idle",
    "sit": "idle",
    "eat": "happy",
    "shy": "happy",
    "typing_body": "sit",
}


@dataclass
class Particle:
    """画面上的星尘、爱心、Zzz、代码浮字等轻量粒子特效。"""

    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    kind: str  # "star" | "heart" | "zzz" | "spark" | "code"
    size: float
    color: QColor
    rot: float = 0.0
    vrot: float = 0.0
    text: str = ""


@dataclass
class FlyingFish:
    """抛物线飞向猫猫的小鱼干投喂动画对象。"""

    start_x: float
    start_y: float
    ctrl_x: float
    ctrl_y: float
    target_x: float
    target_y: float
    elapsed: float = 0.0
    duration: float = 0.55
    rot_dir: float = 1.0


class StarryCatgirlPet(QWidget):
    """Antigravity 星辰猫猫桌宠 v3.0 主窗口（10 套精灵 + 弹簧物理 + 连贯动作链）。"""

    LINES = {
        "welcome": [
            "星辰猫猫 v3.0 上线啦！10 套动作连贯演化，试试中键投喂或逗猫棒吧✨",
            "喵~ 摸摸猫头会害羞蹭手，滚轮还能随时缩放我的大小哦！",
        ],
        "pet_ear": [
            "呜喵~ 猫耳被顺得舒舒服服，好感度 +2！✨",
            "呼噜呼噜……再多摸两下猫耳朵也不是不行啦！",
            "好耶！猫耳充能完成，继续陪你写代码！",
        ],
        "pet_cheek": [
            "唔……别戳本喵软乎乎的脸颊啦，会变圆的喂！",
            "尊嘟假嘟？一直盯着我的脸看是有什么奇怪想法吗~",
            "喵呜！戳一下还要害羞歪头的嘛✨",
        ],
        "pet_foot": [
            "呀！小脚心好痒！不许偷偷挠人家脚底板啦！",
            "呜哇吓我一跳——差点直接原地反重力起飞！",
        ],
        "rub_head": [
            "呼噜噜~ 最喜欢这种轻轻顺毛的手法啦，好感度 UP！💖",
            "咪~ 被你rua得好害羞……呆毛都要开心得翘起来了✨",
            "贴贴~ 再多顺几下毛，今天所有 Bug 我都帮你盯住！",
        ],
        "eat": [
            "咔嚓咔嚓……接住啦！银河味小鱼干超香！🐟✨",
            "啊呜一口咬住！吃得好满足，算力瞬间回满~",
            "小鱼干万岁！今天接下来的任务全部包在本喵身上！",
        ],
        "eat_done": [
            "吃饱喝足啦！饱食活力大恢复~✨",
        ],
        "feast": [
            "呜哇！！一次三条小鱼干大餐？！幸福到转圈圈！🐟🐟🐟",
        ],
        "drag_start": [
            "呜哇！别突然拎我后衣领呀！",
            "诶诶诶——双脚离地了啦！",
            "救命，本喵被鼠标捕获了！",
        ],
        "land": [
            "呼——反重力缓冲着陆成功！✨",
            "轻点放下来啦，裙摆都晃乱了~",
            "稳稳落地！本喵平衡感满分！",
        ],
        "antigravity_on": [
            "反重力模式启动！进入无重力星海漂浮状态✨",
            "咻——告别地心引力，拖到哪我都能悬停哦！",
        ],
        "antigravity_off": [
            "重力恢复！乖乖回到任务栏上散步啦~",
        ],
        "follow_on": [
            "开启追随鼠标模式！你去哪我就跟到哪~ 🐾",
        ],
        "follow_off": [
            "好哒，不粘着你的鼠标光标啦~",
        ],
        "laser_on": [
            "🪄 发现星光棒光点！！本喵进入扑猎模式啦，快晃动鼠标！",
        ],
        "laser_catch": [
            "抓到星光点啦！本喵反应超快吧✨",
            "咻——精准命中闪耀星星！再来一次再来一次！",
        ],
        "laser_off": [
            "呼呼……玩得好尽兴！先歇口气~",
        ],
        "overload": [
            "点太快啦！！大脑过载要冒烟了……💫",
            "呜哇！CPU 99°C，快投喂小鱼干给我降温！⚡",
        ],
        "sleep_prep": [
            "有点困了，先乖乖坐下来揉揉眼睛~",
        ],
        "sleep": [
            "呼……趴在任务栏上眯一会儿~ Zzz",
            "梦里有好多会飞的烤小鱼干……",
        ],
        "wake": [
            "唔……是谁叫本喵？伸个大懒腰继续营业！✨",
            "早安~ 揉揉眼睛，星辰猫猫满血上线！",
        ],
        "hungry": [
            "咕噜……肚子有点饿啦，鼠标中键能丢一条小鱼干给我吗~🐟",
        ],
        "typing_start": [
            "发现主人开始码字！本喵也掏出星辰小键盘陪你⌨️✨",
            "哒哒哒~ 开启同步写代码模式，今天效率拉满！",
        ],
        "typing_wake": [
            "唔……听到键盘声啦，起来掏出小键盘陪你一起敲⌨️",
        ],
        "typing_done": [
            "一口气敲了这么多字，伸个懒腰休息下吧~✨",
            "呼——本轮码字达成！写出来的代码一定一遍过！",
        ],
        "idle_chatter": [
            "今天的代码写得顺利吗？记得歇歇眼睛哦~",
            "试着在头顶轻轻来回滑动鼠标，可以rua到本喵害羞蹭手哦！",
            "右键拿出『🪄 逗猫星光棒』，看我蓄力飞扑抓光点🐾",
            "按鼠标中键直接投喂小鱼干，滚轮还能无级缩放体型✨",
        ],
    }

    def __init__(self):
        self.cfg: PetConfig = load_config()
        flags = Qt.FramelessWindowHint | Qt.Tool
        if self.cfg.always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        super().__init__(None, flags)

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        # 加载 11 套透明精灵图、原装拆件双臂及 Live2D 2x 变形器
        self.sprites: dict[str, QPixmap] = {}
        self.hit_grids: dict[str, QImage] = {}
        self.arm_sprites: dict[str, QPixmap] = {}
        self._load_sprites()
        self.live2d_enabled = self.cfg.live2d_enabled
        self.live2d = Live2DController()
        self.live2d_warper = Live2DMeshWarper(SPRITE_DIR)

        # 基础视觉尺寸与窗口尺寸
        self.pet_size = self.cfg.pet_size
        self._apply_window_size()

        # 状态机、弹簧物理机与连贯动作编排队列
        self.state = "idle"  # idle | walk | happy | sit | eat | shy | sleep | dragged | falling | overload | flip
        self.prev_sprite_key = "idle"
        self.active_sprite_key = "idle"
        self.crossfade_progress = 1.0

        self.rig = PoseRig()
        self.action_queue = ActionQueue()

        self.facing_right = True
        self.antigravity_mode = self.cfg.antigravity
        self.auto_walk_enabled = self.cfg.auto_walk
        self.follow_mouse = self.cfg.follow_mouse
        self.typing_sync = self.cfg.typing_sync
        self.laser_mode = False
        self.always_on_top = self.cfg.always_on_top

        # 同步模仿打字状态与弹性通道（0.0=高高举起, 0.45=待命微悬, 1.0=重拍键帽）
        self.typing_idle_timer = 0.0
        self.typing_session_keys = 0
        self.typing_bubble_cooldown = 0.0
        self.sleep_wake_taps: list[float] = []
        self.recent_type_times: list[float] = []
        self.typing_hand = "left"
        self.typing_pose = "ready"  # "ready" | "left_down" | "right_down" | "both_down"
        self.typing_pose_hold = 0.0
        self.last_lit_zone = ""
        self.key_lit_timer = 0.0
        self.left_paw_press = SpringValue(0.45, 0.45, stiffness=280.0, damping=18.0)
        self.right_paw_press = SpringValue(0.45, 0.45, stiffness=280.0, damping=18.0)
        self.keyboard_pop = SpringValue(0.0, 0.0, stiffness=210.0, damping=18.0)
        self.kb_shake = SpringValue(0.0, 0.0, stiffness=420.0, damping=22.0)

        self.pos_x = 0.0
        self.pos_y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.render_dy = 0.0
        self.flip_spin_angle = 0.0
        self.laser_pounce_cooldown = 0.0
        self.laser_pounce_vx = 0.0
        self.laser_pounce_vy = 0.0
        self.laser_caught_in_pounce = False
        self.chew_pulse_timer = 0.0

        # 拖拽与钟摆晃动物理
        self.dragging = False
        self.drag_moved = False
        self.drag_offset = QPoint()
        self.last_mouse_global = QPoint()
        self.swing_angle = 0.0
        self.swing_vel = 0.0

        # 悬停 rua 猫头追踪
        self.last_hover_pos: QPoint | None = None
        self.rub_distance = 0.0
        self.rub_cooldown = 0.0

        # 动画计时、粒子与飞鱼投喂
        self.anim_time = 0.0
        self.state_timer = 0.0
        self.next_decision_in = 3.5
        self.recent_clicks: list[float] = []
        self.particles: list[Particle] = []
        self.flying_fishes: list[FlyingFish] = []
        self.chatter_cooldown = 16.0
        self.hungry_ticker = 0

        # 小助手计时器数据
        self.pomodoro_remaining_sec = 0
        self.drink_elapsed_sec = 0

        # 音效、气泡、逗猫光球、状态卡片、打字感知器
        self.sound = SoundManager(self, enabled=self.cfg.sound_enabled)
        self.bubble = BubbleWidget()
        self.laser_toy = LaserToyWidget()
        self.status_dialog = StatusDialog(self.sprites["idle"])
        self.status_dialog.feed_requested.connect(self.feed_fish)
        self.status_dialog.pomodoro_toggled.connect(self.toggle_pomodoro)
        self.status_dialog.laser_toggled.connect(lambda: self.toggle_laser_mode(not self.laser_mode))
        self.status_dialog.trick_requested.connect(self.perform_backflip)
        self.typing_monitor = TypingMonitor(self, enabled=self.typing_sync)
        self.typing_monitor.key_tapped.connect(self._on_global_key_tap)

        # 恢复保存的坐标或默认放置
        self._place_initial_position()

        # 共享菜单（托盘与右键实时同步）
        self.shared_menu = QMenu()
        self.shared_menu.setStyleSheet(self._menu_stylesheet())
        self.shared_menu.aboutToShow.connect(self._refresh_shared_menu)
        self._setup_tray()

        # 60 FPS 主更新循环
        self.last_tick = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        # 1 秒级辅助定时器：陪伴时长、饱食度缓慢消耗、番茄钟、喝水提醒
        self.sec_timer = QTimer(self)
        self.sec_timer.setInterval(1000)
        self.sec_timer.timeout.connect(self._on_second_tick)
        self.sec_timer.start()

        # 60 秒定期保存
        self.save_timer = QTimer(self)
        self.save_timer.setInterval(60000)
        self.save_timer.timeout.connect(self.save_state)
        self.save_timer.start()

        QTimer.singleShot(450, lambda: self.say(random.choice(self.LINES["welcome"]), 4800))

    def _load_sprites(self):
        """加载 10 套透明精灵图，缺失可选扩展图时安全回退。"""
        base_idle = os.path.join(SPRITE_DIR, "idle.png")
        if not os.path.isfile(base_idle):
            raise FileNotFoundError(f"缺少核心精灵图: {base_idle}")

        for name in SPRITE_NAMES:
            path = os.path.join(SPRITE_DIR, f"{name}.png")
            pm = QPixmap(path) if os.path.isfile(path) else QPixmap()
            if pm.isNull():
                fb_key = SPRITE_FALLBACKS.get(name, "idle")
                pm = self.sprites.get(fb_key) or QPixmap(base_idle)
            if pm.isNull():
                raise FileNotFoundError(f"无法加载桌宠精灵图: {path}")
            self.sprites[name] = pm
            img = (
                pm.toImage()
                .scaled(HIT_GRID_SIZE, HIT_GRID_SIZE, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                .convertToFormat(QImage.Format_ARGB32)
            )
            self.hit_grids[name] = img

        for arm_name in ("arm_left", "arm_right", "sleeves_top"):
            arm_path = os.path.join(SPRITE_DIR, f"{arm_name}.png")
            arm_pm = QPixmap(arm_path) if os.path.isfile(arm_path) else QPixmap()
            if not arm_pm.isNull():
                self.arm_sprites[arm_name] = arm_pm

    @staticmethod
    def _menu_stylesheet() -> str:
        return """
            QMenu {
                background-color: #fdfcff;
                color: #2a2d60;
                border: 1px solid #c5c2ea;
                border-radius: 10px;
                padding: 6px;
                font-family: "Microsoft YaHei UI";
                font-size: 13px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background-color: #ebe8ff;
                color: #3f38a8;
            }
            QMenu::separator {
                height: 1px;
                background: #e5e3f5;
                margin: 4px 8px;
            }
        """

    def _apply_window_size(self):
        margin = int(self.pet_size * 0.36)
        self.margin = margin
        win_w = self.pet_size + margin * 2
        win_h = self.pet_size + margin * 2
        self.resize(win_w, win_h)

    def _screen_bounds(self, point: QPoint | None = None) -> QRectF:
        ref = point if point is not None else self.frameGeometry().center()
        screen = QApplication.screenAt(ref) or QApplication.primaryScreen()
        return QRectF(screen.availableGeometry())

    def _floor_y(self) -> float:
        bounds = self._screen_bounds()
        foot_offset_from_win_bottom = self.margin + self.pet_size * 0.04
        return bounds.bottom() - self.height() + foot_offset_from_win_bottom

    def _place_initial_position(self):
        bounds = QApplication.primaryScreen().availableGeometry()
        if self.cfg.pos_x is not None and self.cfg.pos_y is not None:
            saved_pt = QPoint(
                int(self.cfg.pos_x + self.width() * 0.5),
                int(self.cfg.pos_y + self.height() * 0.5),
            )
            target_bounds = self._screen_bounds(saved_pt)
            min_x = target_bounds.left() - self.margin * 0.4
            max_x = target_bounds.right() - self.width() + self.margin * 0.4
            self.pos_x = max(min_x, min(max_x, float(self.cfg.pos_x)))
            if self.antigravity_mode:
                self.pos_y = max(
                    target_bounds.top(),
                    min(target_bounds.bottom() - self.height() + self.margin, float(self.cfg.pos_y)),
                )
            else:
                self.pos_y = self._floor_y()
        else:
            self.pos_x = float(bounds.right() - self.width() - 36)
            self.pos_y = self._floor_y()
        self.move(int(self.pos_x), int(self.pos_y))

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(QIcon(self.sprites["idle"]))
        self.tray.setToolTip("Antigravity 星辰猫猫桌宠 v3.0")
        self.tray.setContextMenu(self.shared_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if not self.isVisible():
                self.show()
                self.raise_()
            else:
                self.trigger_happy("喵呜~ 我在这里哦！✨")

    def _refresh_shared_menu(self):
        """在托盘或右键菜单即将弹出前实时重建菜单项，保证所有勾选与倒计时同步。"""
        menu = self.shared_menu
        menu.clear()

        act_feed = QAction("🐟 投喂小鱼干 (中键快捷)", menu)
        act_feed.triggered.connect(self.feed_fish)
        menu.addAction(act_feed)

        act_feast = QAction("🍱 投喂小鱼干大餐 (×3)", menu)
        act_feast.triggered.connect(self.feed_feast)
        menu.addAction(act_feast)

        act_laser = QAction("🪄 收起逗猫星光棒" if self.laser_mode else "🪄 拿出逗猫星光棒", menu)
        act_laser.setCheckable(True)
        act_laser.setChecked(self.laser_mode)
        act_laser.triggered.connect(self.toggle_laser_mode)
        menu.addAction(act_laser)

        act_flip = QAction("🌀 表演反重力后空翻", menu)
        act_flip.triggered.connect(self.perform_backflip)
        menu.addAction(act_flip)

        act_status = QAction("📊 查看猫猫状态面板", menu)
        act_status.triggered.connect(self.open_status_dialog)
        menu.addAction(act_status)

        menu.addSeparator()

        act_antigrav = QAction("✨ 反重力漂浮模式", menu)
        act_antigrav.setCheckable(True)
        act_antigrav.setChecked(self.antigravity_mode)
        act_antigrav.triggered.connect(self.toggle_antigravity)
        menu.addAction(act_antigrav)

        act_follow = QAction("🐾 追随鼠标散步", menu)
        act_follow.setCheckable(True)
        act_follow.setChecked(self.follow_mouse)
        act_follow.triggered.connect(self.toggle_follow_mouse)
        menu.addAction(act_follow)

        act_typing = QAction("⌨️ 同步模仿打字", menu)
        act_typing.setCheckable(True)
        act_typing.setChecked(self.typing_sync)
        act_typing.triggered.connect(self.toggle_typing_sync)
        menu.addAction(act_typing)

        act_walk = QAction("🚶 桌面自由散步", menu)
        act_walk.setCheckable(True)
        act_walk.setChecked(self.auto_walk_enabled)
        act_walk.triggered.connect(self.toggle_auto_walk)
        menu.addAction(act_walk)

        act_live2d = QAction("✨ Live2D 灵动物理 (追视/眨眼/抖耳)", menu)
        act_live2d.setCheckable(True)
        act_live2d.setChecked(self.live2d_enabled)
        act_live2d.triggered.connect(self.toggle_live2d)
        menu.addAction(act_live2d)

        menu.addSeparator()

        if self.pomodoro_remaining_sec > 0:
            mm, ss = divmod(self.pomodoro_remaining_sec, 60)
            pomo_label = f"🍅 停止番茄钟 (剩余 {mm:02d}:{ss:02d})"
        else:
            pomo_label = "🍅 番茄专注 25分钟"
        act_pomo = QAction(pomo_label, menu)
        act_pomo.triggered.connect(self.toggle_pomodoro)
        menu.addAction(act_pomo)

        act_drink = QAction(f"💧 喝水休息提醒 ({self.cfg.drink_interval_min}分钟)", menu)
        act_drink.setCheckable(True)
        act_drink.setChecked(self.cfg.drink_reminder_enabled)
        act_drink.triggered.connect(self.toggle_drink_reminder)
        menu.addAction(act_drink)

        menu.addSeparator()

        pose_menu = menu.addMenu("🎭 切换当前动作")
        for label, st in (
            ("星辰待机", "idle"),
            ("乖巧坐下", "sit"),
            ("开心蹦跳", "happy"),
            ("啃小鱼干", "eat"),
            ("害羞贴贴", "shy"),
            ("趴着打盹", "sleep"),
            ("大脑过载", "overload"),
        ):
            act = QAction(label, pose_menu)
            act.triggered.connect(lambda checked=False, s=st: self.force_state(s))
            pose_menu.addAction(act)

        size_menu = menu.addMenu(f"📏 调整大小 (当前 {self.pet_size}px，支持滚轮)")
        size_group = QActionGroup(size_menu)
        for label, px in (("小巧 (140px)", 140), ("标准 (180px)", 180), ("大只 (230px)", 230)):
            act = QAction(label, size_menu)
            act.setCheckable(True)
            act.setChecked(abs(self.pet_size - px) <= 5)
            act.triggered.connect(lambda checked=False, p=px: self.set_pet_size(p))
            size_group.addAction(act)
            size_menu.addAction(act)

        settings_menu = menu.addMenu("⚙️ 更多设置")
        act_sound = QAction("🔊 互动音效", settings_menu)
        act_sound.setCheckable(True)
        act_sound.setChecked(self.sound.enabled)
        act_sound.triggered.connect(self.toggle_sound)
        settings_menu.addAction(act_sound)

        act_top = QAction("📌 始终置顶", settings_menu)
        act_top.setCheckable(True)
        act_top.setChecked(self.always_on_top)
        act_top.triggered.connect(self.toggle_always_on_top)
        settings_menu.addAction(act_top)

        act_auto = QAction("🚀 开机自动启动", settings_menu)
        act_auto.setCheckable(True)
        act_auto.setChecked(is_autostart_enabled())
        act_auto.triggered.connect(self.toggle_autostart)
        settings_menu.addAction(act_auto)

        menu.addSeparator()

        vis_label = "👁️ 隐藏桌宠" if self.isVisible() else "👁️ 显示桌宠"
        act_toggle_vis = QAction(vis_label, menu)
        act_toggle_vis.triggered.connect(self.toggle_visibility)
        menu.addAction(act_toggle_vis)

        act_quit = QAction("🚪 退出桌宠", menu)
        act_quit.triggered.connect(self.quit_app)
        menu.addAction(act_quit)

    # ---------- 像素级精准点击穿透 ----------
    def _walk_stride_phase(self) -> float:
        """走路迈步相位，用于锁相切换双步态与身体弹跳倾身。"""
        freq = 4.6 if self.laser_mode else 3.1
        return self.anim_time * freq

    def _current_sprite_key(self) -> str:
        if self.state == "dragged":
            return "dragged"
        if self.state == "falling":
            return "dragged" if self.vy > 120 else "happy"
        if self.state in ("sleep", "overload", "happy", "sit", "eat", "shy"):
            return self.state
        if self.state == "flip":
            return "happy"
        if self.state == "typing":
            # 使用专门抹除原双手的坐姿底图，由程序从肩膀接出连续双臂，避免四只手
            return "typing_body"
        if self.state == "walk":
            # 锁相双步态：仅在 walk_a 与 walk_b 之间交替迈步，避免夹入 idle 引起手部闪跳
            return ("walk_a", "walk_b")[int(self._walk_stride_phase()) % 2]
        return "idle"

    def _is_point_on_pet(self, local_pt: QPoint) -> bool:
        """检查窗口逻辑坐标是否落在猫猫本体（或弹出的星辰小键盘）上。"""
        sprite_left = float(self.margin) + self.rig.dx.value
        sprite_top = float(self.margin) + self.render_dy
        sprite_rect = QRectF(sprite_left, sprite_top, float(self.pet_size), float(self.pet_size))

        if not sprite_rect.adjusted(-10, -10, 10, 10).contains(QPointF(local_pt)):
            return False

        # 若小键盘正在弹出，点击小键盘所在矩形也直接命中
        if self.keyboard_pop.value > 0.2:
            kb_cx = sprite_left + self.pet_size * 0.5
            kb_cy = sprite_top + self.pet_size * 0.812
            kb_rect = QRectF(
                kb_cx - self.pet_size * 0.32,
                kb_cy - self.pet_size * 0.13,
                self.pet_size * 0.64,
                self.pet_size * 0.26,
            )
            if kb_rect.contains(QPointF(local_pt)):
                return True

        nx = (local_pt.x() - sprite_left) / max(1.0, float(self.pet_size))
        ny = (local_pt.y() - sprite_top) / max(1.0, float(self.pet_size))

        if self.rig.flip_scale.value < 0.0:
            nx = 1.0 - nx

        nx = max(0.0, min(0.999, nx))
        ny = max(0.0, min(0.999, ny))

        grid_img = self.hit_grids.get(self.active_sprite_key) or self.hit_grids["idle"]
        gx = int(nx * HIT_GRID_SIZE)
        gy = int(ny * HIT_GRID_SIZE)

        for oy in range(-3, 4):
            py = gy + oy
            if py < 0 or py >= HIT_GRID_SIZE:
                continue
            for ox in range(-3, 4):
                px = gx + ox
                if px < 0 or px >= HIT_GRID_SIZE:
                    continue
                if qAlpha(grid_img.pixel(px, py)) > 20:
                    return True
        return False

    def nativeEvent(self, eventType, message):
        """Windows 像素级点击穿透：透明留白处返回 HTTRANSPARENT，不遮挡桌面和窗口。"""
        if sys.platform == "win32" and not self.dragging:
            try:
                if bytes(eventType) == b"windows_generic_MSG":
                    msg = ctypes.wintypes.MSG.from_address(int(message))
                    if msg.message == WM_NCHITTEST:
                        local_pt = self.mapFromGlobal(QCursor.pos())
                        if not self._is_point_on_pet(local_pt):
                            return True, HTTRANSPARENT
            except Exception:
                pass
        return super().nativeEvent(eventType, message)

    # ---------- 状态切换、交叉淡入与动作编排 ----------
    def _set_state(self, new_state: str):
        old_key = self.active_sprite_key
        self.state = new_state
        new_key = self._current_sprite_key()
        if new_key != old_key:
            self.prev_sprite_key = old_key
            self.active_sprite_key = new_key
            self.crossfade_progress = 0.0
        else:
            self.active_sprite_key = new_key

    def _sync_sprite_crossfade(self, dt: float):
        desired_key = self._current_sprite_key()
        if desired_key != self.active_sprite_key:
            old_key = self.active_sprite_key
            self.prev_sprite_key = old_key
            self.active_sprite_key = desired_key
            # 走路序列帧（walk_a ↔ walk_b）直接零淡入切换，避免半透明重影闪烁
            if {old_key, desired_key}.issubset({"walk_a", "walk_b"}):
                self.crossfade_progress = 1.0
            else:
                self.crossfade_progress = 0.0
        elif self.crossfade_progress < 1.0:
            self.crossfade_progress = min(1.0, self.crossfade_progress + dt / 0.10)

    def _apply_action_step(self, step: ActionStep):
        self._set_state(step.state)
        self.state_timer = 0.0
        self.vx = 0.0
        if step.state == "eat":
            self.chew_pulse_timer = 0.0
            self.rig.impulse_squash(0.11)
        elif step.state == "flip":
            self.flip_spin_angle = 0.0
        elif step.state == "happy" and step.tag == "flip_land":
            self.rig.impulse_squash(0.20)
        if step.message:
            self.say(step.message)
        if step.particle_kind and step.particle_count > 0:
            self.spawn_burst(step.particle_kind, step.particle_count)
        if step.sound:
            self.sound.play(step.sound)

    def _start_sequence(self, steps: list[ActionStep]):
        first = self.action_queue.replace(steps)
        if first is not None:
            self._apply_action_step(first)

    # ---------- 6 条核心连贯动作链 ----------
    def start_sleep_sequence(self, chatter: bool = True):
        msg_prep = random.choice(self.LINES["sleep_prep"]) if chatter else None
        msg_sleep = random.choice(self.LINES["sleep"]) if chatter else None
        self._start_sequence(
            [
                ActionStep("sit", 2.4, message=msg_prep),
                ActionStep("sleep", random.uniform(10.0, 14.0), message=msg_sleep),
                ActionStep("sit", 1.5, message="睡醒啦~ 先坐起来发会呆…"),
                ActionStep("happy", 0.9, message="伸个大懒腰！继续陪你✨", particle_kind="star", particle_count=4, sound="pet"),
                ActionStep("idle", 0.1),
            ]
        )

    def start_wake_sequence(self):
        self._start_sequence(
            [
                ActionStep("sit", 0.9, message="唔……是谁在叫本喵？", particle_kind="star", particle_count=3, sound="pet"),
                ActionStep("happy", 0.9, message=random.choice(self.LINES["wake"]), particle_kind="star", particle_count=5),
                ActionStep("idle", 0.1),
            ]
        )

    def perform_backflip(self):
        """反重力 360° 后空翻炫技链。"""
        if not self.isVisible():
            self.show()
        if self.dragging:
            return
        self.cfg.trick_count += 1
        self._add_affection(3)
        self._start_sequence(
            [
                ActionStep("sit", 0.42, message="看好了！反重力后空翻准备——", sound="pet"),
                ActionStep("flip", 0.72, particle_kind="star", particle_count=8, sound="jump", spin_360=True),
                ActionStep("happy", 1.15, message="完美落地！这波操作满分吧~✨", particle_kind="star", particle_count=10, tag="flip_land"),
                ActionStep("idle", 0.1),
            ]
        )
        self.save_state()

    def trigger_overload(self):
        self._start_sequence(
            [
                ActionStep("overload", 2.6, message=random.choice(self.LINES["overload"]), particle_kind="spark", particle_count=10, sound="overload"),
                ActionStep("sit", 1.7, message="呼……瘫坐缓一下，CPU 终于降回常温了"),
                ActionStep("idle", 0.1),
            ]
        )

    def trigger_rub_sequence(self, msg: str | None = None):
        self._start_sequence(
            [
                ActionStep("shy", 1.45, message=msg or random.choice(self.LINES["rub_head"]), particle_kind="heart", particle_count=5, sound="shy"),
                ActionStep("happy", 0.85, particle_kind="star", particle_count=4),
                ActionStep("idle", 0.1),
            ]
        )

    # ---------- 养成、投喂、助手与开关 ----------
    def _add_affection(self, delta: int):
        old_lv, _, _, _ = get_affinity_level(self.cfg.affection)
        self.cfg.affection = max(0, self.cfg.affection + delta)
        new_lv, new_title, _, _ = get_affinity_level(self.cfg.affection)
        if new_lv > old_lv:
            self.spawn_burst("heart", 10)
            self.spawn_burst("star", 10)
            self.say(f"✨ 亲密等级提升至 Lv.{new_lv}「{new_title}」啦！继续贴贴~", 4500)
        self._refresh_status_if_open()

    def _refresh_status_if_open(self):
        if self.status_dialog.isVisible():
            self.status_dialog.refresh(
                self.cfg,
                self.pomodoro_remaining_sec,
                self.drink_elapsed_sec,
                laser_active=self.laser_mode,
            )

    def save_state(self):
        self.cfg.pet_size = self.pet_size
        self.cfg.pos_x = float(self.pos_x)
        self.cfg.pos_y = float(self.pos_y)
        self.cfg.auto_walk = self.auto_walk_enabled
        self.cfg.follow_mouse = self.follow_mouse
        self.cfg.antigravity = self.antigravity_mode
        self.cfg.always_on_top = self.always_on_top
        self.cfg.sound_enabled = self.sound.enabled
        self.cfg.live2d_enabled = self.live2d_enabled
        save_config(self.cfg)

    def open_status_dialog(self):
        self._refresh_status_if_open()
        self.status_dialog.refresh(
            self.cfg,
            self.pomodoro_remaining_sec,
            self.drink_elapsed_sec,
            laser_active=self.laser_mode,
        )
        anchor = QPoint(int(self.pos_x + self.width() * 0.5), int(self.pos_y + self.margin))
        self.status_dialog.show_near(anchor)

    def say(self, text: str, duration_ms: int = 3400):
        if not self.isVisible():
            return
        anchor = QPoint(
            int(self.pos_x + self.width() * 0.5),
            int(self.pos_y + self.margin + 6 + self.render_dy * 0.4),
        )
        self.bubble.show_message(text, anchor, duration_ms)

    def spawn_burst(self, kind: str, count: int = 6, origin: tuple[float, float] | None = None):
        cx = origin[0] if origin else self.width() * 0.5
        cy = origin[1] if origin else self.height() * 0.42
        palette = {
            "star": [QColor(255, 218, 95), QColor(140, 210, 255), QColor(200, 155, 255)],
            "heart": [QColor(255, 115, 175), QColor(255, 155, 200), QColor(255, 200, 110)],
            "spark": [QColor(255, 200, 60), QColor(255, 120, 90), QColor(150, 210, 255)],
            "zzz": [QColor(115, 125, 215)],
        }
        colors = palette.get(kind, [QColor(255, 220, 120)])
        for _ in range(count):
            ang = random.uniform(-math.pi * 0.92, -math.pi * 0.08)
            spd = random.uniform(35, 98) if kind != "zzz" else random.uniform(18, 30)
            self.particles.append(
                Particle(
                    x=cx + random.uniform(-self.pet_size * 0.22, self.pet_size * 0.22),
                    y=cy + random.uniform(-self.pet_size * 0.18, self.pet_size * 0.10),
                    vx=math.cos(ang) * spd if kind != "zzz" else random.uniform(8, 22),
                    vy=math.sin(ang) * spd if kind != "zzz" else random.uniform(-34, -22),
                    life=0.0,
                    max_life=random.uniform(0.75, 1.35) if kind != "zzz" else 1.7,
                    kind=kind,
                    size=random.uniform(8, 14),
                    color=random.choice(colors),
                    rot=random.uniform(0, math.tau),
                    vrot=random.uniform(-3.0, 3.0),
                )
            )

    def feed_fish(self, from_left: bool | None = None):
        """生成抛物线小鱼干飞向猫猫嘴部，到达时进入大口吃鱼连贯动作链。"""
        if not self.isVisible():
            self.show()
        if from_left is None:
            from_left = random.choice([True, False])
        sx = self.margin * 0.22 if from_left else self.width() - self.margin * 0.22
        sy = self.margin * 0.30
        tx = self.width() * 0.5
        ty = self.margin + self.pet_size * 0.44
        ctrl_x = (sx + tx) * 0.5 + (24 if from_left else -24)
        ctrl_y = min(sy, ty) - self.pet_size * 0.34
        self.flying_fishes.append(
            FlyingFish(
                start_x=sx,
                start_y=sy,
                ctrl_x=ctrl_x,
                ctrl_y=ctrl_y,
                target_x=tx,
                target_y=ty,
                rot_dir=1.0 if from_left else -1.0,
            )
        )
        # 醒来并期待小鱼干
        if self.state == "sleep":
            self.action_queue.clear()
            self._set_state("idle")
            self.say("嗅嗅……是谁端来了香喷喷的小鱼干！🐟", 1500)
        self.facing_right = not from_left  # 朝向鱼来的方位（左来朝左，右来朝右）

    def feed_feast(self):
        """连抛 3 条小鱼干的大餐演出！"""
        self.say(random.choice(self.LINES["feast"]), 2800)
        self.feed_fish(True)
        QTimer.singleShot(280, lambda: self.feed_fish(False))
        QTimer.singleShot(560, lambda: self.feed_fish(True))

    def _on_fish_caught(self, x: float, y: float):
        self.cfg.feed_count += 1
        self.cfg.satiety = min(100, self.cfg.satiety + 18)
        self.spawn_burst("star", 10, (x, y))
        self.spawn_burst("heart", 6, (x, y))
        self.live2d.impulse_ears(1.2, asymmetric=False)
        self.live2d.impulse_ahoge(110.0)

        cur = self.action_queue.current()
        if cur is not None and cur.state == "eat":
            # 连抛大餐期间继续接住后续小鱼干，叠加强化咀嚼反馈与延长吃鱼时间
            self.action_queue.elapsed = max(0.0, self.action_queue.elapsed - 0.9)
            self.rig.impulse_squash(0.14)
            self.sound.play("eat")
        else:
            self._start_sequence(
                [
                    ActionStep("eat", 2.4, message=random.choice(self.LINES["eat"]), sound="eat"),
                    ActionStep(
                        "happy",
                        1.15,
                        message=random.choice(self.LINES["eat_done"]) if self.cfg.satiety >= 90 else None,
                        particle_kind="star",
                        particle_count=6,
                        sound="feed",
                    ),
                    ActionStep("idle", 0.1),
                ]
            )
        self._add_affection(6)
        self.save_state()

    def trigger_happy(self, message: str | None = None, sound: bool = True):
        self.action_queue.clear()
        self._set_state("happy")
        self.state_timer = 0.0
        self.next_decision_in = 2.4
        self.vx = 0.0
        self.rig.impulse_squash(0.12)
        self.spawn_burst("heart", 5)
        self.spawn_burst("star", 4)
        if sound:
            self.sound.play("pet")
        if message:
            self.say(message)

    def force_state(self, st: str):
        self.action_queue.clear()
        if st == "sleep":
            self.start_sleep_sequence(chatter=True)
        elif st == "happy":
            self.trigger_happy("好耶！今天也要元气满满！✨")
        elif st == "overload":
            self.trigger_overload()
        elif st == "eat":
            self.feed_fish()
        elif st == "shy":
            self.trigger_rub_sequence("呜……突然这样看着我干嘛啦~ 💖")
        elif st == "sit":
            self._set_state("sit")
            self.state_timer = 0.0
            self.next_decision_in = 6.0
            self.say("乖乖坐下陪着你~")
        else:
            self._set_state("idle")
            self.state_timer = 0.0
            self.next_decision_in = 4.0
            self.say("切换回星辰待机姿态啦~")

    def toggle_laser_mode(self, checked: bool):
        self.laser_mode = bool(checked)
        if self.laser_mode:
            if not self.isVisible():
                self.show()
            self.action_queue.clear()
            if self.state == "sleep":
                self._set_state("idle")
            self.laser_toy.start()
            self.sound.play("jump")
            self.say(random.choice(self.LINES["laser_on"]), 3800)
        else:
            self.laser_toy.stop()
            if self.state == "walk":
                self._set_state("idle")
            self.say(random.choice(self.LINES["laser_off"]), 2400)
        self._refresh_status_if_open()

    def toggle_antigravity(self, checked: bool):
        self.antigravity_mode = bool(checked)
        self.cfg.antigravity = self.antigravity_mode
        if self.antigravity_mode:
            self.say(random.choice(self.LINES["antigravity_on"]))
            self.spawn_burst("star", 10)
            self.sound.play("jump")
            self.vy = -85.0
            if self.state in ("sleep", "sit"):
                self.action_queue.clear()
                self._set_state("idle")
        else:
            self.say(random.choice(self.LINES["antigravity_off"]))
            if self.pos_y < self._floor_y() - 4:
                self.action_queue.clear()
                self._set_state("falling")
                self.vy = 0.0
        self.save_state()

    def toggle_follow_mouse(self, checked: bool):
        self.follow_mouse = bool(checked)
        self.cfg.follow_mouse = self.follow_mouse
        if self.follow_mouse and self.state == "sleep":
            self.action_queue.clear()
            self._set_state("idle")
        self.say(random.choice(self.LINES["follow_on"] if self.follow_mouse else self.LINES["follow_off"]))
        self.save_state()

    def toggle_auto_walk(self, checked: bool):
        self.auto_walk_enabled = bool(checked)
        self.cfg.auto_walk = self.auto_walk_enabled
        if not self.auto_walk_enabled and self.state == "walk" and not self.follow_mouse and not self.laser_mode:
            self._set_state("idle")
            self.vx = 0.0
        self.say("开启桌面自由巡逻！" if self.auto_walk_enabled else "好哒，我乖乖待在原地不乱跑~")
        self.save_state()

    def toggle_pomodoro(self):
        if self.pomodoro_remaining_sec > 0:
            self.pomodoro_remaining_sec = 0
            self.say("🍅 已暂停并停止本轮番茄专注计时~")
        else:
            self.pomodoro_remaining_sec = 25 * 60
            self.sound.play("pet")
            self.spawn_burst("star", 6)
            self.say("🍅 番茄钟开始！接下来 25 分钟本喵陪你一起专注~", 3800)
        self._refresh_status_if_open()

    def toggle_drink_reminder(self, checked: bool):
        self.cfg.drink_reminder_enabled = bool(checked)
        self.drink_elapsed_sec = 0
        if checked:
            self.sound.play("pet")
            self.say(f"💧 喝水提醒已开启！每 {self.cfg.drink_interval_min} 分钟提醒你喝口水~")
        else:
            self.say("💧 已关闭喝水提醒~")
        self.save_state()
        self._refresh_status_if_open()

    def toggle_sound(self, checked: bool):
        self.sound.enabled = bool(checked)
        self.cfg.sound_enabled = self.sound.enabled
        if self.sound.enabled:
            self.sound.play("pet")
            self.say("🔊 互动音效已开启！")
        else:
            self.say("🔇 已静音互动音效~")
        self.save_state()

    def toggle_always_on_top(self, checked: bool):
        self.always_on_top = bool(checked)
        self.cfg.always_on_top = self.always_on_top
        flags = Qt.FramelessWindowHint | Qt.Tool
        if self.always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        self.save_state()

    def toggle_autostart(self, checked: bool):
        ok = set_autostart(bool(checked), BASE_DIR)
        if ok:
            self.say("🚀 已开启开机自动启动！" if checked else "🚀 已取消开机自动启动~")
        else:
            self.say("⚠️ 无法修改开机自启项，请检查系统权限。")

    def set_pet_size(self, px: int, announce: bool = False):
        px = max(120, min(260, int(px)))
        old_bottom = self.pos_y + self.height()
        old_cx = self.pos_x + self.width() * 0.5
        self.pet_size = px
        self.cfg.pet_size = px
        self._apply_window_size()
        self.pos_x = old_cx - self.width() * 0.5
        self.pos_y = (
            min(old_bottom - self.height(), self._floor_y())
            if not self.antigravity_mode
            else old_bottom - self.height()
        )
        self.move(int(self.pos_x), int(self.pos_y))
        self.rig.impulse_squash(0.09)
        if announce:
            self.say(f"📏 体型调整为 {px}px ✨", 1600)
        self.update()
        self.save_state()

    def toggle_typing_sync(self, checked: bool):
        self.typing_sync = bool(checked)
        self.cfg.typing_sync = self.typing_sync
        self.typing_monitor.set_enabled(self.typing_sync)
        if self.typing_sync:
            self.sound.play("pet")
            self.say("⌨️ 同步模仿打字已开启！快敲键盘试试看~")
        else:
            if self.state == "typing":
                self._finish_typing_session(quiet=True)
            self.say("⌨️ 已暂停同步模仿打字~")
        self.save_state()

    def toggle_live2d(self, checked: bool):
        self.live2d_enabled = bool(checked)
        self.cfg.live2d_enabled = self.live2d_enabled
        if self.live2d_enabled:
            self.live2d.trigger_blink()
            self.live2d.impulse_ears(1.1, asymmetric=True)
            self.say("✨ Live2D 灵动物理已开启！我会悄悄看着你哦~")
        else:
            self.say("✨ 已切回经典静态手绘渲染模式~")
        self.update()
        self.save_state()

    def toggle_visibility(self):
        if self.isVisible():
            if self.laser_mode:
                self.laser_mode = False
                self.laser_toy.stop()
            self.typing_monitor.stop()
            self.bubble.hide()
            self.status_dialog.hide()
            self.hide()
        else:
            self.show()
            self.raise_()
            if self.typing_sync:
                self.typing_monitor.start()
            self.say("我回来啦！✨")

    def wake_from_external(self):
        if not self.isVisible():
            self.show()
        self.raise_()
        if self.typing_sync:
            self.typing_monitor.start()
        self.trigger_happy("喵呜~ 我已经在桌面上啦，不用重复召唤我哦✨")

    def quit_app(self):
        self.save_state()
        self.typing_monitor.stop()
        self.laser_toy.stop()
        self.laser_toy.close()
        self.bubble.close()
        self.status_dialog.close()
        self.tray.hide()
        QApplication.quit()

    # ---------- 鼠标与键盘交互 ----------
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.laser_mode:
            self.toggle_laser_mode(False)
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta != 0:
            step = 10 if delta > 0 else -10
            new_px = max(120, min(260, self.pet_size + step))
            if new_px != self.pet_size:
                self.set_pet_size(new_px, announce=True)
            event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_moved = False
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.last_mouse_global = event.globalPosition().toPoint()
            self.vx = 0.0
            self.vy = 0.0
            event.accept()
        elif event.button() == Qt.MiddleButton:
            # 鼠标中键快捷丢出小鱼干
            from_left = event.position().x() < self.width() * 0.5
            self.feed_fish(from_left=from_left)
            event.accept()
        elif event.button() == Qt.RightButton:
            self._refresh_shared_menu()
            self.shared_menu.exec(QCursor.pos())
            event.accept()

    def mouseMoveEvent(self, event):
        if self.dragging and (event.buttons() & Qt.LeftButton):
            gpos = event.globalPosition().toPoint()
            delta = gpos - self.last_mouse_global
            if abs(delta.x()) + abs(delta.y()) >= 3:
                if not self.drag_moved:
                    self.drag_moved = True
                    self.action_queue.clear()
                    self._set_state("dragged")
                    self.state_timer = 0.0
                    self.say(random.choice(self.LINES["drag_start"]), 2400)

                new_top_left = gpos - self.drag_offset
                self.pos_x = float(new_top_left.x())
                self.pos_y = float(new_top_left.y())
                self.move(int(self.pos_x), int(self.pos_y))

                self.swing_vel += max(-180.0, min(180.0, -delta.x() * 4.8))
                self.vx = max(-520.0, min(520.0, delta.x() * 24.0))
                self.vy = max(-420.0, min(420.0, delta.y() * 18.0))
                self.last_mouse_global = gpos

                if self.bubble.isVisible():
                    self.bubble.reposition(
                        QPoint(int(self.pos_x + self.width() * 0.5), int(self.pos_y + self.margin + 6))
                    )
            event.accept()
            return

        # 悬停在头顶/脸颊区左右轻抚（rua 猫头顺毛连贯害羞蹭手）
        local_pt = event.position().toPoint()
        ny = (local_pt.y() - (self.margin + self.render_dy)) / max(1.0, float(self.pet_size))
        nx = (local_pt.x() - self.margin) / max(1.0, float(self.pet_size))
        if (
            0.12 <= nx <= 0.88
            and 0.06 <= ny <= 0.56
            and self.state not in ("dragged", "overload", "flip", "eat")
            and not self.laser_mode
        ):
            if self.last_hover_pos is not None:
                step_x = abs(local_pt.x() - self.last_hover_pos.x())
                if 1 <= step_x <= 38:
                    self.rub_distance += step_x
                    if self.rub_distance >= 115.0 and self.rub_cooldown <= 0.0:
                        self.rub_distance = 0.0
                        self.rub_cooldown = 2.8
                        self.cfg.pet_count += 1
                        self.rig.impulse_tilt(22.0 if nx > 0.5 else -22.0)
                        self.live2d.impulse_ears(1.15, asymmetric=False)
                        self.live2d.impulse_ahoge(95.0 if nx > 0.5 else -95.0)
                        self.trigger_rub_sequence()
                        self._add_affection(2)
                        self.save_state()
            self.last_hover_pos = local_pt
        else:
            self.last_hover_pos = None
            self.rub_distance = max(0.0, self.rub_distance - 10.0)

    def leaveEvent(self, event):
        self.last_hover_pos = None
        self.rub_distance = 0.0
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.dragging:
            self.dragging = False
            if self.drag_moved:
                if self.antigravity_mode:
                    self._set_state("idle")
                    self.state_timer = 0.0
                    self.vx *= 0.25
                    self.vy *= 0.25
                    self.spawn_burst("star", 5)
                else:
                    if self.pos_y < self._floor_y() - 6:
                        self._set_state("falling")
                        self.state_timer = 0.0
                    else:
                        self.pos_y = self._floor_y()
                        self.rig.impulse_squash(0.22)
                        self._set_state("idle")
                        self.state_timer = 0.0
                        self.say(random.choice(self.LINES["land"]), 2400)
                self.save_state()
            else:
                now = time.perf_counter()
                self.recent_clicks = [t for t in self.recent_clicks if now - t < 1.6]
                self.recent_clicks.append(now)
                if len(self.recent_clicks) >= 4:
                    self.recent_clicks.clear()
                    self.trigger_overload()
                elif self.state == "sleep":
                    self.start_wake_sequence()
                else:
                    ny = (event.position().y() - (self.margin + self.render_dy)) / max(1.0, float(self.pet_size))
                    nx = (event.position().x() - self.margin) / max(1.0, float(self.pet_size))
                    self.cfg.pet_count += 1
                    if ny < 0.42:
                        self.live2d.impulse_ears(1.3, asymmetric=True)
                        self.live2d.impulse_ahoge(130.0 if nx < 0.5 else -130.0)
                        self.trigger_happy(random.choice(self.LINES["pet_ear"]))
                        self._add_affection(2)
                    elif ny < 0.68:
                        self.rig.impulse_tilt(28.0 if nx > 0.5 else -28.0)
                        self.live2d.impulse_ears(0.95, asymmetric=False)
                        self.live2d.trigger_blink()
                        self.trigger_rub_sequence(random.choice(self.LINES["pet_cheek"]))
                        self._add_affection(2)
                    else:
                        if not self.antigravity_mode:
                            self.vy = -140.0
                            self.action_queue.clear()
                            self._set_state("falling")
                        self.rig.impulse_squash(0.15)
                        self.live2d.impulse_ahoge(-120.0)
                        self.spawn_burst("star", 5)
                        self.sound.play("jump")
                        self.say(random.choice(self.LINES["pet_foot"]))
                        self._add_affection(1)
                    self.save_state()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.action_queue.clear()
            if not self.antigravity_mode and self.state != "falling":
                self.vy = -210.0
                self._set_state("falling")
            self.rig.impulse_squash(0.14)
            self.spawn_burst("star", 9)
            self.sound.play("jump")
            self.say("咻——反重力小跳！✨", 2200)
            event.accept()

    # ---------- 同步模仿打字感知与收尾演出 ----------
    def _spawn_code_particle(self):
        """在星辰小键盘上方冒出可爱的迷你代码符号/音符浮字。"""
        cx = self.width() * 0.5 + self.rig.dx.value
        cy = self.margin + self.pet_size * 0.72 + self.render_dy
        glyph = random.choice(["{ }", "<>", "0", "1", "★", "♪", "()"])
        col = random.choice(
            [
                QColor(115, 130, 245),
                QColor(235, 120, 195),
                QColor(95, 195, 235),
                QColor(245, 185, 70),
            ]
        )
        self.particles.append(
            Particle(
                x=cx + random.uniform(-self.pet_size * 0.24, self.pet_size * 0.24),
                y=cy + random.uniform(-6, 6),
                vx=random.uniform(-22, 22),
                vy=random.uniform(-68, -42),
                life=0.0,
                max_life=random.uniform(0.75, 1.15),
                kind="code",
                size=random.uniform(9.5, 12.5),
                color=col,
                rot=0.0,
                vrot=0.0,
                text=glyph,
            )
        )

    def _finish_typing_session(self, quiet: bool = False):
        """停止打字后自动收起小键盘并连贯过渡回休息/待机态。"""
        keys = self.typing_session_keys
        self.typing_session_keys = 0
        self.typing_idle_timer = 0.0
        self.typing_pose = "ready"
        self.typing_pose_hold = 0.0
        self.recent_type_times.clear()
        self.left_paw_press.target = 0.45
        self.right_paw_press.target = 0.45
        self.keyboard_pop.target = 0.0

        if not quiet and keys >= 30:
            msg = random.choice(self.LINES["typing_done"]) if self.typing_bubble_cooldown <= 0.0 else None
            if msg:
                self.typing_bubble_cooldown = 45.0
            self._start_sequence(
                [
                    ActionStep("sit", 0.70),
                    ActionStep("happy", 0.90, message=msg, particle_kind="star", particle_count=6, sound="pet"),
                    ActionStep("idle", 0.1),
                ]
            )
        else:
            self._start_sequence(
                [
                    ActionStep("sit", 0.75),
                    ActionStep("idle", 0.1),
                ]
            )
        self.save_state()

    def _on_global_key_tap(self, hand: str):
        """响应全局键盘输入（仅接收匿名左右手/双手拍键，绝不接触具体按键内容）。"""
        if (
            not self.typing_sync
            or not self.isVisible()
            or self.dragging
            or self.laser_mode
            or self.state in ("overload", "flip", "eat")
        ):
            return

        now = time.perf_counter()

        # 若猫猫正在打盹，需连续敲 3 下才温和唤醒，避免误触吵醒
        if self.state == "sleep":
            self.sleep_wake_taps = [t for t in self.sleep_wake_taps if now - t < 2.0]
            self.sleep_wake_taps.append(now)
            if len(self.sleep_wake_taps) < 3:
                return
            self.sleep_wake_taps.clear()
            self.action_queue.clear()
            self._set_state("typing")
            self.rig.impulse_squash(0.14)
            if self.typing_bubble_cooldown <= 0.0:
                self.typing_bubble_cooldown = 45.0
                self.say(random.choice(self.LINES["typing_wake"]), 3400)

        self.typing_idle_timer = 0.0
        self.typing_session_keys += 1
        self.cfg.type_count += 1
        if self.cfg.type_count % 100 == 0:
            self._add_affection(1)
        else:
            self._refresh_status_if_open()

        self.recent_type_times = [t for t in self.recent_type_times if now - t < 1.5]
        self.recent_type_times.append(now)
        is_fast = len(self.recent_type_times) >= 10

        if self.state != "typing":
            self.action_queue.clear()
            self._set_state("typing")
            self.state_timer = 0.0
            self.vx = 0.0
            self.vy = 0.0
            self.rig.impulse_squash(0.13)
            if self.typing_bubble_cooldown <= 0.0:
                self.typing_bubble_cooldown = 45.0
                self.sound.play("pet")
                self.say(random.choice(self.LINES["typing_start"]), 3400)

        # 左右萌爪强烈反差交替拍键（一高举、一拍键并保持 0.42s）
        if hand == "left":
            if self.typing_pose == "left_down":
                # 同手连续敲击时先瞬时微抬，再清晰拍下
                self.left_paw_press.value = 0.52
            self.typing_hand = "left"
            self.typing_pose = "left_down"
            self.typing_pose_hold = 0.42
            self.last_lit_zone = "left"
            self.left_paw_press.target = 1.0
            self.right_paw_press.target = 0.0
            self.rig.impulse_tilt(-15.0)
            self.rig.impulse_squash(0.05)
            self.kb_shake.impulse(28.0)
            self.live2d.impulse_ears(0.45, asymmetric=True)
            self.live2d.impulse_ahoge(-52.0)
        elif hand == "right":
            if self.typing_pose == "right_down":
                self.right_paw_press.value = 0.52
            self.typing_hand = "right"
            self.typing_pose = "right_down"
            self.typing_pose_hold = 0.42
            self.last_lit_zone = "right"
            self.right_paw_press.target = 1.0
            self.left_paw_press.target = 0.0
            self.rig.impulse_tilt(15.0)
            self.rig.impulse_squash(0.05)
            self.kb_shake.impulse(28.0)
            self.live2d.impulse_ears(0.45, asymmetric=True)
            self.live2d.impulse_ahoge(52.0)
        else:  # both（Space / Enter 双爪齐重拍）
            self.typing_hand = "right" if self.typing_hand == "left" else "left"
            self.typing_pose = "both_down"
            self.typing_pose_hold = 0.36
            self.last_lit_zone = "space"
            self.left_paw_press.value = 0.45
            self.left_paw_press.target = 1.0
            self.right_paw_press.value = 0.45
            self.right_paw_press.target = 1.0
            self.rig.impulse_squash(0.10)
            self.kb_shake.impulse(45.0)
            self.live2d.impulse_ears(0.85, asymmetric=False)
            self.live2d.impulse_ahoge(95.0)
            self.spawn_burst("star", 3)

        self.key_lit_timer = 0.22
        if is_fast or random.random() < 0.55:
            self._spawn_code_particle()
        if is_fast and random.random() < 0.45:
            self.spawn_burst("spark" if random.random() < 0.5 else "star", 1)

    # ---------- 60 FPS 与 1 秒循环 ----------
    def _on_second_tick(self):
        self.cfg.companion_seconds += 1

        self.hungry_ticker += 1
        if self.hungry_ticker >= 180:
            self.hungry_ticker = 0
            self.cfg.satiety = max(0, self.cfg.satiety - 1)
            if (
                self.cfg.satiety < 25
                and self.state == "idle"
                and not self.action_queue.is_active()
                and not self.laser_mode
            ):
                self._start_sequence(
                    [
                        ActionStep("sit", 2.8, message=random.choice(self.LINES["hungry"])),
                        ActionStep("idle", 0.1),
                    ]
                )

        if self.pomodoro_remaining_sec > 0:
            self.pomodoro_remaining_sec -= 1
            if self.pomodoro_remaining_sec == 0:
                self.sound.play("remind")
                self.trigger_happy("🍅 25分钟专注完成啦！快站起来活动一下~", sound=False)
                self.spawn_burst("star", 10)
                self._add_affection(5)
                self.save_state()

        if self.cfg.drink_reminder_enabled:
            self.drink_elapsed_sec += 1
            if self.drink_elapsed_sec >= self.cfg.drink_interval_min * 60:
                self.drink_elapsed_sec = 0
                self.sound.play("remind")
                self.trigger_happy("💧 已经专注很久啦，快喝口水休息下眼睛哦~", sound=False)
                self.spawn_burst("star", 8)

        self._refresh_status_if_open()

    def _tick(self):
        now = time.perf_counter()
        dt = min(0.05, max(0.005, now - self.last_tick))
        self.last_tick = now

        self.anim_time += dt
        self.state_timer += dt
        self.chatter_cooldown -= dt
        if self.typing_bubble_cooldown > 0.0:
            self.typing_bubble_cooldown = max(0.0, self.typing_bubble_cooldown - dt)
        if self.key_lit_timer > 0.0:
            self.key_lit_timer = max(0.0, self.key_lit_timer - dt)
        if self.rub_cooldown > 0.0:
            self.rub_cooldown = max(0.0, self.rub_cooldown - dt)
        if self.laser_pounce_cooldown > 0.0:
            self.laser_pounce_cooldown = max(0.0, self.laser_pounce_cooldown - dt)

        # 更新星辰小键盘弹出、受击震动与左右萌爪弹簧
        self.keyboard_pop.target = 1.0 if (self.state == "typing" and not self.dragging) else 0.0
        self.keyboard_pop.step(dt)
        self.kb_shake.step(dt)
        self.left_paw_press.step(dt)
        self.right_paw_press.step(dt)

        # 保持一高举一拍键反差；超时归回待命微悬，2.8秒无按键收起键盘
        if self.state == "typing" and not self.dragging:
            if self.typing_pose != "ready":
                self.typing_pose_hold -= dt
                if self.typing_pose_hold <= 0.0:
                    self.typing_pose = "ready"
                    self.left_paw_press.target = 0.45
                    self.right_paw_press.target = 0.45
            self.typing_idle_timer += dt
            if self.typing_idle_timer >= 2.8:
                self._finish_typing_session(quiet=False)

        bounds = self._screen_bounds()
        floor_y = self._floor_y()

        # 推进动作链队列
        if not self.dragging and self.action_queue.is_active():
            entered = self.action_queue.advance(dt)
            if entered is not None:
                self._apply_action_step(entered)
            elif not self.action_queue.is_active() and self.state not in ("falling", "dragged"):
                self._set_state("idle")
                self.state_timer = 0.0
                self.next_decision_in = random.uniform(2.8, 5.0)

        # 处理吃鱼咀嚼小弹性 & 360 后空翻螺旋旋转
        cur_step = self.action_queue.current()
        if self.state == "eat":
            self.chew_pulse_timer += dt
            if self.chew_pulse_timer >= 0.45:
                self.chew_pulse_timer = 0.0
                self.rig.impulse_squash(0.07)
                if random.random() < 0.55:
                    self.spawn_burst("heart", 1)
        elif self.state == "flip" and cur_step is not None and cur_step.spin_360:
            prog = self.action_queue.progress()
            direction = -1.0 if self.facing_right else 1.0
            self.flip_spin_angle = direction * 360.0 * prog
            if random.random() < dt * 28.0:
                self.spawn_burst("star", 1)
        else:
            self.flip_spin_angle = 0.0

        # 钟摆弹簧恢复（拎起晃悠）
        stiffness = 28.0 if self.dragging else 46.0
        damping = 4.2 if self.dragging else 7.5
        acc = -stiffness * self.swing_angle - damping * self.swing_vel
        self.swing_vel += acc * dt
        self.swing_angle += self.swing_vel * dt
        self.swing_angle = max(-32.0, min(32.0, self.swing_angle))

        if not self.dragging:
            if self.antigravity_mode:
                self._step_antigravity(dt, bounds, floor_y)
            elif self.state == "falling":
                self._step_falling(dt, bounds, floor_y)
            else:
                self._step_grounded(dt, bounds, floor_y)

            # 逗猫棒扑抓中持续冲刺并判定扑中光点
            if (
                self.laser_mode
                and cur_step is not None
                and cur_step.tag == "laser_pounce"
                and self.state == "happy"
            ):
                self._step_laser_pounce(dt, bounds, floor_y)

            # 无动作链时的自主行为决策
            if not self.action_queue.is_active() and self.state in ("idle", "walk", "happy", "sit", "shy", "eat"):
                if (self.follow_mouse or self.laser_mode) and self.state in ("idle", "walk"):
                    pass
                elif self.state_timer >= self.next_decision_in:
                    self._choose_next_behavior()

            if self.chatter_cooldown <= 0 and self.state in ("idle", "walk") and not self.action_queue.is_active():
                self.chatter_cooldown = random.uniform(28.0, 50.0)
                if not self.bubble.isVisible():
                    self.say(random.choice(self.LINES["idle_chatter"]), 3800)

            self.move(int(self.pos_x), int(self.pos_y))
            if self.bubble.isVisible():
                self.bubble.reposition(
                    QPoint(
                        int(self.pos_x + self.width() * 0.5),
                        int(self.pos_y + self.margin + 6 + self.render_dy * 0.4),
                    )
                )

        # 更新飞鱼投喂抛物线
        still_flying: list[FlyingFish] = []
        for fish in self.flying_fishes:
            fish.elapsed += dt
            if fish.elapsed >= fish.duration:
                self._on_fish_caught(fish.target_x, fish.target_y)
            else:
                t = fish.elapsed / fish.duration
                if random.random() < 0.45:
                    inv = 1.0 - t
                    fx = inv * inv * fish.start_x + 2 * inv * t * fish.ctrl_x + t * t * fish.target_x
                    fy = inv * inv * fish.start_y + 2 * inv * t * fish.ctrl_y + t * t * fish.target_y
                    self.particles.append(
                        Particle(
                            x=fx,
                            y=fy,
                            vx=random.uniform(-14, 14),
                            vy=random.uniform(-10, 14),
                            life=0.0,
                            max_life=0.45,
                            kind="star",
                            size=6.5,
                            color=QColor(255, 224, 115),
                        )
                    )
                still_flying.append(fish)
        self.flying_fishes = still_flying

        # 更新粒子
        alive: list[Particle] = []
        for p in self.particles:
            p.life += dt
            if p.life < p.max_life:
                p.x += p.vx * dt
                p.y += p.vy * dt
                if p.kind != "zzz":
                    p.vy += 32.0 * dt
                p.rot += p.vrot * dt
                alive.append(p)
        self.particles = alive

        # 同步弹簧姿势与交叉淡入淡出
        self._update_pose_rig(dt)
        self._sync_sprite_crossfade(dt)

        # 同步 2.5D Live2D 视线追踪、自动眨眼与呆毛/猫耳物理
        if self.live2d_enabled:
            gpos = QCursor.pos()
            pet_cx = self.pos_x + self.width() * 0.5
            pet_cy = self.pos_y + self.margin + self.pet_size * 0.42 + self.render_dy
            self.live2d.update(
                dt=dt,
                cursor_x=float(gpos.x()),
                cursor_y=float(gpos.y()),
                pet_cx=pet_cx,
                pet_cy=pet_cy,
                vx=self.vx,
                vy=self.vy,
                flipped=(self.rig.flip_scale.value < 0.0),
                state=self.state,
                anim_time=self.anim_time,
                dragging=self.dragging,
            )

        self.update()

    def _trigger_laser_pounce(self, dx: float, dy: float):
        """逗猫星光棒近距离蓄力飞扑连贯动作链。"""
        self.laser_pounce_cooldown = 1.7
        self.laser_caught_in_pounce = False
        self.facing_right = dx >= 0
        dist = max(1.0, math.hypot(dx, dy))
        speed = 260.0 if self.antigravity_mode else 235.0
        self.laser_pounce_vx = (dx / dist) * speed
        self.laser_pounce_vy = (dy / dist) * speed if self.antigravity_mode else 0.0

        self._start_sequence(
            [
                ActionStep("sit", 0.28, message="瞄准光点……蓄力！" if random.random() < 0.45 else None),
                ActionStep("happy", 0.52, particle_kind="star", particle_count=6, sound="jump", tag="laser_pounce"),
                ActionStep("idle", 0.1),
            ]
        )

    def _step_laser_pounce(self, dt: float, bounds: QRectF, floor_y: float):
        self.pos_x += self.laser_pounce_vx * dt
        if self.antigravity_mode:
            self.pos_y += self.laser_pounce_vy * dt

        min_x = bounds.left() - self.margin * 0.4
        max_x = bounds.right() - self.width() + self.margin * 0.4
        self.pos_x = max(min_x, min(max_x, self.pos_x))
        if self.antigravity_mode:
            self.pos_y = max(bounds.top(), min(floor_y, self.pos_y))

        if random.random() < dt * 16.0:
            self.spawn_burst("star", 1)

        if not self.laser_caught_in_pounce:
            gpos = QCursor.pos()
            cx = self.pos_x + self.width() * 0.5
            cy = self.pos_y + self.height() * 0.5
            hit_dist = math.hypot(gpos.x() - cx, gpos.y() - cy) if self.antigravity_mode else abs(gpos.x() - cx)
            if hit_dist < 68.0:
                self.laser_caught_in_pounce = True
                self.cfg.trick_count += 1
                self.rig.impulse_squash(0.16)
                self.spawn_burst("star", 12)
                self.spawn_burst("heart", 6)
                self.sound.play("pet")
                self._add_affection(3)
                self.say(random.choice(self.LINES["laser_catch"]), 2500)
                self.save_state()

    def _step_antigravity(self, dt: float, bounds: QRectF, floor_y: float):
        if self.action_queue.is_active():
            self.vx *= math.pow(0.15, dt)
            self.vy *= math.pow(0.15, dt)
        elif self.laser_mode and self.state in ("idle", "walk"):
            gpos = QCursor.pos()
            cx = self.pos_x + self.width() * 0.5
            cy = self.pos_y + self.height() * 0.5
            dx = gpos.x() - cx
            dy = gpos.y() - cy
            dist = math.hypot(dx, dy)
            if 55.0 <= dist <= 135.0 and self.laser_pounce_cooldown <= 0.0:
                self._trigger_laser_pounce(dx, dy)
            elif dist > 135.0:
                self._set_state("walk")
                self.facing_right = dx >= 0
                speed = min(240.0, max(130.0, dist * 0.8))
                self.vx = (dx / dist) * speed
                self.vy = (dy / dist) * speed
            elif dist < 55.0:
                if self.state == "walk":
                    self._set_state("idle")
                self.vx *= math.pow(0.05, dt)
                self.vy *= math.pow(0.05, dt)
        elif self.follow_mouse and self.state in ("idle", "walk"):
            gpos = QCursor.pos()
            cx = self.pos_x + self.width() * 0.5
            cy = self.pos_y + self.height() * 0.5
            dx = gpos.x() - cx
            dy = gpos.y() - cy
            dist = math.hypot(dx, dy)
            if dist > 110.0:
                self._set_state("walk")
                self.facing_right = dx >= 0
                speed = min(195.0, max(98.0, dist * 0.65))
                self.vx = (dx / dist) * speed
                self.vy = (dy / dist) * speed
            elif dist < 75.0:
                if self.state == "walk":
                    self._set_state("idle")
                self.vx *= math.pow(0.05, dt)
                self.vy *= math.pow(0.05, dt)
            else:
                self.vx *= math.pow(0.22, dt)
                self.vy *= math.pow(0.22, dt)
        else:
            self.vx *= math.pow(0.22, dt)
            self.vy *= math.pow(0.22, dt)
            if self.auto_walk_enabled and self.state == "walk":
                target_vx = 54.0 if self.facing_right else -54.0
                self.vx += (target_vx - self.vx) * min(1.0, dt * 3.0)
                self.vy += math.sin(self.anim_time * 1.4) * 18.0 * dt

        self.pos_x += self.vx * dt
        self.pos_y += self.vy * dt

        if random.random() < dt * 3.5:
            self.spawn_burst("star", 1)

        min_x = bounds.left() - self.margin * 0.5
        max_x = bounds.right() - self.width() + self.margin * 0.5
        min_y = bounds.top()
        max_y = floor_y
        if self.pos_x < min_x:
            self.pos_x = min_x
            self.facing_right = True
            self.vx = abs(self.vx)
        elif self.pos_x > max_x:
            self.pos_x = max_x
            self.facing_right = False
            self.vx = -abs(self.vx)
        self.pos_y = max(min_y, min(max_y, self.pos_y))

    def _step_falling(self, dt: float, bounds: QRectF, floor_y: float):
        gravity = 560.0
        self.vy = min(380.0, self.vy + gravity * dt)
        self.vx *= math.pow(0.45, dt)
        self.pos_x += self.vx * dt
        self.pos_y += self.vy * dt

        if random.random() < dt * 10.0:
            self.spawn_burst("star", 1)

        min_x = bounds.left() - self.margin * 0.5
        max_x = bounds.right() - self.width() + self.margin * 0.5
        if self.pos_x < min_x:
            self.pos_x = min_x
            self.vx = -self.vx * 0.5
        elif self.pos_x > max_x:
            self.pos_x = max_x
            self.vx = -self.vx * 0.5

        if self.pos_y >= floor_y:
            self.pos_y = floor_y
            self.vy = 0.0
            self.vx = 0.0
            self.rig.impulse_squash(0.24)
            self._set_state("idle")
            self.state_timer = 0.0
            self.next_decision_in = random.uniform(2.5, 4.5)
            self.spawn_burst("star", 4)
            if random.random() < 0.7:
                self.say(random.choice(self.LINES["land"]), 2400)

    def _step_grounded(self, dt: float, bounds: QRectF, floor_y: float):
        self.pos_y = floor_y
        if self.action_queue.is_active():
            pass
        elif self.laser_mode and self.state in ("idle", "walk"):
            gpos = QCursor.pos()
            cx = self.pos_x + self.width() * 0.5
            dx = gpos.x() - cx
            dist = abs(dx)
            if 55.0 <= dist <= 135.0 and self.laser_pounce_cooldown <= 0.0:
                self._trigger_laser_pounce(dx, 0.0)
            elif dist > 135.0:
                self._set_state("walk")
                self.facing_right = dx >= 0
                speed = min(230.0, max(120.0, dist * 0.7))
                self.pos_x += (speed if self.facing_right else -speed) * dt
            elif dist < 55.0 and self.state == "walk":
                self._set_state("idle")
        elif self.follow_mouse and self.state in ("idle", "walk"):
            gpos = QCursor.pos()
            cx = self.pos_x + self.width() * 0.5
            dx = gpos.x() - cx
            dist = abs(dx)
            if dist > 110.0:
                self._set_state("walk")
                self.facing_right = dx >= 0
                speed = min(180.0, max(86.0, dist * 0.55))
                self.pos_x += (speed if self.facing_right else -speed) * dt
            elif dist < 75.0 and self.state == "walk":
                self._set_state("idle")
        elif self.state == "walk":
            speed = 74.0
            self.pos_x += (speed if self.facing_right else -speed) * dt
            min_x = bounds.left() - self.margin * 0.35
            max_x = bounds.right() - self.width() + self.margin * 0.35
            if self.pos_x <= min_x:
                self.pos_x = min_x
                self.facing_right = True
            elif self.pos_x >= max_x:
                self.pos_x = max_x
                self.facing_right = False
        elif self.state == "sleep":
            if random.random() < dt * 1.4:
                self.spawn_burst("zzz", 1)
        elif self.state == "overload":
            if random.random() < dt * 5.0:
                self.spawn_burst("spark", 1)

        min_x = bounds.left() - self.margin * 0.35
        max_x = bounds.right() - self.width() + self.margin * 0.35
        self.pos_x = max(min_x, min(max_x, self.pos_x))

    def _choose_next_behavior(self):
        self.state_timer = 0.0
        if self.state in ("happy", "overload", "sleep", "sit", "eat", "shy"):
            self._set_state("idle")
            self.next_decision_in = random.uniform(2.8, 5.2)
            return

        r = random.random()
        if self.auto_walk_enabled and r < 0.48:
            self._set_state("walk")
            self.facing_right = random.choice([True, False])
            self.next_decision_in = random.uniform(3.2, 6.8)
        elif not self.antigravity_mode and r < 0.66:
            self.start_sleep_sequence(chatter=True)
        elif r < 0.78:
            self._set_state("sit")
            self.next_decision_in = random.uniform(3.0, 5.0)
        elif r < 0.88:
            self._set_state("happy")
            self.next_decision_in = random.uniform(2.0, 3.0)
            self.spawn_burst("star", 3)
        else:
            self._set_state("idle")
            self.next_decision_in = random.uniform(2.8, 5.5)

    def _update_pose_rig(self, dt: float):
        """计算当前动作的目标弹簧姿态，保证跨动作切换丝滑连贯。"""
        tx, ty, tsx, tsy, tangle = 0.0, 0.0, 1.0, 1.0, 0.0
        cur_step = self.action_queue.current()

        if self.state == "dragged":
            tangle = self.swing_angle
            ty = math.sin(self.anim_time * 6.0) * 2.5
        elif self.state == "falling":
            tangle = max(-18.0, min(18.0, self.vx * 0.04)) + self.swing_angle * 0.5
            tsx, tsy = 0.96, 1.04
        elif self.state == "flip":
            prog = self.action_queue.progress()
            jump_arc = math.sin(prog * math.pi)
            ty = -jump_arc * (self.pet_size * 0.44)
            tsx, tsy = 0.96, 1.05
        elif self.state == "walk":
            stride_phase = self._walk_stride_phase()
            step_frac = stride_phase % 1.0
            hop = math.sin(step_frac * math.pi)
            sway_sign = 1.0 if int(stride_phase) % 2 == 0 else -1.0
            ty = -hop * (13.0 if self.laser_mode else 8.5)
            tsy = 1.0 + hop * 0.032 - (1.0 - hop) * 0.022
            tsx = 1.0 - hop * 0.020 + (1.0 - hop) * 0.020
            tangle = sway_sign * hop * 3.4
        elif self.state == "happy":
            if cur_step is not None and cur_step.tag == "laser_pounce":
                prog = self.action_queue.progress()
                ty = -math.sin(prog * math.pi) * (self.pet_size * 0.22)
                tangle = 10.0 if self.facing_right else -10.0
                tsx, tsy = 1.04, 0.96
            else:
                hop = abs(math.sin(self.anim_time * 7.2))
                ty = -hop * 15.0
                tsy = 1.0 + hop * 0.055
                tsx = 1.0 - hop * 0.035
                tangle = math.sin(self.anim_time * 3.6) * 4.2
        elif self.state == "sit":
            breath = math.sin(self.anim_time * 2.5)
            tsx = 1.0 + breath * 0.015
            tsy = 1.0 - breath * 0.018
            if cur_step is not None and cur_step.duration <= 0.5:
                # 蓄力下压准备起跳！
                tsx, tsy, ty = 1.12, 0.86, 6.0
        elif self.state == "typing":
            now = time.perf_counter()
            self.recent_type_times = [t for t in self.recent_type_times if now - t < 1.5]
            fast = len(self.recent_type_times) >= 10
            if self.typing_pose == "left_down":
                tangle = -5.0
                ty = 2.0
            elif self.typing_pose == "right_down":
                tangle = 5.0
                ty = 2.0
            elif self.typing_pose == "both_down":
                tsx, tsy, ty = 1.06, 0.94, 4.0
            else:
                breath = math.sin(self.anim_time * 3.8)
                tsx = 1.0 + breath * 0.014
                tsy = 1.0 - breath * 0.016

            if fast:
                # 高速码字狂热律动：叠加前倾微振
                tx += math.sin(self.anim_time * 32.0) * 1.6
                ty += abs(math.sin(self.anim_time * 18.0)) * -3.0
                tangle += math.sin(self.anim_time * 16.0) * 2.4
        elif self.state == "eat":
            chew = math.sin(self.anim_time * 11.5)
            tsy = 1.0 + chew * 0.028
            tsx = 1.0 - chew * 0.020
            tangle = math.sin(self.anim_time * 5.2) * 2.4
        elif self.state == "shy":
            # 顺毛蹭手时朝鼠标光标方向温柔歪头贴近
            gpos = QCursor.pos()
            cx = self.pos_x + self.width() * 0.5
            dx = gpos.x() - cx
            lean = max(-6.5, min(6.5, dx * 0.05))
            tangle = lean + math.sin(self.anim_time * 4.5) * 2.2
            tsx, tsy = 1.02, 0.98
        elif self.state == "sleep":
            breath = math.sin(self.anim_time * 2.1)
            tsx = 1.0 + breath * 0.025
            tsy = 1.0 - breath * 0.028
            ty = 2.0
        elif self.state == "overload":
            tx = math.sin(self.anim_time * 46.0) * 4.5
            ty = math.cos(self.anim_time * 52.0) * 2.5
            tangle = math.sin(self.anim_time * 38.0) * 2.2
        else:  # idle
            breath = math.sin(self.anim_time * 2.8)
            tsx = 1.0 - breath * 0.014
            tsy = 1.0 + breath * 0.018
            # 近距离温柔歪头注视鼠标光标
            if not self.laser_mode and not self.action_queue.is_active():
                gpos = QCursor.pos()
                cx = self.pos_x + self.width() * 0.5
                cy = self.pos_y + self.height() * 0.5
                dx = gpos.x() - cx
                if math.hypot(dx, gpos.y() - cy) < 220.0:
                    tangle = max(-4.5, min(4.5, dx * 0.025))

        if self.antigravity_mode and not self.dragging and self.state != "flip":
            ty += math.sin(self.anim_time * 2.6) * 9.0 - 8.0
            tangle += math.sin(self.anim_time * 1.6) * 2.5

        self.rig.update(dt, tx, ty, tsx, tsy, tangle, self.facing_right)
        self.render_dy = self.rig.dy.value

    # ---------- 绘制精灵（弹簧物理 + 交叉淡入 + 3D转身）、小鱼干与粒子 ----------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        w, h = self.width(), self.height()
        cx = w * 0.5
        base_bottom = h - self.margin

        # 1. 脚底柔和投影
        if not self.dragging:
            shadow_alpha = 52
            shadow_w = self.pet_size * 0.50
            if self.antigravity_mode:
                shadow_alpha = 26
                shadow_w = self.pet_size * 0.36
            elif self.state in ("falling", "flip"):
                shadow_alpha = 18
                shadow_w = self.pet_size * 0.28
            elif self.state == "sleep":
                shadow_w = self.pet_size * 0.68

            grad = QRadialGradient(cx, base_bottom - 4, shadow_w * 0.55)
            grad.setColorAt(0.0, QColor(40, 42, 92, shadow_alpha))
            grad.setColorAt(1.0, QColor(40, 42, 92, 0))
            painter.setBrush(QBrush(grad))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(cx, base_bottom - 4), shadow_w * 0.55, 10)

        # 2. 读取弹簧物理参数与 360 后空翻旋转
        dx = self.rig.dx.value
        dy = self.rig.dy.value
        sx = max(0.2, self.rig.sx.value)
        sy = max(0.2, self.rig.sy.value)
        angle = self.rig.angle.value + self.flip_spin_angle

        raw_flip = self.rig.flip_scale.value
        if abs(raw_flip) < 0.04:
            flip_x = 0.04 if raw_flip >= 0 else -0.04
        else:
            flip_x = raw_flip

        # 3. 绘制透明精灵（支持 0.14s 交叉淡入淡出）
        if self.state == "dragged":
            pivot_ratio = 0.22
        elif self.state == "flip":
            pivot_ratio = 0.50
        else:
            pivot_ratio = 0.94

        pivot_y = self.margin + self.pet_size * pivot_ratio
        draw_x = -self.pet_size * 0.5
        draw_y = -(pivot_y - self.margin)
        target_rect = QRectF(draw_x, draw_y, self.pet_size, self.pet_size)

        pet_transform = QTransform()
        pet_transform.translate(cx + dx, pivot_y + dy)
        pet_transform.rotate(angle)
        pet_transform.scale(sx * flip_x, sy)

        painter.save()
        painter.setTransform(pet_transform, combine=True)

        if self.crossfade_progress < 1.0 and self.prev_sprite_key != self.active_sprite_key:
            prev_pm = self.sprites[self.prev_sprite_key]
            curr_base = self.sprites[self.active_sprite_key]
            curr_pm = (
                self.live2d_warper.get_warped_pixmap(self.active_sprite_key, self.live2d, curr_base)
                if self.live2d_enabled
                else curr_base
            )
            t = self.crossfade_progress
            # 底层 1.0 不透明 + 顶层渐变叠加，彻底避免 Porter-Duff 双半透明叠加发虚闪烁
            if t < 0.5:
                painter.setOpacity(1.0)
                painter.drawPixmap(target_rect, prev_pm, QRectF(prev_pm.rect()))
                painter.setOpacity(t * 2.0)
                painter.drawPixmap(target_rect, curr_pm, QRectF(curr_pm.rect()))
            else:
                painter.setOpacity(1.0)
                painter.drawPixmap(target_rect, curr_pm, QRectF(curr_pm.rect()))
                painter.setOpacity((1.0 - t) * 2.0)
                painter.drawPixmap(target_rect, prev_pm, QRectF(prev_pm.rect()))
            painter.setOpacity(1.0)
        else:
            curr_base = self.sprites[self.active_sprite_key]
            curr_pm = (
                self.live2d_warper.get_warped_pixmap(self.active_sprite_key, self.live2d, curr_base)
                if self.live2d_enabled
                else curr_base
            )
            painter.drawPixmap(target_rect, curr_pm, QRectF(curr_pm.rect()))
        painter.restore()

        # 3b. 绘制弹出式星辰迷你小键盘与原装手绘双臂（Live2D 肩关节绑定旋转 + 顶层袖口遮罩）
        if self.keyboard_pop.value > 0.03:
            self._draw_starry_keyboard_and_arms(
                painter,
                pet_transform,
                target_rect,
                cx + dx,
                self.margin + self.pet_size * 0.812 + dy + self.kb_shake.value,
            )

        # 4. 绘制飞行中的可爱小鱼干
        for fish in self.flying_fishes:
            t = min(1.0, fish.elapsed / fish.duration)
            inv = 1.0 - t
            fx = inv * inv * fish.start_x + 2 * inv * t * fish.ctrl_x + t * t * fish.target_x
            fy = inv * inv * fish.start_y + 2 * inv * t * fish.ctrl_y + t * t * fish.target_y
            self._draw_fish(painter, fx, fy, t * 420.0 * fish.rot_dir, 1.0 - 0.25 * t)

        # 5. 绘制粒子特效
        for p in self.particles:
            t = p.life / p.max_life
            alpha = int(255 * (1.0 - t) ** 1.2)
            col = QColor(p.color)
            col.setAlpha(max(0, min(255, alpha)))
            painter.save()
            painter.translate(p.x, p.y)
            painter.rotate(math.degrees(p.rot))

            if p.kind == "star":
                self._draw_star(painter, p.size * (0.6 + 0.5 * math.sin(t * math.pi)), col)
            elif p.kind == "heart":
                self._draw_heart(painter, p.size * 0.9, col)
            elif p.kind == "spark":
                painter.setPen(QPen(col, 2.2, Qt.SolidLine, Qt.RoundCap))
                r = p.size * 0.65
                painter.drawLine(QPointF(-r, 0), QPointF(r, 0))
                painter.drawLine(QPointF(0, -r), QPointF(0, r))
            elif p.kind == "zzz":
                painter.rotate(-math.degrees(p.rot))
                f = QFont("Microsoft YaHei UI", int(9 + t * 5), QFont.Bold)
                painter.setFont(f)
                painter.setPen(col)
                painter.drawText(QPointF(0, 0), "Z")
            elif p.kind == "code":
                painter.rotate(-math.degrees(p.rot))
                f = QFont("Consolas", int(max(8, p.size * (0.9 + 0.25 * math.sin(t * math.pi)))), QFont.Bold)
                painter.setFont(f)
                # 微描边增强白底或深色背景下的清晰度
                painter.setPen(QColor(42, 45, 96, int(col.alpha() * 0.65)))
                painter.drawText(QPointF(-9, 1), p.text)
                painter.setPen(col)
                painter.drawText(QPointF(-10, 0), p.text)
            painter.restore()

    def _draw_starry_keyboard_and_arms(
        self,
        painter: QPainter,
        pet_transform: QTransform,
        target_rect: QRectF,
        center_x: float,
        center_y: float,
    ):
        """绘制身前弹出的星辰迷你小键盘，并将 sit 原装手绘双臂绕真实肩关节旋转叠加拍打。"""
        pop = max(0.0, self.keyboard_pop.value)
        alpha = max(0.0, min(1.0, pop * 1.35))
        scale = 0.45 + 0.55 * pop
        y_slide = (1.0 - min(1.2, pop)) * 14.0

        kb_w = self.pet_size * 0.56
        kb_h = self.pet_size * 0.21
        outline_col = QColor(42, 45, 96)
        kb_cx = center_x
        kb_cy = center_y + y_slide

        # 1. 绘制星辰迷你小键盘（先画在原装手掌下方）
        painter.save()
        painter.setOpacity(alpha)
        painter.translate(kb_cx, kb_cy)
        painter.scale(scale, scale)

        # 键盘底影
        painter.setBrush(QColor(42, 45, 96, 38))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(-kb_w * 0.51, -kb_h * 0.42 + 3.0, kb_w * 1.02, kb_h), 9, 9)

        # 键盘机身（前透视圆角梯形，浅紫蓝渐变 + 深蓝粗描边）
        body = QPainterPath()
        top_half = kb_w * 0.46
        bot_half = kb_w * 0.52
        y_top = -kb_h * 0.50
        y_bot = kb_h * 0.50
        body.moveTo(-top_half + 6, y_top)
        body.lineTo(top_half - 6, y_top)
        body.quadTo(top_half, y_top, top_half + 2, y_top + 6)
        body.lineTo(bot_half, y_bot - 6)
        body.quadTo(bot_half, y_bot, bot_half - 7, y_bot)
        body.lineTo(-bot_half + 7, y_bot)
        body.quadTo(-bot_half, y_bot, -bot_half, y_bot - 6)
        body.lineTo(-top_half - 2, y_top + 6)
        body.quadTo(-top_half, y_top, -top_half + 6, y_top)
        body.closeSubpath()

        kb_grad = QLinearGradient(0, y_top, 0, y_bot)
        kb_grad.setColorAt(0.0, QColor(232, 226, 255))
        kb_grad.setColorAt(1.0, QColor(178, 174, 240))
        painter.setBrush(kb_grad)
        painter.setPen(QPen(outline_col, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(body)

        # 右上角迷你金色四角星指示灯
        painter.save()
        painter.translate(top_half - 8, y_top + 6)
        self._draw_star(painter, 3.6, QColor(255, 222, 105))
        painter.restore()

        # 键帽布局与实时星光高亮
        lit_active = self.key_lit_timer > 0.0
        glow_ratio = max(0.0, min(1.0, self.key_lit_timer / 0.22))

        rows = 2
        cols = 8
        grid_w = kb_w * 0.80
        grid_h = kb_h * 0.48
        gx0 = -grid_w * 0.5
        gy0 = y_top + kb_h * 0.15
        kw = (grid_w - (cols - 1) * 2.5) / cols
        kh = (grid_h - 2.5) / rows

        for r in range(rows):
            for c in range(cols):
                zone = "left" if c < 4 else "right"
                is_lit = lit_active and (self.last_lit_zone == zone)
                kx = gx0 + c * (kw + 2.5)
                ky = gy0 + r * (kh + 2.5) + (1.8 * glow_ratio if is_lit else 0.0)
                if is_lit:
                    fill = QColor(255, 205, 118) if zone == "left" else QColor(135, 225, 255)
                else:
                    fill = QColor(253, 252, 255) if (r + c) % 2 == 0 else QColor(240, 236, 255)
                painter.setBrush(fill)
                painter.setPen(QPen(outline_col, 1.15))
                painter.drawRoundedRect(QRectF(kx, ky, kw, kh), 2.2, 2.2)

        # 底部长空格键与左右功能键
        sp_lit = lit_active and (self.last_lit_zone == "space")
        sp_y = gy0 + grid_h + 2.8 + (1.8 * glow_ratio if sp_lit else 0.0)
        sp_h = max(4.2, kb_h * 0.21)
        sp_w = kb_w * 0.46
        sp_fill = QColor(255, 178, 226) if sp_lit else QColor(253, 250, 255)
        painter.setBrush(sp_fill)
        painter.setPen(QPen(outline_col, 1.2))
        painter.drawRoundedRect(QRectF(-sp_w * 0.5, sp_y, sp_w, sp_h), 2.5, 2.5)

        side_w = kb_w * 0.14
        painter.setBrush(QColor(198, 192, 248))
        painter.drawRoundedRect(QRectF(-sp_w * 0.5 - side_w - 3, sp_y, side_w, sp_h), 2.2, 2.2)
        painter.drawRoundedRect(QRectF(sp_w * 0.5 + 3, sp_y, side_w, sp_h), 2.2, 2.2)

        # 拍击瞬间的键盘星芒冲击波
        kb_scaled_w = kb_w * scale
        kb_scaled_h = kb_h * scale
        kb_top_y = y_top
        if lit_active:
            if self.last_lit_zone == "left" and self.left_paw_press.value > 0.65:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(255, 195, 115, int(215 * glow_ratio)), 2.0))
                painter.drawEllipse(QPointF(-kb_w * 0.22, kb_top_y + kb_h * 0.36), 11.0, 5.5)
            elif self.last_lit_zone == "right" and self.right_paw_press.value > 0.65:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(125, 225, 255, int(215 * glow_ratio)), 2.0))
                painter.drawEllipse(QPointF(kb_w * 0.22, kb_top_y + kb_h * 0.36), 11.0, 5.5)
            elif self.last_lit_zone == "space":
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(255, 175, 225, int(225 * glow_ratio)), 2.2))
                painter.drawEllipse(QPointF(0.0, kb_top_y + kb_h * 0.65), 16.0, 6.5)

        painter.restore()

        # 2. 直接使用与猫猫主体相同的 pet_transform 挂载原装手绘左右手臂（绕真实肩枢轴旋转）
        if self.active_sprite_key != "typing_body":
            return

        draw_x = target_rect.x()
        draw_y = target_rect.y()
        arm_blend = min(1.0, pop)
        hit_space = self.typing_pose == "both_down"

        # 若猫猫当前镜像朝左，自动互换左右臂按压通道，使屏幕左/右手臂永远对应键盘左/右亮灯区
        if self.rig.flip_scale.value < 0.0:
            raw_p_l = self.right_paw_press.value
            raw_p_r = self.left_paw_press.value
        else:
            raw_p_l = self.left_paw_press.value
            raw_p_r = self.right_paw_press.value

        # 左臂：press=0.0 高举(+44°)，press=1.0 拍键(-30° / 空格 -42°)
        p_l = max(-0.1, min(1.1, raw_p_l))
        deg_l = (44.0 * (1.0 - p_l) + (-42.0 if hit_space else -30.0) * p_l) * arm_blend
        scale_l = 1.0 + max(0.0, p_l - 0.5) * 0.12 * arm_blend
        pivot_l = QPointF(draw_x + self.pet_size * 0.344, draw_y + self.pet_size * 0.685)

        # 右臂：press=0.0 高举(-44°)，press=1.0 拍键(+30° / 空格 +42°)
        p_r = max(-0.1, min(1.1, raw_p_r))
        deg_r = (-44.0 * (1.0 - p_r) + (42.0 if hit_space else 30.0) * p_r) * arm_blend
        scale_r = 1.0 + max(0.0, p_r - 0.5) * 0.12 * arm_blend
        pivot_r = QPointF(draw_x + self.pet_size * 0.609, draw_y + self.pet_size * 0.688)

        for arm_key, pivot, deg, arm_sc in (
            ("arm_left", pivot_l, deg_l, scale_l),
            ("arm_right", pivot_r, deg_r, scale_r),
        ):
            arm_pm = self.arm_sprites.get(arm_key)
            if arm_pm is None or arm_pm.isNull():
                continue
            painter.save()
            painter.setTransform(pet_transform, combine=True)
            painter.translate(pivot)
            painter.rotate(deg)
            painter.scale(1.0, arm_sc)
            painter.translate(-pivot)
            painter.drawPixmap(target_rect, arm_pm, QRectF(arm_pm.rect()))
            painter.restore()

        # 3. 顶层袖口遮罩层（sleeves_top）：覆盖双臂球形关节头，确保手臂严丝合缝从荷叶边袖口伸出
        sleeves_pm = self.arm_sprites.get("sleeves_top")
        if sleeves_pm is not None and not sleeves_pm.isNull():
            painter.save()
            painter.setTransform(pet_transform, combine=True)
            painter.drawPixmap(target_rect, sleeves_pm, QRectF(sleeves_pm.rect()))
            painter.restore()

    @staticmethod
    def _draw_fish(painter: QPainter, x: float, y: float, angle_deg: float, scale: float):
        """手绘金黄香脆的 Q 版小鱼干。"""
        painter.save()
        painter.translate(x, y)
        painter.rotate(angle_deg)
        painter.scale(scale, scale)

        body = QPainterPath()
        body.moveTo(14, 0)
        body.quadTo(4, -10, -8, -4)
        body.lineTo(-15, -8)
        body.quadTo(-12, 0, -15, 8)
        body.lineTo(-8, 4)
        body.quadTo(4, 10, 14, 0)

        grad = QLinearGradient(-15, -8, 14, 8)
        grad.setColorAt(0.0, QColor(255, 224, 130))
        grad.setColorAt(1.0, QColor(248, 165, 72))
        painter.setBrush(grad)
        painter.setPen(QPen(QColor(92, 54, 34), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(body)

        painter.setBrush(QColor(68, 42, 32))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(7.5, -1.5), 1.7, 1.7)
        painter.setPen(QPen(QColor(196, 114, 52), 1.3, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(-2, -3.5), QPointF(1, 3.5))
        painter.drawLine(QPointF(-5.5, -2.5), QPointF(-3, 2.5))

        painter.restore()

    @staticmethod
    def _draw_star(painter: QPainter, r: float, color: QColor):
        path = QPainterPath()
        r_in = r * 0.32
        for i in range(8):
            ang = i * math.pi / 4.0
            rad = r if i % 2 == 0 else r_in
            pt = QPointF(math.cos(ang) * rad, math.sin(ang) * rad)
            if i == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        path.closeSubpath()
        painter.setBrush(color)
        outline = QColor(42, 46, 102, int(color.alpha() * 0.85))
        painter.setPen(QPen(outline, 1.3))
        painter.drawPath(path)

    @staticmethod
    def _draw_heart(painter: QPainter, size: float, color: QColor):
        s = size * 0.55
        path = QPainterPath()
        path.moveTo(0, s * 0.4)
        path.cubicTo(-s * 1.2, -s * 0.4, -s * 0.6, -s * 1.3, 0, -s * 0.45)
        path.cubicTo(s * 0.6, -s * 1.3, s * 1.2, -s * 0.4, 0, s * 0.4)
        painter.setBrush(color)
        painter.setPen(QPen(QColor(110, 40, 85, int(color.alpha() * 0.8)), 1.2))
        painter.drawPath(path)


def qAlpha(pixel: int) -> int:
    """兼容 ARGB32 整数像素的 Alpha 通道提取。"""
    return (pixel >> 24) & 0xFF


def _notify_running_instance() -> bool:
    """检查是否已有实例在运行；若有则唤醒并返回 True。"""
    sock = QLocalSocket()
    sock.connectToServer(SINGLE_INSTANCE_KEY)
    if sock.waitForConnected(220):
        sock.write(b"WAKE")
        sock.flush()
        sock.waitForBytesWritten(220)
        sock.disconnectFromServer()
        return True
    return False


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    if _notify_running_instance():
        sys.exit(0)

    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    ipc_server = QLocalServer()
    ipc_server.listen(SINGLE_INSTANCE_KEY)

    pet = StarryCatgirlPet()

    def _on_new_ipc_conn():
        conn = ipc_server.nextPendingConnection()
        if conn is not None:
            conn.readyRead.connect(
                lambda: pet.wake_from_external() if b"WAKE" in bytes(conn.readAll()) else None
            )

    ipc_server.newConnection.connect(_on_new_ipc_conn)
    app.aboutToQuit.connect(ipc_server.close)

    pet.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
