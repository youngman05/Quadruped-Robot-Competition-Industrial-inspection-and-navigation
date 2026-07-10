# 仪表柜面检测 — YOLO 版

替换了原来的模板匹配方案。使用训练好的 YOLOv8 模型同时检测字母和仪表颜色。

> **⚠️ 识别前必须满足的条件：**
> 1. 机器狗在距离被检测柜面 **30cm** 处停稳
> 2. 相机正对柜面，画面清晰无抖动
> 3. 满足以上条件后再调用 `/whz/inspect` 进行识别
>
> 距离太远/太近、画面晃动都会导致识别失败。

## 类别

| ID | 名称 | 类型 |
|----|------|------|
| 0 | A | 字母 |
| 1 | B | 字母 |
| 2 | C | 字母 |
| 3 | D | 字母 |
| 4 | green | 仪表颜色 |
| 5 | red | 仪表颜色 |
| 6 | yellow | 仪表颜色 |

## 使用

```python
from cv.gauge_detector import GaugeDetector

det = GaugeDetector()
result = det.detect(image)  # BGR numpy array

# 字母
print(result.best_letter.letter)       # 'C'
print(result.best_letter.confidence)   # 0.95

# 仪表
print(result.best_gauge.color)         # 'green'

# 画框
annotated = det.draw(image, result)
```

## 模型

`InstanceSegmentation/projects/gauge/model/best.pt`
mAP50: 0.973 (130 train / 32 val, 520 instances)
