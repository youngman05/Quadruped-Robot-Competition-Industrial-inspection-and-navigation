#!/usr/bin/env python3
"""Render a static Nav2 map direction calibration image.

This is an offline visualization helper. It does not publish ROS messages or
send robot commands. Use it to compare what Nav2 considers +X/-X/+Y/-Y and
"robot forward" against the physical field seen by the operator.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


DEFAULT_MAP_YAML = Path("navi/map/competition_field.yaml")


def parse_simple_yaml(path: Path) -> dict[str, object]:
    data: dict[str, object] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            data[key] = [float(part.strip()) for part in value[1:-1].split(",")]
        else:
            try:
                data[key] = float(value)
            except ValueError:
                data[key] = value
    return data


def read_pgm(path: Path) -> Image.Image:
    with path.open("rb") as handle:
        magic = handle.readline().strip()
        if magic != b"P5":
            raise ValueError(f"Unsupported PGM magic {magic!r}; expected P5")

        line = handle.readline()
        while line.startswith(b"#"):
            line = handle.readline()
        width, height = [int(part) for part in line.split()]
        max_value = int(handle.readline().strip())
        if max_value != 255:
            raise ValueError(f"Unsupported PGM max value {max_value}; expected 255")
        payload = handle.read(width * height)
    return Image.frombytes("L", (width, height), payload)


def load_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            pass
    return ImageFont.load_default()


class MapProjector:
    def __init__(
        self,
        width: int,
        height: int,
        resolution: float,
        origin: list[float],
        scale: float,
        offset_px: tuple[int, int] = (0, 0),
    ):
        self.width = width
        self.height = height
        self.resolution = resolution
        self.origin_x = float(origin[0])
        self.origin_y = float(origin[1])
        self.scale = scale
        self.offset_x, self.offset_y = offset_px

    @property
    def map_height_m(self) -> float:
        return self.height * self.resolution

    def world_to_px(self, x: float, y: float) -> tuple[float, float]:
        col = (x - self.origin_x) / self.resolution
        row = self.height - ((y - self.origin_y) / self.resolution)
        return self.offset_x + col * self.scale, self.offset_y + row * self.scale

    def meters_to_px(self, meters: float) -> float:
        return meters / self.resolution * self.scale


def draw_label(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font, fill=(20, 20, 20)):
    x, y = xy
    bbox = draw.textbbox((0, 0), text, font=font)
    pad = 4
    draw.rectangle(
        (x - pad, y - pad, x + bbox[2] - bbox[0] + pad, y + bbox[3] - bbox[1] + pad),
        fill=(255, 255, 240),
        outline=(120, 120, 120),
    )
    draw.text((x, y), text, font=font, fill=fill)


def draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    color: tuple[int, int, int],
    width: int = 4,
):
    draw.line((start[0], start[1], end[0], end[1]), fill=color, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    head_len = 16
    head_angle = math.radians(28)
    for sign in (-1, 1):
        a = angle + math.pi + sign * head_angle
        p = (end[0] + head_len * math.cos(a), end[1] + head_len * math.sin(a))
        draw.line((end[0], end[1], p[0], p[1]), fill=color, width=width)


def draw_pose(
    draw: ImageDraw.ImageDraw,
    projector: MapProjector,
    x: float,
    y: float,
    yaw: float,
    font,
    forward_distance: float,
):
    px = projector.world_to_px(x, y)
    radius = 8
    draw.ellipse((px[0] - radius, px[1] - radius, px[0] + radius, px[1] + radius), fill=(30, 90, 220))
    draw_label(draw, (px[0] + 12, px[1] - 34), f"START ({x:.2f}, {y:.2f}) yaw={yaw:.2f}", font)

    forward = (x + forward_distance * math.cos(yaw), y + forward_distance * math.sin(yaw))
    forward_px = projector.world_to_px(*forward)
    draw_arrow(draw, px, forward_px, (230, 40, 40), width=5)
    draw_label(draw, (forward_px[0] + 8, forward_px[1] + 8), f"ROBOT FORWARD {forward_distance:.2f}m", font)


def draw_cardinal_targets(
    draw: ImageDraw.ImageDraw,
    projector: MapProjector,
    x: float,
    y: float,
    distance: float,
    font,
):
    start = projector.world_to_px(x, y)
    targets = [
        ("A +X", x + distance, y, (0, 130, 70)),
        ("B -X", x - distance, y, (180, 80, 0)),
        ("C +Y", x, y + distance, (130, 40, 180)),
        ("D -Y", x, y - distance, (0, 120, 180)),
    ]
    for label, tx, ty, color in targets:
        end = projector.world_to_px(tx, ty)
        draw_arrow(draw, start, end, color, width=3)
        draw_label(draw, (end[0] + 8, end[1] + 8), f"{label} ({tx:.2f}, {ty:.2f})", font)


def draw_requested_targets(
    draw: ImageDraw.ImageDraw,
    projector: MapProjector,
    start_x: float,
    start_y: float,
    targets: list[list[float]],
    font,
):
    if not targets:
        return
    previous = projector.world_to_px(start_x, start_y)
    for index, values in enumerate(targets, start=1):
        tx, ty = values[0], values[1]
        end = projector.world_to_px(tx, ty)
        draw_arrow(draw, previous, end, (20, 20, 20), width=4)
        draw.ellipse((end[0] - 6, end[1] - 6, end[0] + 6, end[1] + 6), fill=(20, 20, 20))
        draw_label(draw, (end[0] + 8, end[1] - 28), f"T{index} ({tx:.2f}, {ty:.2f})", font)
        previous = end


def draw_legend(draw: ImageDraw.ImageDraw, font):
    lines = [
        "Map direction calibration",
        "Blue dot: current start pose",
        "Red arrow: robot forward from yaw",
        "A/B/C/D: +X/-X/+Y/-Y candidate targets",
        "Black arrows: user supplied target sequence",
        "Image top is ROS +Y; image right is ROS +X",
    ]
    x, y = 24, 24
    line_h = 24
    max_w = max(draw.textbbox((0, 0), line, font=font)[2] for line in lines)
    draw.rectangle((x - 10, y - 10, x + max_w + 16, y + line_h * len(lines) + 8), fill=(255, 255, 255), outline=(80, 80, 80))
    for i, line in enumerate(lines):
        draw.text((x, y + i * line_h), line, font=font, fill=(20, 20, 20))


def render(args) -> Path:
    map_yaml = Path(args.map_yaml)
    yaml_data = parse_simple_yaml(map_yaml)
    pgm_path = map_yaml.parent / str(yaml_data["image"])
    resolution = float(yaml_data["resolution"])
    origin = yaml_data.get("origin", [0.0, 0.0, 0.0])

    pgm = read_pgm(pgm_path).convert("RGB")
    width, height = pgm.size
    scale = args.pixel_scale
    map_canvas = pgm.resize((round(width * scale), round(height * scale)), Image.Resampling.NEAREST)
    pad_right = round(180 * scale)
    pad_bottom = round(40 * scale)
    canvas = Image.new("RGB", (map_canvas.width + pad_right, map_canvas.height + pad_bottom), (255, 255, 255))
    canvas.paste(map_canvas, (0, 0))
    draw = ImageDraw.Draw(canvas)
    projector = MapProjector(width, height, resolution, origin, scale)

    font = load_font(args.font_size)
    draw_cardinal_targets(draw, projector, args.x, args.y, args.cardinal_distance, font)
    draw_pose(draw, projector, args.x, args.y, args.yaw, font, args.forward_distance)
    draw_requested_targets(draw, projector, args.x, args.y, args.target, font)
    draw_legend(draw, font)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)
    return output


def parse_args():
    parser = argparse.ArgumentParser(description="Render an offline Nav2 map direction calibration PNG.")
    parser.add_argument("--map-yaml", default=str(DEFAULT_MAP_YAML))
    parser.add_argument("--x", type=float, required=True, help="Current map-frame robot x in meters.")
    parser.add_argument("--y", type=float, required=True, help="Current map-frame robot y in meters.")
    parser.add_argument("--yaw", type=float, required=True, help="Current map-frame robot yaw in radians.")
    parser.add_argument("--forward-distance", type=float, default=0.5)
    parser.add_argument("--cardinal-distance", type=float, default=0.5)
    parser.add_argument("--target", nargs=2, type=float, action="append", metavar=("X", "Y"))
    parser.add_argument("--pixel-scale", type=float, default=3.0)
    parser.add_argument("--font-size", type=int, default=16)
    parser.add_argument("--output", default="navi/map/map_direction_calibration.png")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = render(args)
    print(output)


if __name__ == "__main__":
    main()
