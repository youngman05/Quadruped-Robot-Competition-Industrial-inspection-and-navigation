#include <atomic>
#include <cctype>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <nav_msgs/msg/odometry.hpp>
#include <nlohmann/json.hpp>
#include <rclcpp/rclcpp.hpp>
#include <realsense2_camera_msgs/msg/metadata.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <sensor_msgs/msg/imu.hpp>

namespace
{
using SteadyClock = std::chrono::steady_clock;

struct Sample
{
  std::string category;
  std::string stream;
  std::int64_t source_stamp_ns;
  std::int64_t arrival_monotonic_ns;
  std::optional<std::int64_t> frame_counter;
  std::string counter_key;
};

std::int64_t stamp_to_ns(const builtin_interfaces::msg::Time & stamp)
{
  return static_cast<std::int64_t>(stamp.sec) * 1000000000LL + stamp.nanosec;
}

std::int64_t monotonic_ns()
{
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
    SteadyClock::now().time_since_epoch()).count();
}

std::string normalize_key(const std::string & key)
{
  std::string normalized;
  bool previous_separator = false;
  for (const unsigned char character : key) {
    if (std::isalnum(character)) {
      normalized.push_back(static_cast<char>(std::tolower(character)));
      previous_separator = false;
    } else if (!normalized.empty() && !previous_separator) {
      normalized.push_back('_');
      previous_separator = true;
    }
  }
  while (!normalized.empty() && normalized.back() == '_') {
    normalized.pop_back();
  }
  return normalized;
}

std::optional<std::int64_t> json_integer(const nlohmann::json & value)
{
  if (value.is_number_integer()) {
    return value.get<std::int64_t>();
  }
  if (value.is_number_unsigned()) {
    return static_cast<std::int64_t>(value.get<std::uint64_t>());
  }
  if (value.is_string()) {
    const std::string text = value.get<std::string>();
    const auto first_digit = text.find_first_of("-0123456789");
    if (first_digit == std::string::npos) {
      return std::nullopt;
    }
    std::size_t consumed = 0;
    try {
      const auto parsed = std::stoll(text.substr(first_digit), &consumed);
      return consumed > 0 ? std::optional<std::int64_t>(parsed) : std::nullopt;
    } catch (const std::exception &) {
      return std::nullopt;
    }
  }
  return std::nullopt;
}

std::optional<std::int64_t> find_counter(
  const nlohmann::json & value, const std::string & wanted_key)
{
  if (value.is_object()) {
    for (const auto & [key, child] : value.items()) {
      if (normalize_key(key) == wanted_key) {
        const auto parsed = json_integer(child);
        if (parsed.has_value()) {
          return parsed;
        }
      }
    }
    for (const auto & [key, child] : value.items()) {
      static_cast<void>(key);
      const auto nested = find_counter(child, wanted_key);
      if (nested.has_value()) {
        return nested;
      }
    }
  } else if (value.is_array()) {
    for (const auto & child : value) {
      const auto nested = find_counter(child, wanted_key);
      if (nested.has_value()) {
        return nested;
      }
    }
  }
  return std::nullopt;
}

std::pair<std::optional<std::int64_t>, std::string> parse_frame_counter(
  const std::string & json_data)
{
  try {
    const auto payload = nlohmann::json::parse(json_data);
    const auto hardware_counter = find_counter(payload, "frame_counter");
    if (hardware_counter.has_value()) {
      return {hardware_counter, "frame_counter"};
    }
    const auto frame_number = find_counter(payload, "frame_number");
    return {frame_number, frame_number.has_value() ? "frame_number" : ""};
  } catch (const nlohmann::json::exception &) {
    return {std::nullopt, ""};
  }
}
}  // namespace

class FrameProbeNode : public rclcpp::Node
{
public:
  FrameProbeNode()
  : Node("ros_realsense_frame_probe")
  {
    duration_s_ = declare_parameter<double>("duration_s", 120.0);
    warmup_s_ = declare_parameter<double>("warmup_s", 3.0);
    output_csv_ = declare_parameter<std::string>("output_csv", "/tmp/ros_frame_counter_raw.csv");
    const auto qos_depth = declare_parameter<int>("qos_depth", 64);
    if (duration_s_ <= 0.0 || warmup_s_ < 0.0 || qos_depth <= 0) {
      throw std::invalid_argument("duration_s and qos_depth must be positive; warmup_s must be nonnegative");
    }

    callback_group_ = create_callback_group(rclcpp::CallbackGroupType::Reentrant);
    rclcpp::SubscriptionOptions subscription_options;
    subscription_options.callback_group = callback_group_;
    auto qos = rclcpp::SensorDataQoS().keep_last(static_cast<std::size_t>(qos_depth));
    infra1_sub_ = create_subscription<sensor_msgs::msg::Image>(
      declare_parameter<std::string>("infra1_topic", "/camera/infra1/image_rect_raw"), qos,
      [this](sensor_msgs::msg::Image::ConstSharedPtr message) {
        record_message("infra1", message->header.stamp);
      }, subscription_options);
    infra2_sub_ = create_subscription<sensor_msgs::msg::Image>(
      declare_parameter<std::string>("infra2_topic", "/camera/infra2/image_rect_raw"), qos,
      [this](sensor_msgs::msg::Image::ConstSharedPtr message) {
        record_message("infra2", message->header.stamp);
      }, subscription_options);
    imu_sub_ = create_subscription<sensor_msgs::msg::Imu>(
      declare_parameter<std::string>("imu_topic", "/camera/imu"), qos,
      [this](sensor_msgs::msg::Imu::ConstSharedPtr message) {
        record_message("imu", message->header.stamp);
      }, subscription_options);

    const auto odometry_topic = declare_parameter<std::string>("odometry_topic", "");
    if (!odometry_topic.empty()) {
      odometry_sub_ = create_subscription<nav_msgs::msg::Odometry>(
        odometry_topic, qos,
        [this](nav_msgs::msg::Odometry::ConstSharedPtr message) {
          record_message("odometry", message->header.stamp);
        }, subscription_options);
    }

    add_metadata_subscription(
      "infra1", declare_parameter<std::string>(
        "infra1_metadata_topic", "/camera/infra1/metadata"), qos);
    add_metadata_subscription(
      "infra2", declare_parameter<std::string>(
        "infra2_metadata_topic", "/camera/infra2/metadata"), qos);
    add_metadata_subscription(
      "accel", declare_parameter<std::string>(
        "accel_metadata_topic", "/camera/accel/metadata"), qos);
    add_metadata_subscription(
      "gyro", declare_parameter<std::string>(
        "gyro_metadata_topic", "/camera/gyro/metadata"), qos);

    warmup_timer_ = create_wall_timer(
      std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::duration<double>(warmup_s_)),
      [this]() {
        warmup_timer_->cancel();
        capture_enabled_.store(true);
        RCLCPP_INFO(get_logger(), "Capture started for %.3f seconds", duration_s_);
        capture_timer_ = create_wall_timer(
          std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::duration<double>(duration_s_)),
          [this]() {finish();});
      });
  }

private:
  void record_message(const std::string & stream, const builtin_interfaces::msg::Time & stamp)
  {
    if (!capture_enabled_.load()) {
      return;
    }
    append({"message", stream, stamp_to_ns(stamp), monotonic_ns(), std::nullopt, ""});
  }

  void add_metadata_subscription(
    const std::string & stream, const std::string & topic, const rclcpp::QoS & qos)
  {
    rclcpp::SubscriptionOptions subscription_options;
    subscription_options.callback_group = callback_group_;
    metadata_subscriptions_.push_back(
      create_subscription<realsense2_camera_msgs::msg::Metadata>(
        topic, qos,
        [this, stream](realsense2_camera_msgs::msg::Metadata::ConstSharedPtr message) {
          if (!capture_enabled_.load()) {
            return;
          }
          const auto parsed_counter = parse_frame_counter(message->json_data);
          append({
            "metadata_counter", stream, stamp_to_ns(message->header.stamp), monotonic_ns(),
            parsed_counter.first, parsed_counter.second});
        }, subscription_options));
  }

  void append(Sample sample)
  {
    std::lock_guard<std::mutex> lock(samples_mutex_);
    samples_.push_back(std::move(sample));
  }

  void finish()
  {
    if (finished_.exchange(true)) {
      return;
    }
    capture_enabled_.store(false);
    capture_timer_->cancel();
    write_csv();
    rclcpp::shutdown();
  }

  void write_csv()
  {
    const std::filesystem::path output_path(output_csv_);
    if (output_path.has_parent_path()) {
      std::filesystem::create_directories(output_path.parent_path());
    }
    std::ofstream output(output_path);
    if (!output) {
      throw std::runtime_error("Cannot open output CSV: " + output_csv_);
    }
    output << "category,stream,source_stamp_ns,arrival_monotonic_ns,frame_counter,counter_key\n";
    std::lock_guard<std::mutex> lock(samples_mutex_);
    for (const auto & sample : samples_) {
      output << sample.category << ',' << sample.stream << ',' << sample.source_stamp_ns << ','
             << sample.arrival_monotonic_ns << ',';
      if (sample.frame_counter.has_value()) {
        output << *sample.frame_counter;
      }
      output << ',' << sample.counter_key << '\n';
    }
    RCLCPP_INFO(get_logger(), "Wrote %zu samples to %s", samples_.size(), output_csv_.c_str());
  }

  double duration_s_;
  double warmup_s_;
  std::string output_csv_;
  std::atomic<bool> capture_enabled_{false};
  std::atomic<bool> finished_{false};
  std::mutex samples_mutex_;
  std::vector<Sample> samples_;
  rclcpp::CallbackGroup::SharedPtr callback_group_;
  rclcpp::TimerBase::SharedPtr warmup_timer_;
  rclcpp::TimerBase::SharedPtr capture_timer_;
  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr infra1_sub_;
  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr infra2_sub_;
  rclcpp::Subscription<sensor_msgs::msg::Imu>::SharedPtr imu_sub_;
  rclcpp::Subscription<nav_msgs::msg::Odometry>::SharedPtr odometry_sub_;
  std::vector<rclcpp::Subscription<realsense2_camera_msgs::msg::Metadata>::SharedPtr>
    metadata_subscriptions_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<FrameProbeNode>();
  rclcpp::executors::MultiThreadedExecutor executor(rclcpp::ExecutorOptions(), 4);
  executor.add_node(node);
  executor.spin();
  return 0;
}
