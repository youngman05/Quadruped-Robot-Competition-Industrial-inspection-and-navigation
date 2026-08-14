# Lite3 Front Camera Calibration Board

`lite3_front_chessboard_9x6_25mm_compensated_96pct.pdf` is the printable
calibration board for the Lite3 front wide-angle camera.

- Pattern: `10 x 7` squares, therefore `9 x 6` inner corners.
- Target printed square edge: `25.00 mm`.
- The PDF is pre-enlarged for the measured `96%` printer scale. Print it with
  page orientation **landscape** and scale **100%**. Do not use fit-to-page.
  directly, without selecting another scaling option.
- Measure several printed squares and the bottom reference bar. The reference
  bar must measure `100.0 mm`; otherwise enter the measured square edge, not
  `25`, in the calibration command.

Use it with:

```bash
python3 scripts/calibration/lite3_front_camera_calibration.py \
  --capture-dir /tmp/lite3_calibration \
  --board-cols 9 --board-rows 6 --square-mm 25
```
