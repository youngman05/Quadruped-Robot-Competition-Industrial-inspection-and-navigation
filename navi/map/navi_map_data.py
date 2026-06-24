"""
Map data for the 2026 quadruped robot challenge field.

Coordinate system:
- Unit: millimeter.
- Origin: top-left corner of the main 5000mm x 6000mm field.
- +x points right, +y points down.

The main area boundaries are derived from the supplied dimension/region
figures and the competition PDF. Items marked as estimated are visual
annotations from the figures where the PDF does not provide exact dimensions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Point = tuple[float, float]
Rect = tuple[float, float, float, float]  # x, y, width, height
Confidence = Literal["dimensioned", "inferred", "estimated"]


@dataclass(frozen=True)
class Region:
    id: str
    label_zh: str
    category: str
    rect: Rect
    confidence: Confidence = "dimensioned"
    note: str = ""

    @property
    def polygon(self) -> tuple[Point, Point, Point, Point]:
        x, y, w, h = self.rect
        return ((x, y), (x + w, y), (x + w, y + h), (x, y + h))

    @property
    def center(self) -> Point:
        x, y, w, h = self.rect
        return (x + w / 2.0, y + h / 2.0)


@dataclass(frozen=True)
class BarMarker:
    id: str
    color: Literal["red", "green"]
    meaning_zh: str
    rect: Rect
    confidence: Confidence = "estimated"
    note: str = ""

    @property
    def center(self) -> Point:
        x, y, w, h = self.rect
        return (x + w / 2.0, y + h / 2.0)


FIELD = {
    "id": "quadruped_large_final_field",
    "label_zh": "四足大型组国赛场地",
    "unit": "mm",
    "origin": "top_left",
    "width": 5000.0,
    "height": 6000.0,
}


# Officially dimensioned regions from Figure 6-2/6-3.
REGIONS: dict[str, Region] = {
    "inspection_upper": Region(
        id="inspection_upper",
        label_zh="上检测区域",
        category="inspection",
        rect=(1000.0, 1000.0, 1000.0, 1000.0),
        note="Upper 1000mm x 1000mm inspection block.",
    ),
    "inspection_lower": Region(
        id="inspection_lower",
        label_zh="下检测区域",
        category="inspection",
        rect=(1000.0, 3500.0, 1000.0, 1000.0),
        note="Lower 1000mm x 1000mm inspection block.",
    ),
    "grab": Region(
        id="grab",
        label_zh="抓取区域",
        category="grab",
        rect=(3500.0, 3500.0, 1500.0, 1000.0),
        note="Area containing the randomly placed 800mm x 600mm x 500mm platform.",
    ),
    "obstacle": Region(
        id="obstacle",
        label_zh="障碍区域",
        category="obstacle",
        rect=(1000.0, 4500.0, 4000.0, 1500.0),
        note="Obstacle area; PDF states two cones are randomly placed here.",
    ),
    "placement": Region(
        id="placement",
        label_zh="放置区域",
        category="placement",
        rect=(3000.0, 0.0, 2000.0, 500.0),
        note="Top-right strip split into A/B/C/D cells.",
    ),
}


# A/B/C/D placement cells. Figure 6-6 labels these from left to right.
PLACEMENT_CELLS: dict[str, Region] = {
    letter: Region(
        id=f"placement_{letter.lower()}",
        label_zh=f"{letter}放置区",
        category="placement_cell",
        rect=(3000.0 + idx * 500.0, 0.0, 500.0, 500.0),
        note="Each placement cell corresponds to a 50cm x 50cm x 50cm box mentioned in the PDF.",
    )
    for idx, letter in enumerate(("A", "B", "C", "D"))
}


# The start area appears outside the right boundary in Figure 6-3, but no
# official dimensions are given in the supplied PDF/figures.
START_AREA = Region(
    id="start",
    label_zh="出发区域",
    category="start",
    rect=(5050.0, 4500.0, 600.0, 1500.0),
    confidence="estimated",
    note=(
        "Shown attached outside the lower-right field boundary in Figure 6-3; "
        "size and offset are visual estimates, not official dimensions."
    ),
)


# Useful open corridors between dimensioned regions.
CORRIDORS: dict[str, Region] = {
    "upper_middle_corridor": Region(
        id="upper_middle_corridor",
        label_zh="上中通道",
        category="corridor",
        rect=(2000.0, 1000.0, 1500.0, 1000.0),
        confidence="inferred",
        note="Open space between upper inspection block and right-side route.",
    ),
    "middle_left_corridor": Region(
        id="middle_left_corridor",
        label_zh="左中通道",
        category="corridor",
        rect=(1000.0, 2000.0, 1000.0, 1500.0),
        confidence="inferred",
        note="Vertical gap between the two inspection blocks.",
    ),
    "middle_right_corridor": Region(
        id="middle_right_corridor",
        label_zh="右中通道",
        category="corridor",
        rect=(3500.0, 500.0, 1500.0, 3000.0),
        confidence="inferred",
        note="Right-side vertical route from placement strip to grab area.",
    ),
    "lower_middle_corridor": Region(
        id="lower_middle_corridor",
        label_zh="下中通道",
        category="corridor",
        rect=(2000.0, 3500.0, 1500.0, 1000.0),
        confidence="inferred",
        note="1500mm horizontal gap between lower inspection and grab area.",
    ),
}


# Repeated pale line groups shown in all three figures. They are visual
# markers or lane-like graphics; the PDF does not define them as solid areas.
VISUAL_LINE_GROUPS: dict[str, Region] = {
    "line_group_left_middle": Region(
        id="line_group_left_middle",
        label_zh="左中浅色条纹",
        category="visual_line_group",
        rect=(1000.0, 2400.0, 1000.0, 900.0),
        confidence="estimated",
    ),
    "line_group_center_upper": Region(
        id="line_group_center_upper",
        label_zh="中上浅色条纹",
        category="visual_line_group",
        rect=(2250.0, 1250.0, 1200.0, 650.0),
        confidence="estimated",
    ),
    "line_group_center_lower": Region(
        id="line_group_center_lower",
        label_zh="中下浅色条纹",
        category="visual_line_group",
        rect=(2200.0, 3750.0, 1100.0, 600.0),
        confidence="estimated",
    ),
    "line_group_right_upper": Region(
        id="line_group_right_upper",
        label_zh="右上浅色条纹",
        category="visual_line_group",
        rect=(3900.0, 900.0, 800.0, 1200.0),
        confidence="estimated",
    ),
    "line_group_right_middle": Region(
        id="line_group_right_middle",
        label_zh="右中浅色条纹",
        category="visual_line_group",
        rect=(3900.0, 2400.0, 800.0, 1000.0),
        confidence="estimated",
    ),
}


PLATFORM = Region(
    id="grab_platform",
    label_zh="抓取高台",
    category="platform",
    rect=(3850.0, 3700.0, 800.0, 600.0),
    confidence="estimated",
    note=(
        "PDF gives platform size as 800mm x 600mm x 500mm and says it is "
        "randomly placed in the grab area; this rect is an example placement "
        "matching Figure 6-6."
    ),
)


# Example task bars in Figure 6-6. Exact competition placement is random.
TASK_BARS_EXAMPLE: dict[str, BarMarker] = {
    "red_1": BarMarker(
        id="red_1",
        color="red",
        meaning_zh="异常",
        rect=(3900.0, 3850.0, 50.0, 100.0),
        note="Example red abnormal bar from Figure 6-6.",
    ),
    "red_2": BarMarker(
        id="red_2",
        color="red",
        meaning_zh="异常",
        rect=(4100.0, 3850.0, 50.0, 100.0),
        note="Example red abnormal bar from Figure 6-6.",
    ),
    "green_1": BarMarker(
        id="green_1",
        color="green",
        meaning_zh="正常",
        rect=(4400.0, 3850.0, 50.0, 100.0),
        note="Example green normal bar from Figure 6-6.",
    ),
    "green_2": BarMarker(
        id="green_2",
        color="green",
        meaning_zh="正常",
        rect=(4600.0, 3850.0, 50.0, 100.0),
        note="Example green normal bar from Figure 6-6.",
    ),
}


TASK_OBJECT_SPECS = {
    "cone": {
        "label_zh": "锥形桶",
        "size_mm": (670.0, 320.0, 320.0),
        "count": 2,
        "placement": "random_in_obstacle_area",
    },
    "inspection_cabinet_or_transformer": {
        "label_zh": "配电柜或变压器",
        "size_mm": (500.0, 500.0, 500.0),
        "placement": "in_inspection_areas",
    },
    "grab_platform": {
        "label_zh": "抓取高台",
        "size_mm": (800.0, 600.0, 500.0),
        "placement": "random_in_grab_area",
    },
    "task_bar": {
        "label_zh": "任务长条",
        "size_mm": (100.0, 50.0, 50.0),
        "count": 4,
        "bottom_face_mm": (50.0, 100.0),
        "colors": {"red": "异常", "green": "正常"},
        "placement": "on_grab_platform",
    },
    "placement_box": {
        "label_zh": "放置区域纸箱",
        "size_mm": (500.0, 500.0, 500.0),
        "count": 4,
        "labels": ("A", "B", "C", "D"),
        "placement": "placement_cells",
    },
}


# ═══════════════════════════════════════════════════════════════════
#  巡检柜体 — 每个 500×500×500mm 柜体，两个面贴识别纸
#  哪面贴字母哪面贴仪表由裁判随机决定
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class LabeledFace:
    """柜体上一个贴了标签的面。"""
    face: str                         # "top" | "bottom" | "left" | "right"
    label_types: tuple[str, ...]      # ("letter",) 或 ("gauge",) 或两者都有
    faces_direction: str              # 面朝向: "up" | "down" | "left" | "right"
    note: str = ""


@dataclass(frozen=True)
class InspectionCabinet:
    """巡检区域内的检测柜体。"""
    id: str
    label_zh: str
    region_id: str                    # 所属检测区域
    center_mm: Point                  # 柜体中心坐标 (mm)
    size_mm: tuple[float, float, float]  # (宽, 深, 高) mm
    labeled_faces: tuple[LabeledFace, ...]  # 贴了标签的面
    note: str = ""

    @property
    def rect(self) -> Rect:
        """柜体在俯视图上的矩形 (x, y, w, h)。"""
        w, d, _h = self.size_mm
        return (self.center_mm[0] - w / 2, self.center_mm[1] - d / 2, w, d)


# 两个巡检柜体。标签面由用户确认：
# - 上柜体: 底面 + 右侧面 贴标签
# - 下柜体: 顶面 + 右侧面 贴标签
# 裁判随机决定每个面贴的是字母还是仪表
INSPECTION_CABINETS: dict[str, InspectionCabinet] = {
    "upper": InspectionCabinet(
        id="cabinet_upper",
        label_zh="上巡检柜体",
        region_id="inspection_upper",
        center_mm=(1500.0, 1500.0),
        size_mm=(500.0, 500.0, 500.0),
        labeled_faces=(
            LabeledFace("bottom", ("letter_or_gauge",), "down",
                        note="底面朝下，狗在中间走廊昂头看"),
            LabeledFace("right", ("letter_or_gauge",), "right",
                        note="右侧面朝右，狗需移动到右侧走廊看"),
        ),
        note="放置于上检测区(1000~2000, 1000~2000)。裁判随机决定底面/右侧面哪个贴字母哪个贴仪表。",
    ),
    "lower": InspectionCabinet(
        id="cabinet_lower",
        label_zh="下巡检柜体",
        region_id="inspection_lower",
        center_mm=(1500.0, 4000.0),
        size_mm=(500.0, 500.0, 500.0),
        labeled_faces=(
            LabeledFace("top", ("letter_or_gauge",), "up",
                        note="顶面朝上，狗在中间走廊低头看"),
            LabeledFace("right", ("letter_or_gauge",), "right",
                        note="右侧面朝右，狗需移动到右侧走廊看"),
        ),
        note="放置于下检测区(1000~2000, 3500~4500)。裁判随机决定顶面/右侧面哪个贴字母哪个贴仪表。",
    ),
}


# ═══════════════════════════════════════════════════════════════════
#  观察位 — 狗需要两个位置才能看全四个标签面
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ObservationPosition:
    """狗的一个观察停留点。"""
    id: str
    label_zh: str
    center_mm: Point
    look_directions: tuple[dict, ...]   # 每个观察方向 {yaw_deg, sees, label}
    note: str = ""


OBSERVATION_POSITIONS: dict[str, ObservationPosition] = {
    "pos1_middle": ObservationPosition(
        id="pos1_middle",
        label_zh="观察位① 中间走廊",
        center_mm=(1500.0, 2750.0),
        look_directions=(
            {"yaw_deg": -90, "sees": "cabinet_upper:bottom",
             "label": "仰头看上柜底面"},
            {"yaw_deg": 90, "sees": "cabinet_lower:top",
             "label": "180°转身低头看下柜顶面"},
        ),
        note="狗站在两柜之间，先仰头看上柜底面，再180°转身低头看下柜顶面。",
    ),
    "pos2a_upper_right": ObservationPosition(
        id="pos2a_upper_right",
        label_zh="观察位②a 上中通道",
        center_mm=(2200.0, 1500.0),
        look_directions=(
            {"yaw_deg": 180, "sees": "cabinet_upper:right",
             "label": "面朝左看上柜右侧面"},
        ),
        note="狗移动到上中通道(2000~3500, 1000~2000)，面朝左看上方柜体右侧面。",
    ),
    "pos2b_lower_right": ObservationPosition(
        id="pos2b_lower_right",
        label_zh="观察位②b 下中通道",
        center_mm=(2200.0, 4000.0),
        look_directions=(
            {"yaw_deg": 180, "sees": "cabinet_lower:right",
             "label": "面朝左看下柜右侧面"},
        ),
        note="狗移动到下中通道(2000~3500, 3500~4500)，面朝左看下方柜体右侧面。",
    ),
}


# ═══════════════════════════════════════════════════════════════════
#  锥桶 — 障碍区 2 个随机放置的锥桶（示例位置）
# ═══════════════════════════════════════════════════════════════════

OBSTACLE_CONES_EXAMPLE: list[dict] = [
    {
        "id": "cone_1",
        "label_zh": "锥桶①",
        "center_mm": (2500.0, 4900.0),
        "size_mm": (670.0, 320.0),   # 底面投影约 670×320mm
        "note": "裁判随机放置，此为示例",
    },
    {
        "id": "cone_2",
        "label_zh": "锥桶②",
        "center_mm": (3800.0, 5300.0),
        "size_mm": (670.0, 320.0),
        "note": "裁判随机放置，此为示例",
    },
]


# ═══════════════════════════════════════════════════════════════════
#  机器人起始位姿 (mm 坐标系)
# ═══════════════════════════════════════════════════════════════════

ROBOT_START_POSE = {
    "label_zh": "出发位姿",
    "x_mm": 5350.0,
    "y_mm": 5250.0,
    "yaw_deg": 180,            # 在 mm 坐标系中: 0=右, 90=下, 180=左
    "note": "出发区中心，面朝左(-x)进入场地",
}


# ═══════════════════════════════════════════════════════════════════
#  区域标记策略 — 哪些区域在导航地图中应标记为墙壁/障碍
# ═══════════════════════════════════════════════════════════════════

# 这些区域在 PGM 地图中标记为 occupied (0)，狗不可进入
WALL_REGION_IDS = {
    "inspection_upper",
    "inspection_lower",
    "obstacle",
}


NAVIGATION_LAYERS = {
    "solid_regions": REGIONS,
    "placement_cells": PLACEMENT_CELLS,
    "outside_regions": {"start": START_AREA},
    "inferred_corridors": CORRIDORS,
    "visual_reference_only": VISUAL_LINE_GROUPS,
    "example_grab_objects": {"platform": PLATFORM, "bars": TASK_BARS_EXAMPLE},
}


def all_regions(include_estimated: bool = True) -> dict[str, Region]:
    """Return a flat region mapping useful for visualization or collision checks."""
    regions: dict[str, Region] = {}
    for group in (REGIONS, PLACEMENT_CELLS, {"start": START_AREA}, CORRIDORS, VISUAL_LINE_GROUPS):
        for key, region in group.items():
            if include_estimated or region.confidence != "estimated":
                regions[key] = region
    if include_estimated:
        regions["grab_platform"] = PLATFORM
    return regions


def rect_to_polygon(rect: Rect) -> tuple[Point, Point, Point, Point]:
    x, y, w, h = rect
    return ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
