from dataclasses import dataclass, field


@dataclass
class SpringValue:
    """二阶弹簧阻尼插值器（半隐式欧拉积分），让姿态切换平滑自然且带回弹。"""

    value: float = 0.0
    target: float = 0.0
    vel: float = 0.0
    stiffness: float = 160.0
    damping: float = 18.0

    def step(self, dt: float) -> float:
        """按时间步长 dt 推进弹簧状态（分步子迭代以保持大帧间隔稳定）。"""
        rem = min(0.05, max(0.0, float(dt)))
        while rem > 0.0:
            h = min(0.016, rem)
            acc = -self.stiffness * (self.value - self.target) - self.damping * self.vel
            self.vel += acc * h
            self.value += self.vel * h
            rem -= h
        return self.value

    def snap(self, val: float):
        """瞬间对齐到指定值并清零速度。"""
        self.value = float(val)
        self.target = float(val)
        self.vel = 0.0

    def impulse(self, dv: float):
        """施加瞬时速度冲量（用于落地压缩、戳脸轻弹等瞬间效果）。"""
        self.vel += float(dv)


class PoseRig:
    """统一管理桌宠 6 通道物理弹簧，消除状态切换硬切并实现丝滑 3D 卡片转身。"""

    def __init__(self):
        self.dx = SpringValue(0.0, 0.0, stiffness=180.0, damping=19.0)
        self.dy = SpringValue(0.0, 0.0, stiffness=190.0, damping=19.0)
        self.sx = SpringValue(1.0, 1.0, stiffness=210.0, damping=18.0)
        self.sy = SpringValue(1.0, 1.0, stiffness=210.0, damping=18.0)
        self.angle = SpringValue(0.0, 0.0, stiffness=150.0, damping=16.0)
        # +1.0 朝右，-1.0 朝左；经过 0 时形成丝滑 3D 卡片式转身
        self.flip_scale = SpringValue(1.0, 1.0, stiffness=220.0, damping=20.0)

    def update(
        self,
        dt: float,
        target_dx: float,
        target_dy: float,
        target_sx: float,
        target_sy: float,
        target_angle: float,
        facing_right: bool,
    ):
        self.dx.target = target_dx
        self.dy.target = target_dy
        self.sx.target = target_sx
        self.sy.target = target_sy
        self.angle.target = target_angle
        self.flip_scale.target = 1.0 if facing_right else -1.0

        self.dx.step(dt)
        self.dy.step(dt)
        self.sx.step(dt)
        self.sy.step(dt)
        self.angle.step(dt)
        self.flip_scale.step(dt)

    def impulse_squash(self, amount: float = 0.18):
        """施加纵向压缩 + 横向膨大的 Q 弹冲量。"""
        amt = float(amount)
        self.sx.impulse(amt * 7.5)
        self.sy.impulse(-amt * 8.5)
        self.dy.impulse(amt * 42.0)

    def impulse_tilt(self, deg_vel: float):
        """施加旋转摇晃冲量。"""
        self.angle.impulse(deg_vel)


@dataclass
class ActionStep:
    """连贯动作链中的单个演出步骤。"""

    state: str
    duration: float
    message: str | None = None
    particle_kind: str | None = None
    particle_count: int = 0
    sound: str | None = None
    spin_360: bool = False
    tag: str = ""


class ActionQueue:
    """动作链编排队列，按时间自动无缝推进到下一阶段并返回触发事件。"""

    def __init__(self):
        self.steps: list[ActionStep] = []
        self.elapsed: float = 0.0

    def is_active(self) -> bool:
        return bool(self.steps)

    def current(self) -> ActionStep | None:
        return self.steps[0] if self.steps else None

    def clear(self):
        self.steps.clear()
        self.elapsed = 0.0

    def enqueue(self, steps: list[ActionStep]) -> ActionStep | None:
        was_empty = not self.steps
        self.steps.extend(steps)
        if was_empty and self.steps:
            self.elapsed = 0.0
            return self.steps[0]
        return None

    def replace(self, steps: list[ActionStep]) -> ActionStep | None:
        self.steps = list(steps)
        self.elapsed = 0.0
        return self.steps[0] if self.steps else None

    def progress(self) -> float:
        cur = self.current()
        if cur is None or cur.duration <= 0.0:
            return 1.0
        return max(0.0, min(1.0, self.elapsed / cur.duration))

    def advance(self, dt: float) -> ActionStep | None:
        """推进当前动作计时；若本帧切换到新步骤，返回刚进入的 ActionStep。"""
        if not self.steps:
            return None
        self.elapsed += max(0.0, float(dt))
        entered: ActionStep | None = None
        while self.steps and self.elapsed >= self.steps[0].duration:
            over = self.elapsed - self.steps[0].duration
            self.steps.pop(0)
            self.elapsed = over
            if self.steps:
                entered = self.steps[0]
                if self.steps[0].duration > over:
                    break
            else:
                self.elapsed = 0.0
                break
        return entered
