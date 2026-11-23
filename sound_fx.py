import math
import os
import struct
import wave

from PySide6.QtCore import QObject, QUrl

try:
    from PySide6.QtMultimedia import QSoundEffect
except Exception:
    QSoundEffect = None  # 多媒体不可用时自动降级为静音模式

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SOUND_DIR = os.path.join(BASE_DIR, "assets", "sounds")

SAMPLE_RATE = 22050

# 各音效的音频配方：(文件名, [(起始秒, 时长秒, 起始Hz, 结束Hz, 波形, 音量比例), ...])
SOUND_RECIPES = {
    # 摸头/轻抚：温暖轻快的两音上扬叮咚
    "pet": [
        (0.00, 0.12, 659.25, 783.99, "sine", 0.55),
        (0.09, 0.18, 880.00, 987.77, "sine", 0.45),
    ],
    # 投喂小鱼干：清脆的三连音和弦（C5 - E5 - G5）
    "feed": [
        (0.00, 0.12, 523.25, 523.25, "tri", 0.50),
        (0.08, 0.13, 659.25, 659.25, "tri", 0.50),
        (0.16, 0.22, 783.99, 1046.50, "sine", 0.55),
    ],
    # 反重力小跳：轻盈的滑音嗖响
    "jump": [
        (0.00, 0.18, 420.00, 960.00, "sine", 0.52),
        (0.04, 0.16, 630.00, 1280.00, "sine", 0.22),
    ],
    # 大脑过载：俏皮的滑稽下降嘟嘟声（非刺耳）
    "overload": [
        (0.00, 0.10, 460.00, 310.00, "tri", 0.42),
        (0.11, 0.11, 390.00, 240.00, "tri", 0.40),
        (0.22, 0.15, 320.00, 180.00, "sine", 0.36),
    ],
    # 番茄钟/喝水提醒：柔和清亮的风铃提示音
    "remind": [
        (0.00, 0.16, 783.99, 783.99, "sine", 0.50),
        (0.12, 0.16, 987.77, 987.77, "sine", 0.48),
        (0.24, 0.26, 1174.66, 1174.66, "sine", 0.46),
    ],
    # 吃小鱼干：两下清脆俏皮的咀嚼音
    "eat": [
        (0.00, 0.08, 480.00, 660.00, "tri", 0.45),
        (0.12, 0.08, 540.00, 760.00, "tri", 0.48),
        (0.22, 0.14, 784.00, 987.77, "sine", 0.42),
    ],
    # 害羞顺毛贴贴：温柔暖甜的双音轻颤
    "shy": [
        (0.00, 0.14, 587.33, 698.46, "sine", 0.44),
        (0.10, 0.20, 783.99, 880.00, "sine", 0.46),
    ],
}


def _oscillator(wave_type: str, phase: float) -> float:
    """生成单个采样点的归一化波形值 [-1.0, 1.0]。"""
    if wave_type == "tri":
        # 柔和三角波
        frac = phase - math.floor(phase)
        return 4.0 * abs(frac - 0.5) - 1.0
    return math.sin(2.0 * math.pi * phase)


def _synthesize_wav(path: str, notes: list[tuple[float, float, float, float, str, float]]):
    """根据配方合成无爆音、带淡入淡出包络的 16-bit 单声道 WAV。"""
    total_sec = max(start + dur for start, dur, *_ in notes) + 0.02
    total_samples = int(total_sec * SAMPLE_RATE)
    buf = [0.0] * total_samples

    for start, dur, f0, f1, wave_type, amp in notes:
        start_idx = int(start * SAMPLE_RATE)
        count = max(1, int(dur * SAMPLE_RATE))
        phase = 0.0
        fade_in = max(1, int(0.012 * SAMPLE_RATE))
        fade_out = max(1, int(0.035 * SAMPLE_RATE))

        for i in range(count):
            idx = start_idx + i
            if idx >= total_samples:
                break
            t = i / count
            freq = f0 + (f1 - f0) * t
            phase += freq / SAMPLE_RATE

            # 平滑淡入与指数衰减淡出包络，彻底避免爆音
            env = 1.0
            if i < fade_in:
                env *= i / fade_in
            if i > count - fade_out:
                env *= max(0.0, (count - i) / fade_out)
            env *= math.exp(-2.2 * t)

            buf[idx] += _oscillator(wave_type, phase) * amp * env

    # 软限幅防削波并转换为 int16
    peak = max((abs(s) for s in buf), default=1.0)
    norm = min(1.0, 0.85 / max(peak, 1e-6))
    pcm = bytearray()
    for s in buf:
        val = max(-32767, min(32767, int(s * norm * 32767)))
        pcm.extend(struct.pack("<h", val))

    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(bytes(pcm))


def ensure_sound_files(sound_dir: str = DEFAULT_SOUND_DIR) -> dict[str, str]:
    """确保所有内置轻柔音效 WAV 文件已存在；若缺失则程序自动合成。"""
    os.makedirs(sound_dir, exist_ok=True)
    paths: dict[str, str] = {}
    for name, recipe in SOUND_RECIPES.items():
        wav_path = os.path.join(sound_dir, f"{name}.wav")
        if not os.path.isfile(wav_path) or os.path.getsize(wav_path) < 64:
            _synthesize_wav(wav_path, recipe)
        paths[name] = wav_path
    return paths


class SoundManager(QObject):
    """星辰猫猫轻量音效管理器（支持异常安全降级与实时开关）。"""

    def __init__(
        self,
        parent: QObject | None = None,
        sound_dir: str = DEFAULT_SOUND_DIR,
        enabled: bool = True,
        volume: float = 0.28,
    ):
        super().__init__(parent)
        self.enabled = bool(enabled)
        self.volume = max(0.0, min(1.0, float(volume)))
        self._effects: dict[str, object] = {}
        self.sound_paths: dict[str, str] = {}

        try:
            self.sound_paths = ensure_sound_files(sound_dir)
        except Exception:
            self.sound_paths = {}
            return

        if QSoundEffect is None:
            return

        for name, wav_path in self.sound_paths.items():
            try:
                effect = QSoundEffect(self)
                effect.setSource(QUrl.fromLocalFile(wav_path))
                effect.setVolume(self.volume)
                self._effects[name] = effect
            except Exception:
                # 若音频后端初始化异常则跳过该音效，不阻塞主进程
                pass

    def play(self, name: str):
        """播放指定名称的轻柔音效；静音或异常时静默忽略。"""
        if not self.enabled:
            return
        effect = self._effects.get(name)
        if effect is None:
            return
        try:
            if hasattr(effect, "isLoaded") and effect.status() == QSoundEffect.Status.Error:
                return
            effect.setVolume(self.volume)
            effect.play()
        except Exception:
            pass
