cmake_minimum_required(VERSION 3.8)
project(cuvslam_lightweight_probe)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()

find_package(ament_cmake REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(nlohmann_json REQUIRED)
find_package(rclcpp REQUIRED)
find_package(realsense2_camera_msgs REQUIRED)
find_package(rmw REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)

add_executable(cuvslam_lightweight_probe src/cuvslam_lightweight_probe.cpp)
ament_target_dependencies(
  cuvslam_lightweight_probe
  nav_msgs
  rclcpp
  realsense2_camera_msgs
  rmw
  sensor_msgs
  std_msgs
)
target_link_libraries(cuvslam_lightweight_probe nlohmann_json::nlohmann_json)

install(TARGETS cuvslam_lightweight_probe DESTINATION lib/${PROJECT_NAME})

ament_package()
