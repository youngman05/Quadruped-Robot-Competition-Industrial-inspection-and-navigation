# D455 YOLO Host UDP Bridge

The Docker node `/d455_object_yolo_3d` sends v1 detection JSON to UDP
`127.0.0.1:19002` in `camera_link`. The Host `yolo_udp_bridge` validates and
forwards those positions as `camera_link` ROS data without applying a TF
transform.

```text
Docker YOLO: UDP v1, camera_link
  -> Host yolo_udp_bridge
  -> /yolo/detections       std_msgs/String JSON, frame_id=camera_link
  -> /yolo/detection_poses  geometry_msgs/PoseArray, camera_link
  -> /cone/detections       geometry_msgs/PoseArray, camera_link
  -> /block/detections      geometry_msgs/PoseArray, camera_link
```

The bridge does not contain a camera matrix and does not query TF. The static
`base_link -> camera_link` calibration remains available for downstream users
that explicitly need another frame. A downstream obstacle consumer must treat
an expired output as unsafe.

The JSON packet on `/yolo/detections` follows
`configs/yolo/host_detection_v1.schema.json`. It keeps the detection fields
from the Docker packet, and its `frame_id` and every valid `position_m` remain
`camera_link`. `PoseArray` carries positions only; use the JSON topic whenever
class ID, confidence, depth validity, or bounding boxes are required.

Run the complete Host side independently:

```bash
source /opt/ros/foxy/setup.bash
ros2 launch launch/yolo_udp_bridge.launch.py
```

Or include it in the competition launch with
`enable_yolo_udp_bridge:=true`. The legacy `yolo_detect_publisher` must not
publish `/yolo/detections` at the same time.
