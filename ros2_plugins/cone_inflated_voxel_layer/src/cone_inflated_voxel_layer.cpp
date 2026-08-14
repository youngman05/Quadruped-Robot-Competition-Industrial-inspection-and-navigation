#include "cone_inflated_voxel_layer/cone_inflated_voxel_layer.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <utility>

#include "nav2_costmap_2d/cost_values.hpp"
#include "pluginlib/class_list_macros.hpp"

namespace cone_inflated_voxel_layer
{

unsigned int cellInflationRadius(double inflation_radius, double resolution)
{
  if (inflation_radius <= 0.0 || resolution <= 0.0) {
    return 0;
  }
  return static_cast<unsigned int>(std::ceil(inflation_radius / resolution));
}

unsigned char computeInflationCost(
  double distance_m, double inscribed_radius, double cost_scaling_factor)
{
  if (distance_m <= 0.0) {
    return nav2_costmap_2d::LETHAL_OBSTACLE;
  }
  if (distance_m <= inscribed_radius) {
    return nav2_costmap_2d::INSCRIBED_INFLATED_OBSTACLE;
  }
  const double factor = std::exp(
    -cost_scaling_factor * (distance_m - inscribed_radius));
  return static_cast<unsigned char>(
    (nav2_costmap_2d::INSCRIBED_INFLATED_OBSTACLE - 1) * factor);
}

InflationBounds inflateLethalCells(
  unsigned char * costmap,
  unsigned int size_x,
  unsigned int size_y,
  double resolution,
  double origin_x,
  double origin_y,
  double inflation_radius,
  double inscribed_radius,
  double cost_scaling_factor)
{
  InflationBounds bounds;
  if (
    costmap == nullptr || size_x == 0 || size_y == 0 || resolution <= 0.0 ||
    inflation_radius < 0.0 || inscribed_radius < 0.0 || cost_scaling_factor <= 0.0)
  {
    return bounds;
  }

  std::vector<std::pair<unsigned int, unsigned int>> lethal_cells;
  lethal_cells.reserve(size_x * size_y / 32U + 1U);
  for (unsigned int y = 0; y < size_y; ++y) {
    for (unsigned int x = 0; x < size_x; ++x) {
      if (costmap[y * size_x + x] == nav2_costmap_2d::LETHAL_OBSTACLE) {
        lethal_cells.emplace_back(x, y);
      }
    }
  }

  const unsigned int cell_radius = cellInflationRadius(inflation_radius, resolution);
  for (const auto & source : lethal_cells) {
    const double world_x = origin_x + (static_cast<double>(source.first) + 0.5) * resolution;
    const double world_y = origin_y + (static_cast<double>(source.second) + 0.5) * resolution;
    if (!bounds.valid) {
      bounds.valid = true;
      bounds.min_x = world_x - inflation_radius;
      bounds.min_y = world_y - inflation_radius;
      bounds.max_x = world_x + inflation_radius;
      bounds.max_y = world_y + inflation_radius;
    } else {
      bounds.min_x = std::min(bounds.min_x, world_x - inflation_radius);
      bounds.min_y = std::min(bounds.min_y, world_y - inflation_radius);
      bounds.max_x = std::max(bounds.max_x, world_x + inflation_radius);
      bounds.max_y = std::max(bounds.max_y, world_y + inflation_radius);
    }

    const int source_x = static_cast<int>(source.first);
    const int source_y = static_cast<int>(source.second);
    const int radius = static_cast<int>(cell_radius);
    for (int dy = -radius; dy <= radius; ++dy) {
      const int target_y = source_y + dy;
      if (target_y < 0 || target_y >= static_cast<int>(size_y)) {
        continue;
      }
      for (int dx = -radius; dx <= radius; ++dx) {
        const int target_x = source_x + dx;
        if (target_x < 0 || target_x >= static_cast<int>(size_x)) {
          continue;
        }
        const double distance_m = std::hypot(
          static_cast<double>(dx), static_cast<double>(dy)) * resolution;
        if (distance_m > inflation_radius) {
          continue;
        }
        const unsigned char cost = computeInflationCost(
          distance_m, inscribed_radius, cost_scaling_factor);
        const unsigned int index =
          static_cast<unsigned int>(target_y) * size_x + static_cast<unsigned int>(target_x);
        const unsigned char old_cost = costmap[index];
        if (
          old_cost != nav2_costmap_2d::LETHAL_OBSTACLE &&
          (old_cost == nav2_costmap_2d::NO_INFORMATION || old_cost < cost))
        {
          costmap[index] = cost;
        }
      }
    }
  }
  return bounds;
}

void touchBounds(
  const InflationBounds & bounds,
  double * min_x,
  double * min_y,
  double * max_x,
  double * max_y)
{
  if (!bounds.valid) {
    return;
  }
  *min_x = std::min(*min_x, bounds.min_x);
  *min_y = std::min(*min_y, bounds.min_y);
  *max_x = std::max(*max_x, bounds.max_x);
  *max_y = std::max(*max_y, bounds.max_y);
}

void ConeInflatedVoxelLayer::onInitialize()
{
  nav2_costmap_2d::NonPersistentVoxelLayer::onInitialize();
  auto node = node_;
  if (!node) {
    throw std::runtime_error("costmap lifecycle node expired during cone layer initialization");
  }

  declareParameter("inflation_radius", rclcpp::ParameterValue(0.60));
  declareParameter("cost_scaling_factor", rclcpp::ParameterValue(2.0));
  const std::string inflation_radius_name = getFullName("inflation_radius");
  const std::string cost_scaling_factor_name = getFullName("cost_scaling_factor");
  node->get_parameter(inflation_radius_name, inflation_radius_);
  node->get_parameter(cost_scaling_factor_name, cost_scaling_factor_);
  if (inflation_radius_ < 0.0 || cost_scaling_factor_ <= 0.0) {
    throw std::runtime_error("cone inflation_radius must be non-negative and cost_scaling_factor positive");
  }

  {
    std::lock_guard<std::mutex> lock(requested_state_mutex_);
    requested_enabled_ = enabled_;
  }
  cycle_enabled_ = enabled_;
  completed_enabled_ = enabled_;

  auto status_qos = rclcpp::QoS(rclcpp::KeepLast(1));
  status_qos.reliable();
  status_qos.transient_local();
  status_publisher_ = node->create_publisher<std_msgs::msg::String>(
    name_ + "/applied_status", status_qos);
  parameter_callback_handle_ = node->add_on_set_parameters_callback(
    std::bind(
      &ConeInflatedVoxelLayer::onParametersChanged,
      this,
      std::placeholders::_1));

  RCLCPP_INFO(
    node->get_logger(),
    "%s initialized with source-local inflation radius %.3f m and factor %.3f",
    name_.c_str(), inflation_radius_, cost_scaling_factor_);
}

void ConeInflatedVoxelLayer::activate()
{
  nav2_costmap_2d::ObstacleLayer::activate();
  status_publisher_->on_activate();
}

void ConeInflatedVoxelLayer::deactivate()
{
  status_publisher_->on_deactivate();
  nav2_costmap_2d::ObstacleLayer::deactivate();
}

void ConeInflatedVoxelLayer::updateBounds(
  double robot_x,
  double robot_y,
  double robot_yaw,
  double * min_x,
  double * min_y,
  double * max_x,
  double * max_y)
{
  publishCompletedStatus();
  touchBounds(halo_bounds_, min_x, min_y, max_x, max_y);

  {
    std::lock_guard<std::mutex> lock(requested_state_mutex_);
    cycle_enabled_ = requested_enabled_;
    cycle_revision_ = requested_revision_;
  }
  enabled_ = cycle_enabled_;

  nav2_costmap_2d::NonPersistentVoxelLayer::updateBounds(
    robot_x, robot_y, robot_yaw, min_x, min_y, max_x, max_y);

  InflationBounds current_bounds;
  if (enabled_) {
    current_bounds = inflateLethalCells(
      costmap_,
      size_x_,
      size_y_,
      resolution_,
      origin_x_,
      origin_y_,
      inflation_radius_,
      layered_costmap_->getInscribedRadius(),
      cost_scaling_factor_);
    touchBounds(current_bounds, min_x, min_y, max_x, max_y);
  }
  halo_bounds_ = current_bounds;
}

void ConeInflatedVoxelLayer::updateCosts(
  nav2_costmap_2d::Costmap2D & master_grid,
  int min_i,
  int min_j,
  int max_i,
  int max_j)
{
  nav2_costmap_2d::ObstacleLayer::updateCosts(
    master_grid, min_i, min_j, max_i, max_j);
  completed_enabled_ = cycle_enabled_;
  completed_revision_ = cycle_revision_;
  completed_status_pending_ = true;
}

rcl_interfaces::msg::SetParametersResult ConeInflatedVoxelLayer::onParametersChanged(
  const std::vector<rclcpp::Parameter> & parameters)
{
  rcl_interfaces::msg::SetParametersResult result;
  result.successful = true;
  bool found_enabled = false;
  bool next_enabled = false;
  const std::string enabled_name = getFullName("enabled");
  for (const auto & parameter : parameters) {
    if (parameter.get_name() != enabled_name) {
      continue;
    }
    if (parameter.get_type() != rclcpp::ParameterType::PARAMETER_BOOL) {
      result.successful = false;
      result.reason = enabled_name + " must be a bool";
      return result;
    }
    found_enabled = true;
    next_enabled = parameter.as_bool();
  }
  if (found_enabled) {
    std::lock_guard<std::mutex> lock(requested_state_mutex_);
    requested_enabled_ = next_enabled;
    ++requested_revision_;
  }
  return result;
}

void ConeInflatedVoxelLayer::publishCompletedStatus()
{
  if (!completed_status_pending_) {
    return;
  }
  bool requested_enabled;
  {
    std::lock_guard<std::mutex> lock(requested_state_mutex_);
    requested_enabled = requested_enabled_;
  }
  std_msgs::msg::String message;
  std::ostringstream json;
  json << std::boolalpha
       << "{\"plugin\":\"" << name_ << "\""
       << ",\"requested_enabled\":" << requested_enabled
       << ",\"applied_enabled\":" << completed_enabled_
       << ",\"applied_revision\":" << completed_revision_
       << ",\"status_sequence\":" << ++status_sequence_
       << "}";
  message.data = json.str();
  status_publisher_->publish(message);
  completed_status_pending_ = false;
}

}  // namespace cone_inflated_voxel_layer

PLUGINLIB_EXPORT_CLASS(
  cone_inflated_voxel_layer::ConeInflatedVoxelLayer,
  nav2_costmap_2d::Layer)
