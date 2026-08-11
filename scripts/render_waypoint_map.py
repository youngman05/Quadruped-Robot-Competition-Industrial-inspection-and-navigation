#!/usr/bin/env python3
"""Render a numbered Nav2 waypoint route over a ROS occupancy-grid map."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROUTE_COLOR = (0, 141, 196, 220)
ANCHOR_COLOR = (20, 20, 20, 255)
MARKER_COLORS = (
    (220, 38, 38, 255),
    (234, 88, 12, 255),
    (202, 138, 4, 255),
    (22, 163, 74, 255),
    (8, 145, 178, 255),
    (37, 99, 235, 255),
    (124, 58, 237, 255),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-yaml", type=Path, required=True)
    parser.add_argument("--waypoints", type=Path, required=True)
    parser.add_argument("--route", default="full_interleaved")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scale", type=int, default=5)
    return parser.parse_args()


def load_map_metadata(path: Path) -> dict[str, object]:
    metadata: dict[str, object] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if key == "image":
            metadata[key] = value.strip("\"'")
        elif key == "resolution":
            metadata[key] = float(value)
        elif key == "origin":
            metadata[key] = json.loads(value)
    required = {"image", "resolution", "origin"}
    missing = required - metadata.keys()
    if missing:
        raise ValueError(f"Missing map metadata: {sorted(missing)}")
    return metadata


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    windows_fonts = Path("C:/Windows/Fonts")
    candidates = (
        windows_fonts / ("segoeuib.ttf" if bold else "segoeui.ttf"),
        windows_fonts / ("arialbd.ttf" if bold else "arial.ttf"),
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def arrow(draw: ImageDraw.ImageDraw, start: tuple[float, float], end: tuple[float, float]) -> None:
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    length = math.hypot(dx, dy)
    if length < 8:
        return
    draw.line((sx, sy, ex, ey), fill=ROUTE_COLOR, width=8)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    tip_x = sx + dx * 0.62
    tip_y = sy + dy * 0.62
    back_x = tip_x - ux * 22
    back_y = tip_y - uy * 22
    draw.polygon(
        (
            (tip_x, tip_y),
            (back_x + px * 11, back_y + py * 11),
            (back_x - px * 11, back_y - py * 11),
        ),
        fill=ROUTE_COLOR,
    )


def main() -> None:
    args = parse_args()
    metadata = load_map_metadata(args.map_yaml)
    route_document = json.loads(args.waypoints.read_text(encoding="utf-8-sig"))
    route_labels = route_document["routes"][args.route]
    waypoints = route_document["waypoints"]

    map_path = args.map_yaml.parent / str(metadata["image"])
    source = Image.open(map_path).convert("L")
    source = source.resize(
        (source.width * args.scale, source.height * args.scale),
        Image.Resampling.NEAREST,
    ).convert("RGBA")

    map_margin = 72
    legend_width = 820
    title_height = 135
    footer_height = 80
    canvas_width = source.width + map_margin * 2 + legend_width
    canvas_height = max(
        source.height + title_height + footer_height,
        title_height + 14 * 58 + 150,
    )
    canvas = Image.new("RGBA", (canvas_width, canvas_height), (242, 245, 248, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")
    map_left = map_margin
    map_top = title_height
    canvas.alpha_composite(source, (map_left, map_top))

    title_font = load_font(34, bold=True)
    subtitle_font = load_font(21)
    marker_font = load_font(23, bold=True)
    legend_bold = load_font(22, bold=True)
    small_font = load_font(18)

    draw.text((map_margin, 24), "Competition Field - 14-Goal Nav2 Route", font=title_font, fill=(15, 23, 42, 255))
    draw.text(
        (map_margin, 70),
        "Numbers are route order. Leader lines point to the exact map coordinate.",
        font=subtitle_font,
        fill=(71, 85, 105, 255),
    )

    resolution = float(metadata["resolution"])
    origin = metadata["origin"]
    origin_x, origin_y = float(origin[0]), float(origin[1])

    def world_to_canvas(x: float, y: float) -> tuple[float, float]:
        pixel_x = (x - origin_x) / resolution
        pixel_y = source.height / args.scale - 1 - (y - origin_y) / resolution
        return map_left + pixel_x * args.scale, map_top + pixel_y * args.scale

    max_x_m = source.width / args.scale * resolution
    max_y_m = source.height / args.scale * resolution
    for meter in range(0, math.floor(max_x_m) + 1):
        x, _ = world_to_canvas(meter, 0)
        draw.line((x, map_top, x, map_top + source.height), fill=(30, 41, 59, 65), width=2)
        draw.text((x + 5, map_top + source.height - 29), f"{meter}m", font=small_font, fill=(15, 23, 42, 210))
    for meter in range(0, math.floor(max_y_m) + 1):
        _, y = world_to_canvas(0, meter)
        draw.line((map_left, y, map_left + source.width, y), fill=(30, 41, 59, 65), width=2)
        draw.text((map_left + 5, y - 26), f"{meter}m", font=small_font, fill=(15, 23, 42, 210))

    route = []
    coordinate_groups: dict[tuple[float, float], list[int]] = defaultdict(list)
    for number, label in enumerate(route_labels, start=1):
        waypoint = waypoints[label]
        entry = {
            "number": number,
            "label": label,
            "x": float(waypoint["x"]),
            "y": float(waypoint["y"]),
            "yaw_deg": float(waypoint["yaw_deg"]),
            "action": waypoint["action"],
        }
        route.append(entry)
        coordinate_groups[(entry["x"], entry["y"])].append(number)

    anchors = [world_to_canvas(entry["x"], entry["y"]) for entry in route]
    for start, end in zip(anchors, anchors[1:]):
        arrow(draw, start, end)

    marker_radius = 22
    for entry, anchor in zip(route, anchors):
        group = coordinate_groups[(entry["x"], entry["y"])]
        marker = anchor
        if len(group) > 1:
            position = group.index(entry["number"])
            angle = -math.pi / 2 + position * (2 * math.pi / len(group))
            distance = 64 if len(group) == 2 else 72
            marker = (
                anchor[0] + math.cos(angle) * distance,
                anchor[1] + math.sin(angle) * distance,
            )
            draw.line((*anchor, *marker), fill=(15, 23, 42, 190), width=3)
            draw.ellipse(
                (anchor[0] - 7, anchor[1] - 7, anchor[0] + 7, anchor[1] + 7),
                fill=(255, 255, 255, 255),
                outline=ANCHOR_COLOR,
                width=3,
            )

        color = MARKER_COLORS[(entry["number"] - 1) % len(MARKER_COLORS)]
        draw.ellipse(
            (
                marker[0] - marker_radius,
                marker[1] - marker_radius,
                marker[0] + marker_radius,
                marker[1] + marker_radius,
            ),
            fill=color,
            outline=(255, 255, 255, 255),
            width=4,
        )
        number_text = str(entry["number"])
        bounds = draw.textbbox((0, 0), number_text, font=marker_font)
        draw.text(
            (
                marker[0] - (bounds[2] - bounds[0]) / 2,
                marker[1] - (bounds[3] - bounds[1]) / 2 - 2,
            ),
            number_text,
            font=marker_font,
            fill=(255, 255, 255, 255),
        )

        yaw = math.radians(entry["yaw_deg"])
        yaw_end = (
            anchor[0] + math.cos(yaw) * 35,
            anchor[1] - math.sin(yaw) * 35,
        )
        draw.line((*anchor, *yaw_end), fill=color, width=5)

    draw.rectangle(
        (map_left - 2, map_top - 2, map_left + source.width + 2, map_top + source.height + 2),
        outline=(15, 23, 42, 255),
        width=4,
    )

    legend_left = map_left + source.width + 70
    legend_top = title_height
    draw.text((legend_left, legend_top), "Route order and coordinates", font=title_font, fill=(15, 23, 42, 255))
    legend_y = legend_top + 60
    for entry in route:
        color = MARKER_COLORS[(entry["number"] - 1) % len(MARKER_COLORS)]
        draw.ellipse((legend_left, legend_y + 5, legend_left + 34, legend_y + 39), fill=color)
        number_text = str(entry["number"])
        bounds = draw.textbbox((0, 0), number_text, font=small_font)
        draw.text(
            (legend_left + 17 - (bounds[2] - bounds[0]) / 2, legend_y + 7),
            number_text,
            font=small_font,
            fill=(255, 255, 255, 255),
        )
        draw.text((legend_left + 50, legend_y), entry["label"], font=legend_bold, fill=(15, 23, 42, 255))
        detail = f"x={entry['x']:.2f}  y={entry['y']:.2f}  yaw={entry['yaw_deg']:.0f} deg  |  {entry['action']}"
        draw.text((legend_left + 50, legend_y + 28), detail, font=small_font, fill=(71, 85, 105, 255))
        legend_y += 58

    repeated = [numbers for numbers in coordinate_groups.values() if len(numbers) > 1]
    repeated_text = "; ".join("/".join(map(str, numbers)) for numbers in repeated)
    draw.rounded_rectangle(
        (legend_left, legend_y + 18, canvas_width - 45, legend_y + 112),
        radius=8,
        fill=(255, 255, 255, 245),
        outline=(148, 163, 184, 255),
        width=2,
    )
    draw.text((legend_left + 18, legend_y + 31), "Repeated XY coordinates", font=legend_bold, fill=(15, 23, 42, 255))
    draw.text(
        (legend_left + 18, legend_y + 65),
        f"Route steps {repeated_text} share positions; markers use leader lines.",
        font=small_font,
        fill=(71, 85, 105, 255),
    )

    footer_y = map_top + source.height + 24
    draw.text(
        (map_margin, footer_y),
        f"Source: {args.map_yaml.as_posix()} + {args.waypoints.as_posix()} [{args.route}]",
        font=small_font,
        fill=(71, 85, 105, 255),
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(args.output, quality=95)


if __name__ == "__main__":
    main()
