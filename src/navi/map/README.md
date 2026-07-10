# 地图数据与生成 (src/navi/map)

## 文件说明

| 文件 | 用途 |
|------|------|
| `navi_map_data.py` | 场地所有数据的权威定义 — 区域尺寸、柜体位置、标签面、观察位、锥桶 |
| `render_navi_map_preview.py` | 将数据渲染为可视化预览图 |
| `navi_map_preview.png` | 生成的预览图 |

## 生成预览图

> **平台: 均可 (Windows 开发机 或 Linux)**
> 依赖: Python 3.8+, Pillow

```bash
# [Windows 或 Linux]
cd src/navi/map                          # 从仓库根目录进入
python3 -m pip install Pillow            # 首次需要
python3 render_navi_map_preview.py       # 生成 navi_map_preview.png
```

**在 Jetson 上的完整路径**：

```bash
# [Linux]
cd ~/quadruped-robot-competition/src/navi/map
python3 -m pip install Pillow
python3 render_navi_map_preview.py
```

## 场地坐标系

```text
原点: 场地左上角
单位: mm
+x  → 右
+y  → 下（图片中向下）

转换为 ROS map 坐标系（原点左下, +y 上）:
  ros_x = mm_x / 1000.0
  ros_y = (6000 - mm_y) / 1000.0
```

## 场地关键元素

### 区域 (REGIONS)

| 区域 | 位置 (mm) | 说明 |
|------|-----------|------|
| inspection_upper | (1000, 1000, 1000, 1000) | 上检测区 — 标记为**墙体不可入** |
| inspection_lower | (1000, 3500, 1000, 1000) | 下检测区 — 标记为**墙体不可入** |
| grab | (3500, 3500, 1500, 1000) | 抓取区 |
| obstacle | (1000, 4500, 4000, 1500) | 障碍区 — 标记为**墙体不可入**，2个锥桶随机放置 |
| placement | (3000, 0, 2000, 500) | 放置区，分隔为 A/B/C/D 四格 |

**WALL_REGION_IDS** = {inspection_upper, inspection_lower, obstacle} — 在 PGM 地图中这些区域标记为 occupied (0 = 不可通行)。

### 巡检柜体 (INSPECTION_CABINETS)

500×500×500mm 柜体，各两个面贴识别纸：

| 柜体 | 中心 (mm) | 标签面 |
|------|-----------|--------|
| 上柜 (cabinet_upper) | (1500, 1500) | 底面 (朝下) + 右侧面 (朝右) |
| 下柜 (cabinet_lower) | (1500, 4000) | 顶面 (朝上) + 右侧面 (朝右) |

每个面贴什么（字母或仪表）由裁判随机决定。

### 观察位 (OBSERVATION_POSITIONS)

狗需要 3 个观察位才能看全 4 个标签面：

| 观察位 | 位置 (mm) | 朝向 | 看什么 |
|--------|-----------|------|--------|
| ① 中间走廊 | (1500, 2750) | ↑ 仰头 -90° | 上柜底面 |
| | | ↓ 180°转身 +90° | 下柜顶面 |
| ②a 上中通道 | (2200, 1500) | ← 180° | 上柜右侧面 |
| ②b 下中通道 | (2200, 4000) | ← 180° | 下柜右侧面 |

### 锥桶 (OBSTACLE_CONES_EXAMPLE)

2 个锥桶（670×320mm 底面投影），裁判随机放置在障碍区。文件中提供示例位置。

### 机器人起始位姿 (ROBOT_START_POSE)

```
位置: (5350, 5250) mm — 出发区中心
朝向: yaw=180° (面朝左，向场地内部)
```

## 预览图标注

预览图包含以下标注：
- 红色粗框+斜线 — 墙体不可入区域
- 深灰方块 — 巡检柜体
- 黄色标签 — 贴了识别纸的面
- 红色圆点+FOV扇形 — 观察位及视场
- 橙色三角形 — 锥桶（标注"随机"）
- 绿色圆点+箭头 — 机器人出发位姿

## 生成 Nav2 PGM 地图

> **平台: 均可 (开发机生成后同步到 Jetson)**

```bash
# [Windows 或 Linux]
cd src/navi/map
python3 generate_nav2_map.py
# 输出: competition_field.pgm + competition_field.yaml
```

```bash
# [Linux] Jetson 上直接生成
cd ~/quadruped-robot-competition/src/navi/map
python3 generate_nav2_map.py
```
