# 任务区 AprilTag 36h11

直接打印文件：`apriltag_36h11_all_5_a4_compensated_96pct.pdf`，共 5 页，每页一个标签。

标签映射：

| ID | 区域 | 文件名标识 |
|---:|---|---|
| 0 | 抓取区 | `pickup` |
| 1 | 放置区 A | `place_a` |
| 2 | 放置区 B | `place_b` |
| 3 | 放置区 C | `place_c` |
| 4 | 放置区 D | `place_d` |

## 0.96 打印机补偿

打印机实测把 100 mm 打印成 96 mm，因此 PDF 已按 `1 / 0.96 = 1.0416667` 预放大：

- PDF 黑色标签区：156.25 mm，预计打印为 150 mm。
- PDF 校验条：104.1667 mm，预计打印为 100 mm。
- 打印后含一模块白色静区的总边长：187.5 mm。

不要再选择“适合页面”或额外缩放。打印后先测量页面下方校验条，应为 100 mm；再测量标签最外层黑色正方形，应为 150 mm。PnP 参数使用实际黑色正方形边长：`tag_size_m=0.150`，不包含白色静区。

沿外侧裁切标记裁剪，必须保留完整白色静区。纸面保持平整，不要用反光胶带覆盖标签。

PNG 文件只用于屏幕预览和识别验收，不作为定尺寸打印文件。单页 PDF 可用于只补打一张标签。

## 重新生成

在具备 OpenCV `cv2.aruco` 和 Pillow 的环境中运行：

```bash
python3 scripts/calibration/generate_apriltag_prints.py --printer-scale 0.96
```

Xavier 的 `d455_yolo_repro_20260811` 容器已具备所需环境。
