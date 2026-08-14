#!/usr/bin/env python3
"""Generate exact-size AprilTag 36h11 print assets for the five task zones."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Sequence

import cv2
import numpy as np
from PIL import Image


MM_TO_PT = 72.0 / 25.4
A4_MM = (210.0, 297.0)
TAG_FAMILY = "tag36h11"
BLACK_TAG_SIDE_MM = 150.0
QUIET_ZONE_MODULES = 1
PREVIEW_PIXELS_PER_MODULE = 200
MARKERS = (
    (0, "pickup", "PICK ZONE"),
    (1, "place_a", "PLACE ZONE A"),
    (2, "place_b", "PLACE ZONE B"),
    (3, "place_c", "PLACE ZONE C"),
    (4, "place_d", "PLACE ZONE D"),
)


def marker_matrix(tag_id: int) -> np.ndarray:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    marker_modules = int(dictionary.markerSize) + 2
    pixels = marker_modules * 100
    image = cv2.aruco.generateImageMarker(dictionary, tag_id, pixels, borderBits=1)
    centers = (np.arange(marker_modules) * 100 + 50).astype(int)
    sampled = image[np.ix_(centers, centers)]
    return sampled < 128


def with_quiet_zone(matrix: np.ndarray) -> np.ndarray:
    return np.pad(
        matrix,
        ((QUIET_ZONE_MODULES, QUIET_ZONE_MODULES),) * 2,
        mode="constant",
        constant_values=False,
    )


def write_png(path: Path, matrix: np.ndarray) -> None:
    printable = with_quiet_zone(matrix)
    pixels = np.where(printable, 0, 255).astype(np.uint8)
    image = Image.fromarray(pixels, mode="L").resize(
        tuple(value * PREVIEW_PIXELS_PER_MODULE for value in pixels.shape[::-1]),
        resample=Image.Resampling.NEAREST,
    )
    image.save(path, optimize=True)


def _pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _page_content(matrix: np.ndarray, title: str, tag_id: int, printer_scale: float) -> bytes:
    compensation = 1.0 / printer_scale
    marker_modules = int(matrix.shape[0])
    module_mm = BLACK_TAG_SIDE_MM * compensation / marker_modules
    total_modules = marker_modules + 2 * QUIET_ZONE_MODULES
    total_mm = total_modules * module_mm
    page_width_mm, page_height_mm = A4_MM
    left_mm = (page_width_mm - total_mm) / 2.0
    top_mm = 7.0
    bottom_mm = page_height_mm - top_mm - total_mm

    def pt(value_mm: float) -> float:
        return value_mm * MM_TO_PT

    commands = ["0 0 0 rg", "0 0 0 RG", "0.5 w"]
    for row, values in enumerate(matrix):
        for column, black in enumerate(values):
            if not black:
                continue
            x_mm = left_mm + (column + QUIET_ZONE_MODULES) * module_mm
            y_mm = bottom_mm + (marker_modules - row - 1 + QUIET_ZONE_MODULES) * module_mm
            commands.append(
                "{:.4f} {:.4f} {:.4f} {:.4f} re f".format(
                    pt(x_mm), pt(y_mm), pt(module_mm), pt(module_mm)
                )
            )

    gap_mm = 0.8
    crop_mm = 3.0
    x0, x1 = left_mm, left_mm + total_mm
    y0, y1 = bottom_mm, bottom_mm + total_mm
    segments = (
        (x0 - gap_mm, y0, x0 - gap_mm - crop_mm, y0),
        (x0, y0 - gap_mm, x0, y0 - gap_mm - crop_mm),
        (x1 + gap_mm, y0, x1 + gap_mm + crop_mm, y0),
        (x1, y0 - gap_mm, x1, y0 - gap_mm - crop_mm),
        (x0 - gap_mm, y1, x0 - gap_mm - crop_mm, y1),
        (x0, y1 + gap_mm, x0, y1 + gap_mm + crop_mm),
        (x1 + gap_mm, y1, x1 + gap_mm + crop_mm, y1),
        (x1, y1 + gap_mm, x1, y1 + gap_mm + crop_mm),
    )
    for xa, ya, xb, yb in segments:
        commands.append("{:.4f} {:.4f} m {:.4f} {:.4f} l S".format(pt(xa), pt(ya), pt(xb), pt(yb)))

    def centered_text(text: str, y_mm: float, size: int, bold: bool = False) -> None:
        font = "F2" if bold else "F1"
        # Helvetica is used only for ASCII labels. This estimate is sufficient for centering.
        estimated_width_pt = len(text) * size * 0.52
        x_pt = (pt(page_width_mm) - estimated_width_pt) / 2.0
        commands.append(
            "BT /{} {} Tf {:.4f} {:.4f} Td ({}) Tj ET".format(
                font, size, x_pt, pt(y_mm), _pdf_text(text)
            )
        )

    centered_text("APRILTAG 36H11 - {} - ID {}".format(title, tag_id), 79.0, 14, True)
    centered_text(
        "PDF black square: 156.250 mm -> expected print: 150.0 mm",
        72.0,
        9,
    )
    centered_text("PnP tag_size_m: 0.150 (measure black square, exclude white margin)", 67.0, 8)
    centered_text("Cut at outer marks and keep the complete white quiet zone.", 62.0, 8)

    bar_width_mm = 100.0 * compensation
    bar_left_mm = (page_width_mm - bar_width_mm) / 2.0
    commands.append(
        "{:.4f} {:.4f} {:.4f} {:.4f} re f".format(
            pt(bar_left_mm), pt(31.0), pt(bar_width_mm), pt(3.0)
        )
    )
    centered_text("PDF bar: 104.167 mm -> expected printed measurement: 100 mm", 25.0, 9)
    centered_text("Print at the printer's fixed 96% output. Do not apply another fit-to-page scale.", 19.0, 8)
    return ("\n".join(commands) + "\n").encode("ascii")


def write_pdf(
    path: Path,
    pages: Iterable[tuple[np.ndarray, str, int]],
    printer_scale: float,
) -> None:
    page_contents = [
        _page_content(matrix, title, tag_id, printer_scale)
        for matrix, title, tag_id in pages
    ]
    page_count = len(page_contents)
    page_object_ids = [4 + index * 2 for index in range(page_count)]
    content_object_ids = [value + 1 for value in page_object_ids]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            "<< /Type /Pages /Count {} /Kids [{}] >>".format(
                page_count, " ".join("{} 0 R".format(value) for value in page_object_ids)
            )
        ).encode("ascii"),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    bold_font_id = 4 + page_count * 2
    objects[bold_font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"
    for page_id, content_id, content in zip(page_object_ids, content_object_ids, page_contents):
        objects[page_id] = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {:.4f} {:.4f}] "
            "/Resources << /Font << /F1 3 0 R /F2 {} 0 R >> >> /Contents {} 0 R >>".format(
                A4_MM[0] * MM_TO_PT,
                A4_MM[1] * MM_TO_PT,
                bold_font_id,
                content_id,
            )
        ).encode("ascii")
        objects[content_id] = (
            "<< /Length {} >>\nstream\n".format(len(content)).encode("ascii")
            + content
            + b"endstream"
        )

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {0: 0}
    for object_id in sorted(objects):
        offsets[object_id] = len(output)
        output.extend("{} 0 obj\n".format(object_id).encode("ascii"))
        output.extend(objects[object_id])
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    max_id = max(objects)
    output.extend("xref\n0 {}\n".format(max_id + 1).encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for object_id in range(1, max_id + 1):
        output.extend("{:010d} 00000 n \n".format(offsets[object_id]).encode("ascii"))
    output.extend(
        (
            "trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{}\n%%EOF\n".format(
                max_id + 1, xref_offset
            )
        ).encode("ascii")
    )
    path.write_bytes(output)


def write_metadata(path: Path, printer_scale: float) -> None:
    marker_modules = int(marker_matrix(0).shape[0])
    compensation = 1.0 / printer_scale
    metadata = {
        "schema_version": 1,
        "family": TAG_FAMILY,
        "markers": [
            {"id": tag_id, "zone": name, "label": title}
            for tag_id, name, title in MARKERS
        ],
        "measured_printer_scale": printer_scale,
        "pdf_compensation_factor": compensation,
        "marker_modules": marker_modules,
        "quiet_zone_modules_each_side": QUIET_ZONE_MODULES,
        "pdf_black_tag_side_mm": BLACK_TAG_SIDE_MM * compensation,
        "expected_printed_black_tag_side_mm": BLACK_TAG_SIDE_MM,
        "pdf_reference_bar_mm": 100.0 * compensation,
        "expected_printed_reference_bar_mm": 100.0,
        "expected_printed_total_side_with_quiet_zone_mm": (
            BLACK_TAG_SIDE_MM
            * (marker_modules + 2 * QUIET_ZONE_MODULES)
            / marker_modules
        ),
        "pnp_tag_size_m": BLACK_TAG_SIDE_MM / 1000.0,
    }
    path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    script_path = Path(__file__).resolve()
    default_output_dir = (
        script_path.parents[2] / "assets" / "task_apriltags"
        if len(script_path.parents) > 2
        else Path.cwd() / "task_apriltags"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output_dir,
    )
    parser.add_argument(
        "--printer-scale",
        type=float,
        default=0.96,
        help="Measured printed/reference ratio; 0.96 means 100 mm is printed as 96 mm.",
    )
    args = parser.parse_args()
    if not 0.0 < args.printer_scale <= 1.0:
        raise ValueError("printer_scale must be greater than zero and at most one")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    pages = []
    for tag_id, name, title in MARKERS:
        matrix = marker_matrix(tag_id)
        pages.append((matrix, title, tag_id))
        write_png(args.output_dir / "apriltag_36h11_id{}_{}_preview.png".format(tag_id, name), matrix)
        write_pdf(
            args.output_dir / "apriltag_36h11_id{}_{}_a4_compensated_96pct.pdf".format(tag_id, name),
            [(matrix, title, tag_id)],
            args.printer_scale,
        )

    write_pdf(
        args.output_dir / "apriltag_36h11_all_5_a4_compensated_96pct.pdf",
        pages,
        args.printer_scale,
    )
    write_metadata(args.output_dir / "apriltag_36h11_print_96pct.json", args.printer_scale)


if __name__ == "__main__":
    main()
