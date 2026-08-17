#!/usr/bin/env bash

set -u

CN="$(docker ps --format '{{.Names}}' --filter name=cuvslam | head -n 1)"
if [ -z "$CN" ]; then
    echo "cuVSLAM container not running" >&2
    exit 1
fi

docker exec -d "$CN" bash -lc \
    '/opt/quadruped/perception/bin/run_yolo_3d_node.sh >/tmp/yolo_3d.log 2>&1'
