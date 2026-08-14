#!/usr/bin/env python3
"""Create four compensated 100 mm AprilTag 36h11 print pages from the task PDF."""

from __future__ import annotations

import re
import zlib
from pathlib import Path


MM_TO_PT = 72.0 / 25.4
PAGE_WIDTH_MM = 210.0
PAGE_HEIGHT_MM = 297.0
PRINTER_SCALE = 0.96
TARGET_BLACK_SIDE_MM = 100.0
SOURCE_BLACK_SIDE_MM = 75.0
PRINTED_CUT_MARGIN_MM = 10.0
# The source page positions of IDs 0-3, measured at the outer white quiet zone.
SOURCE_OUTER_ORIGINS_MM = ((7.5, 183.25), (108.75, 183.25), (7.5, 57.25), (108.75, 57.25))
SOURCE_OUTER_SIDE_MM = 93.75


def object_data(pdf: bytes, object_id: int) -> bytes:
    match = re.search(
        rb"(?:^|\n)" + str(object_id).encode("ascii") + rb" 0 obj\n(.*?)\nendobj",
        pdf,
        re.DOTALL,
    )
    if match is None:
        raise ValueError("missing source PDF object {}".format(object_id))
    return match.group(1)


def object_stream(pdf: bytes, object_id: int) -> bytes:
    data = object_data(pdf, object_id)
    match = re.search(rb"stream\r?\n(.*?)\r?\nendstream", data, re.DOTALL)
    if match is None:
        raise ValueError("missing stream in source PDF object {}".format(object_id))
    return zlib.decompress(match.group(1))


def source_tag_groups(source_content: bytes) -> tuple[bytes, list[bytes]]:
    root_transform = source_content.split(b"\n", 1)[0] + b"\n"
    groups = re.findall(
        rb"(q\n11\.0770111 0 0 11\.0774288 [^\n]+ cm\n.*?\nQ)\nq\n11\.8154764",
        source_content,
        re.DOTALL,
    )
    if len(groups) != 4:
        raise ValueError("expected four tag vector groups, found {}".format(len(groups)))
    return root_transform, groups


def page_content(root_transform: bytes, tag_group: bytes, tag_id: int) -> bytes:
    scale = (TARGET_BLACK_SIDE_MM / PRINTER_SCALE) / SOURCE_BLACK_SIDE_MM
    pdf_black_side_mm = TARGET_BLACK_SIDE_MM / PRINTER_SCALE
    target_outer_side_mm = SOURCE_OUTER_SIDE_MM * scale
    target_x_mm = (PAGE_WIDTH_MM - target_outer_side_mm) / 2.0
    target_y_mm = PAGE_HEIGHT_MM - 22.0 - target_outer_side_mm
    source_x_mm, source_y_mm = SOURCE_OUTER_ORIGINS_MM[tag_id]
    translate_x_mm = target_x_mm - source_x_mm * scale
    translate_y_mm = target_y_mm - source_y_mm * scale
    # The source keeps a 12.5 mm printed quiet zone. The cut line leaves 10 mm
    # around the black tag and keeps the remaining 2.5 mm outside as cut waste.
    cut_margin_pdf_mm = PRINTED_CUT_MARGIN_MM / PRINTER_SCALE
    black_x_mm = target_x_mm + (target_outer_side_mm - pdf_black_side_mm) / 2.0
    black_y_mm = target_y_mm + (target_outer_side_mm - pdf_black_side_mm) / 2.0
    cut_x_mm = black_x_mm - cut_margin_pdf_mm
    cut_y_mm = black_y_mm - cut_margin_pdf_mm
    cut_side_mm = pdf_black_side_mm + 2.0 * cut_margin_pdf_mm

    prefix = (
        "q\n"
        "{s:.9f} 0 0 {s:.9f} {tx:.4f} {ty:.4f} cm\n".format(
            s=scale,
            tx=translate_x_mm * MM_TO_PT,
            ty=translate_y_mm * MM_TO_PT,
        )
    ).encode("ascii")
    suffix = (
        "Q\n"
        "0.62 0.62 0.62 RG 0.70 w [{dash:.4f} {gap:.4f}] 0 d "
        "{cut_x:.4f} {cut_y:.4f} {cut_side:.4f} {cut_side:.4f} re S [] 0 d\n"
        "0 0 0 rg\n"
        "BT /F1 16 Tf 72 115 Td (APRILTAG 36H11 - ID {tag_id}) Tj ET\n"
        "BT /F1 10 Tf 72 94 Td (Black square: 100.0 mm after 96% print scaling; PDF size: 104.167 mm) Tj ET\n"
        "BT /F1 10 Tf 72 77 Td (PnP tag_size_m: 0.100. Print at 96%; disable fit-to-page.) Tj ET\n"
        "0 0 0 rg {bar_x:.4f} 46 {bar_w:.4f} 8 re f\n"
        "BT /F1 9 Tf 72 30 Td (Length check: expected printed length = 100 mm) Tj ET\n".format(
            tag_id=tag_id,
            dash=3.0 * MM_TO_PT,
            gap=2.0 * MM_TO_PT,
            cut_x=cut_x_mm * MM_TO_PT,
            cut_y=cut_y_mm * MM_TO_PT,
            cut_side=cut_side_mm * MM_TO_PT,
            bar_x=(PAGE_WIDTH_MM - TARGET_BLACK_SIDE_MM / PRINTER_SCALE) * MM_TO_PT / 2.0,
            bar_w=(TARGET_BLACK_SIDE_MM / PRINTER_SCALE) * MM_TO_PT,
        )
    ).encode("ascii")
    # Separate operators so the final Q restores the page coordinate system.
    return prefix + root_transform + tag_group + b"\n" + suffix


def write_pdf(path: Path, source_pdf: bytes) -> None:
    source_content = object_stream(source_pdf, 7)
    root_transform, tag_groups = source_tag_groups(source_content)
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Count 4 /Kids [30 0 R 32 0 R 34 0 R 36 0 R] >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        # These are the source PDF's fonts and graphics states used by its vector tag paths.
        4: object_data(source_pdf, 3),
        5: object_data(source_pdf, 4),
        6: object_data(source_pdf, 5),
        7: object_data(source_pdf, 6),
    }
    for source_id in range(15, 23):
        objects[source_id] = object_data(source_pdf, source_id)

    for index, page_id in enumerate((30, 32, 34, 36)):
        content_id = page_id + 1
        content = zlib.compress(page_content(root_transform, tag_groups[index], index), level=9)
        objects[page_id] = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.2756 841.8898] "
            "/Resources << /ProcSet [/PDF /Text] "
            "/ExtGState << /G3 4 0 R /G6 7 0 R >> "
            "/Font << /F1 3 0 R /F4 5 0 R /F5 6 0 R >> >> "
            "/Contents {} 0 R >>".format(content_id)
        ).encode("ascii")
        objects[content_id] = (
            "<< /Filter /FlateDecode /Length {} >>\nstream\n".format(len(content)).encode("ascii")
            + content
            + b"\nendstream"
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
        if object_id in offsets:
            output.extend("{:010d} 00000 n \n".format(offsets[object_id]).encode("ascii"))
        else:
            output.extend(b"0000000000 00000 f \n")
    output.extend(
        "trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{}\n%%EOF\n".format(max_id + 1, xref_offset).encode("ascii")
    )
    path.write_bytes(output)


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    assets = root / "assets" / "task_apriltags"
    source = assets / "Finalapriltag36h11_0-3_096_print.pdf"
    destination = assets / "apriltag36h11_id0-3_100mm_compensated_96pct.pdf"
    write_pdf(destination, source.read_bytes())
    print(destination)


if __name__ == "__main__":
    main()
