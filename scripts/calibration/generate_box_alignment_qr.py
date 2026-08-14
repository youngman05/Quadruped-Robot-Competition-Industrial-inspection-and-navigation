#!/usr/bin/env python3
"""Generate the fixed-size box alignment QR assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw
from qrcode.constants import ERROR_CORRECT_H
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas


PAYLOAD = "QRCOMP:BOX_CENTER:V1"
QR_VERSION = 3
ERROR_CORRECTION = "H"
QUIET_ZONE_MODULES = 4
BLACK_SYMBOL_SIDE_MM = 150.0
PREVIEW_PIXELS_PER_MODULE = 50


def build_matrix() -> list[list[bool]]:
    qr = qrcode.QRCode(
        version=QR_VERSION,
        error_correction=ERROR_CORRECT_H,
        box_size=1,
        border=0,
    )
    qr.add_data(PAYLOAD, optimize=0)
    qr.make(fit=False)
    matrix = [[bool(value) for value in row] for row in qr.get_matrix()]
    expected_modules = 17 + 4 * QR_VERSION
    if len(matrix) != expected_modules or any(len(row) != expected_modules for row in matrix):
        raise RuntimeError("unexpected QR matrix dimensions")
    return matrix


def write_svg(path: Path, matrix: list[list[bool]]) -> None:
    symbol_modules = len(matrix)
    total_modules = symbol_modules + 2 * QUIET_ZONE_MODULES
    module_mm = BLACK_SYMBOL_SIDE_MM / symbol_modules
    total_mm = total_modules * module_mm
    commands = []
    for row, values in enumerate(matrix):
        for column, enabled in enumerate(values):
            if enabled:
                x = column + QUIET_ZONE_MODULES
                y = row + QUIET_ZONE_MODULES
                commands.append(f"M{x} {y}h1v1h-1z")
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_mm:.6f}mm" '
        f'height="{total_mm:.6f}mm" viewBox="0 0 {total_modules} {total_modules}" '
        'shape-rendering="crispEdges">\n'
        f'  <rect width="{total_modules}" height="{total_modules}" fill="#fff"/>\n'
        f'  <path d="{"".join(commands)}" fill="#000"/>\n'
        '</svg>\n'
    )
    path.write_text(svg, encoding="utf-8")


def write_png(path: Path, matrix: list[list[bool]]) -> None:
    symbol_modules = len(matrix)
    total_modules = symbol_modules + 2 * QUIET_ZONE_MODULES
    scale = PREVIEW_PIXELS_PER_MODULE
    image = Image.new("1", (total_modules * scale, total_modules * scale), color=1)
    draw = ImageDraw.Draw(image)
    for row, values in enumerate(matrix):
        for column, enabled in enumerate(values):
            if not enabled:
                continue
            x0 = (column + QUIET_ZONE_MODULES) * scale
            y0 = (row + QUIET_ZONE_MODULES) * scale
            draw.rectangle((x0, y0, x0 + scale - 1, y0 + scale - 1), fill=0)
    image.save(path, optimize=True)


def _crop_mark(canvas: Canvas, x: float, y: float, sx: int, sy: int) -> None:
    gap = 0.8 * mm
    length = 3.0 * mm
    canvas.line(x + sx * gap, y, x + sx * (gap + length), y)
    canvas.line(x, y + sy * gap, x, y + sy * (gap + length))


def write_pdf(path: Path, matrix: list[list[bool]], printer_scale: float) -> None:
    page_width, page_height = A4
    symbol_modules = len(matrix)
    if not 0.0 < printer_scale <= 1.0:
        raise ValueError("printer_scale must be greater than zero and at most one")
    compensation = 1.0 / printer_scale
    pdf_symbol_side_mm = BLACK_SYMBOL_SIDE_MM * compensation
    module_size = (pdf_symbol_side_mm * mm) / symbol_modules
    total_modules = symbol_modules + 2 * QUIET_ZONE_MODULES
    total_size = total_modules * module_size
    if total_size > page_width:
        raise ValueError(
            "compensated QR does not fit A4: printer_scale={:.6f}".format(printer_scale)
        )
    left = (page_width - total_size) / 2.0
    top_margin = 12.0 * mm
    bottom = page_height - top_margin - total_size

    canvas = Canvas(str(path), pagesize=A4, pageCompression=1)
    canvas.setTitle("Quadruped Box Center Alignment QR ({:.2f}% printer)".format(printer_scale * 100.0))
    canvas.setAuthor("quadruped-vision-yolo-refactor")
    canvas.setFillColorRGB(0, 0, 0)
    canvas.setStrokeColorRGB(0, 0, 0)
    canvas.setLineWidth(0.2 * mm)

    for row, values in enumerate(matrix):
        for column, enabled in enumerate(values):
            if not enabled:
                continue
            x = left + (column + QUIET_ZONE_MODULES) * module_size
            y = bottom + (symbol_modules - row - 1 + QUIET_ZONE_MODULES) * module_size
            canvas.rect(x, y, module_size, module_size, stroke=0, fill=1)

    _crop_mark(canvas, left, bottom, -1, -1)
    _crop_mark(canvas, left + total_size, bottom, 1, -1)
    _crop_mark(canvas, left, bottom + total_size, -1, 1)
    _crop_mark(canvas, left + total_size, bottom + total_size, 1, 1)

    text_y = 68.0 * mm
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawCentredString(
        page_width / 2.0,
        text_y,
        "BOX CENTER ALIGNMENT QR - {:.2f}% PRINTER COMPENSATION".format(printer_scale * 100.0),
    )
    canvas.setFont("Helvetica", 9)
    canvas.drawCentredString(page_width / 2.0, text_y - 6.0 * mm, f"Payload: {PAYLOAD}")
    canvas.drawCentredString(
        page_width / 2.0,
        text_y - 11.0 * mm,
        "PDF symbol: {:.3f} mm -> expected print: {:.1f} mm | Version {}-{}".format(
            pdf_symbol_side_mm, BLACK_SYMBOL_SIDE_MM, QR_VERSION, ERROR_CORRECTION
        ),
    )
    canvas.drawCentredString(
        page_width / 2.0,
        text_y - 16.0 * mm,
        "Cut only at the outer crop marks. Keep the complete white quiet zone.",
    )

    bar_width = 100.0 * compensation * mm
    bar_height = 3.0 * mm
    bar_left = (page_width - bar_width) / 2.0
    bar_bottom = 30.0 * mm
    canvas.rect(bar_left, bar_bottom, bar_width, bar_height, stroke=1, fill=1)
    canvas.setFont("Helvetica", 9)
    canvas.drawCentredString(
        page_width / 2.0,
        bar_bottom - 5.0 * mm,
        "PDF bar: {:.3f} mm -> expected printed measurement: 100 mm".format(100.0 * compensation),
    )

    canvas.showPage()
    canvas.save()


def write_metadata(path: Path, matrix: list[list[bool]]) -> None:
    symbol_modules = len(matrix)
    module_mm = BLACK_SYMBOL_SIDE_MM / symbol_modules
    metadata = {
        "schema_version": 1,
        "marker_id": "box_center_v1",
        "payload": PAYLOAD,
        "qr_version": QR_VERSION,
        "error_correction": ERROR_CORRECTION,
        "symbol_modules": symbol_modules,
        "quiet_zone_modules_each_side": QUIET_ZONE_MODULES,
        "module_size_mm": module_mm,
        "black_symbol_side_mm": BLACK_SYMBOL_SIDE_MM,
        "total_printed_square_side_mm": module_mm * (symbol_modules + 2 * QUIET_ZONE_MODULES),
        "placement": {
            "surface": "box_front_face",
            "centered_on_box_face": True,
            "keep_flat": True,
        },
        "pnp_object_square_side_m": BLACK_SYMBOL_SIDE_MM / 1000.0,
    }
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_print_metadata(path: Path, matrix: list[list[bool]], printer_scale: float) -> None:
    symbol_modules = len(matrix)
    compensation = 1.0 / printer_scale
    target_module_mm = BLACK_SYMBOL_SIDE_MM / symbol_modules
    metadata = {
        "schema_version": 1,
        "marker_id": "box_center_v1",
        "payload": PAYLOAD,
        "measured_printer_scale": printer_scale,
        "pdf_compensation_factor": compensation,
        "pdf_reference_bar_mm": 100.0 * compensation,
        "expected_printed_reference_bar_mm": 100.0,
        "pdf_black_symbol_side_mm": BLACK_SYMBOL_SIDE_MM * compensation,
        "expected_printed_black_symbol_side_mm": BLACK_SYMBOL_SIDE_MM,
        "pdf_total_square_side_mm": (
            target_module_mm
            * (symbol_modules + 2 * QUIET_ZONE_MODULES)
            * compensation
        ),
        "expected_printed_total_square_side_mm": (
            target_module_mm * (symbol_modules + 2 * QUIET_ZONE_MODULES)
        ),
    }
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "assets" / "box_alignment_qr",
    )
    parser.add_argument(
        "--printer-scale",
        type=float,
        default=1.0,
        help="Measured printed/reference ratio, for example 0.96 when 100 mm prints as 96 mm.",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    matrix = build_matrix()
    write_svg(args.output_dir / "box_alignment_qr.svg", matrix)
    write_png(args.output_dir / "box_alignment_qr_preview.png", matrix)
    write_metadata(args.output_dir / "box_alignment_qr.json", matrix)
    percent_label = int(round(args.printer_scale * 100.0))
    if abs(args.printer_scale - 1.0) < 1e-9:
        pdf_name = "box_alignment_qr_a4.pdf"
    else:
        pdf_name = "box_alignment_qr_a4_compensated_{}pct.pdf".format(percent_label)
        write_print_metadata(
            args.output_dir / "box_alignment_qr_print_{}pct.json".format(percent_label),
            matrix,
            args.printer_scale,
        )
    write_pdf(args.output_dir / pdf_name, matrix, args.printer_scale)


if __name__ == "__main__":
    main()
