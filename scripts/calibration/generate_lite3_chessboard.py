#!/usr/bin/env python3
"""Generate a compensated A4 chessboard for Lite3 front-camera calibration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


INNER_COLS = 9
INNER_ROWS = 6
TARGET_SQUARE_MM = 25.0


def board_geometry(printer_scale: float):
    if not 0.0 < printer_scale <= 1.0:
        raise ValueError("printer_scale must be in (0, 1]")
    page_width, page_height = 297.0, 210.0
    squares_x, squares_y = INNER_COLS + 1, INNER_ROWS + 1
    square_mm = TARGET_SQUARE_MM / printer_scale
    board_width = squares_x * square_mm
    board_height = squares_y * square_mm
    if board_width > page_width - 16.0 or board_height > page_height - 16.0:
        raise ValueError("compensated board does not fit A4 landscape")
    return page_width, page_height, squares_x, squares_y, square_mm, board_width, board_height


def write_svg(path: Path, printer_scale: float) -> None:
    page_width, page_height, squares_x, squares_y, square_mm, board_width, board_height = board_geometry(printer_scale)
    left = (page_width - board_width) / 2.0
    top = (page_height - board_height) / 2.0
    rectangles = []
    for row in range(squares_y):
        for column in range(squares_x):
            if (row + column) % 2 == 0:
                rectangles.append(
                    '<rect x="{:.6f}" y="{:.6f}" width="{:.6f}" height="{:.6f}"/>'.format(
                        left + column * square_mm, top + row * square_mm, square_mm, square_mm
                    )
                )
    bar_width = 100.0 / printer_scale
    svg = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="297mm" height="210mm" viewBox="0 0 297 210">
  <title>Lite3 front camera calibration chessboard</title>
  <rect width="297" height="210" fill="white"/>
  <g fill="black">{rectangles}</g>
  <rect x="{left:.6f}" y="{top:.6f}" width="{board_width:.6f}" height="{board_height:.6f}" fill="none" stroke="black" stroke-width="0.25"/>
  <rect x="{bar_left:.6f}" y="201" width="{bar_width:.6f}" height="2.5" fill="black" stroke="black" stroke-width="0.2"/>
  <text x="148.5" y="207" text-anchor="middle" font-family="Arial" font-size="3">Reference bar: expected printed length 100.0 mm</text>
</svg>
'''.format(
        rectangles="".join(rectangles), left=left, top=top,
        board_width=board_width, board_height=board_height,
        bar_left=(page_width - bar_width) / 2.0, bar_width=bar_width,
    )
    path.write_text(svg, encoding="utf-8")


def write_pdf(path: Path, printer_scale: float) -> None:
    """Write the same board as a minimal vector A4 PDF without dependencies."""

    page_width, page_height, squares_x, squares_y, square_mm, board_width, board_height = board_geometry(printer_scale)
    points_per_mm = 72.0 / 25.4
    left = (page_width - board_width) / 2.0
    bottom = (page_height - board_height) / 2.0
    commands = ["0 0 0 rg"]
    for row in range(squares_y):
        for column in range(squares_x):
            if (row + column) % 2 == 0:
                x = (left + column * square_mm) * points_per_mm
                y = (bottom + (squares_y - row - 1) * square_mm) * points_per_mm
                side = square_mm * points_per_mm
                commands.append("{:.5f} {:.5f} {:.5f} {:.5f} re f".format(x, y, side, side))
    bar_width = 100.0 / printer_scale
    commands.append(
        "{:.5f} {:.5f} {:.5f} {:.5f} re f".format(
            ((page_width - bar_width) / 2.0) * points_per_mm,
            4.0 * points_per_mm,
            bar_width * points_per_mm,
            2.5 * points_per_mm,
        )
    )
    stream = ("\n".join(commands) + "\n").encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {:.5f} {:.5f}] /Contents 4 0 R >>".format(
            page_width * points_per_mm, page_height * points_per_mm
        ).encode("ascii"),
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream",
    ]
    data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend("{} 0 obj\n".format(index).encode("ascii"))
        data.extend(obj)
        data.extend(b"\nendobj\n")
    startxref = len(data)
    data.extend("xref\n0 {}\n".format(len(objects) + 1).encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend("{:010d} 00000 n \n".format(offset).encode("ascii"))
    data.extend(
        "trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{}\n%%EOF\n".format(
            len(objects) + 1, startxref
        ).encode("ascii")
    )
    path.write_bytes(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--printer-scale", type=float, default=0.96)
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path(__file__).resolve().parents[2] / "assets" / "lite3_front_camera_calibration",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    label = int(round(args.printer_scale * 100.0))
    svg = args.output_dir / "lite3_front_chessboard_9x6_25mm_compensated_{}pct.svg".format(label)
    pdf = args.output_dir / "lite3_front_chessboard_9x6_25mm_compensated_{}pct.pdf".format(label)
    write_svg(svg, args.printer_scale)
    write_pdf(pdf, args.printer_scale)
    metadata = {
        "inner_corners": [INNER_COLS, INNER_ROWS],
        "squares": [INNER_COLS + 1, INNER_ROWS + 1],
        "target_printed_square_mm": TARGET_SQUARE_MM,
        "printer_scale": args.printer_scale,
        "pdf_square_mm": TARGET_SQUARE_MM / args.printer_scale,
        "expected_printed_reference_bar_mm": 100.0,
    }
    svg.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(pdf)


if __name__ == "__main__":
    main()
