# 导航地图模块 (navi)

本目录包含比赛场地的地图数据定义、可视化预览和 PGM 栅格地图生成。

## 目录结构

```text
navi/
  map/
    navi_map_data.py           场地数据定义（区域、柜体、观察位、锥桶）
    render_navi_map_preview.py  场地预览渲染脚本
    navi_map_preview.png        生成的预览图
    generate_nav2_map.py        PGM 栅格地图生成（待完成）
    competition_field.pgm       生成的 Nav2 地图（待生成）
    competition_field.yaml      地图元数据（待生成）
  2026年...赛规.pdf            比赛官方规则文档
```

## 快速生成预览图

> **平台: 均可 (Windows/Linux)**

```bash
# [Windows 或 Linux]
cd navi/map
python3 -m pip install Pillow
python3 render_navi_map_preview.py
# 输出: navi_map_preview.png
```

```bash
# [Linux] Jetson 上
cd ~/quadruped-robot-competition/navi/map
python3 -m pip install Pillow
python3 render_navi_map_preview.py
```

## 场地概要

| 参数 | 值 |
|------|-----|
| 场地尺寸 | 5000 × 6000 mm |
| 坐标系原点 | 场地左上角 (mm), +x 右, +y 下 |
| 出发区 | 右下角外侧 (5050, 4500) mm |

详见 [map/README.md](map/README.md)。
