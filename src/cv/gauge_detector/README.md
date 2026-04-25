# 仪表盘识别系统 — 使用说明

## 文件说明

| 文件 | 功能 |
|------|------|
| `gauge_detector.py` | 核心识别脚本，可单独调用 |
| `test_gauge.py` | 自动测试脚本（生成模拟图像+多场景测试） |

---

## 环境要求

```bash
pip install opencv-python-headless numpy
# 或使用国内镜像
pip install opencv-python-headless numpy -i https://mirrors.aliyun.com/pypi/simple/
```

系统：Ubuntu（比赛要求）/ macOS 均支持

---

## 快速使用

### 识别单张图像
```bash
python3 gauge_detector.py 图像路径.jpg
```

输出示例：
```
【gauge.jpg】指针位于绿色区域 → 正常，状态：正常
【gauge.jpg】指针位于黄色区域 → 偏低，状态：异常
【gauge.jpg】指针位于红色区域 → 偏高，状态：异常
```

### 带调试可视化输出
```bash
python3 gauge_detector.py 图像路径.jpg --debug
```
会在同目录生成 `*_debug.jpg`，标注检测到的圆、指针方向、颜色区域。

### 批量识别（代码集成）
```python
from gauge_detector import detect_gauge, print_result

result = detect_gauge("gauge.jpg")
# result = {"status": "异常", "level": "偏低", "color": "yellow", "angle": -164.1}

print_result("A区配电柜", result)
# 输出：【A区配电柜】指针位于黄色区域 → 偏低，状态：异常
```

---

## 算法原理

```
输入图像
    ↓
预处理（CLAHE增强 + 双边滤波 + 高斯平滑）
    ↓
HoughCircles 定位仪表盘圆形区域
    ↓
HoughLinesP 霍夫线段检测（主算法）→ 找过圆心的最长线段 → 计算指针角度
    ↓（若霍夫失败）
暗色像素质心法（备用）→ 取最暗像素群质心 → 计算角度
    ↓
沿指针方向在刻度弧带（65%~93%R处）采样颜色
    ↓
HSV颜色匹配：黄/绿/红 → 输出状态
```

---

## 颜色区域与比赛状态对应关系

| 颜色区域 | 状态 | 含义 |
|----------|------|------|
| 🟡 黄色 | 偏低 | **异常** |
| 🟢 绿色 | 正常 | **正常** |
| 🔴 红色 | 偏高 | **异常** |

---

## 测试结果（模拟环境）

| 场景 | 准确率 |
|------|--------|
| 正常光线 | 6/6 = 100% |
| 变暗 50% | 6/6 = 100% |
| 变亮 80% | 6/6 = 100% |
| 顺时针旋转 15° | 6/6 = 100% |
| 逆时针旋转 20° | 6/6 = 100% |
| 透视变形 | 6/6 = 100% |
| 加强噪声 | 4/6 = 67% |
| 轻微模糊 | 6/6 = 100% |
| 暗 + 旋转 | 6/6 = 100% |
| 亮 + 透视 | 6/6 = 100% |
| **总计** | **58/60 = 96.7%** |

> 注：加噪声场景的2个失败案例均为极端噪声（sigma=25），在真实打印识别场景中不易出现，且失败结果仍为"异常"类，不影响安全判断。

---

## 在机器狗上集成示例

```python
#!/usr/bin/env python3
from gauge_detector import detect_gauge

def inspect_gauge(image_path: str, location: str):
    """
    巡检识别主函数
    image_path: 相机拍摄的图像路径
    location: 区域标识，如 "A区"
    """
    result = detect_gauge(image_path)
    if result is None:
        print(f"{location}仪表盘识别失败")
        return
    
    level  = result["level"]   # "偏低" / "正常" / "偏高"
    status = result["status"]  # "异常" / "正常"
    
    # 终端中文输出（比赛要求）
    print(f"{location}仪表盘显示{level}，状态{status}")
    
    # 语音播报（需配合 TTS 模块）
    # speak(f"{location}仪表盘显示{level}，状态{status}")

if __name__ == "__main__":
    inspect_gauge("/tmp/capture.jpg", "A区")
```

---

## 调参建议（针对打印图像）

若识别效果不佳，可在 `gauge_detector.py` 中调整：

1. **颜色范围** `COLOR_RANGES`：根据打印机颜色实测调整 HSV 上下界
2. **采样半径** `angle_to_color_zone` 中 `r_frac` 范围：若彩弧位置不同，调整 0.65~0.93
3. **霍夫线参数** `find_needle_angle_hough`：`threshold`/`minLineLength` 可根据图像清晰度调整
