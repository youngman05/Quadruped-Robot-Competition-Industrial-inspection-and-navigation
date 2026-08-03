# Build with the existing Jetson image that already contains ROS 2, CUDA,
# RealSense/cuVSLAM ROS runtime and the existing YOLO Python dependency set.
# The tested Jetson Torch site-packages are mounted read-only at runtime.
ARG BASE_IMAGE=cuvslam_yolo:humble
FROM ${BASE_IMAGE}

WORKDIR /opt/quadruped/perception

COPY docker/d455_perception/d455_yolo_3d_core.py bin/d455_yolo_3d_core.py
COPY docker/d455_perception/d455_yolo_3d_pipeline.py bin/d455_yolo_3d_pipeline.py
COPY docker/d455_perception/d455_yolo_3d_node.py bin/d455_yolo_3d_node.py

COPY docker/d455_perception/run_yolo_3d_node.sh bin/run_yolo_3d_node.sh
ENV PYTHONPATH=/opt/quadruped/perception/bin:${PYTHONPATH}
ENV YOLO_MODEL_PATH=/opt/quadruped/perception/models/red_green_obstacle.pt

# The model is mounted read-only during validation, then copied into the
# competition image only after its checksum has been accepted.
CMD ["bash"]
