#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

: "${TORCH_WHEEL_URL:?set TORCH_WHEEL_URL to the accepted JetPack torch wheel}"
: "${TORCH_WHEEL_SHA256:?set TORCH_WHEEL_SHA256}"
: "${TORCHVISION_WHEEL_URL:?set TORCHVISION_WHEEL_URL to the matching torchvision wheel}"
: "${TORCHVISION_WHEEL_SHA256:?set TORCHVISION_WHEEL_SHA256}"

IMAGE="${IMAGE:-isaac_ros_cuvslam_runtime:humble-rs-cone-pick-place}"

docker build \
  --file docker/Dockerfile.cuvslam-pick-place \
  --build-arg BASE_IMAGE=isaac_ros_cuvslam_runtime:humble-rs-cone \
  --build-arg TORCH_WHEEL_URL="$TORCH_WHEEL_URL" \
  --build-arg TORCH_WHEEL_SHA256="$TORCH_WHEEL_SHA256" \
  --build-arg TORCHVISION_WHEEL_URL="$TORCHVISION_WHEEL_URL" \
  --build-arg TORCHVISION_WHEEL_SHA256="$TORCHVISION_WHEEL_SHA256" \
  --tag "$IMAGE" \
  .

docker run --rm --runtime nvidia --network none \
  -e YOLO_DEVICE=0 \
  --entrypoint python3 \
  "$IMAGE" \
  /opt/quadruped/perception/bin/verify_runtime.py

echo "Built and verified: $IMAGE"
