cmake_minimum_required(VERSION 3.8)
project(ros_realsense_frame_probe)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()

find_package(ament_cmake REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(nlohmann_json REQUIRED)
find_package(rclcpp REQUIRED)
find_package(realsense2_camera_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)

add_executable(ros_realsense_frame_probe src/ros_realsense_frame_probe.cpp)
ament_target_dependencies(
  ros_realsense_frame_probe
  nav_msgs
  rclcpp
  realsense2_camera_msgs
  sensor_msgs
)
target_link_libraries(ros_realsense_frame_probe nlohmann_json::nlohmann_json)

install(TARGETS ros_realsense_frame_probe DESTINATION lib/${PROJECT_NAME})

ament_package()
