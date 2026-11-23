import json
import os
import sys
from dataclasses import asdict, dataclass, fields

if sys.platform == "win32":
    import winreg
else:
    winreg = None  # 非 Windows 平台占位

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(BASE_DIR, "data", "state.json")

REG_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_APP_NAME = "AntigravityStarryCatgirlPet"

# 亲密等级梯度：(等级, 称号, 起始好感度, 下一级好感度上限)
AFFINITY_TIERS = [
    (1, "初遇访客", 0, 50),
    (2, "熟络铲屎官", 50, 150),
    (3, "星辰投喂官", 150, 320),
    (4, "首席rua猫师", 320, 600),
    (5, "银河灵魂搭档", 600, 1000),
]


@dataclass
class PetConfig:
    """星辰猫猫桌宠的本地配置与养成状态。"""

    pet_size: int = 180
    pos_x: float | None = None
    pos_y: float | None = None
    auto_walk: bool = True
    follow_mouse: bool = False
    antigravity: bool = False
    always_on_top: bool = True
    sound_enabled: bool = True
    typing_sync: bool = True
    drink_reminder_enabled: bool = False
    drink_interval_min: int = 45
    affection: int = 20
    satiety: int = 80
    feed_count: int = 0
    pet_count: int = 0
    trick_count: int = 0
    type_count: int = 0
    companion_seconds: int = 0


def get_affinity_level(affection: int) -> tuple[int, str, int, int]:
    """根据好感度计算当前亲密等级，返回 (等级, 称号, 当前级起点, 下一级终点)。"""
    val = max(0, int(affection))
    for level, title, low, high in AFFINITY_TIERS:
        if val < high or level == AFFINITY_TIERS[-1][0]:
            return level, title, low, high
    return AFFINITY_TIERS[-1]


def load_config(path: str = DEFAULT_CONFIG_PATH) -> PetConfig:
    """从 JSON 文件加载桌宠配置与养成数据；若损坏或字段缺失则自动兜底。"""
    cfg = PetConfig()
    if not os.path.isfile(path):
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return cfg

        valid_fields = {fd.name: fd for fd in fields(PetConfig)}
        for name, val in raw.items():
            if name not in valid_fields:
                continue
            default_val = getattr(cfg, name)
            if name in ("pos_x", "pos_y"):
                if val is None or isinstance(val, (int, float)):
                    setattr(cfg, name, float(val) if val is not None else None)
            elif isinstance(default_val, bool):
                if isinstance(val, bool):
                    setattr(cfg, name, val)
            elif isinstance(default_val, int):
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    setattr(cfg, name, int(val))
    except Exception:
        return PetConfig()

    # 基础边界校验（兼容滚轮 120px~260px 无级缩放）
    cfg.pet_size = max(120, min(260, int(cfg.pet_size)))
    cfg.drink_interval_min = max(1, int(cfg.drink_interval_min))
    cfg.affection = max(0, int(cfg.affection))
    cfg.satiety = max(0, min(100, int(cfg.satiety)))
    cfg.feed_count = max(0, int(cfg.feed_count))
    cfg.pet_count = max(0, int(cfg.pet_count))
    cfg.trick_count = max(0, int(cfg.trick_count))
    cfg.type_count = max(0, int(cfg.type_count))
    cfg.companion_seconds = max(0, int(cfg.companion_seconds))
    return cfg


def save_config(cfg: PetConfig, path: str = DEFAULT_CONFIG_PATH) -> bool:
    """安全持久化桌宠配置到 JSON 文件（先写临时文件再原子替换）。"""
    try:
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(asdict(cfg), f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        return True
    except Exception:
        return False


def is_autostart_enabled() -> bool:
    """查询 Windows 当前用户启动项中是否已注册本桌宠。"""
    if sys.platform != "win32" or winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, REG_APP_NAME)
            return bool(val and "antigravity-catgirl-pet" in str(val).lower())
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_autostart(enabled: bool, base_dir: str = BASE_DIR) -> bool:
    """设置或取消 Windows 开机自启（操作 HKCU\\...\\Run 注册表键）。"""
    if sys.platform != "win32" or winreg is None:
        return False
    try:
        if enabled:
            pythonw = os.path.join(base_dir, ".venv", "Scripts", "pythonw.exe")
            if not os.path.isfile(pythonw):
                pythonw = sys.executable
            main_py = os.path.join(base_dir, "main.py")
            cmd = f'"{pythonw}" "{main_py}"'
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_RUN_PATH) as key:
                winreg.SetValueEx(key, REG_APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, REG_RUN_PATH, 0, winreg.KEY_SET_VALUE
                ) as key:
                    winreg.DeleteValue(key, REG_APP_NAME)
            except FileNotFoundError:
                pass
        return True
    except OSError:
        return False
