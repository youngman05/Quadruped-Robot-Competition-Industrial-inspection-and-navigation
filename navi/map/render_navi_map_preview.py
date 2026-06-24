"""Render a detailed field preview with cabinets, observation positions, and obstacles."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from navi_map_data import (
    CORRIDORS,
    FIELD,
    INSPECTION_CABINETS,
    OBSERVATION_POSITIONS,
    OBSTACLE_CONES_EXAMPLE,
    PLACEMENT_CELLS,
    PLATFORM,
    REGIONS,
    ROBOT_START_POSE,
    START_AREA,
    TASK_BARS_EXAMPLE,
    VISUAL_LINE_GROUPS,
    WALL_REGION_IDS,
)


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "navi_map_preview.png"
SCALE = 0.14
MARGIN = 80


def mm_to_px(x: float, y: float) -> tuple[int, int]:
    return (round(MARGIN + x * SCALE), round(MARGIN + y * SCALE))


def rect_to_px(rect):
    x, y, w, h = rect
    x0, y0 = mm_to_px(x, y)
    x1, y1 = mm_to_px(x + w, y + h)
    return (x0, y0, x1, y1)


def load_font(size: int):
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def blend(color: tuple[int, int, int], alpha: float, bg: tuple[int, int, int] = (251, 250, 192)):
    return tuple(round(channel * alpha + base * (1 - alpha)) for channel, base in zip(color, bg))


def draw_centered(draw: ImageDraw.ImageDraw, rect, label: str, font, fill=(17, 17, 17)):
    if not label:
        return
    x0, y0, x1, y1 = rect
    box = draw.textbbox((0, 0), label, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    draw.text((x0 + (x1 - x0 - tw) / 2, y0 + (y1 - y0 - th) / 2), label, font=font, fill=fill)


def add_rect(draw, rect, label, face, edge=(34, 34, 34), width=2, alpha=0.75, font=None):
    px_rect = rect_to_px(rect)
    draw.rectangle(px_rect, fill=blend(face, alpha), outline=edge, width=width)
    if font:
        draw_centered(draw, px_rect, label, font)


def draw_arrow(draw, x, y, yaw_deg, length=40, color=(220, 50, 50), width=3):
    """Draw an arrow from (x,y) pointing in yaw_deg (mm coordinate system: 0=right)."""
    rad = math.radians(yaw_deg)
    end_x = x + length * math.cos(rad)
    end_y = y + length * math.sin(rad)
    draw.line((x, y, end_x, end_y), fill=color, width=width)

    # Arrowhead
    head_len = 12
    head_angle = math.radians(25)
    a1 = rad + math.pi - head_angle
    a2 = rad + math.pi + head_angle
    draw.line((end_x, end_y, end_x + head_len * math.cos(a1), end_y + head_len * math.sin(a1)),
              fill=color, width=width)
    draw.line((end_x, end_y, end_x + head_len * math.cos(a2), end_y + head_len * math.sin(a2)),
              fill=color, width=width)


def draw_fov_triangle(draw, x, y, yaw_deg, distance=300, fov_deg=45, color=(255, 100, 100, 60), outline=(220, 50, 50)):
    """Draw a translucent FOV cone from observation position."""
    rad = math.radians(yaw_deg)
    half_fov = math.radians(fov_deg / 2)
    left_rad = rad - half_fov
    right_rad = rad + half_fov

    tip = (x, y)
    left_end = (x + distance * SCALE * math.cos(left_rad), y + distance * SCALE * math.sin(left_rad))
    right_end = (x + distance * SCALE * math.cos(right_rad), y + distance * SCALE * math.sin(right_rad))

    # Draw as polygon on an overlay
    overlay = Image.new('RGBA', draw.im.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.polygon([tip, left_end, right_end], fill=color)
    draw._image.paste(overlay, (0, 0), overlay)

    # Outline the FOV
    draw.line((tip[0], tip[1], left_end[0], left_end[1]), fill=outline, width=1)
    draw.line((tip[0], tip[1], right_end[0], right_end[1]), fill=outline, width=1)


def draw_cabinet_face_label(draw, cabinet_center_px, face, label_text, font):
    """Draw a label marker on a cabinet face.
    face: 'top','bottom','left','right' in mm coords (y down).
    """
    cx, cy = cabinet_center_px
    # Cabinet is 500mm → 70px at scale 0.14
    half = 35
    offsets = {
        "top":    (0, -half - 18),
        "bottom": (0, half + 6),
        "left":   (-half - 18, 0),
        "right":  (half + 6, 0),
    }
    ox, oy = offsets.get(face, (0, 0))
    tx, ty = cx + ox, cy + oy

    # Background pill
    bbox = draw.textbbox((0, 0), label_text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 6
    draw.rounded_rectangle(
        (tx - tw // 2 - pad, ty - th // 2 - pad, tx + tw // 2 + pad, ty + th // 2 + pad),
        radius=4, fill=(255, 255, 200), outline=(180, 130, 30), width=2,
    )
    draw.text((tx - tw // 2, ty - th // 2), label_text, font=font, fill=(140, 40, 40))

    # Connector line
    edge_x = cx + (ox // 2) if abs(ox) > abs(oy) else cx
    edge_y = cy + (oy // 2) if abs(oy) > abs(ox) else cy
    draw.line((tx, ty, edge_x, edge_y), fill=(180, 130, 30), width=1)


def main() -> None:
    width = round(MARGIN * 2 + 5750 * SCALE)
    height = round(MARGIN * 2 + 6250 * SCALE)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = load_font(22)
    small = load_font(16)
    tiny = load_font(13)

    # ── 场地背景 ──────────────────────────────────
    field_rect = rect_to_px((0, 0, FIELD["width"], FIELD["height"]))
    draw.rectangle(field_rect, fill=(251, 250, 192), outline=(17, 17, 17), width=3)

    # 网格线
    for x in range(0, 5500, 500):
        x0, y0 = mm_to_px(x, 0)
        _, y1 = mm_to_px(x, FIELD["height"])
        draw.line((x0, y0, x0, y1), fill=(221, 221, 221), width=1)
        draw.text((x0 - 12, y1 + 8), str(x), font=small, fill=(80, 80, 80))
    for y in range(0, 6500, 500):
        x0, y0 = mm_to_px(0, y)
        x1, _ = mm_to_px(FIELD["width"], y)
        draw.line((x0, y0, x1, y0), fill=(221, 221, 221), width=1)
        draw.text((18, y0 - 8), str(y), font=small, fill=(80, 80, 80))

    # ── 区域绘制 ──────────────────────────────────
    region_colors = {
        "inspection": (200, 200, 200),
        "grab": (217, 217, 217),
        "obstacle": (255, 248, 168),
        "placement": (217, 217, 217),
    }
    for region in REGIONS.values():
        is_wall = region.id in WALL_REGION_IDS
        face_color = (180, 180, 180) if is_wall else region_colors.get(region.category, (221, 221, 221))
        edge_color = (120, 40, 40) if is_wall else (80, 80, 80)
        edge_w = 4 if is_wall else 2
        add_rect(draw, region.rect, region.label_zh, face_color, edge=edge_color, width=edge_w, alpha=0.85, font=font)

        # 墙体区域加斜线 hatch
        if is_wall:
            px_rect = rect_to_px(region.rect)
            x0, y0, x1, y1 = px_rect
            for i in range(x0, x1, 14):
                draw.line((i, y0, min(i + (y1 - y0), x1), y1 - max(0, i - x0)),
                          fill=(180, 160, 160), width=1)

    # ── 放置区格子 ────────────────────────────────
    for letter, cell in PLACEMENT_CELLS.items():
        add_rect(draw, cell.rect, letter, (238, 238, 238), alpha=0.35, width=2, font=font)

    # ── 通道 ──────────────────────────────────────
    for corridor in CORRIDORS.values():
        add_rect(draw, corridor.rect, corridor.label_zh, (199, 233, 255),
                 edge=(70, 151, 191), alpha=0.14, width=1, font=small)

    # ── 浅色条纹 ──────────────────────────────────
    for group in VISUAL_LINE_GROUPS.values():
        px_rect = rect_to_px(group.rect)
        draw.rectangle(px_rect, outline=(170, 170, 170), width=1)
        x0, y0, x1, y1 = px_rect
        for lx in range(x0 + 6, x1, 14):
            draw.line((lx, y0, lx, y1), fill=(235, 235, 235), width=3)

    # ── 出发区 ────────────────────────────────────
    add_rect(draw, START_AREA.rect, START_AREA.label_zh, (240, 248, 255),
             edge=(32, 70, 111), alpha=0.65, width=3, font=font)

    # ══════════════════════════════════════════════
    #  巡检柜体
    # ══════════════════════════════════════════════
    cabinet_color = (160, 160, 180)

    for _cab_id, cab in INSPECTION_CABINETS.items():
        cx_px, cy_px = mm_to_px(*cab.center_mm)
        half_px = round(250 * SCALE)  # 500mm / 2 * 0.14 = 35px

        # 柜体方块
        draw.rectangle(
            (cx_px - half_px, cy_px - half_px, cx_px + half_px, cy_px + half_px),
            fill=cabinet_color, outline=(60, 60, 80), width=3,
        )
        # 标签
        draw_centered(draw,
                      (cx_px - half_px, cy_px - half_px, cx_px + half_px, cy_px + half_px),
                      cab.label_zh, small, fill=(40, 40, 60))

        # 画每个标签面
        for face in cab.labeled_faces:
            face_type = "字母/仪表"  # 随机，简写
            draw_cabinet_face_label(draw, (cx_px, cy_px), face.face, face_type, tiny)

    # ══════════════════════════════════════════════
    #  锥桶（障碍区）
    # ══════════════════════════════════════════════
    for cone in OBSTACLE_CONES_EXAMPLE:
        cx, cy = mm_to_px(*cone["center_mm"])
        w_px = round(cone["size_mm"][0] * SCALE)
        h_px = round(cone["size_mm"][1] * SCALE)

        # 橙色三角形表示锥桶
        draw.polygon(
            [(cx, cy - h_px // 2), (cx + w_px // 2, cy + h_px // 2),
             (cx - w_px // 2, cy + h_px // 2)],
            fill=(255, 165, 0), outline=(200, 100, 0), width=2,
        )
        draw.text((cx - 18, cy + 4), cone["label_zh"], font=tiny, fill=(180, 80, 0))
        draw.text((cx - 40, cy + 18), "(随机)", font=tiny, fill=(160, 140, 140))

    # ══════════════════════════════════════════════
    #  抓取高台 + 长条
    # ══════════════════════════════════════════════
    add_rect(draw, PLATFORM.rect, "抓取高台(随机)", (204, 204, 204),
             edge=(68, 68, 68), alpha=0.55, width=2, font=small)

    bar_colors = {"red": (232, 63, 82), "green": (61, 127, 39)}
    for bar in TASK_BARS_EXAMPLE.values():
        draw.rectangle(rect_to_px(bar.rect), fill=bar_colors[bar.color])

    # ══════════════════════════════════════════════
    #  观察位
    # ══════════════════════════════════════════════
    for _obs_id, obs in OBSERVATION_POSITIONS.items():
        ox, oy = mm_to_px(*obs.center_mm)

        # 画 FOV 锥
        for look in obs.look_directions:
            draw_fov_triangle(draw, ox, oy, look["yaw_deg"],
                              distance=250, fov_deg=30,
                              color=(255, 120, 120, 40), outline=(200, 80, 80))

        # 观察位圆点
        r = 10
        draw.ellipse((ox - r, oy - r, ox + r, oy + r), fill=(220, 50, 50), outline=(160, 20, 20), width=2)

        # 方向箭头
        for look in obs.look_directions:
            draw_arrow(draw, ox, oy, look["yaw_deg"], length=45, color=(200, 40, 40), width=3)

        # 标签
        label_y = oy + 22
        for look in obs.look_directions:
            draw.text((ox - 60, label_y), look.get("label", ""), font=tiny, fill=(180, 30, 30))
            label_y += 16

        draw.text((ox - 50, oy - 28), obs.label_zh, font=small, fill=(200, 40, 40))

    # ══════════════════════════════════════════════
    #  机器人起始位姿
    # ══════════════════════════════════════════════
    sp = ROBOT_START_POSE
    sx, sy = mm_to_px(sp["x_mm"], sp["y_mm"])
    r = 12
    draw.ellipse((sx - r, sy - r, sx + r, sy + r), fill=(34, 139, 34), outline=(0, 100, 0), width=3)
    draw_arrow(draw, sx, sy, sp["yaw_deg"], length=50, color=(0, 140, 0), width=4)
    draw.text((sx - 50, sy - 30), "🐕 出发", font=small, fill=(0, 100, 0))

    # ── 标题 ──────────────────────────────────────
    draw.text((MARGIN, 22), "比赛场地预览 — 巡检柜体 + 观察位 + 障碍", font=font, fill=(17, 17, 17))
    draw.text((MARGIN, 48), "红色斜线区=墙壁不可入 | 橙色△=锥桶(随机) | 红色圆点+FOV=观察位 | 绿色圆=出发",
              font=small, fill=(100, 100, 100))

    image.save(OUT)
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
