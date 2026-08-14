#ifndef CONE_INFLATED_VOXEL_LAYER__CONE_INFLATED_VOXEL_LAYER_HPP_
#define CONE_INFLATED_VOXEL_LAYER__CONE_INFLATED_VOXEL_LAYER_HPP_

#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

#include "nav2_costmap_2d/costmap_2d.hpp"
#include "nonpersistent_voxel_layer/nonpersistent_voxel_layer.hpp"
#include "rcl_interfaces/msg/set_parameters_result.hpp"
#include "rclcpp/node_interfaces/node_parameters_interface.hpp"
#include "rclcpp/parameter.hpp"
#include "rclcpp_lifecycle/lifecycle_publisher.hpp"
#include "std_msgs/msg/string.hpp"

namespace cone_inflated_voxel_layer
{

struct InflationBounds
{
  bool valid{false};
  double min_x{0.0};
  double min_y{0.0};
  double max_x{0.0};
  double max_y{0.0};
};

unsigned int cellInflationRadius(double inflation_radius, double resolution);

unsigned char computeInflationCost(
  double distance_m, double inscribed_radius, double cost_scaling_factor);

InflationBounds inflateLethalCells(
  unsigned char * costmap,
  unsigned int size_x,
  unsigned int size_y,
  double resolution,
  double origin_x,
  double origin_y,
  double inflation_radius,
  double inscribed_radius,
  double cost_scaling_factor);

void touchBounds(
  const InflationBounds & bounds,
  double * min_x,
  double * min_y,
  double * max_x,
  double * max_y);

class ConeInflatedVoxelLayer : public nav2_costmap_2d::NonPersistentVoxelLayer
{
public:
  ConeInflatedVoxelLayer() = default;
  ~ConeInflatedVoxelLayer() override = default;

  void onInitialize() override;
  void activate() override;
  void deactivate() override;

  void updateBounds(
    double robot_x,
    double robot_y,
    double robot_yaw,
    double * min_x,
    double * min_y,
    double * max_x,
    double * max_y) override;

  void updateCosts(
    nav2_costmap_2d::Costmap2D & master_grid,
    int min_i,
    int min_j,
    int max_i,
    int max_j) override;

private:
  rcl_interfaces::msg::SetParametersResult onParametersChanged(
    const std::vector<rclcpp::Parameter> & parameters);
  void publishCompletedStatus();

  double inflation_radius_{0.60};
  double cost_scaling_factor_{2.0};
  InflationBounds halo_bounds_;

  std::mutex requested_state_mutex_;
  bool requested_enabled_{true};
  std::uint64_t requested_revision_{0};

  bool cycle_enabled_{true};
  std::uint64_t cycle_revision_{0};
  bool completed_status_pending_{false};
  bool completed_enabled_{true};
  std::uint64_t completed_revision_{0};
  std::uint64_t status_sequence_{0};

  rclcpp::node_interfaces::OnSetParametersCallbackHandle::SharedPtr parameter_callback_handle_;
  rclcpp_lifecycle::LifecyclePublisher<std_msgs::msg::String>::SharedPtr status_publisher_;
};

}  // namespace cone_inflated_voxel_layer

#endif  // CONE_INFLATED_VOXEL_LAYER__CONE_INFLATED_VOXEL_LAYER_HPP_
