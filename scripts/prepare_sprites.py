import os
import shutil
import cv2
import numpy as np
from PIL import Image

BRAIN_DIR = r"C:\Users\Administrator\.gemini\antigravity\brain\07a249c7-007b-4e44-b690-268e8b765a87"
PROJ_DIR = r"C:\Users\Administrator\.gemini\antigravity\scratch\antigravity-catgirl-pet"
RAW_DIR = os.path.join(PROJ_DIR, "assets", "raw")
SPRITE_DIR = os.path.join(PROJ_DIR, "assets", "sprites")

SRC_MAP = {
    "idle": os.path.join(BRAIN_DIR, "catgirl_idle_sprite_v2_1795355566869.jpg"),
    "happy": os.path.join(BRAIN_DIR, "catgirl_joyful_jump_sprite_1795355545438.jpg"),
    "sleep": os.path.join(BRAIN_DIR, "catgirl_sleep_sprite_1795355545096.jpg"),
    "dragged": os.path.join(BRAIN_DIR, "catgirl_dangled_sprite_1795355552221.jpg"),
    "overload": os.path.join(BRAIN_DIR, "catgirl_dizzy_raw_1795355561945.jpg"),
    "walk_a": os.path.join(BRAIN_DIR, "walk_left_foot_forward_v3_1795407850016.jpg"),
    "walk_b": os.path.join(BRAIN_DIR, "walk_b_right_foot_forward_v3_1795407881679.jpg"),
    "sit": os.path.join(BRAIN_DIR, "catgirl_sitting_v2_1795407853585.jpg"),
    "eat": os.path.join(BRAIN_DIR, "eat_fish_sprite_1795407823415.jpg"),
    "shy": os.path.join(BRAIN_DIR, "chibi_catgirl_shy_nuzzle_pose2_1795407863532.jpg"),
}


def fix_sleep_extra_leg(img_rgb: np.ndarray) -> np.ndarray:
    """精确抹除 sleep 原图左侧下方多余伸出的第三条小腿，保留对称的两只俏皮翘脚。"""
    out = img_rgb.copy()
    h, w = out.shape[:2]
    poly = np.array(
        [
            [0, 645],
            [135, 645],
            [178, 720],
            [196, 755],
            [180, 845],
            [140, 885],
            [0, 885],
        ],
        dtype=np.int32,
    )
    poly[:, 0] = (poly[:, 0] * w / 1024.0).astype(np.int32)
    poly[:, 1] = (poly[:, 1] * h / 1024.0).astype(np.int32)
    cv2.fillPoly(out, [poly], (255, 255, 255))
    return out


def synthesize_alternate_walk_b(walk_a_rgb: np.ndarray, walk_b_rgb: np.ndarray) -> np.ndarray:
    """
    以 walk_a 作为唯一上半身基准，确保呆毛、头部、发饰与衣袖 100% 像素一致，
    仅将裙摆底部以下的迈步双腿水平翻转拼入，让双步态走路绝对不闪烁。
    """
    h, w = walk_a_rgb.shape[:2]
    out = walk_a_rgb.copy()
    # 定位裙摆底部白色荷叶边中下区域（约 y: 74%..98%, x: 30%..69%，避开外侧垂发）
    y0 = int(h * 0.745)
    y1 = int(h * 0.99)
    x0 = int(w * 0.31)
    x1 = int(w * 0.69)

    leg_patch = walk_a_rgb[y0:y1, x0:x1]
    flipped_legs = cv2.flip(leg_patch, 1)

    # 只替换非背景区域和原腿所在区域的白底，使用柔和过渡避免生硬接缝
    # 先把目标区域内的原腿（靠近白色以外的像素，但避开左右边缘的紫蓝长发）擦白
    # 检查边缘是否有紫发像素：通过横向掩码保护左右 6px 羽化
    mask_blend = np.ones((y1 - y0, x1 - x0, 1), dtype=np.float32)
    fade_top = max(1, int((y1 - y0) * 0.08))
    mask_blend[:fade_top, :, 0] = np.linspace(0.0, 1.0, fade_top)[:, None]
    fade_side = max(1, int((x1 - x0) * 0.05))
    mask_blend[:, :fade_side, 0] *= np.linspace(0.0, 1.0, fade_side)[None, :]
    mask_blend[:, -fade_side:, 0] *= np.linspace(1.0, 0.0, fade_side)[None, :]

    blended = (
        out[y0:y1, x0:x1].astype(np.float32) * (1.0 - mask_blend)
        + flipped_legs.astype(np.float32) * mask_blend
    )
    out[y0:y1, x0:x1] = np.clip(blended, 0, 255).astype(np.uint8)
    return out


def extract_transparent_sprite(
    img_rgb: np.ndarray,
    out_size: int = 384,
    bottom_aligned: bool = True,
    pad_ratio: float = 0.06,
) -> Image.Image:
    """
    通过四角洪水填充精准去除纯白外部背景（不误伤内部白色耳毛/衣领/白袜/小鱼干高光），
    并对深蓝描边外沿执行抗锯齿羽化与去白边（defringe）处理。
    """
    h, w = img_rgb.shape[:2]

    padded = cv2.copyMakeBorder(
        img_rgb, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=(255, 255, 255)
    )
    ph, pw = padded.shape[:2]

    r, g, b = (
        padded[:, :, 0].astype(np.int16),
        padded[:, :, 1].astype(np.int16),
        padded[:, :, 2].astype(np.int16),
    )
    min_c = np.minimum(np.minimum(r, g), b)
    max_c = np.maximum(np.maximum(r, g), b)
    is_near_white = ((min_c >= 232) & ((max_c - min_c) <= 22)).astype(np.uint8)

    flood = is_near_white.copy()
    mask = np.zeros((ph + 2, pw + 2), np.uint8)
    cv2.floodFill(flood, mask, (0, 0), 2)
    bg_mask = (flood == 2).astype(np.uint8)[2:-2, 2:-2]

    # 清理左右两侧垂发夹缝与裙腿之间封闭的纯白背景空洞
    strict_white = ((min_c >= 242) & ((max_c - min_c) <= 12)).astype(np.uint8)[2:-2, 2:-2]
    inner_white = (strict_white == 1) & (bg_mask == 0)
    n_holes, hole_labels, hole_stats, hole_centroids = cv2.connectedComponentsWithStats(
        inner_white.astype(np.uint8), connectivity=4
    )
    dil_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    for lbl in range(1, n_holes):
        area = hole_stats[lbl, cv2.CC_STAT_AREA]
        cx, cy = hole_centroids[lbl]
        in_hair_sides = (cx < w * 0.27 or cx > w * 0.73) and (h * 0.42 < cy < h * 0.82)
        in_leg_gap = (w * 0.34 < cx < w * 0.66) and (h * 0.72 < cy < h * 0.94)
        if not ((in_hair_sides or in_leg_gap) and 90 <= area <= 18000):
            continue
        comp = (hole_labels == lbl).astype(np.uint8)
        ring = (cv2.dilate(comp, dil_kernel, iterations=1) == 1) & (comp == 0)
        ring_pixels = img_rgb[ring]
        if ring_pixels.size == 0:
            continue
        # 头发夹缝或深蓝袜靴外描边周围蓝色通道较高，排除白袜内部纯白区域
        blue_purple_ratio = np.mean(
            ring_pixels[:, 2].astype(np.int16) >= ring_pixels[:, 0].astype(np.int16) - 4
        )
        dark_outline_ratio = np.mean(np.max(ring_pixels, axis=1) < 135)
        if blue_purple_ratio >= 0.78 and (in_hair_sides or dark_outline_ratio >= 0.35):
            bg_mask[comp == 1] = 1

    fg_mask = (1 - bg_mask).astype(np.uint8)

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(fg_mask, connectivity=8)
    clean_fg = np.zeros_like(fg_mask)
    for lbl in range(1, num_labels):
        if stats[lbl, cv2.CC_STAT_AREA] >= 120:
            clean_fg[labels == lbl] = 1

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    eroded = cv2.erode(clean_fg, kernel, iterations=1)
    edge_band = (clean_fg == 1) & (eroded == 0)

    alpha = (clean_fg * 255).astype(np.float32)
    lum = 0.299 * img_rgb[:, :, 0] + 0.587 * img_rgb[:, :, 1] + 0.114 * img_rgb[:, :, 2]
    rgb_clean = img_rgb.astype(np.float32)

    edge_factor = np.clip((245.0 - lum) / 90.0, 0.0, 1.0)
    alpha[edge_band] = edge_factor[edge_band] * 255.0

    semi = edge_band & (alpha > 15) & (alpha < 250)
    a_norm = (alpha[semi] / 255.0)[:, None]
    rgb_clean[semi] = np.clip(
        (rgb_clean[semi] - (1.0 - a_norm) * 255.0) / np.maximum(a_norm, 0.25), 0, 255
    )

    alpha_u8 = np.clip(alpha, 0, 255).astype(np.uint8)
    alpha_soft = cv2.GaussianBlur(alpha_u8, (3, 3), 0.55)
    alpha_final = np.where(eroded == 1, 255, np.where(clean_fg == 0, 0, alpha_soft))

    rgba = np.dstack([rgb_clean.astype(np.uint8), alpha_final])

    ys, xs = np.where(alpha_final > 12)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    cropped = Image.fromarray(rgba[y0:y1, x0:x1], mode="RGBA")

    avail = int(out_size * (1.0 - 2.0 * pad_ratio))
    cw, ch = cropped.size
    scale = min(avail / cw, avail / ch)
    nw, nh = max(1, int(round(cw * scale))), max(1, int(round(ch * scale)))
    resized = cropped.resize((nw, nh), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (out_size, out_size), (0, 0, 0, 0))
    px = (out_size - nw) // 2
    if bottom_aligned:
        py = out_size - nh - int(out_size * pad_ratio)
    else:
        py = (out_size - nh) // 2
    canvas.paste(resized, (px, py), resized)
    return canvas


def make_checkerboard_preview(sprites: dict[str, Image.Image], out_path: str):
    """生成 2 行 × 5 列棋盘格透明抠图验收预览图。"""
    cell = 240
    cols = 5
    rows = max(1, (len(sprites) + cols - 1) // cols)
    w, h = cell * cols, cell * rows
    bg = np.zeros((h, w, 3), dtype=np.uint8)
    tile = 16
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            c = 218 if ((x // tile + y // tile) % 2 == 0) else 178
            bg[y : y + tile, x : x + tile] = c
    canvas = Image.fromarray(bg, mode="RGB").convert("RGBA")
    for idx, (_, sp) in enumerate(sprites.items()):
        thumb = sp.resize((cell, cell), Image.Resampling.LANCZOS)
        r = idx // cols
        c = idx % cols
        canvas.alpha_composite(thumb, (c * cell, r * cell))
    canvas.convert("RGB").save(out_path)


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(SPRITE_DIR, exist_ok=True)

    walk_a_rgb = None
    if os.path.isfile(SRC_MAP["walk_a"]):
        walk_a_rgb = np.array(Image.open(SRC_MAP["walk_a"]).convert("RGB"))

    sprites = {}
    order = ["idle", "happy", "sleep", "dragged", "overload", "walk_a", "walk_b", "sit", "eat", "shy"]
    for name in order:
        src = SRC_MAP.get(name)
        if not src or not os.path.isfile(src):
            print(f"Skipped missing source for {name}: {src}")
            continue
        dst_raw = os.path.join(RAW_DIR, f"{name}.jpg")
        shutil.copy2(src, dst_raw)

        img_rgb = np.array(Image.open(dst_raw).convert("RGB"))
        if name == "sleep":
            img_rgb = fix_sleep_extra_leg(img_rgb)
        elif name == "walk_b" and walk_a_rgb is not None:
            img_rgb = synthesize_alternate_walk_b(walk_a_rgb, img_rgb)

        sprite = extract_transparent_sprite(
            img_rgb,
            out_size=384,
            bottom_aligned=(name != "dragged"),
            pad_ratio=0.05,
        )
        out_png = os.path.join(SPRITE_DIR, f"{name}.png")
        sprite.save(out_png)
        sprites[name] = sprite
        print(f"Prepared sprite: {out_png}")

    preview_path = os.path.join(PROJ_DIR, "assets", "sprites_preview.png")
    make_checkerboard_preview(sprites, preview_path)
    brain_preview = os.path.join(BRAIN_DIR, "pet_sprites_v3_preview.png")
    shutil.copy2(preview_path, brain_preview)
    print(f"Preview saved: {preview_path}")
    print(f"Brain preview saved: {brain_preview}")


if __name__ == "__main__":
    main()
