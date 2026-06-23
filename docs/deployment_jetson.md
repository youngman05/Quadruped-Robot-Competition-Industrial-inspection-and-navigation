# Jetson Deployment

目标机器：Jetson Xavier NX，Ubuntu 20.04 / L4T 35.x。

## 已验证基础环境

```text
Python 3.8.10
OpenCV 4.2.0
pyrealsense2 2.55.1
TensorRT 8.5.2.2
D455 RGB-D stream OK
```

## 首次部署

```bash
sudo apt-get update
sudo apt-get install -y \
  python3-pip python3-venv python3-dev python3-opencv v4l-utils \
  git cmake build-essential pkg-config libusb-1.0-0-dev libgl1 libglib2.0-0
```

RealSense Python:

```bash
python3 -m pip install --no-cache-dir pyrealsense2==2.55.1.6486
```

TensorRT:

```bash
sudo apt-get install -y \
  tensorrt python3-libnvinfer libnvinfer-bin libnvinfer-dev \
  libnvonnxparsers8 libnvonnxparsers-dev onnx-graphsurgeon \
  libcudla-11-4 libcudla-dev-11-4
```

## 拉取仓库

```bash
cd ~
git clone <private-repo-url>
cd quadruped-robot-competition
bash scripts/check_jetson_env.sh
```

安装本仓库 Python 包的 editable 入口，供 `cv.realsense_camera` 等 `src/` 下模块导入：

```bash
python3 -m pip install -e .
```

## D455 测试

```bash
python3 scripts/realsense_smoke_test.py
```

预期输出：

```text
device: Intel RealSense D455
color: 640x480
depth: 640x480
center depth: <value> m
```

## 仪表盘样例测试

```bash
python3 scripts/run_gauge_sample.py
```

## 注意

- 不要在 Jetson 上直接改长期代码。
- Jetson 上的改动必须同步回 Git。
- 模型权重和数据集不要直接提交到仓库。
- 比赛正式推理建议使用 TensorRT engine，而不是长期跑 `.pt`。
