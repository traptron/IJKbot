#include "vision_cpp/qr.hpp"
#include <condition_variable>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <mutex>
#include <sstream>
#include <thread>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>
#include <std_msgs/msg/bool.hpp>
#include <std_msgs/msg/string.hpp>

class QrReader : public rclcpp::Node {
  using Image = sensor_msgs::msg::CompressedImage;
  using Steady = vision_cpp::Clock;
public:
  QrReader() : Node("qr_reader_node"), confirmation_(declare_parameter("confirm_frames", 1)) {
    snapshot_ = declare_parameter("snapshot_mode", false);
    state_filter_ = declare_parameter("state_filter_enabled", true);
    save_ = declare_parameter("save_snapshot", true);
    one_shot_ = declare_parameter("one_shot", false);
    const double max_fps = declare_parameter("max_decode_fps", 3.0);
    decode_duty_cycle_ = declare_parameter("decode_duty_cycle", 0.7);
    const double timeout = declare_parameter("confirmation_timeout_sec", 5.0);
    if (!std::isfinite(max_fps) || max_fps <= 0 || max_fps > 30 ||
      !std::isfinite(timeout) || timeout <= 0 || timeout > 60 ||
      !std::isfinite(decode_duty_cycle_) || decode_duty_cycle_ <= 0 || decode_duty_cycle_ > 1)
    {throw std::invalid_argument("Invalid QR decode rate or confirmation timeout");}
    decode_period_ = std::chrono::duration_cast<Steady::duration>(std::chrono::duration<double>(1 / max_fps));
    confirmation_timeout_ = std::chrono::duration_cast<Steady::duration>(std::chrono::duration<double>(timeout));
    log_dir_ = declare_parameter("log_dir", "log");
    const auto image_topic = declare_parameter("image_topic", "/camera/color/image_raw/compressed");
    auto result_qos = rclcpp::QoS(one_shot_ ? 1 : 10).reliable();
    if (one_shot_) {result_qos.transient_local();}
    status_pub_ = create_publisher<std_msgs::msg::String>(declare_parameter("status_topic", "/victim_status"), result_qos);
    detected_pub_ = create_publisher<std_msgs::msg::Bool>(declare_parameter("detected_topic", "/vision/qr/detected"), 10);
    evidence_pub_ = create_publisher<Image>(declare_parameter("qr_image_topic", "/vision/qr/image/compressed"), result_qos);
    if (one_shot_) {
      complete_pub_ = create_publisher<std_msgs::msg::Bool>(
        declare_parameter("complete_topic", "/vision/qr/session_complete"),
        rclcpp::QoS(1).reliable().transient_local());
    }
    image_sub_ = create_subscription<Image>(image_topic, rclcpp::SensorDataQoS().keep_last(1),
      [this](Image::ConstSharedPtr message) {
        std::lock_guard<std::mutex> guard(mutex_);
        if (completed_) {return;}
        latest_ = message;
        last_received_ = Steady::now();
        if (snapshot_ || !allowed()) {return;}
        // A forced photograph cannot be replaced by a later streaming frame.
        if (!forced_) {
          if (pending_) {++replaced_;}
          pending_ = message; pending_time_ = last_received_;
        }
        wake_.notify_one();
      });
    trigger_sub_ = create_subscription<std_msgs::msg::Bool>(
      declare_parameter("trigger_topic", "/vision/take_photo"), 10,
      [this](std_msgs::msg::Bool::ConstSharedPtr message) {
        if (!message->data) {return;}
        std::lock_guard<std::mutex> guard(mutex_);
        if (completed_) {return;}
        if (!latest_) {RCLCPP_WARN(get_logger(), "Photo requested but no camera frame received"); return;}
        pending_ = latest_;
        pending_time_ = Steady::now();
        forced_ = true;
        wake_.notify_one();
      });
    state_sub_ = create_subscription<std_msgs::msg::String>(
      declare_parameter("mission_state_topic", "/mission/state"), 10,
      [this](std_msgs::msg::String::ConstSharedPtr message) {
        std::lock_guard<std::mutex> guard(mutex_);
        if (completed_) {return;}
        const auto start = message->data.find_first_not_of(" \t\r\n");
        const auto end = message->data.find_last_not_of(" \t\r\n");
        const auto state = start == std::string::npos ? "" : message->data.substr(start, end - start + 1);
        if (state_ == state) {return;}
        state_ = state;
        ++epoch_;
        if (!allowed()) {confirmation_.reset(); last_stamp_.reset(); pending_.reset(); forced_ = false;}
      });
    timer_ = create_wall_timer(std::chrono::milliseconds(500), [this] {
        std::lock_guard<std::mutex> guard(mutex_);
        if (completed_) {return;}
        if (last_received_ != Steady::time_point{} && Steady::now() - last_received_ > confirmation_timeout_) {
          confirmation_.reset(); last_stamp_.reset();
          ++epoch_;  // Reject a decode still running after capture has gone stale.
          std_msgs::msg::Bool message;
          message.data = false;
          detected_pub_->publish(message);
        }
      });
    RCLCPP_INFO(get_logger(), "Native QR reader: %s; confirmation=%d; snapshot=%d; state_filter=%d",
      image_topic.c_str(), static_cast<int>(get_parameter("confirm_frames").as_int()), snapshot_, state_filter_);
    RCLCPP_INFO(get_logger(), "Background OpenCV QR: max %.1f attempts/s; full resolution; confirmation gap %.1f s",
      max_fps, timeout);
    worker_ = std::thread([this] {
        try {work();} catch (const std::exception & error) {
          RCLCPP_ERROR(get_logger(), "QR worker stopped: %s", error.what());
        }
      });
  }
  ~QrReader() override {
    {std::lock_guard<std::mutex> guard(mutex_); stop_ = true;}
    wake_.notify_all();
    if (worker_.joinable()) {worker_.join();}
  }
private:
  bool allowed() const {return !state_filter_ || state_ == "SEARCHING_VICTIM" || state_ == "READING_QR";}
  void save_snapshot(const vision_cpp::Bytes & jpeg) {
    try {
      std::filesystem::path directory = log_dir_;
      if (log_dir_ == "log") {
        if (const char * configured = std::getenv("IJKBOT_LOG_DIR")) {directory = configured;}
        else if (std::filesystem::is_directory("/home/lev/IJKbot/log")) {directory = "/home/lev/IJKbot/log";}
      }
      std::filesystem::create_directories(directory);
      const auto timestamp = std::chrono::system_clock::now().time_since_epoch();
      const auto id = std::chrono::duration_cast<std::chrono::nanoseconds>(timestamp).count();
      auto filename = directory / ("qr_snapshot_" + std::to_string(id) + "_" + std::to_string(snapshot_id_++) + ".jpg");
      std::ofstream output(filename, std::ios::binary);
      output.write(reinterpret_cast<const char *>(jpeg.data()), static_cast<std::streamsize>(jpeg.size()));
      if (!output) {throw std::runtime_error("Cannot write QR snapshot");}
      RCLCPP_INFO(get_logger(), "QR evidence saved: %s", filename.c_str());
    } catch (const std::exception & error) {RCLCPP_ERROR(get_logger(), "QR snapshot: %s", error.what());}
  }
  void work() {
    vision_cpp::QrDecoder decoder;
    auto next_decode = Steady::now();
    auto last_stats = Steady::now();
    while (true) {
      Image::ConstSharedPtr image;
      bool force;
      uint64_t epoch;
      Steady::time_point received;
      {
        std::unique_lock<std::mutex> guard(mutex_);
        wake_.wait(guard, [this] {return stop_ || pending_;});
        if (stop_) {return;}
        wake_.wait_until(guard, next_decode, [this] {return stop_ || forced_;});
        if (stop_) {return;}
        if (!pending_) {continue;}
        image = std::move(pending_);
        force = forced_;
        forced_ = false;
        epoch = epoch_;
        received = pending_time_;
        const auto stamp = std::make_pair(image->header.stamp.sec, image->header.stamp.nanosec);
        if (!force && stamp != std::make_pair(0, 0U) && last_stamp_ == stamp) {continue;}
        if (last_frame_ == Steady::time_point{} || received - last_frame_ > confirmation_timeout_ ||
          (last_publication_ != Steady::time_point{} && received - last_publication_ >= std::chrono::seconds(1)))
        {confirmation_.reset(); last_publication_ = {};}
        last_stamp_ = stamp;
        last_frame_ = received;
      }
      const auto started = Steady::now();
      next_decode = started + decode_period_;
      std::optional<vision_cpp::Detection> detection;
      try {detection = decoder.decode(image->data, force);} catch (const std::exception & error) {
        RCLCPP_WARN(get_logger(), "QR decoding: %s", error.what());
      }
      // A slow failed decode must also yield CPU to capture and preview.
      // Forced snapshots bypass this cooldown; normal work still keeps only the newest frame.
      const auto elapsed = Steady::now() - started;
      next_decode = std::max(next_decode, started +
        std::chrono::duration_cast<Steady::duration>(elapsed / decode_duty_cycle_));
      std::lock_guard<std::mutex> guard(mutex_);
      if (stop_ || !rclcpp::ok()) {return;}
      if (Steady::now() - last_stats >= std::chrono::seconds(5)) {
        RCLCPP_INFO(get_logger(), "QR worker: decode %.0f ms; replaced pending frames=%lu; method=%s",
          std::chrono::duration<double, std::milli>(Steady::now() - started).count(),
          static_cast<unsigned long>(replaced_), detection ? detection->method.c_str() : "not decoded");
        last_stats = Steady::now(); replaced_ = 0;
      }
      // Do not publish a result from a mission state that has already ended.
      if (!force && (epoch != epoch_ || !allowed())) {continue;}
      std_msgs::msg::Bool found;
      found.data = detection.has_value();
      detected_pub_->publish(found);
      auto confirmed = confirmation_.observe(detection ? detection->text : "");
      if (force && detection) {confirmed = detection->text;}
      if (!confirmed) {continue;}
      std_msgs::msg::String status;
      status.data = *confirmed;
      status_pub_->publish(status);
      last_publication_ = Steady::now();
      Image evidence;
      evidence.header = image->header;
      if (evidence.header.stamp.sec == 0 && evidence.header.stamp.nanosec == 0) {evidence.header.stamp = now();}
      evidence.format = "jpeg";
      // Encode evidence only after confirmation and reuse the already decoded Mat.
      try {evidence.data = decoder.annotate(*detection);} catch (const std::exception & error) {
        RCLCPP_WARN(get_logger(), "QR annotation: %s", error.what()); evidence.data = image->data;
      }
      evidence_pub_->publish(evidence);
      if (save_ && (force || last_saved_ != *confirmed)) {save_snapshot(evidence.data); last_saved_ = *confirmed;}
      if (last_logged_ != *confirmed) {RCLCPP_INFO(get_logger(), "QR confirmed: %s", confirmed->c_str()); last_logged_ = *confirmed;}
      if (one_shot_) {
        completed_ = true;
        latest_.reset(); pending_.reset();
        std_msgs::msg::Bool complete;
        complete.data = true;
        complete_pub_->publish(complete);
        RCLCPP_INFO(get_logger(), "QR session complete: one result retained; stopping capture and preview");
        return;  // Keep ROS alive to deliver the cached result after Wi-Fi reconnects.
      }
    }
  }
  bool snapshot_, state_filter_, save_, one_shot_, completed_ = false, stop_ = false, forced_ = false;
  std::string log_dir_, state_, last_saved_, last_logged_;
  uint64_t epoch_ = 0, snapshot_id_ = 0, replaced_ = 0;
  std::mutex mutex_;
  std::condition_variable wake_;
  std::thread worker_;
  Image::ConstSharedPtr latest_, pending_;
  Steady::time_point last_frame_{}, last_publication_{}, pending_time_{};
  Steady::time_point last_received_{};
  Steady::duration decode_period_{}, confirmation_timeout_{};
  double decode_duty_cycle_;
  std::optional<std::pair<int32_t, uint32_t>> last_stamp_;
  vision_cpp::Confirmation confirmation_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr status_pub_;
  rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr detected_pub_;
  rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr complete_pub_;
  rclcpp::Publisher<Image>::SharedPtr evidence_pub_;
  rclcpp::Subscription<Image>::SharedPtr image_sub_;
  rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr trigger_sub_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr state_sub_;
  rclcpp::TimerBase::SharedPtr timer_;
};
int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  cv::setNumThreads(1);
  int result = 0;
  try {rclcpp::spin(std::make_shared<QrReader>());} catch (const std::exception & error) {
    RCLCPP_ERROR(rclcpp::get_logger("qr_reader_node"), "%s", error.what()); result = 1;
  }
  rclcpp::shutdown();
  return result;
}
