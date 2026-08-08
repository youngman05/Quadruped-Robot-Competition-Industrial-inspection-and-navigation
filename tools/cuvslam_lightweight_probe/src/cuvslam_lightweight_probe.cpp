#include <algorithm>
#include <cctype>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <numeric>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <nav_msgs/msg/odometry.hpp>
#include <nlohmann/json.hpp>
#include <rclcpp/rclcpp.hpp>
#include <realsense2_camera_msgs/msg/metadata.hpp>
#include <rmw/types.h>
#include <sensor_msgs/msg/imu.hpp>
#include <std_msgs/msg/string.hpp>

namespace
{
using SteadyClock = std::chrono::steady_clock;
using SystemClock = std::chrono::system_clock;

std::int64_t monotonic_ns()
{
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
    SteadyClock::now().time_since_epoch()).count();
}

std::int64_t realtime_ns()
{
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
    SystemClock::now().time_since_epoch()).count();
}

std::int64_t process_cpu_ns()
{
  timespec value{};
  if (clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &value) != 0) {
    throw std::runtime_error("clock_gettime(CLOCK_PROCESS_CPUTIME_ID) failed");
  }
  return static_cast<std::int64_t>(value.tv_sec) * 1000000000LL + value.tv_nsec;
}

std::int64_t stamp_to_ns(const builtin_interfaces::msg::Time & stamp)
{
  return static_cast<std::int64_t>(stamp.sec) * 1000000000LL + stamp.nanosec;
}

std::string lowercase(std::string value)
{
  std::transform(
    value.begin(), value.end(), value.begin(),
    [](unsigned char character) {return static_cast<char>(std::tolower(character));});
  return value;
}

std::optional<std::int64_t> parse_integer_text(const std::string & text)
{
  const auto first_digit = text.find_first_of("-0123456789");
  if (first_digit == std::string::npos) {
    return std::nullopt;
  }
  try {
    std::size_t consumed = 0;
    const auto parsed = std::stoll(text.substr(first_digit), &consumed);
    return consumed > 0 ? std::optional<std::int64_t>(parsed) : std::nullopt;
  } catch (const std::exception &) {
    return std::nullopt;
  }
}

std::string normalize_key(const std::string & key)
{
  std::string normalized;
  bool separator = false;
  for (const unsigned char character : key) {
    if (std::isalnum(character)) {
      normalized.push_back(static_cast<char>(std::tolower(character)));
      separator = false;
    } else if (!normalized.empty() && !separator) {
      normalized.push_back('_');
      separator = true;
    }
  }
  while (!normalized.empty() && normalized.back() == '_') {
    normalized.pop_back();
  }
  return normalized;
}

class FrameCounterSax : public nlohmann::json_sax<nlohmann::json>
{
public:
  using json = nlohmann::json;
  using number_float_t = json::number_float_t;
  using number_integer_t = json::number_integer_t;
  using number_unsigned_t = json::number_unsigned_t;
  using string_t = json::string_t;

  bool null() override {return finish_scalar();}
  bool boolean(bool) override {return finish_scalar();}

  bool number_integer(number_integer_t value) override
  {
    capture(value);
    return finish_scalar();
  }

  bool number_unsigned(number_unsigned_t value) override
  {
    if (value <= static_cast<number_unsigned_t>(std::numeric_limits<std::int64_t>::max())) {
      capture(static_cast<std::int64_t>(value));
    }
    return finish_scalar();
  }

  bool number_float(number_float_t, const string_t &) override {return finish_scalar();}

  bool string(string_t & value) override
  {
    const auto parsed = parse_integer_text(value);
    if (parsed.has_value()) {
      capture(*parsed);
    }
    return finish_scalar();
  }

  bool start_object(std::size_t) override {return finish_scalar();}
  bool end_object() override {return true;}
  bool start_array(std::size_t) override {return finish_scalar();}
  bool end_array() override {return true;}

  bool key(string_t & value) override
  {
    current_key_ = normalize_key(value);
    return true;
  }

  bool parse_error(
    std::size_t, const std::string &, const nlohmann::detail::exception &) override
  {
    return false;
  }

  std::optional<std::int64_t> value() const
  {
    return frame_counter_.has_value() ? frame_counter_ : frame_number_;
  }

private:
  bool finish_scalar()
  {
    current_key_.clear();
    return true;
  }

  void capture(std::int64_t value)
  {
    if (current_key_ == "frame_counter") {
      frame_counter_ = value;
    } else if (current_key_ == "frame_number" && !frame_number_.has_value()) {
      frame_number_ = value;
    }
  }

  std::string current_key_;
  std::optional<std::int64_t> frame_counter_;
  std::optional<std::int64_t> frame_number_;
};

std::optional<std::int64_t> parse_frame_counter(const std::string & json_data)
{
  FrameCounterSax sax;
  return nlohmann::json::sax_parse(json_data, &sax) ? sax.value() : std::nullopt;
}

std::size_t checked_capacity(int value)
{
  if (value <= 0) {
    throw std::invalid_argument("anomaly_capacity must be positive");
  }
  return static_cast<std::size_t>(value);
}

struct Anomaly
{
  std::string kind;
  std::string stream;
  std::string detail;
  std::int64_t source_ns{0};
  std::int64_t monotonic_ns{0};
  std::int64_t realtime_ns{0};
};

class AnomalyRing
{
public:
  explicit AnomalyRing(std::size_t capacity)
  : data_(capacity)
  {
    if (capacity == 0U) {
      throw std::invalid_argument("anomaly capacity must be positive");
    }
  }

  void add(Anomaly anomaly)
  {
    if (size_ < data_.size()) {
      data_[size_] = std::move(anomaly);
      ++size_;
      return;
    }
    data_[next_] = std::move(anomaly);
    next_ = (next_ + 1U) % data_.size();
    ++overwritten_;
  }

  std::vector<Anomaly> ordered() const
  {
    std::vector<Anomaly> result;
    result.reserve(size_);
    if (size_ < data_.size()) {
      result.insert(result.end(), data_.begin(), data_.begin() + size_);
      return result;
    }
    result.insert(result.end(), data_.begin() + next_, data_.end());
    result.insert(result.end(), data_.begin(), data_.begin() + next_);
    return result;
  }

  std::size_t overwritten() const {return overwritten_;}

private:
  std::vector<Anomaly> data_;
  std::size_t size_{0};
  std::size_t next_{0};
  std::size_t overwritten_{0};
};

class StreamStats
{
public:
  StreamStats() = default;
  StreamStats(std::string name, double expected_hz, AnomalyRing * anomalies)
  : name_(std::move(name)), expected_period_ns_(1.0e9 / expected_hz), anomalies_(anomalies)
  {}

  void record(std::int64_t source_ns, std::int64_t arrival_ns, std::int64_t wall_ns)
  {
    if (count_ > 0U) {
      const auto source_delta = source_ns - last_source_ns_;
      const auto arrival_delta = arrival_ns - last_arrival_ns_;
      max_source_delta_ns_ = std::max(max_source_delta_ns_, source_delta);
      max_arrival_delta_ns_ = std::max(max_arrival_delta_ns_, arrival_delta);
      if (source_delta <= 0) {
        ++nonmonotonic_source_count_;
        anomalies_->add({
          "nonmonotonic_source", name_, "source timestamp did not increase",
          source_ns, arrival_ns, wall_ns});
      } else if (static_cast<double>(source_delta) > expected_period_ns_ * 2.5) {
        ++gap_over_2_5x_count_;
        estimated_missing_ += std::max<std::int64_t>(
          0, static_cast<std::int64_t>(std::llround(source_delta / expected_period_ns_)) - 1);
        std::ostringstream detail;
        detail << std::fixed << std::setprecision(3)
               << "source_delta_ms=" << source_delta / 1.0e6;
        anomalies_->add({"stream_gap", name_, detail.str(), source_ns, arrival_ns, wall_ns});
      }
    } else {
      first_source_ns_ = source_ns;
    }
    ++count_;
    last_source_ns_ = source_ns;
    last_arrival_ns_ = arrival_ns;
  }

  nlohmann::json report(double expected_hz) const
  {
    nlohmann::json result = {
      {"count", count_},
      {"expected_hz", expected_hz},
      {"gap_over_2_5x_count", gap_over_2_5x_count_},
      {"estimated_missing_samples", estimated_missing_},
      {"nonmonotonic_source_count", nonmonotonic_source_count_},
      {"max_source_delta_ms", max_source_delta_ns_ / 1.0e6},
      {"max_arrival_delta_ms", max_arrival_delta_ns_ / 1.0e6}
    };
    if (count_ >= 2U && last_source_ns_ > first_source_ns_) {
      result["observed_hz"] =
        static_cast<double>(count_ - 1U) * 1.0e9 / (last_source_ns_ - first_source_ns_);
    } else {
      result["observed_hz"] = nullptr;
    }
    return result;
  }

  std::size_t count() const {return count_;}
  std::size_t gaps() const {return gap_over_2_5x_count_;}
  std::size_t nonmonotonic() const {return nonmonotonic_source_count_;}

private:
  std::string name_;
  double expected_period_ns_{1.0};
  AnomalyRing * anomalies_{nullptr};
  std::size_t count_{0};
  std::size_t gap_over_2_5x_count_{0};
  std::size_t nonmonotonic_source_count_{0};
  std::int64_t estimated_missing_{0};
  std::int64_t first_source_ns_{0};
  std::int64_t last_source_ns_{0};
  std::int64_t last_arrival_ns_{0};
  std::int64_t max_source_delta_ns_{0};
  std::int64_t max_arrival_delta_ns_{0};
};

class CounterStats
{
public:
  CounterStats() = default;
  CounterStats(std::string name, AnomalyRing * anomalies)
  : name_(std::move(name)), anomalies_(anomalies)
  {}

  void record(
    const std::optional<std::int64_t> & counter, std::int64_t source_ns,
    std::int64_t arrival_ns, std::int64_t wall_ns)
  {
    ++message_count_;
    if (!counter.has_value()) {
      ++parse_error_count_;
      return;
    }
    ++valid_count_;
    if (last_counter_.has_value()) {
      auto delta = *counter - *last_counter_;
      if (delta < 0 && *last_counter_ > 0xF0000000LL && *counter < 0x0FFFFFFFLL) {
        delta = (1LL << 32) - *last_counter_ + *counter;
      }
      if (delta == 0) {
        ++duplicate_count_;
      } else if (delta < 0) {
        ++nonmonotonic_count_;
        anomalies_->add({
          "counter_nonmonotonic", name_, "hardware frame counter decreased",
          source_ns, arrival_ns, wall_ns});
      } else if (delta > 1) {
        const auto missing = delta - 1;
        missing_total_ += missing;
        ++gap_event_count_;
        anomalies_->add({
          "counter_gap", name_, "missing=" + std::to_string(missing),
          source_ns, arrival_ns, wall_ns});
      }
    }
    last_counter_ = counter;
  }

  nlohmann::json report() const
  {
    return {
      {"message_count", message_count_},
      {"valid_counter_count", valid_count_},
      {"parse_error_count", parse_error_count_},
      {"missing_total", missing_total_},
      {"gap_event_count", gap_event_count_},
      {"duplicate_count", duplicate_count_},
      {"nonmonotonic_count", nonmonotonic_count_}
    };
  }

  std::size_t valid_count() const {return valid_count_;}
  std::int64_t missing_total() const {return missing_total_;}
  std::size_t nonmonotonic() const {return nonmonotonic_count_;}

private:
  std::string name_;
  AnomalyRing * anomalies_{nullptr};
  std::optional<std::int64_t> last_counter_;
  std::size_t message_count_{0};
  std::size_t valid_count_{0};
  std::size_t parse_error_count_{0};
  std::size_t duplicate_count_{0};
  std::size_t nonmonotonic_count_{0};
  std::size_t gap_event_count_{0};
  std::int64_t missing_total_{0};
};

struct CpuTicks
{
  std::uint64_t total{0};
  std::uint64_t idle{0};
};

std::map<std::string, CpuTicks> read_cpu_ticks()
{
  std::ifstream input("/proc/stat");
  if (!input) {
    throw std::runtime_error("cannot read /proc/stat");
  }
  std::map<std::string, CpuTicks> result;
  std::string line;
  while (std::getline(input, line)) {
    std::istringstream parser(line);
    std::string name;
    parser >> name;
    if (name.rfind("cpu", 0) != 0) {
      break;
    }
    std::vector<std::uint64_t> values;
    std::uint64_t value = 0;
    while (parser >> value) {
      values.push_back(value);
    }
    if (values.size() < 4U) {
      continue;
    }
    const auto used_fields = std::min<std::size_t>(values.size(), 8U);
    const auto total = std::accumulate(values.begin(), values.begin() + used_fields, 0ULL);
    const auto idle = values[3] + (values.size() > 4U ? values[4] : 0ULL);
    result[name] = {total, idle};
  }
  return result;
}

double percentile(std::vector<double> values, double percent)
{
  if (values.empty()) {
    return 0.0;
  }
  std::sort(values.begin(), values.end());
  const auto rank = (values.size() - 1U) * percent / 100.0;
  const auto lower = static_cast<std::size_t>(std::floor(rank));
  const auto upper = static_cast<std::size_t>(std::ceil(rank));
  if (lower == upper) {
    return values[lower];
  }
  const auto weight = rank - static_cast<double>(lower);
  return values[lower] * (1.0 - weight) + values[upper] * weight;
}

nlohmann::json metric_report(const std::vector<double> & values)
{
  if (values.empty()) {
    return {
      {"count", 0}, {"average", nullptr}, {"p95", nullptr},
      {"p99", nullptr}, {"max", nullptr}
    };
  }
  const auto average = std::accumulate(values.begin(), values.end(), 0.0) / values.size();
  return {
    {"count", values.size()},
    {"average", average},
    {"p95", percentile(values, 95.0)},
    {"p99", percentile(values, 99.0)},
    {"max", *std::max_element(values.begin(), values.end())}
  };
}

std::string reliability_name(rmw_qos_reliability_policy_t policy)
{
  switch (policy) {
    case RMW_QOS_POLICY_RELIABILITY_RELIABLE:
      return "reliable";
    case RMW_QOS_POLICY_RELIABILITY_BEST_EFFORT:
      return "best_effort";
    case RMW_QOS_POLICY_RELIABILITY_SYSTEM_DEFAULT:
      return "system_default";
    default:
      return "unknown";
  }
}

std::string durability_name(rmw_qos_durability_policy_t policy)
{
  switch (policy) {
    case RMW_QOS_POLICY_DURABILITY_TRANSIENT_LOCAL:
      return "transient_local";
    case RMW_QOS_POLICY_DURABILITY_VOLATILE:
      return "volatile";
    case RMW_QOS_POLICY_DURABILITY_SYSTEM_DEFAULT:
      return "system_default";
    default:
      return "unknown";
  }
}
}  // namespace

class CuvslamLightweightProbe : public rclcpp::Node
{
public:
  explicit CuvslamLightweightProbe(const rclcpp::NodeOptions & options)
  : Node("cuvslam_lightweight_probe", options),
    subscribe_topics_(declare_parameter<bool>("subscribe_topics", true)),
    duration_s_(declare_parameter<double>("duration_s", 120.0)),
    warmup_s_(declare_parameter<double>("warmup_s", 3.0)),
    sample_interval_s_(declare_parameter<double>("sample_interval_s", 1.0)),
    output_json_(declare_parameter<std::string>("output_json", "/tmp/cuvslam_observer.json")),
    launch_log_path_(declare_parameter<std::string>("launch_log_path", "/logs/launch.log")),
    infra_hz_(declare_parameter<double>("infra_hz", 30.0)),
    imu_hz_(declare_parameter<double>("imu_hz", 200.0)),
    odometry_hz_(declare_parameter<double>("odometry_hz", 30.0)),
    qos_depth_(declare_parameter<int>("qos_depth", 16)),
    anomalies_(checked_capacity(declare_parameter<int>("anomaly_capacity", 256))),
    infra1_stream_("infra1_metadata", infra_hz_, &anomalies_),
    infra2_stream_("infra2_metadata", infra_hz_, &anomalies_),
    imu_stream_("imu", imu_hz_, &anomalies_),
    odometry_stream_("odometry", odometry_hz_, &anomalies_),
    infra1_counter_("infra1", &anomalies_),
    infra2_counter_("infra2", &anomalies_)
  {
    if (duration_s_ <= 0.0 || warmup_s_ < 0.0 || sample_interval_s_ <= 0.0) {
      throw std::invalid_argument("duration_s/sample_interval_s must be positive; warmup_s nonnegative");
    }
    if (infra_hz_ <= 0.0 || imu_hz_ <= 0.0 || odometry_hz_ <= 0.0) {
      throw std::invalid_argument("expected topic rates must be positive");
    }
    if (qos_depth_ < 8 || qos_depth_ > 16) {
      throw std::invalid_argument("qos_depth must be between 8 and 16");
    }

    infra1_metadata_topic_ = declare_parameter<std::string>(
      "infra1_metadata_topic", "/camera/infra1/metadata");
    infra2_metadata_topic_ = declare_parameter<std::string>(
      "infra2_metadata_topic", "/camera/infra2/metadata");
    imu_topic_ = declare_parameter<std::string>("imu_topic", "/camera/imu");
    odometry_topic_ = declare_parameter<std::string>(
      "odometry_topic", "/visual_slam/tracking/odometry");
    status_topic_ = declare_parameter<std::string>("status_topic", "/visual_slam/status");

    if (subscribe_topics_) {
      create_measurement_subscriptions();
    }
    const auto warmup_delay = std::max(0.001, warmup_s_);
    warmup_timer_ = create_wall_timer(
      std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::duration<double>(warmup_delay)),
      [this]() {begin_capture();});
  }

private:
  void create_measurement_subscriptions()
  {
    const auto qos = rclcpp::SensorDataQoS().keep_last(static_cast<std::size_t>(qos_depth_));
    infra1_metadata_sub_ = create_subscription<realsense2_camera_msgs::msg::Metadata>(
      infra1_metadata_topic_, qos,
      [this](realsense2_camera_msgs::msg::Metadata::ConstSharedPtr message) {
        record_metadata("infra1", message, infra1_stream_, infra1_counter_);
      });
    infra2_metadata_sub_ = create_subscription<realsense2_camera_msgs::msg::Metadata>(
      infra2_metadata_topic_, qos,
      [this](realsense2_camera_msgs::msg::Metadata::ConstSharedPtr message) {
        record_metadata("infra2", message, infra2_stream_, infra2_counter_);
      });
    imu_sub_ = create_subscription<sensor_msgs::msg::Imu>(
      imu_topic_, qos,
      [this](sensor_msgs::msg::Imu::ConstSharedPtr message) {
        if (capture_enabled_) {
          const auto mono = monotonic_ns();
          imu_stream_.record(stamp_to_ns(message->header.stamp), mono, realtime_ns());
        }
      });
    odometry_sub_ = create_subscription<nav_msgs::msg::Odometry>(
      odometry_topic_, qos,
      [this](nav_msgs::msg::Odometry::ConstSharedPtr message) {
        if (capture_enabled_) {
          const auto mono = monotonic_ns();
          odometry_stream_.record(stamp_to_ns(message->header.stamp), mono, realtime_ns());
        }
      });
  }

  void record_metadata(
    const std::string & name,
    const realsense2_camera_msgs::msg::Metadata::ConstSharedPtr & message,
    StreamStats & stream, CounterStats & counter)
  {
    if (!capture_enabled_) {
      return;
    }
    const auto mono = monotonic_ns();
    const auto wall = realtime_ns();
    const auto source = stamp_to_ns(message->header.stamp);
    stream.record(source, mono, wall);
    const auto parsed = parse_frame_counter(message->json_data);
    counter.record(parsed, source, mono, wall);
    static_cast<void>(name);
  }

  void inspect_status_topic()
  {
    status_graph_ = {
      {"topic", status_topic_}, {"available", false}, {"compatible", false},
      {"publishers", nlohmann::json::array()}
    };
    try {
      const auto endpoints = get_publishers_info_by_topic(status_topic_);
      for (const auto & endpoint : endpoints) {
        const auto profile = endpoint.qos_profile().get_rmw_qos_profile();
        status_graph_["publishers"].push_back({
          {"node_name", endpoint.node_name()},
          {"node_namespace", endpoint.node_namespace()},
          {"topic_type", endpoint.topic_type()},
          {"qos", {
              {"reliability", reliability_name(profile.reliability)},
              {"durability", durability_name(profile.durability)},
              {"depth", profile.depth}
            }}
        });
        status_graph_["available"] = true;
        if (endpoint.topic_type() == "std_msgs/msg/String") {
          status_graph_["compatible"] = true;
        }
      }
    } catch (const std::exception & error) {
      status_graph_["inspection_error"] = error.what();
    }

    if (subscribe_topics_ && status_graph_.value("compatible", false)) {
      const auto qos = rclcpp::QoS(rclcpp::KeepLast(qos_depth_)).best_effort();
      status_sub_ = create_subscription<std_msgs::msg::String>(
        status_topic_, qos,
        [this](std_msgs::msg::String::ConstSharedPtr message) {record_status(message->data);});
    }
  }

  void record_status(const std::string & status)
  {
    if (!capture_enabled_) {
      return;
    }
    ++status_message_count_;
    const auto normalized = lowercase(status);
    const bool lost = normalized == "lost" || normalized == "tracking_lost" ||
      normalized.find("tracking is lost") != std::string::npos ||
      normalized.find("tracking lost") != std::string::npos;
    if (lost) {
      ++status_lost_count_;
      anomalies_.add({
        "tracking_lost_status", "status", status, 0, monotonic_ns(), realtime_ns()});
    }
    if (!last_status_.empty() && status != last_status_) {
      ++status_transition_count_;
      anomalies_.add({
        "status_change", "status", last_status_ + " -> " + status,
        0, monotonic_ns(), realtime_ns()});
    }
    last_status_ = status;
  }

  void begin_capture()
  {
    warmup_timer_->cancel();
    inspect_status_topic();
    initialize_log_offset();
    previous_cpu_ticks_ = read_cpu_ticks();
    capture_started_monotonic_ns_ = monotonic_ns();
    capture_started_realtime_ns_ = realtime_ns();
    previous_cpu_sample_monotonic_ns_ = capture_started_monotonic_ns_;
    previous_process_cpu_ns_ = process_cpu_ns();
    process_cpu_started_ns_ = previous_process_cpu_ns_;
    next_cpu_due_ns_ = capture_started_monotonic_ns_ + interval_ns();
    capture_enabled_ = true;

    cpu_timer_ = create_wall_timer(
      std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::duration<double>(sample_interval_s_)),
      [this]() {sample_cpu_and_log();});
    finish_timer_ = create_wall_timer(
      std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::duration<double>(duration_s_)),
      [this]() {finish();});
    std::cout << "capture_started mode=" << (subscribe_topics_ ? "observer" : "baseline")
              << " duration_s=" << duration_s_ << " qos=BEST_EFFORT/" << qos_depth_
              << std::endl;
  }

  std::int64_t interval_ns() const
  {
    return static_cast<std::int64_t>(sample_interval_s_ * 1.0e9);
  }

  void sample_cpu_and_log()
  {
    if (!capture_enabled_) {
      return;
    }
    const auto now_mono = monotonic_ns();
    const auto now_process = process_cpu_ns();
    const auto current_ticks = read_cpu_ticks();
    const auto elapsed_ns = now_mono - previous_cpu_sample_monotonic_ns_;
    if (elapsed_ns > 0) {
      self_cpu_samples_.push_back(
        100.0 * (now_process - previous_process_cpu_ns_) / static_cast<double>(elapsed_ns));
    }
    for (const auto & [name, current] : current_ticks) {
      const auto previous = previous_cpu_ticks_.find(name);
      if (previous == previous_cpu_ticks_.end()) {
        continue;
      }
      const auto total_delta = current.total - previous->second.total;
      const auto idle_delta = current.idle - previous->second.idle;
      if (total_delta > 0 && idle_delta <= total_delta) {
        cpu_usage_samples_[name].push_back(
          100.0 * (total_delta - idle_delta) / static_cast<double>(total_delta));
      }
    }
    scheduler_delay_ms_.push_back(
      std::max<std::int64_t>(0, now_mono - next_cpu_due_ns_) / 1.0e6);
    do {
      next_cpu_due_ns_ += interval_ns();
    } while (next_cpu_due_ns_ <= now_mono);

    previous_cpu_ticks_ = current_ticks;
    previous_cpu_sample_monotonic_ns_ = now_mono;
    previous_process_cpu_ns_ = now_process;
    poll_launch_log();

    const auto elapsed_s = (now_mono - capture_started_monotonic_ns_) / 1.0e9;
    const auto total_cpu = latest_metric(cpu_usage_samples_["cpu"]);
    const auto self_cpu = latest_metric(self_cpu_samples_);
    std::cout << std::fixed << std::setprecision(2)
              << "elapsed_s=" << elapsed_s
              << " total_cpu_pct=" << total_cpu
              << " self_cpu_pct_one_core=" << self_cpu
              << " ir_missing=" << infra1_counter_.missing_total() << '/'
              << infra2_counter_.missing_total()
              << " imu_gaps=" << imu_stream_.gaps()
              << " odom_gaps=" << odometry_stream_.gaps()
              << " tracking_lost=" << status_lost_count_ + log_tracking_lost_count_
              << std::endl;
  }

  static double latest_metric(const std::vector<double> & values)
  {
    return values.empty() ? 0.0 : values.back();
  }

  void initialize_log_offset()
  {
    try {
      launch_log_offset_ = std::filesystem::exists(launch_log_path_) ?
        std::filesystem::file_size(launch_log_path_) : 0U;
    } catch (const std::filesystem::filesystem_error & error) {
      launch_log_error_ = error.what();
      launch_log_offset_ = 0U;
    }
  }

  void poll_launch_log()
  {
    if (launch_log_path_.empty()) {
      return;
    }
    try {
      if (!std::filesystem::exists(launch_log_path_)) {
        return;
      }
      const auto size = std::filesystem::file_size(launch_log_path_);
      if (size < launch_log_offset_) {
        launch_log_offset_ = 0U;
      }
      std::ifstream input(launch_log_path_);
      input.seekg(static_cast<std::streamoff>(launch_log_offset_));
      std::string line;
      while (std::getline(input, line)) {
        const auto normalized = lowercase(line);
        const bool tracking_lost = normalized.find("visual tracking is lost") != std::string::npos;
        const bool frame_delta =
          normalized.find("delta between current and previous frame") != std::string::npos ||
          normalized.find("frame delta") != std::string::npos ||
          (normalized.find("frame") != std::string::npos &&
          normalized.find("timestamp") != std::string::npos &&
          normalized.find("delta") != std::string::npos);
        if (!tracking_lost && !frame_delta) {
          continue;
        }
        const auto now_mono = monotonic_ns();
        const auto now_wall = realtime_ns();
        const auto detail = line.substr(0, 500);
        if (tracking_lost) {
          ++log_tracking_lost_count_;
          anomalies_.add({"tracking_lost_log", "launch_log", detail, 0, now_mono, now_wall});
        }
        if (frame_delta) {
          ++log_frame_delta_count_;
          anomalies_.add({"frame_delta_log", "launch_log", detail, 0, now_mono, now_wall});
        }
      }
      launch_log_offset_ = size;
    } catch (const std::exception & error) {
      launch_log_error_ = error.what();
    }
  }

  void finish()
  {
    if (finished_) {
      return;
    }
    finished_ = true;
    capture_enabled_ = false;
    finish_timer_->cancel();
    cpu_timer_->cancel();
    poll_launch_log();
    capture_finished_monotonic_ns_ = monotonic_ns();
    capture_finished_realtime_ns_ = realtime_ns();
    process_cpu_finished_ns_ = process_cpu_ns();
    write_report();
    std::cout << "report_written=" << output_json_ << std::endl;
    rclcpp::shutdown();
  }

  void write_report()
  {
    const auto elapsed_ns = capture_finished_monotonic_ns_ - capture_started_monotonic_ns_;
    const auto self_average = elapsed_ns > 0 ?
      100.0 * (process_cpu_finished_ns_ - process_cpu_started_ns_) /
      static_cast<double>(elapsed_ns) : 0.0;

    nlohmann::json cpu_per_core = nlohmann::json::object();
    for (const auto & [name, values] : cpu_usage_samples_) {
      if (name != "cpu") {
        cpu_per_core[name] = metric_report(values);
      }
    }
    auto self_metrics = metric_report(self_cpu_samples_);
    self_metrics["average"] = self_average;

    nlohmann::json gate_checks = nlohmann::json::object();
    bool gate_passed = true;
    if (subscribe_topics_) {
      gate_checks = {
        {"infra1_counter_present", infra1_counter_.valid_count() > 0U},
        {"infra2_counter_present", infra2_counter_.valid_count() > 0U},
        {"infra1_counter_continuous",
          infra1_counter_.missing_total() == 0 && infra1_counter_.nonmonotonic() == 0U},
        {"infra2_counter_continuous",
          infra2_counter_.missing_total() == 0 && infra2_counter_.nonmonotonic() == 0U},
        {"infra1_metadata_timing_continuous",
          infra1_stream_.count() > 0U && infra1_stream_.gaps() == 0U && infra1_stream_.nonmonotonic() == 0U},
        {"infra2_metadata_timing_continuous",
          infra2_stream_.count() > 0U && infra2_stream_.gaps() == 0U && infra2_stream_.nonmonotonic() == 0U},
        {"imu_continuous",
          imu_stream_.count() > 0U && imu_stream_.gaps() == 0U && imu_stream_.nonmonotonic() == 0U},
        {"odometry_continuous",
          odometry_stream_.count() > 0U && odometry_stream_.gaps() == 0U &&
          odometry_stream_.nonmonotonic() == 0U},
        {"no_tracking_lost", status_lost_count_ + log_tracking_lost_count_ == 0U},
        {"no_cuvslam_frame_delta_warning", log_frame_delta_count_ == 0U}
      };
      for (const auto & item : gate_checks.items()) {
        gate_passed = gate_passed && item.value().get<bool>();
      }
    }

    nlohmann::json anomaly_json = nlohmann::json::array();
    for (const auto & anomaly : anomalies_.ordered()) {
      anomaly_json.push_back({
        {"kind", anomaly.kind}, {"stream", anomaly.stream}, {"detail", anomaly.detail},
        {"source_ns", anomaly.source_ns}, {"monotonic_ns", anomaly.monotonic_ns},
        {"realtime_ns", anomaly.realtime_ns}
      });
    }

    nlohmann::json report = {
      {"schema_version", 1},
      {"mode", subscribe_topics_ ? "observer" : "baseline"},
      {"subscribe_topics", subscribe_topics_},
      {"duration_s", duration_s_},
      {"warmup_s", warmup_s_},
      {"qos", {{"reliability", "best_effort"}, {"depth", qos_depth_}}},
      {"clocks", {
          {"started_monotonic_ns", capture_started_monotonic_ns_},
          {"finished_monotonic_ns", capture_finished_monotonic_ns_},
          {"started_realtime_ns", capture_started_realtime_ns_},
          {"finished_realtime_ns", capture_finished_realtime_ns_}
        }},
      {"cpu", {
          {"units", {
              {"probe_self", "100 percent equals one CPU core"},
              {"aggregate_and_per_core", "each value normalized to 0-100 percent"}
            }},
          {"probe_self_pct_one_core", self_metrics},
          {"aggregate_pct", metric_report(cpu_usage_samples_["cpu"])},
          {"per_core_pct", cpu_per_core},
          {"scheduler_delay_ms", metric_report(scheduler_delay_ms_)}
        }},
      {"status_graph", status_graph_},
      {"status", {
          {"message_count", status_message_count_},
          {"transition_count", status_transition_count_},
          {"lost_count", status_lost_count_},
          {"last", last_status_}
        }},
      {"launch_log", {
          {"path", launch_log_path_},
          {"frame_delta_warning_count", log_frame_delta_count_},
          {"tracking_lost_count", log_tracking_lost_count_},
          {"error", launch_log_error_}
        }},
      {"anomalies", anomaly_json},
      {"anomaly_overwritten_count", anomalies_.overwritten()},
      {"gate_checks", gate_checks},
      {"measurement_gate_passed", subscribe_topics_ ? nlohmann::json(gate_passed) : nlohmann::json(nullptr)}
    };

    if (subscribe_topics_) {
      report["streams"] = {
        {"infra1_metadata", infra1_stream_.report(infra_hz_)},
        {"infra2_metadata", infra2_stream_.report(infra_hz_)},
        {"imu", imu_stream_.report(imu_hz_)},
        {"odometry", odometry_stream_.report(odometry_hz_)}
      };
      report["frame_counters"] = {
        {"infra1", infra1_counter_.report()},
        {"infra2", infra2_counter_.report()}
      };
    }

    const std::filesystem::path output_path(output_json_);
    if (output_path.has_parent_path()) {
      std::filesystem::create_directories(output_path.parent_path());
    }
    std::ofstream output(output_path);
    if (!output) {
      throw std::runtime_error("cannot write report: " + output_json_);
    }
    output << report.dump(2) << '\n';
  }

  bool subscribe_topics_;
  double duration_s_;
  double warmup_s_;
  double sample_interval_s_;
  std::string output_json_;
  std::string launch_log_path_;
  double infra_hz_;
  double imu_hz_;
  double odometry_hz_;
  int qos_depth_;
  std::string infra1_metadata_topic_;
  std::string infra2_metadata_topic_;
  std::string imu_topic_;
  std::string odometry_topic_;
  std::string status_topic_;

  bool capture_enabled_{false};
  bool finished_{false};
  AnomalyRing anomalies_;
  StreamStats infra1_stream_;
  StreamStats infra2_stream_;
  StreamStats imu_stream_;
  StreamStats odometry_stream_;
  CounterStats infra1_counter_;
  CounterStats infra2_counter_;

  rclcpp::TimerBase::SharedPtr warmup_timer_;
  rclcpp::TimerBase::SharedPtr cpu_timer_;
  rclcpp::TimerBase::SharedPtr finish_timer_;
  rclcpp::Subscription<realsense2_camera_msgs::msg::Metadata>::SharedPtr infra1_metadata_sub_;
  rclcpp::Subscription<realsense2_camera_msgs::msg::Metadata>::SharedPtr infra2_metadata_sub_;
  rclcpp::Subscription<sensor_msgs::msg::Imu>::SharedPtr imu_sub_;
  rclcpp::Subscription<nav_msgs::msg::Odometry>::SharedPtr odometry_sub_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr status_sub_;

  std::map<std::string, CpuTicks> previous_cpu_ticks_;
  std::map<std::string, std::vector<double>> cpu_usage_samples_;
  std::vector<double> self_cpu_samples_;
  std::vector<double> scheduler_delay_ms_;
  std::int64_t capture_started_monotonic_ns_{0};
  std::int64_t capture_finished_monotonic_ns_{0};
  std::int64_t capture_started_realtime_ns_{0};
  std::int64_t capture_finished_realtime_ns_{0};
  std::int64_t previous_cpu_sample_monotonic_ns_{0};
  std::int64_t previous_process_cpu_ns_{0};
  std::int64_t process_cpu_started_ns_{0};
  std::int64_t process_cpu_finished_ns_{0};
  std::int64_t next_cpu_due_ns_{0};

  nlohmann::json status_graph_ = nlohmann::json::object();
  std::size_t status_message_count_{0};
  std::size_t status_transition_count_{0};
  std::size_t status_lost_count_{0};
  std::string last_status_;
  std::uintmax_t launch_log_offset_{0};
  std::size_t log_frame_delta_count_{0};
  std::size_t log_tracking_lost_count_{0};
  std::string launch_log_error_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::NodeOptions options;
  options.enable_rosout(false);
  auto node = std::make_shared<CuvslamLightweightProbe>(options);
  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(node);
  executor.spin();
  return 0;
}
