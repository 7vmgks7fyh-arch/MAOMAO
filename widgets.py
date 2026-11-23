import math

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config_store import PetConfig, get_affinity_level


def format_duration(seconds: int) -> str:
    """将累计陪伴秒数格式化为友好的中文时长字符串。"""
    sec = max(0, int(seconds))
    hours = sec // 3600
    minutes = (sec % 3600) // 60
    if hours > 0:
        return f"{hours}小时 {minutes}分"
    if minutes > 0:
        return f"{minutes}分钟"
    return f"{sec}秒"


class BubbleWidget(QWidget):
    """独立悬浮在桌宠上方的星辰风格圆角气泡台词框（支持柔光渐变边框与淡入上浮）。"""

    def __init__(self):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.text = ""
        self.opacity_val = 0.0
        self.target_opacity = 0.0
        self.anchor_point = QPoint()
        self.font_ui = QFont("Microsoft YaHei UI", 9)
        self.font_ui.setWeight(QFont.Medium)

        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.fade_out)

        self.fade_timer = QTimer(self)
        self.fade_timer.setInterval(20)
        self.fade_timer.timeout.connect(self._step_fade)

    def show_message(self, text: str, anchor_top_center: QPoint, duration_ms: int = 3400):
        self.text = text
        self.anchor_point = QPoint(anchor_top_center)
        fm = QFontMetrics(self.font_ui)
        max_text_w = 220
        bound = fm.boundingRect(0, 0, max_text_w, 220, Qt.TextWordWrap, text)
        pad_x, pad_y = 14, 10
        tail_h = 8
        w = max(92, min(max_text_w, bound.width()) + pad_x * 2 + 10)
        h = bound.height() + pad_y * 2 + tail_h + 8
        self.resize(w, h)

        self.target_opacity = 1.0
        if not self.isVisible():
            self.opacity_val = 0.0
            self.reposition(self.anchor_point)
            self.setWindowOpacity(0.0)
            self.show()
        else:
            self.reposition(self.anchor_point)
        if not self.fade_timer.isActive():
            self.fade_timer.start()
        self.hide_timer.start(duration_ms)
        self.update()

    def reposition(self, anchor_top_center: QPoint):
        self.anchor_point = QPoint(anchor_top_center)
        if not self.width():
            return
        screen = QApplication.screenAt(anchor_top_center) or QApplication.primaryScreen()
        geo = screen.availableGeometry()
        float_lift = int((1.0 - self.opacity_val) * 8)
        x = anchor_top_center.x() - self.width() // 2
        y = anchor_top_center.y() - self.height() - 4 + float_lift
        x = max(geo.left() + 8, min(geo.right() - self.width() - 8, x))
        y = max(geo.top() + 8, min(geo.bottom() - self.height() - 8, y))
        self.move(x, y)

    def fade_out(self):
        self.target_opacity = 0.0
        if not self.fade_timer.isActive():
            self.fade_timer.start()

    def _step_fade(self):
        step = 0.14
        if self.opacity_val < self.target_opacity:
            self.opacity_val = min(self.target_opacity, self.opacity_val + step)
        elif self.opacity_val > self.target_opacity:
            self.opacity_val = max(self.target_opacity, self.opacity_val - step)
        else:
            self.fade_timer.stop()
            if self.opacity_val <= 0.01:
                self.hide()
                return
        self.reposition(self.anchor_point)
        self.setWindowOpacity(self.opacity_val)
        self.update()

    def paintEvent(self, event):
        if not self.text:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        w, h = self.width(), self.height()
        tail_h = 8
        box = QRectF(3, 3, w - 6, h - tail_h - 6)

        path = QPainterPath()
        path.addRoundedRect(box, 14, 14)
        cx = w * 0.5
        tail = QPainterPath()
        tail.moveTo(cx - 6, box.bottom() - 1)
        tail.lineTo(cx, box.bottom() + tail_h - 1)
        tail.lineTo(cx + 6, box.bottom() - 1)
        tail.closeSubpath()
        path = path.united(tail)

        painter.save()
        painter.translate(0, 2)
        painter.fillPath(path, QColor(58, 52, 130, 44))
        painter.restore()

        bg_grad = QLinearGradient(box.topLeft(), box.bottomRight())
        bg_grad.setColorAt(0.0, QColor(255, 253, 255, 248))
        bg_grad.setColorAt(1.0, QColor(244, 241, 255, 248))
        border_grad = QLinearGradient(box.topLeft(), box.bottomRight())
        border_grad.setColorAt(0.0, QColor(115, 118, 224, 235))
        border_grad.setColorAt(1.0, QColor(178, 115, 218, 235))

        painter.setBrush(bg_grad)
        painter.setPen(QPen(border_grad, 2.0))
        painter.drawPath(path)

        painter.setFont(self.font_ui)
        painter.setPen(QColor(42, 45, 96))
        text_rect = box.adjusted(10, 6, -10, -6)
        painter.drawText(text_rect, Qt.AlignCenter | Qt.TextWordWrap, self.text)


class LaserToyWidget(QWidget):
    """全透明鼠标穿透的逗猫星光棒光点，带旋转四角星、呼吸光晕与尾迹星尘。"""

    def __init__(self):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(56, 56)
        self.phase = 0.0
        self.trail: list[QPointF] = []
        self.cur_global = QPointF(QCursor.pos())

        self.follow_timer = QTimer(self)
        self.follow_timer.setInterval(16)
        self.follow_timer.timeout.connect(self._tick_follow)

    def start(self):
        self.cur_global = QPointF(QCursor.pos())
        self.trail = [QPointF(self.cur_global) for _ in range(3)]
        self.move(int(self.cur_global.x() - 28), int(self.cur_global.y() - 28))
        self.show()
        self.raise_()
        if not self.follow_timer.isActive():
            self.follow_timer.start()

    def stop(self):
        self.follow_timer.stop()
        self.hide()

    def _tick_follow(self):
        self.phase += 0.08
        target = QPointF(QCursor.pos())
        self.cur_global = target
        if len(self.trail) < 3:
            self.trail = [QPointF(target) for _ in range(3)]
        else:
            # 3 颗尾迹星尘依次平滑追随
            self.trail[0] += (target - self.trail[0]) * 0.45
            self.trail[1] += (self.trail[0] - self.trail[1]) * 0.42
            self.trail[2] += (self.trail[1] - self.trail[2]) * 0.38
        self.move(int(target.x() - 28), int(target.y() - 28))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        cx, cy = 28.0, 28.0

        # 尾迹小星尘
        for idx, pt in enumerate(self.trail):
            lx = cx + max(-22.0, min(22.0, pt.x() - self.cur_global.x()))
            ly = cy + max(-22.0, min(22.0, pt.y() - self.cur_global.y()))
            alpha = max(35, 145 - idx * 42)
            r = max(2.0, 4.2 - idx * 0.9)
            painter.setBrush(QColor(255, 195, 228, alpha))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(lx, ly), r, r)

        # 呼吸光晕环
        pulse = 0.5 + 0.5 * math.sin(self.phase * 1.4)
        halo_r = 16.0 + 4.5 * pulse
        grad = QRadialGradient(cx, cy, halo_r)
        grad.setColorAt(0.0, QColor(255, 236, 140, 175))
        grad.setColorAt(0.55, QColor(255, 128, 200, 95))
        grad.setColorAt(1.0, QColor(145, 160, 255, 0))
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(cx, cy), halo_r, halo_r)

        # 中心旋转粉金四角星
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(math.degrees(self.phase * 0.9))
        r_out = 10.5 + 1.5 * pulse
        r_in = r_out * 0.34
        star = QPainterPath()
        for i in range(8):
            ang = i * math.pi / 4.0
            rad = r_out if i % 2 == 0 else r_in
            p = QPointF(math.cos(ang) * rad, math.sin(ang) * rad)
            if i == 0:
                star.moveTo(p)
            else:
                star.lineTo(p)
        star.closeSubpath()

        star_grad = QLinearGradient(-r_out, -r_out, r_out, r_out)
        star_grad.setColorAt(0.0, QColor(255, 244, 156))
        star_grad.setColorAt(1.0, QColor(255, 130, 206))
        painter.setBrush(star_grad)
        painter.setPen(QPen(QColor(82, 58, 138, 210), 1.4))
        painter.drawPath(star)
        painter.restore()


class StatusDialog(QWidget):
    """精致无边框星辰猫猫状态卡片，展示好感度、饱食度、互动统计与快捷演出入口。"""

    feed_requested = Signal()
    pomodoro_toggled = Signal()
    laser_toggled = Signal()
    trick_requested = Signal()

    def __init__(self, avatar_pixmap: QPixmap):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedWidth(332)
        self._build_ui(avatar_pixmap)

    def _build_ui(self, avatar_pixmap: QPixmap):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        card = QFrame(self)
        card.setObjectName("StarCard")
        card.setStyleSheet(
            """
            QFrame#StarCard {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #fdfcff, stop:1 #f4f1ff);
                border: 2px solid #9b95e6;
                border-radius: 16px;
            }
            QLabel {
                color: #2a2d60;
                font-family: "Microsoft YaHei UI";
            }
            QProgressBar {
                background-color: #e6e2fa;
                border: none;
                border-radius: 5px;
                height: 9px;
                text-align: center;
            }
            QProgressBar::chunk {
                border-radius: 5px;
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7c7ef5, stop:1 #e578be);
            }
            QProgressBar#SatietyBar::chunk {
                border-radius: 5px;
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #f6b95c, stop:1 #f47c7c);
            }
            QPushButton {
                font-family: "Microsoft YaHei UI";
                font-size: 12px;
                font-weight: 600;
                padding: 6px 9px;
                border-radius: 9px;
                border: 1px solid #c9c3ef;
                background-color: #ffffff;
                color: #363977;
            }
            QPushButton:hover {
                background-color: #efeafd;
                border-color: #8f88e3;
            }
            QPushButton#PrimaryBtn {
                background-color: #6f6be0;
                color: #ffffff;
                border: none;
            }
            QPushButton#PrimaryBtn:hover {
                background-color: #5c58d2;
            }
            """
        )
        root.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(9)

        # 头部：圆角头像 + 名称 + 亲密等级徽章
        header = QHBoxLayout()
        header.setSpacing(10)

        avatar_lbl = QLabel()
        avatar_lbl.setFixedSize(56, 56)
        avatar_lbl.setStyleSheet(
            "background-color: #f3f0ff; border: 1.5px solid #c5bff2; border-radius: 14px;"
        )
        avatar_lbl.setAlignment(Qt.AlignCenter)
        scaled = avatar_pixmap.scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        avatar_lbl.setPixmap(scaled)
        header.addWidget(avatar_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        name_lbl = QLabel("Antigravity 星辰猫猫")
        name_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #26295c;")
        self.level_badge = QLabel("Lv.1 初遇访客")
        self.level_badge.setStyleSheet(
            "font-size: 11px; font-weight: 600; color: #5b52c7; "
            "background-color: #ebe7ff; border-radius: 8px; padding: 2px 8px;"
        )
        title_col.addWidget(name_lbl)
        title_col.addWidget(self.level_badge, 0, Qt.AlignLeft)
        header.addLayout(title_col, 1)
        layout.addLayout(header)

        # 好感度进度条
        aff_row = QHBoxLayout()
        aff_title = QLabel("💖 亲密好感度")
        aff_title.setStyleSheet("font-size: 12px; font-weight: 600;")
        self.aff_val_lbl = QLabel("20 / 50")
        self.aff_val_lbl.setStyleSheet("font-size: 12px; color: #615da8; font-weight: 600;")
        aff_row.addWidget(aff_title)
        aff_row.addStretch()
        aff_row.addWidget(self.aff_val_lbl)
        layout.addLayout(aff_row)

        self.aff_bar = QProgressBar()
        self.aff_bar.setTextVisible(False)
        layout.addWidget(self.aff_bar)

        # 饱食活力条
        sat_row = QHBoxLayout()
        sat_title = QLabel("🍙 饱食活力")
        sat_title.setStyleSheet("font-size: 12px; font-weight: 600;")
        self.sat_val_lbl = QLabel("80%")
        self.sat_val_lbl.setStyleSheet("font-size: 12px; color: #c46a45; font-weight: 600;")
        sat_row.addWidget(sat_title)
        sat_row.addStretch()
        sat_row.addWidget(self.sat_val_lbl)
        layout.addLayout(sat_row)

        self.sat_bar = QProgressBar()
        self.sat_bar.setObjectName("SatietyBar")
        self.sat_bar.setTextVisible(False)
        layout.addWidget(self.sat_bar)

        # 2×2 四格统计卡片
        stats_grid = QGridLayout()
        stats_grid.setSpacing(7)
        self.feed_num_lbl = self._make_stat_box(stats_grid, 0, 0, "🐟 投喂小鱼干", "0 次")
        self.pet_num_lbl = self._make_stat_box(stats_grid, 0, 1, "🖐️ 摸头顺毛", "0 次")
        self.type_num_lbl = self._make_stat_box(stats_grid, 1, 0, "⌨️ 陪你码字", "0 键")
        self.time_num_lbl = self._make_stat_box(stats_grid, 1, 1, "⏳ 陪伴时长", "0秒")
        layout.addLayout(stats_grid)

        # 小助手状态栏
        helper_box = QFrame()
        helper_box.setStyleSheet(
            "background-color: #ffffff; border: 1px solid #e3dff8; border-radius: 10px;"
        )
        helper_lay = QVBoxLayout(helper_box)
        helper_lay.setContentsMargins(10, 8, 10, 8)
        helper_lay.setSpacing(3)
        self.pomo_lbl = QLabel("🍅 番茄专注：未开启")
        self.pomo_lbl.setStyleSheet("font-size: 12px; color: #3d4078;")
        self.drink_lbl = QLabel("💧 喝水提醒：已关闭")
        self.drink_lbl.setStyleSheet("font-size: 12px; color: #5b5e8f;")
        helper_lay.addWidget(self.pomo_lbl)
        helper_lay.addWidget(self.drink_lbl)
        layout.addWidget(helper_box)

        # 快捷操作按钮（两行紧凑排布）
        row1 = QHBoxLayout()
        row1.setSpacing(7)
        btn_feed = QPushButton("🐟 喂小鱼干")
        btn_feed.setObjectName("PrimaryBtn")
        btn_feed.setCursor(Qt.PointingHandCursor)
        btn_feed.clicked.connect(self.feed_requested.emit)

        self.btn_laser = QPushButton("🪄 逗猫棒")
        self.btn_laser.setCursor(Qt.PointingHandCursor)
        self.btn_laser.clicked.connect(self.laser_toggled.emit)

        btn_trick = QPushButton("🌀 后空翻")
        btn_trick.setCursor(Qt.PointingHandCursor)
        btn_trick.clicked.connect(self.trick_requested.emit)

        row1.addWidget(btn_feed)
        row1.addWidget(self.btn_laser)
        row1.addWidget(btn_trick)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(7)
        self.btn_pomo = QPushButton("🍅 开启番茄钟")
        self.btn_pomo.setCursor(Qt.PointingHandCursor)
        self.btn_pomo.clicked.connect(self.pomodoro_toggled.emit)

        btn_close = QPushButton("关闭")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.hide)

        row2.addWidget(self.btn_pomo, 2)
        row2.addWidget(btn_close, 1)
        layout.addLayout(row2)

    def _make_stat_box(self, grid: QGridLayout, row: int, col: int, title: str, value: str) -> QLabel:
        box = QFrame()
        box.setStyleSheet(
            "background-color: #ffffff; border: 1px solid #e3dff8; border-radius: 10px;"
        )
        v = QVBoxLayout(box)
        v.setContentsMargins(6, 7, 6, 7)
        v.setSpacing(2)
        t_lbl = QLabel(title)
        t_lbl.setAlignment(Qt.AlignCenter)
        t_lbl.setStyleSheet("font-size: 10px; color: #6b6e9e; border: none;")
        val_lbl = QLabel(value)
        val_lbl.setAlignment(Qt.AlignCenter)
        val_lbl.setStyleSheet("font-size: 12px; font-weight: 700; color: #2b2e64; border: none;")
        v.addWidget(t_lbl)
        v.addWidget(val_lbl)
        grid.addWidget(box, row, col)
        return val_lbl

    def refresh(
        self,
        cfg: PetConfig,
        pomodoro_remaining_sec: int,
        drink_elapsed_sec: int,
        laser_active: bool = False,
    ):
        level, title, low, high = get_affinity_level(cfg.affection)
        self.level_badge.setText(f"Lv.{level} {title}")
        self.aff_val_lbl.setText(f"{cfg.affection} / {high}")
        span = max(1, high - low)
        progress = max(0, min(100, int((cfg.affection - low) * 100 / span)))
        if cfg.affection >= high:
            progress = 100
        self.aff_bar.setValue(progress)

        sat = max(0, min(100, int(cfg.satiety)))
        self.sat_bar.setValue(sat)
        self.sat_val_lbl.setText(f"{sat}%（有点饿啦）" if sat < 30 else f"{sat}%")

        self.feed_num_lbl.setText(f"{cfg.feed_count} 次")
        self.pet_num_lbl.setText(f"{cfg.pet_count} 次")
        self.type_num_lbl.setText(f"{cfg.type_count} 键")
        self.time_num_lbl.setText(format_duration(cfg.companion_seconds))

        self.btn_laser.setText("🪄 收起逗猫棒" if laser_active else "🪄 逗猫棒")

        if pomodoro_remaining_sec > 0:
            mm, ss = divmod(pomodoro_remaining_sec, 60)
            self.pomo_lbl.setText(f"🍅 番茄专注中：剩余 {mm:02d}:{ss:02d}")
            self.btn_pomo.setText("⏹ 停止番茄钟")
        else:
            self.pomo_lbl.setText("🍅 番茄专注：未开启（25分钟/轮）")
            self.btn_pomo.setText("🍅 开启番茄钟")

        if cfg.drink_reminder_enabled:
            remain = max(0, cfg.drink_interval_min * 60 - drink_elapsed_sec)
            mm, ss = divmod(remain, 60)
            self.drink_lbl.setText(f"💧 喝水提醒：已开启（距下次 {mm:02d}:{ss:02d}）")
        else:
            self.drink_lbl.setText("💧 喝水提醒：已关闭")

    def show_near(self, anchor_center: QPoint):
        self.adjustSize()
        screen = QApplication.screenAt(anchor_center) or QApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = anchor_center.x() - self.width() // 2
        y = anchor_center.y() - self.height() - 18
        if y < geo.top() + 12:
            y = anchor_center.y() + 24
        x = max(geo.left() + 10, min(geo.right() - self.width() - 10, x))
        y = max(geo.top() + 10, min(geo.bottom() - self.height() - 10, y))
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    def changeEvent(self, event):
        if event.type() == event.Type.ActivationChange and not self.isActiveWindow():
            self.hide()
        super().changeEvent(event)
