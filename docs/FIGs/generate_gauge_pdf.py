"""
Generate a 24-page PDF from the official 6 gauge images.
Each page: A4, top = large letter (A/B/C/D), bottom = gauge.
Output: gauge_test_24pages.pdf
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FIGS = Path(__file__).resolve().parent
GAUGE_DIR = FIGS / "extracted"
GAUGES = sorted(GAUGE_DIR.glob("gauge_*.jpg"))
LETTERS = ["A", "B", "C", "D"]
OUT_PDF = FIGS / "gauge_test_24pages.pdf"

if not GAUGES:
    raise SystemExit(f"No gauge images found in {GAUGE_DIR}")

# A4 at 200 DPI
DPI = 200
W = int(21.0 / 2.54 * DPI)   # ~1654 px
H = int(29.7 / 2.54 * DPI)   # ~2339 px
MARGIN = 80
GAUGE_SIZE = int(min(W, H) * 0.58)


def _load_font(size):
    for path in [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/simhei.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


font_letter = _load_font(300)
font_label = _load_font(32)

pages = []

for letter in LETTERS:
    for gpath in GAUGES:
        gauge_img = Image.open(gpath).convert("RGB")

        # fit gauge into square, keep aspect
        ratio = min(GAUGE_SIZE / gauge_img.width, GAUGE_SIZE / gauge_img.height)
        new_w = int(gauge_img.width * ratio)
        new_h = int(gauge_img.height * ratio)
        gauge_img = gauge_img.resize((new_w, new_h), Image.LANCZOS)

        # white A4 canvas
        page = Image.new("RGB", (W, H), "white")
        draw = ImageDraw.Draw(page)

        # ── letter ──
        bbox = draw.textbbox((0, 0), letter, font=font_letter)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((W - tw) // 2, MARGIN + 60), letter, fill=(0, 0, 0), font=font_letter)

        # ── gauge (below letter, centered) ──
        gap_after_letter = MARGIN + 60 + th + 40
        gx = (W - new_w) // 2
        gy = gap_after_letter + (H - gap_after_letter - new_h) // 2
        page.paste(gauge_img, (gx, gy))

        # ── footer ──
        label = f"{letter}  —  {gpath.stem}"
        lbbox = draw.textbbox((0, 0), label, font=font_label)
        lw, lh = lbbox[2] - lbbox[0], lbbox[3] - lbbox[1]
        draw.text(((W - lw) // 2, H - MARGIN - lh), label, fill=(120, 120, 120), font=font_label)

        pages.append(page)
        print(f"  {letter} + {gpath.name}")

# save
pages[0].save(OUT_PDF, "PDF", save_all=True, append_images=pages[1:], resolution=DPI)
print(f"\nDone: {OUT_PDF}  ({len(pages)} pages)")
