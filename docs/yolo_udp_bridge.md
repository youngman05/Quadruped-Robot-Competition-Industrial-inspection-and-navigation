# D455 YOLO Host UDP Bridge

The Docker node `/d455_object_yolo_3d` sends v1 detection JSON to UDP
`127.0.0.1:19002` in `camera_link`. The Host `yolo_udp_bridge` is the only
consumer that turns those positions into `base_link` ROS data.

```text
Docker YOLO: UDP v1, camera_link
  -> Host yolo_udp_bridge
  -> tf2 lookup(base_link <- camera_link)
  -> /yolo/detections       std_msgs/String JSON, frame_id=base_link
  -> /yolo/detection_poses  geometry_msgs/PoseArray, base_link
  -> /cone/detections       geometry_msgs/PoseArray, base_link
  -> /block/detections      geometry_msgs/PoseArray, base_link
```

The bridge does not contain a camera matrix. `launch/static_transforms.launch.py`
publishes `base_link -> camera_link` from
`configs/transforms/static_extrinsics.yaml`, and the bridge queries that TF.
If TF is unavailable, it publishes no converted output. A downstream obstacle
consumer must treat an expired output as unsafe.

The JSON packet on `/yolo/detections` follows
`configs/yolo/host_detection_v1.schema.json`. It keeps the detection fields
from the Docker packet, but its `frame_id` and every valid `position_m` are
`base_link`. `PoseArray` carries positions only; use the JSON topic whenever
class ID, confidence, depth validity, or bounding boxes are required.

Run the complete Host side independently:

```bash
source /opt/ros/foxy/setup.bash
ros2 launch launch/yolo_udp_bridge.launch.py
```

Or include it in the competition launch with
`enable_yolo_udp_bridge:=true`. The legacy `yolo_detect_publisher` must not
publish `/yolo/detections` at the same time.
