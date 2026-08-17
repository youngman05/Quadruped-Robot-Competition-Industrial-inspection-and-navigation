#!/usr/bin/env bash

set -u

VALUE="${1:-true}"
case "${VALUE,,}" in
    true|1|yes|on) VALUE=true ;;
    false|0|no|off) VALUE=false ;;
    *) echo "usage: $0 [true|false]" >&2; exit 2 ;;
esac

CN="$(docker ps --format '{{.Names}}' --filter name=cuvslam | head -n 1)"
if [ -z "$CN" ]; then
    echo "cuVSLAM container not running" >&2
    exit 1
fi

docker exec "$CN" bash -lc \
    "source /opt/ros/humble/setup.bash && ros2 param set /camera/camera enable_color $VALUE"
