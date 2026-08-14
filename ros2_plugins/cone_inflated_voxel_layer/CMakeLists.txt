cmake_minimum_required(VERSION 3.5)
project(cone_inflated_voxel_layer)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(nav2_costmap_2d REQUIRED)
find_package(nonpersistent_voxel_layer REQUIRED)
find_package(pluginlib REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_lifecycle REQUIRED)
find_package(rcl_interfaces REQUIRED)
find_package(std_msgs REQUIRED)

set(
  NONPERSISTENT_VOXEL_LAYER_SOURCE_INCLUDE
  ""
  CACHE PATH
  "Path to nonpersistent_voxel_layer 2.2.1 source include directory"
)
if(NOT EXISTS "${NONPERSISTENT_VOXEL_LAYER_SOURCE_INCLUDE}/nonpersistent_voxel_layer/nonpersistent_voxel_layer.hpp")
  message(FATAL_ERROR
    "NONPERSISTENT_VOXEL_LAYER_SOURCE_INCLUDE must point to the pinned 2.2.1 source include directory")
endif()

add_library(${PROJECT_NAME}_core SHARED
  src/cone_inflated_voxel_layer.cpp
)
target_compile_definitions(${PROJECT_NAME}_core PUBLIC "PLUGINLIB__DISABLE_BOOST_FUNCTIONS")
target_include_directories(${PROJECT_NAME}_core PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<BUILD_INTERFACE:${NONPERSISTENT_VOXEL_LAYER_SOURCE_INCLUDE}>
  $<INSTALL_INTERFACE:include>
)
ament_target_dependencies(${PROJECT_NAME}_core
  nav2_costmap_2d
  nonpersistent_voxel_layer
  pluginlib
  rclcpp
  rclcpp_lifecycle
  rcl_interfaces
  std_msgs
)

pluginlib_export_plugin_description_file(nav2_costmap_2d costmap_plugins.xml)

install(TARGETS ${PROJECT_NAME}_core
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION bin
)
install(DIRECTORY include/ DESTINATION include)
install(FILES costmap_plugins.xml DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_cone_inflation test/test_cone_inflation.cpp)
  target_link_libraries(test_cone_inflation ${PROJECT_NAME}_core)
endif()

ament_export_include_directories(include)
ament_export_libraries(${PROJECT_NAME}_core)
ament_export_dependencies(
  nav2_costmap_2d
  nonpersistent_voxel_layer
  rclcpp
  rclcpp_lifecycle
  rcl_interfaces
  std_msgs
)
ament_package()
