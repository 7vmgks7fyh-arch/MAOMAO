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


def extract_sit_arms(sit_rgba: Image.Image) -> tuple[Image.Image, Image.Image, Image.Image, Image.Image]:
    """
    基于 sit.png 精准拆件：
    - arm_left / arm_right：保留原画笔触与五指，并在顶部延伸圆润肤色球形关节帽；
    - sleeves_top：提取原画左右肩袖与白色荷叶边作为顶层遮罩；
    - typing_body：抹除原装双手并消除袖口白雾污渍，清理左掌外侧多余外凸轮廓。
    """
    rgba = np.array(sit_rgba, dtype=np.uint8)
    rgb = rgba[:, :, :3].copy()
    alpha = rgba[:, :, 3]
    h, w = alpha.shape

    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)
    max_c = np.maximum(np.maximum(r, g), b)
    min_c = np.minimum(np.minimum(r, g), b)
    yy, xx = np.mgrid[0:h, 0:w]

    skin = (alpha > 120) & (r > 182) & (g > 138) & (b > 125) & ((r - b) > 10)
    is_purple_hair = (alpha > 120) & (b > 145) & ((b - r) > 22) & (g < 185)
    dark_outline_cuff = (alpha > 120) & (max_c < 138)
    gold_trim = (alpha > 120) & (r > 165) & (g > 135) & ((r - b) > 20)

    # 1. 提取左右原画肩袖 + 白色荷叶边作为顶层遮罩层（sleeves_top）
    sleeve_polys = [
        np.array([[120, 236], [128, 223], [145, 226], [150, 259], [142, 268], [128, 265], [116, 258], [114, 248]], dtype=np.int32),
        np.array([[222, 224], [244, 227], [256, 246], [252, 260], [236, 267], [221, 268], [218, 256]], dtype=np.int32),
    ]
    sleeve_poly_mask = np.zeros((h, w), dtype=np.uint8)
    for poly in sleeve_polys:
        cv2.fillPoly(sleeve_poly_mask, [poly], 1)

    # 剔除位于袖子最外缘背后的纯紫背景发丝，保留袖子本体与右袖内侧前景小发丝
    bg_hair_in_sleeve = is_purple_hair & (((xx <= 122) & (yy >= 236)) | ((xx >= 250) & (yy >= 242)))
    sleeve_fg = ((sleeve_poly_mask == 1) & (~skin) & (~bg_hair_in_sleeve) & (alpha > 30)).astype(np.uint8)
    # 仅留有效主肩袖轮廓并柔化外缘 alpha，保持主体 100% 实色遮挡手臂根部
    sleeve_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    sleeve_eroded = cv2.erode(sleeve_fg, sleeve_k, iterations=1)
    sleeve_alpha_raw = np.where(sleeve_fg == 1, alpha, 0).astype(np.uint8)
    sleeve_alpha_soft = cv2.GaussianBlur(sleeve_alpha_raw, (3, 3), 0.5)
    sleeve_alpha = np.where(sleeve_eroded == 1, sleeve_alpha_raw, np.where(sleeve_fg == 0, 0, sleeve_alpha_soft))
    sleeves_top = Image.fromarray(np.dstack([rgb, sleeve_alpha.astype(np.uint8)]), mode="RGBA")

    arm_layers: list[Image.Image] = []
    combined_erase = np.zeros((h, w), dtype=np.uint8)
    left_erase_mask = np.zeros((h, w), dtype=np.uint8)

    # 左右手臂 ROI 与实测真实肩关节枢轴
    rois = [
        ("left", 92, 152, 250, 303, (132, 263), (129, 270)),
        ("right", 222, 274, 250, 303, (234, 264), (236, 271)),
    ]
    close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    dil_erase_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    dil_arm_edge_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    for side, x0, x1, y0, y1, pivot_pt, default_conn in rois:
        roi_mask = (xx >= x0) & (xx < x1) & (yy >= y0) & (yy < y1)
        # 精确切掉紧邻手臂内下侧的裙摆金边及腋下暗角区域
        if side == "left":
            roi_mask &= ~((xx >= 135) & (yy >= 270))
            roi_mask &= ~((xx >= 131) & (yy >= 278))
            roi_mask &= ~((xx >= 129) & (yy >= 285))
        else:
            roi_mask &= ~((xx <= 233) & (yy >= 282))
            roi_mask &= ~((xx <= 240) & (yy >= 292))

        skin_roi = (skin & roi_mask).astype(np.uint8)

        # 到肤色的欧氏距离：紧锁护腕本体与外描边，彻底隔离裙摆与头发外线
        dist_to_skin = cv2.distanceTransform(1 - skin_roi, cv2.DIST_L2, 5)
        # 顶部袖口接缝处（yy <= 270）不吸收白荷叶边的横向黑描边，避免在球形关节中间留下黑横线
        allow_dark_outline = dark_outline_cuff & (dist_to_skin <= 4.4) & (yy >= 271)
        arm_cand = (
            roi_mask
            & (~is_purple_hair)
            & (
                skin
                | allow_dark_outline
                | (gold_trim & (dist_to_skin <= 3.4) & (yy >= 271))
            )
        ).astype(np.uint8)
        # 上臂柔和截断在白荷叶边袖口下，不吃入上方荷叶边及紫发；且顶部只留高饱和纯肤色
        arm_cand[(yy <= 261) | ((yy <= 270) & (skin_roi == 0))] = 0
        arm_cand[(yy <= 269) & ((r < 225) | (g < 180))] = 0
        arm_cand[alpha <= 30] = 0

        # 轻微闭运算填充金边接缝，并清理孤立 1px 细毛丝
        arm_closed = cv2.morphologyEx(arm_cand, cv2.MORPH_CLOSE, close_k)
        arm_clean = cv2.morphologyEx(arm_closed, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        # 恢复核心肤色，防止开运算误削指尖
        arm_clean = np.maximum(arm_clean, skin_roi)

        # 仅保留包含最多肤色像素的最大主连通域
        num_lbl, lbls, _, _ = cv2.connectedComponentsWithStats(arm_clean, connectivity=8)
        best_lbl = 0
        best_skin_cnt = -1
        for lbl in range(1, num_lbl):
            cnt = int(np.sum((lbls == lbl) & (skin_roi == 1)))
            if cnt > best_skin_cnt:
                best_skin_cnt = cnt
                best_lbl = lbl

        arm_fg = (lbls == best_lbl).astype(np.uint8) if best_lbl > 0 else skin_roi
        # 若手指边缘需要微扩 1px 保留清晰黑描边
        arm_fg = cv2.dilate(arm_fg, np.ones((2, 2), np.uint8), iterations=1) & arm_closed
        arm_fg = np.maximum(arm_fg, (lbls == best_lbl).astype(np.uint8))

        arm_alpha = np.where(arm_fg == 1, alpha, 0).astype(np.uint8)
        eroded = cv2.erode(arm_fg, close_k, iterations=1)
        soft_a = cv2.GaussianBlur(arm_alpha, (3, 3), 0.55)
        final_a = np.where(eroded == 1, arm_alpha, np.where(arm_fg == 0, 0, soft_a))
        # 上沿 262..270 渐强融合，确保与上方球节皮肤零折痕顺滑衔接
        top_feather = np.clip((yy.astype(np.float32) - 262.0) / 7.0, 0.0, 1.0)
        final_a = np.where(yy < 270, (final_a.astype(np.float32) * top_feather).astype(np.uint8), final_a)
        raw_arm_img = Image.fromarray(np.dstack([rgb, final_a.astype(np.uint8)]), mode="RGBA")

        # 2. 顶部补全圆润肤色球形关节延伸帽（隐藏在袖口内，避免旋转露平切口）
        upper_skin = (skin_roi == 1) & (yy <= 278)
        if np.any(upper_skin):
            skin_pixels = rgb[upper_skin]
            skin_fill = np.median(skin_pixels, axis=0).astype(np.float32)
            uy, ux = np.where(upper_skin & (yy <= 273))
            if len(ux) > 0:
                conn_pt = (int(round(float(np.mean(ux)))), int(round(float(np.mean(uy)))))
            else:
                conn_pt = default_conn
        else:
            skin_fill = np.array([255, 224, 214], dtype=np.float32)
            conn_pt = default_conn
        skin_shadow = np.clip(skin_fill * np.array([0.93, 0.85, 0.87], dtype=np.float32), 0, 255)

        cap_outline = np.zeros((h, w), dtype=np.uint8)
        cap_inner = np.zeros((h, w), dtype=np.uint8)
        radius = 9
        cv2.line(cap_outline, pivot_pt, conn_pt, 255, thickness=(radius + 2) * 2, lineType=cv2.LINE_AA)
        cv2.line(cap_inner, pivot_pt, conn_pt, 255, thickness=radius * 2, lineType=cv2.LINE_AA)

        cap_rgba = np.zeros((h, w, 4), dtype=np.uint8)
        outline_col = np.array([42, 40, 86], dtype=np.float32)
        inner_t = (cap_inner.astype(np.float32) / 255.0)[:, :, None]
        grad_t = np.clip((yy - (pivot_pt[1] - radius)) / max(1.0, float(conn_pt[1] - pivot_pt[1] + radius)), 0.0, 1.0)[:, :, None]
        fill_rgb = skin_shadow[None, None, :] * (1.0 - grad_t) + skin_fill[None, None, :] * grad_t
        cap_rgb = outline_col[None, None, :] * (1.0 - inner_t) + fill_rgb * inner_t
        cap_rgba[:, :, :3] = np.clip(cap_rgb, 0, 255).astype(np.uint8)
        cap_rgba[:, :, 3] = np.maximum(cap_outline, cap_inner)

        # 将原装高保真手臂像素盖在胶囊之上；且用柔和淡入避免顶部交界露白/黑细线
        cap_img = Image.fromarray(cap_rgba, mode="RGBA")
        cap_img.alpha_composite(raw_arm_img)
        arm_layers.append(cap_img)

        # typing_body 抹手掩码：涵盖整个护腕外缘 2px 与上臂肤色（不在 sleeve_fg 内侵蚀）
        erase_roi = (xx >= x0) & (xx < x1) & (yy >= 260) & (yy < y1) & (sleeve_fg == 0)
        skin_erase = (skin & erase_roi).astype(np.uint8)
        arm_dil = cv2.dilate(arm_fg, dil_arm_edge_k, iterations=1)
        erase_side = (cv2.dilate(skin_erase, dil_erase_k, iterations=1) | arm_dil)
        erase_side[~erase_roi] = 0
        combined_erase |= erase_side
        if side == "left":
            left_erase_mask = erase_side.copy()

    erase_mask = (combined_erase * 255).astype(np.uint8)
    erase_mask[alpha <= 30] = 0
    erase_mask[sleeve_fg == 1] = 0

    # 3. 防白雾与黑影渗色修复：inpaint 前临时掩蔽上方亮白荷叶边及护腕深黑邻边
    rgb_for_inpaint = rgb.copy()
    bright_white = (yy < 274) & (min_c > 175)
    rgb_for_inpaint[alpha <= 30] = (120, 120, 214)
    rgb_for_inpaint[(sleeve_fg == 1) | bright_white] = (118, 120, 212)

    bgr = cv2.cvtColor(rgb_for_inpaint, cv2.COLOR_RGB2BGR)
    inpainted_bgr = cv2.inpaint(bgr, erase_mask, inpaintRadius=6, flags=cv2.INPAINT_TELEA)
    inpainted_rgb = cv2.cvtColor(inpainted_bgr, cv2.COLOR_BGR2RGB)
    body_rgb = np.where(erase_mask[:, :, None] > 0, inpainted_rgb, rgb)

    # 4. 清理左手掌外侧凸出左发外轮廓的残余外凸像素，保持左发轮廓顺滑自然
    body_alpha = alpha.copy()
    left_hair = ((is_purple_hair | (dark_outline_cuff & (xx >= 102) & (xx <= 122))) & (xx >= 100) & (xx <= 135) & (yy >= 255) & (yy <= 315)).astype(np.uint8)
    dist_to_left_hair = cv2.distanceTransform(1 - left_hair, cv2.DIST_L2, 5)
    protrude_left = (xx <= 114) & (yy >= 274) & (yy <= 303) & (left_erase_mask == 1) & (dist_to_left_hair > 2.4)
    body_alpha[protrude_left] = 0
    # 边界 1px 抗锯齿
    protrude_edge = (cv2.dilate(protrude_left.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0) & (~protrude_left) & (body_alpha > 0) & (xx <= 115) & (yy >= 273) & (yy <= 304)
    body_alpha[protrude_edge] = (body_alpha[protrude_edge].astype(np.float32) * 0.72).astype(np.uint8)

    typing_body = Image.fromarray(np.dstack([body_rgb, body_alpha]), mode="RGBA")

    return arm_layers[0], arm_layers[1], sleeves_top, typing_body


def save_arms_cutout_check(
    arm_left: Image.Image,
    arm_right: Image.Image,
    sleeves_top: Image.Image,
    typing_body: Image.Image,
    out_path: str,
):
    """生成左右手臂（含圆头球节）、顶层袖口遮罩及去手底图肩袖特写的高清棋盘格验收图。"""
    cell = 260
    w, h = cell * 4, cell
    bg = np.zeros((h, w, 3), dtype=np.uint8)
    tile = 14
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            c = 228 if ((x // tile + y // tile) % 2 == 0) else 190
            bg[y : y + tile, x : x + tile] = c
    canvas = Image.fromarray(bg, mode="RGB").convert("RGBA")

    l_crop = arm_left.crop((80, 235, 170, 325)).resize((cell, cell), Image.Resampling.NEAREST)
    r_crop = arm_right.crop((208, 235, 298, 325)).resize((cell, cell), Image.Resampling.NEAREST)
    s_crop = sleeves_top.crop((96, 200, 276, 310)).resize((cell, cell), Image.Resampling.NEAREST)
    b_crop = typing_body.crop((86, 210, 286, 330)).resize((cell, cell), Image.Resampling.LANCZOS)

    canvas.alpha_composite(l_crop, (0, 0))
    canvas.alpha_composite(r_crop, (cell, 0))
    canvas.alpha_composite(s_crop, (cell * 2, 0))
    canvas.alpha_composite(b_crop, (cell * 3, 0))
    canvas.convert("RGB").save(out_path)


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

    if "sit" in sprites:
        arm_left, arm_right, sleeves_top, typing_body = extract_sit_arms(sprites["sit"])
        for arm_name, arm_img in (
            ("arm_left", arm_left),
            ("arm_right", arm_right),
            ("sleeves_top", sleeves_top),
            ("typing_body", typing_body),
        ):
            out_p = os.path.join(SPRITE_DIR, f"{arm_name}.png")
            arm_img.save(out_p)
            print(f"Prepared sprite: {out_p}")
        arms_check_path = os.path.join(BRAIN_DIR, "arms_cutout_check.png")
        save_arms_cutout_check(arm_left, arm_right, sleeves_top, typing_body, arms_check_path)
        print(f"Arms cutout check saved: {arms_check_path}")

    preview_path = os.path.join(PROJ_DIR, "assets", "sprites_preview.png")
    make_checkerboard_preview(sprites, preview_path)
    brain_preview = os.path.join(BRAIN_DIR, "pet_sprites_v3_preview.png")
    shutil.copy2(preview_path, brain_preview)
    print(f"Preview saved: {preview_path}")
    print(f"Brain preview saved: {brain_preview}")


if __name__ == "__main__":
    main()
