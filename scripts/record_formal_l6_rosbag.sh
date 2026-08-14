#!/bin/bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
QOS_OVERRIDE="$PROJECT_ROOT/configs/ros/cone_rosbag_qos.yaml"

if [ "$#" -lt 2 ]; then
    echo "Usage: bash scripts/record_formal_l6_rosbag.sh OUTPUT_URI TOPIC [TOPIC ...]" >&2
    exit 2
fi

OUTPUT_URI="$1"
shift

[ -f "$QOS_OVERRIDE" ] || {
    echo "Foxy rosbag QoS override is missing: $QOS_OVERRIDE" >&2
    exit 2
}

exec ros2 bag record \
    -o "$OUTPUT_URI" \
    --qos-profile-overrides-path "$QOS_OVERRIDE" \
    "$@"
