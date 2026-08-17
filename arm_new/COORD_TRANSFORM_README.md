# 坐标转换 API

> 运行时 ROS 节点不使用本模块维护外参；它们只查询由
> `configs/transforms/static_extrinsics.yaml` 发布的 TF。本模块和
> `config/frame_transforms.yaml` 仅保留给离线计算、CLI 与兼容 API。

纯计算模块，不控制机械臂。

## 文件

- `arm_api/transforms.py`：坐标转换 API
- `config/frame_transforms.yaml`：外参矩阵
- `scripts/transform_point.py`：命令行测试

## 坐标

`arm`：

```text
+Y 机械臂正前方
+X 横向偏移
+Z 向上
单位 m
```

`camera`：RealSense 光学系通常为 `+X 图像右，+Y 图像下，+Z 镜头前`。

## 使用

```bash
python3 scripts/transform_point.py 0.1 0.2 0.3 --from-frame camera --to-frame arm
```

```python
from arm_api import FrameTransformer

tf = FrameTransformer.from_yaml("config/frame_transforms.yaml")
p_arm = tf.camera_to_arm((x, y, z))
p_dog = tf.arm_to_dog(p_arm)
```

## 矩阵怎么填

`arm_from_camera` 表示：

```text
p_arm = T_arm_camera * p_camera
```

矩阵格式：

```yaml
arm_from_camera:
  matrix:
    - [r11, r12, r13, tx]
    - [r21, r22, r23, ty]
    - [r31, r32, r33, tz]
    - [0.0, 0.0, 0.0, 1.0]
```

其中：

```text
tx ty tz = 相机原点在 arm 坐标系下的位置，单位 m
第 1 列 = camera +X 轴在 arm 坐标系下的方向
第 2 列 = camera +Y 轴在 arm 坐标系下的方向
第 3 列 = camera +Z 轴在 arm 坐标系下的方向
```

`arm_from_dog` 同理，填狗坐标系原点和三根轴在 `arm` 坐标系下的位置/方向。
