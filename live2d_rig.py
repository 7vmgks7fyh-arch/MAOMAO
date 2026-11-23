import math
import os
import random
from dataclasses import dataclass

import numpy as np
from PIL import Image
from PySide6.QtGui import QImage, QPixmap

from motion import SpringValue

# 384x384 全图活动局部 ROI，覆盖呆毛、猫耳、面部五官及双侧垂发发尾
ROI_Y0 = 8
ROI_Y1 = 316
ROI_X0 = 52
ROI_X1 = 332
ROI_H = ROI_Y1 - ROI_Y0  # 308
ROI_W = ROI_X1 - ROI_X0  # 280

# 支持眼部视线追踪、2.5D 转头与自然眨眼的全功能立绘集合
FULL_LIVE2D_SPRITES = frozenset({"idle", "sit", "typing_body", "walk_a", "walk_b"})
# 仅开启呆毛/猫耳/发尾柔和弹性物理（保留原有特写表情）的立绘集合
SOFT_PHYSICS_SPRITES = frozenset({"happy", "eat", "shy"})
# 需配对加载闭眼贴图的立绘
BLINK_SPRITE_KEYS = ("idle", "sit", "typing_body", "walk_a", "walk_b")


@dataclass
class _BasisFields:
    """预计算的连续平滑 Live2D 位移基向量场（对应 ROI 局部区域）。"""

    eye_w: np.ndarray
    face_w: np.ndarray
    lid_wy: np.ndarray
    ahoge_wx: np.ndarray
    ahoge_wy: np.ndarray
    ear_l_wx: np.ndarray
    ear_l_wy: np.ndarray
    ear_r_wx: np.ndarray
    ear_r_wy: np.ndarray
    hair_w: np.ndarray
    blink_mask_eye: np.ndarray


class Live2DController:
    """2.5D Live2D 物理、视线追视、呆毛/猫耳抖动与自动眨眼控制器。"""

    def __init__(self):
        self.gaze_x = SpringValue(0.0, 0.0, stiffness=125.0, damping=17.0)
        self.gaze_y = SpringValue(0.0, 0.0, stiffness=125.0, damping=17.0)
        self.head_x = SpringValue(0.0, 0.0, stiffness=92.0, damping=15.0)
        self.head_y = SpringValue(0.0, 0.0, stiffness=92.0, damping=15.0)

        self.ahoge_deg = SpringValue(0.0, 0.0, stiffness=140.0, damping=7.5)
        self.ear_l_deg = SpringValue(0.0, 0.0, stiffness=180.0, damping=9.0)
        self.ear_r_deg = SpringValue(0.0, 0.0, stiffness=180.0, damping=9.0)
        self.hair_sway = SpringValue(0.0, 0.0, stiffness=95.0, damping=6.5)

        self.blink_value: float = 0.0
        self._blink_timer: float = random.uniform(2.4, 4.8)
        self._blink_progress: float = -1.0
        self._blink_duration: float = 0.14
        self._double_blink_pending: bool = False

        self._ear_twitch_timer: float = random.uniform(3.2, 6.8)
        self._prev_vx: float = 0.0
        self._prev_vy: float = 0.0
        self._prev_flipped: bool = False

    def trigger_blink(self, double: bool = False):
        """主动触发一次自然眨眼（可选连眨两次）。"""
        if self._blink_progress < 0.0:
            self._blink_progress = 0.0
            self._blink_duration = random.uniform(0.13, 0.17)
            self._double_blink_pending = double

    def impulse_ears(self, strength: float = 1.0, asymmetric: bool = False):
        """给猫耳施加俏皮抖耳冲量（用于摸头、投喂、敲键、跳跃互动）。"""
        s = float(strength)
        if asymmetric:
            if random.random() < 0.5:
                self.ear_l_deg.impulse(145.0 * s)
                self.ear_r_deg.impulse(-38.0 * s)
            else:
                self.ear_l_deg.impulse(38.0 * s)
                self.ear_r_deg.impulse(-145.0 * s)
        else:
            self.ear_l_deg.impulse(120.0 * s)
            self.ear_r_deg.impulse(-120.0 * s)

    def impulse_ahoge(self, vel_deg: float):
        """给头顶呆毛施加弹跳速度冲量。"""
        self.ahoge_deg.impulse(float(vel_deg))

    def update(
        self,
        dt: float,
        cursor_x: float,
        cursor_y: float,
        pet_cx: float,
        pet_cy: float,
        vx: float,
        vy: float,
        flipped: bool,
        state: str,
        anim_time: float,
        dragging: bool = False,
    ):
        """按帧推进视线追视、2.5D 脸部视差、自动眨眼及呆毛/猫耳/长发物理。"""
        dt = min(0.05, max(0.001, float(dt)))
        flip_sign = -1.0 if flipped else 1.0

        # 转身切换瞬间给发尾与呆毛甩动冲量
        if flipped != self._prev_flipped:
            turn_dir = 1.0 if not flipped else -1.0
            self.ahoge_deg.impulse(turn_dir * 85.0)
            self.hair_sway.impulse(turn_dir * 5.2)
            self._prev_flipped = flipped

        # 1. 计算目标视线与 2.5D 转头方向（按镜像朝向转换到贴图局部坐标系）
        dx_scr = cursor_x - pet_cx
        dy_scr = cursor_y - pet_cy
        dist = math.hypot(dx_scr, dy_scr)

        if state in ("sleep", "overload", "dragged", "flip"):
            tx, ty = 0.0, 0.0
        elif dist > 14.0:
            # 距离越近追踪越敏感，超过 260px 后平稳封顶
            norm_x = max(-1.0, min(1.0, dx_scr / 220.0))
            norm_y = max(-1.0, min(1.0, dy_scr / 220.0))
            # 当猫猫水平镜像绘制时，反转贴图局部水平方向使屏幕视线 100% 指向光标
            tx = norm_x * flip_sign
            ty = norm_y
        else:
            tx, ty = 0.0, 0.0

        self.gaze_x.target = tx
        self.gaze_y.target = ty
        self.head_x.target = tx * 0.85
        self.head_y.target = ty * 0.85

        self.gaze_x.step(dt)
        self.gaze_y.step(dt)
        self.head_x.step(dt)
        self.head_y.step(dt)

        # 2. 运动加速度与柔和微风驱动呆毛和双侧长发
        dvx = (vx - self._prev_vx) / dt if dt > 0.0 else 0.0
        dvy = (vy - self._prev_vy) / dt if dt > 0.0 else 0.0
        self._prev_vx = vx
        self._prev_vy = vy

        local_vx = vx * flip_sign
        breeze = math.sin(anim_time * 1.9) * 0.22 + math.sin(anim_time * 3.1 + 0.7) * 0.09
        self.ahoge_deg.target = max(-14.0, min(14.0, -local_vx * 0.055 + breeze * 14.0 + self.head_x.value * 3.5))
        self.ahoge_deg.impulse(max(-120.0, min(120.0, (-dvx * flip_sign * 0.015 + dvy * 0.012) * dt * 20.0)))

        hair_drag = max(-0.95, min(0.95, -local_vx * 0.0045 + breeze * 0.75 + self.head_x.value * 0.16))
        self.hair_sway.target = hair_drag

        # 摸头害羞或开心状态下双耳柔和微倾
        if state == "shy":
            self.ear_l_deg.target = -7.0
            self.ear_r_deg.target = 7.0
        elif state == "happy" or dragging:
            self.ear_l_deg.target = math.sin(anim_time * 11.0) * 5.0
            self.ear_r_deg.target = -math.sin(anim_time * 11.0) * 5.0
        else:
            self.ear_l_deg.target = math.sin(anim_time * 2.2) * 1.5
            self.ear_r_deg.target = -math.sin(anim_time * 2.2 + 0.4) * 1.5

        # 随机俏皮抖耳
        self._ear_twitch_timer -= dt
        if self._ear_twitch_timer <= 0.0:
            self._ear_twitch_timer = random.uniform(3.2, 7.0)
            if state not in ("sleep", "overload", "flip"):
                self.impulse_ears(strength=random.uniform(0.75, 1.15), asymmetric=(random.random() < 0.72))

        self.ahoge_deg.step(dt)
        self.ear_l_deg.step(dt)
        self.ear_r_deg.step(dt)
        self.hair_sway.step(dt)

        # 3. 自然眨眼状态机（每隔 2.6 ~ 5.4s 自动眨眼，18% 概率连眨两次）
        if state in ("sleep", "eat", "shy", "happy", "overload", "dragged", "flip"):
            self.blink_value = 0.0
            self._blink_progress = -1.0
        else:
            if self._blink_progress >= 0.0:
                self._blink_progress += dt / max(0.08, self._blink_duration)
                if self._blink_progress >= 1.0:
                    self._blink_progress = -1.0
                    self.blink_value = 0.0
                    if self._double_blink_pending:
                        self._double_blink_pending = False
                        self._blink_timer = 0.08
                    else:
                        self._blink_timer = random.uniform(2.6, 5.4)
                else:
                    # 0 -> 1 -> 0 的正弦平方顺滑快速眨眼曲线
                    s = math.sin(self._blink_progress * math.pi)
                    self.blink_value = min(1.0, s ** 0.85)
            else:
                self.blink_value = 0.0
                self._blink_timer -= dt
                if self._blink_timer <= 0.0:
                    self.trigger_blink(double=(random.random() < 0.18))


class Live2DMeshWarper:
    """基于 2x 超采样缓存与预计算连续平滑基向量场的高速 2.5D Live2D 渲染器。"""

    # 384 空间及 ROI 相对坐标系下的双眼微矩形切片（仅 74x128 像素，眨眼混合极低开销）
    _EYE_Y0 = 118
    _EYE_Y1 = 192
    _EYE_X0 = 112
    _EYE_X1 = 240
    _EYE_RY0 = _EYE_Y0 - ROI_Y0
    _EYE_RY1 = _EYE_Y1 - ROI_Y0
    _EYE_RX0 = _EYE_X0 - ROI_X0
    _EYE_RX1 = _EYE_X1 - ROI_X0

    def __init__(self, sprite_dir: str):
        self.sprite_dir = sprite_dir
        self._base_arr: dict[str, np.ndarray] = {}
        self._roi_2x: dict[str, np.ndarray] = {}
        self._blink_roi_2x: dict[str, np.ndarray] = {}
        self._work_rgba = np.zeros((384, 384, 4), dtype=np.uint8)
        self._fallback_pixmaps: dict[str, QPixmap] = {}

        yy, xx = np.mgrid[ROI_Y0:ROI_Y1, ROI_X0:ROI_X1].astype(np.float32)
        self._xx_roi = xx
        self._yy_roi = yy
        self._fields: dict[str, _BasisFields] = {
            "stand": self._build_basis(y_shift=0.0),
            "sit": self._build_basis(y_shift=11.5),
        }
        self._load_all_textures()

    def _build_basis(self, y_shift: float) -> _BasisFields:
        """预计算 ROI 内的 6 组连续平滑形变权重场，消除一切边界撕裂。"""
        xx = self._xx_roi
        yy = self._yy_roi

        # A. 左右星瞳视线追踪权重 + 眨眼上眼皮遮蔽权重 + 2x 纹理混合掩码
        if y_shift > 5.0:
            eye_specs = [(141.5, 157.5, 12.0, 13.0, 26.0, 22.0), (206.5, 159.5, 12.0, 13.0, 26.0, 22.0)]
        else:
            eye_specs = [(147.5, 145.5, 11.5, 12.5, 25.0, 21.0), (204.5, 147.5, 11.5, 12.5, 25.0, 21.0)]

        eye_w = np.zeros((ROI_H, ROI_W), dtype=np.float32)
        lid_wy = np.zeros((ROI_H, ROI_W), dtype=np.float32)
        for ecx, ecy, rx, ry, _, _ in eye_specs:
            rn2 = ((xx - ecx) / rx) ** 2 + ((yy - ecy) / ry) ** 2
            eye_w = np.maximum(eye_w, np.clip(1.0 - rn2, 0.0, 1.0) ** 1.55)
            # 眨眼过渡时眼眶上半部柔和下沉
            w_lid = np.exp(-(((xx - ecx) / (rx * 1.45)) ** 2 + ((yy - (ecy - 3.0)) / (ry * 0.95)) ** 2))
            lid_wy = np.maximum(lid_wy, w_lid)

        # 双眼局部切片内的平滑混合蒙版（384 空间），仅在眨眼时覆盖眼眶像素
        yye, xxe = np.mgrid[self._EYE_Y0 : self._EYE_Y1, self._EYE_X0 : self._EYE_X1].astype(np.float32)
        blink_mask_eye = np.zeros((self._EYE_Y1 - self._EYE_Y0, self._EYE_X1 - self._EYE_X0), dtype=np.float32)
        for ecx, ecy, _, _, brx, bry in eye_specs:
            rn2_e = ((xxe - ecx) / brx) ** 2 + ((yye - ecy) / bry) ** 2
            m = np.clip((1.0 - rn2_e) / 0.35, 0.0, 1.0)
            blink_mask_eye = np.maximum(blink_mask_eye, m)

        # B. 2.5D 面部五官与刘海立体转头视差权重（避开最外缘防剪裁锯齿）
        face_w = np.exp(-(((xx - 177.0) / 56.0) ** 2 + ((yy - (148.0 + y_shift * 0.85)) / 46.0) ** 2)).astype(np.float32)

        # C. 头顶呆毛弯曲旋转基（以根部为旋转中心，线性切向向量场）
        ahoge_pivot_x, ahoge_pivot_y = 177.0, 56.0 + y_shift * 0.75
        w_ahoge = (
            np.exp(-(((xx - 183.0) / 28.0) ** 2 + ((yy - (34.0 + y_shift * 0.75)) / 22.0) ** 2))
            * np.clip((ahoge_pivot_y + 2.0 - yy) / 28.0, 0.0, 1.0)
        ).astype(np.float32)
        ahoge_wx = -w_ahoge * (yy - ahoge_pivot_y) * (math.pi / 180.0)
        ahoge_wy = w_ahoge * (xx - ahoge_pivot_x) * (math.pi / 180.0)

        # D. 左右猫耳物理抖动旋转基
        el_px, el_py = 128.0, 78.0 + y_shift * 0.85
        w_el = (
            np.exp(-(((xx - 114.0) / 24.0) ** 2 + ((yy - (62.0 + y_shift * 0.85)) / 24.0) ** 2))
            * np.clip((el_py + 6.0 - yy) / 32.0, 0.0, 1.0)
            * (xx < 155.0)
        ).astype(np.float32)
        ear_l_wx = -w_el * (yy - el_py) * (math.pi / 180.0)
        ear_l_wy = w_el * (xx - el_px) * (math.pi / 180.0)

        er_px, er_py = 236.0, 80.0 + y_shift * 0.85
        w_er = (
            np.exp(-(((xx - 246.0) / 24.0) ** 2 + ((yy - (65.0 + y_shift * 0.85)) / 24.0) ** 2))
            * np.clip((er_py + 6.0 - yy) / 32.0, 0.0, 1.0)
            * (xx > 215.0)
        ).astype(np.float32)
        ear_r_wx = -w_er * (yy - er_py) * (math.pi / 180.0)
        ear_r_wy = w_er * (xx - er_px) * (math.pi / 180.0)

        # E. 双侧长发发尾飘动基（严格位于身体肩袖外缘之外，不影响打字肩袖接缝）
        hair_y_fade = np.clip((yy - 165.0) / 135.0, 0.0, 1.0) ** 1.35
        hair_sides = (np.exp(-((xx - 88.0) / 24.0) ** 2) * (xx < 116.0)) + (
            np.exp(-((xx - 282.0) / 24.0) ** 2) * (xx > 256.0)
        )
        hair_w = (hair_y_fade * hair_sides * np.clip((312.0 - yy) / 18.0, 0.0, 1.0)).astype(np.float32)

        return _BasisFields(
            eye_w=eye_w,
            face_w=face_w,
            lid_wy=lid_wy,
            ahoge_wx=ahoge_wx,
            ahoge_wy=ahoge_wy,
            ear_l_wx=ear_l_wx,
            ear_l_wy=ear_l_wy,
            ear_r_wx=ear_r_wx,
            ear_r_wy=ear_r_wy,
            hair_w=hair_w,
            blink_mask_eye=blink_mask_eye[:, :, None],
        )

    def _load_all_textures(self):
        """加载所有标准精灵图，并为支持的精灵预构建 2x 超采样 ROI 与配对闭眼贴图。"""
        all_keys = list(FULL_LIVE2D_SPRITES | SOFT_PHYSICS_SPRITES | {"sleep", "dragged", "overload"})
        for key in all_keys:
            path = os.path.join(self.sprite_dir, f"{key}.png")
            if not os.path.isfile(path):
                continue
            pil = Image.open(path).convert("RGBA")
            self._base_arr[key] = np.array(pil, dtype=np.uint8)
            self._fallback_pixmaps[key] = QPixmap(path)

            if key in FULL_LIVE2D_SPRITES or key in SOFT_PHYSICS_SPRITES:
                pil_2x = pil.resize((768, 768), Image.Resampling.LANCZOS)
                arr_2x = np.array(pil_2x, dtype=np.uint8)
                self._roi_2x[key] = arr_2x[ROI_Y0 * 2 : ROI_Y1 * 2, ROI_X0 * 2 : ROI_X1 * 2].copy()

            if key in BLINK_SPRITE_KEYS:
                bpath = os.path.join(self.sprite_dir, f"{key}_blink.png")
                if os.path.isfile(bpath):
                    bpil_2x = Image.open(bpath).convert("RGBA").resize((768, 768), Image.Resampling.LANCZOS)
                    barr_2x = np.array(bpil_2x, dtype=np.uint8)
                    self._blink_roi_2x[key] = barr_2x[ROI_Y0 * 2 : ROI_Y1 * 2, ROI_X0 * 2 : ROI_X1 * 2].copy()

    def get_warped_pixmap(self, key: str, ctrl: Live2DController, fallback: QPixmap) -> QPixmap:
        """根据当前 Live2D 物理与视线参数返回实时变形后的高清 QPixmap。"""
        if key not in self._base_arr or key not in self._roi_2x:
            return fallback

        full_mode = key in FULL_LIVE2D_SPRITES
        soft_mode = key in SOFT_PHYSICS_SPRITES
        if not full_mode and not soft_mode:
            return fallback

        basis_key = "sit" if key in ("sit", "typing_body") else "stand"
        bf = self._fields[basis_key]

        gaze_x = ctrl.gaze_x.value if full_mode else 0.0
        gaze_y = ctrl.gaze_y.value if full_mode else 0.0
        head_x = ctrl.head_x.value if full_mode else 0.0
        head_y = ctrl.head_y.value if full_mode else 0.0
        blink = ctrl.blink_value if full_mode else 0.0

        ahoge_deg = ctrl.ahoge_deg.value
        ear_l_deg = ctrl.ear_l_deg.value
        ear_r_deg = ctrl.ear_r_deg.value
        hair_sway = ctrl.hair_sway.value

        # 若所有动态通道都接近静态零位且未眨眼，直接零开销返回原图
        if (
            abs(gaze_x) < 0.01
            and abs(gaze_y) < 0.01
            and abs(head_x) < 0.01
            and abs(head_y) < 0.01
            and abs(ahoge_deg) < 0.15
            and abs(ear_l_deg) < 0.15
            and abs(ear_r_deg) < 0.15
            and abs(hair_sway) < 0.01
            and blink < 0.02
        ):
            return self._fallback_pixmaps.get(key, fallback)

        # 合成局部连续偏移场 (dx, dy)
        dx = bf.ahoge_wx * ahoge_deg + bf.ear_l_wx * ear_l_deg + bf.ear_r_wx * ear_r_deg + bf.hair_w * (-hair_sway * 5.2)
        dy = bf.ahoge_wy * ahoge_deg + bf.ear_l_wy * ear_l_deg + bf.ear_r_wy * ear_r_deg

        if full_mode:
            dx = dx - bf.eye_w * (gaze_x * 3.5) - bf.face_w * (head_x * 3.1)
            dy = dy - bf.eye_w * (gaze_y * 2.8) - bf.face_w * (head_y * 2.2)
            if 0.02 < blink < 0.98:
                # 眨眼开合瞬间的上眼睑快速压眯动态（避免半透明重影）
                lid_push = math.sin(min(1.0, blink * 1.4) * math.pi) * 3.8
                dy = dy - bf.lid_wy * lid_push

        # 将 384 空间的 (xx + dx, yy + dy) 映射回 2x 超采样源缓存索引（半像素高清重采样）
        nx = np.clip(np.rint((self._xx_roi - ROI_X0 + dx) * 2.0).astype(np.int32), 0, ROI_W * 2 - 1)
        ny = np.clip(np.rint((self._yy_roi - ROI_Y0 + dy) * 2.0).astype(np.int32), 0, ROI_H * 2 - 1)

        np.copyto(self._work_rgba, self._base_arr[key])
        self._work_rgba[ROI_Y0:ROI_Y1, ROI_X0:ROI_X1] = self._roi_2x[key][ny, nx]

        # 若正在眨眼，干脆利落地从“微眯眼睑”切换为“原画级闭眼弯月睫毛”（无半透明重瞳鬼影）
        if full_mode and blink >= 0.44 and key in self._blink_roi_2x:
            t_b = min(1.0, max(0.0, (blink - 0.44) / 0.22))
            b_alpha = t_b * t_b * (3.0 - 2.0 * t_b)
            ry0, ry1 = self._EYE_RY0, self._EYE_RY1
            rx0, rx1 = self._EYE_RX0, self._EYE_RX1
            y0, y1 = self._EYE_Y0, self._EYE_Y1
            x0, x1 = self._EYE_X0, self._EYE_X1
            b_sub = self._blink_roi_2x[key][ny[ry0:ry1, rx0:rx1], nx[ry0:ry1, rx0:rx1]].astype(np.float32)
            o_sub = self._work_rgba[y0:y1, x0:x1].astype(np.float32)
            mix_m = bf.blink_mask_eye * b_alpha
            self._work_rgba[y0:y1, x0:x1] = (b_sub * mix_m + o_sub * (1.0 - mix_m)).astype(np.uint8)

        qimg = QImage(self._work_rgba.data, 384, 384, 384 * 4, QImage.Format_RGBA8888)
        return QPixmap.fromImage(qimg)
