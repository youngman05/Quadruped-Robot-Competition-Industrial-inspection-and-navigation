# arm_new 独立部署到 Jetson

`arm_new/` 使用纯 Python 几何 IK，不依赖原 ArmPi 的 `ik_transform.py` 或 `inverse_kinematics.so`。复制整个 `arm_new/` 目录到 Jetson 即可。

## 复制目录

建议部署到：

```bash
/home/ubuntu/arm_new
```

目录应类似：

```text
/home/ubuntu/arm_new/
+-- arm_api/
+-- scripts/
+-- examples/
+-- requirements.txt
+-- README.md
```

## 安装依赖

```bash
cd /home/ubuntu/arm_new
python3 -m pip install -r requirements.txt
```

当前主链路只需要 Python 标准库和 `pyserial`。`requirements.txt` 里保留的额外依赖不会影响运行。

## 最小自检

当前 `L4=0.2700 m` 模型的端面抓取测试点为
`(0.0, 0.42, 0.15)`。完整的已验证中心线范围见 `README.md` 的
“新模型已验证的中心线可达范围”；不要继续使用旧模型的 `y=0.18` 或
`y=0.34` 示例。

只规划，不开串口：

```bash
cd /home/ubuntu/arm_new
python3 - <<'PY'
from arm_api import ArmGrabPlanner

planner = ArmGrabPlanner()
steps = planner.plan_grab((0.0, 0.42, 0.15), rotation_deg=0.0, include_home=True)
print("planned steps:", len(steps))
for step in steps:
    print(step.name, step.coordinate, step.servos)
PY
```

高层服务 dry-run：

```bash
python3 - <<'PY'
from arm_api import ArmService, ArmServiceConfig

arm = ArmService(ArmServiceConfig(port="/dev/ttyACM0", dry_run=True))
result = arm.grab_from_pose((0.0, 0.42, 0.15), rotation_deg=0.0)
print(result.ok, result.message)
PY
```

端面靠近抓取 dry-run：

```bash
python3 scripts/face_approach_grab.py 0 0.42 0.15 --steps 8
```

确认安全后真实执行：

```bash
python3 scripts/face_approach_grab.py 0 0.42 0.15 --execute --read-before --duration-scale 2.0
```

## BusLinker 真机检查

确认串口：

```bash
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
```

只动夹爪小幅测试：

```bash
python3 - <<'PY'
from arm_api import ArmService, ArmServiceConfig

arm = ArmService(ArmServiceConfig(port="/dev/ttyACM0", dry_run=True))
arm.smoke_test_gripper(dry_run=False)
PY
```

第一次真实运动时，手放在电源开关旁边，异常立即断电。

## 主程序接入

主程序应先把目标点转换到机械臂基座坐标系，再调用：

```python
result = arm.grab_from_pose((x_arm, y_arm, z_arm), rotation_deg=0.0)
```

相机坐标到机械臂坐标的转换 API 后续单独加入。
