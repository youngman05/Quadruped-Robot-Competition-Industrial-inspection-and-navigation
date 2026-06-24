#!/usr/bin/env bash
set -euo pipefail

echo "== System =="
uname -a
cat /etc/os-release | sed -n '1,6p'

echo
echo "== Disk / Memory =="
df -h /
free -h

echo
echo "== Python =="
python3 --version
python3 -m pip --version || true

echo
echo "== Python packages =="
python3 - <<'PY'
def check(name, import_name=None):
    import importlib
    mod_name = import_name or name
    try:
        mod = importlib.import_module(mod_name)
        version = getattr(mod, "__version__", "ok")
        print(f"{name}: {version}")
    except Exception as exc:
        print(f"{name}: MISSING ({exc})")

check("cv2")
check("pyrealsense2")
check("tensorrt")
PY

echo
echo "== USB =="
lsusb || true

echo
echo "== Video devices =="
ls -l /dev/video* /dev/media* 2>/dev/null || true
if command -v v4l2-ctl >/dev/null 2>&1; then
  v4l2-ctl --list-devices || true
fi

echo
echo "== TensorRT =="
if [ -x /usr/src/tensorrt/bin/trtexec ]; then
  /usr/src/tensorrt/bin/trtexec --version | head -2 || true
else
  echo "trtexec not found at /usr/src/tensorrt/bin/trtexec"
fi

