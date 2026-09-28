#include "vision_cpp/camera.hpp"
#include <memory>
#include <thread>
#include <condition_variable>
#include <mutex>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>
#include <std_msgs/msg/bool.hpp>

class CameraNode : public rclcpp::Node {
public:
  CameraNode() : Node("rpi_camera_node") {
    vision_cpp::Options options;
    options.fps = declare_parameter("fps", 10);
    options.quality = declare_parameter("jpeg_quality", 85);
    options.exposure = declare_parameter("exposure", 2500);
    options.gain = declare_parameter("analogue_gain", 320);
    options.width = declare_parameter("width", 640);
    options.height = declare_parameter("height", 480);
    options.mock = declare_parameter("mock_hardware", false);
    options.monochrome = declare_parameter("monochrome", false);
    monochrome_ = options.monochrome;
    options.backend = declare_parameter("backend", "v4l2_raw");
    options.device = declare_parameter("device", "/dev/video0");
    options.subdevice = declare_parameter("subdevice", "/dev/v4l-subdev0");
    options.camera_name = declare_parameter("camera_name", "");
    options.validate();
    frame_id_ = declare_parameter("frame_id", "camera_optical_frame");
    const auto topic = declare_parameter("image_topic", "/camera/color/image_raw/compressed");
    publisher_ = create_publisher<sensor_msgs::msg::CompressedImage>(topic,
      rclcpp::SensorDataQoS().keep_last(1));
    const auto qr_topic = declare_parameter("qr_image_topic", "");
    preview_fps_ = declare_parameter("preview_fps", 4);
    preview_quality_ = declare_parameter("preview_quality", 85);
    if (preview_fps_ < 1 || preview_fps_ > 15 || preview_quality_ < 1 || preview_quality_ > 100) {
      throw std::invalid_argument("Invalid preview FPS/JPEG quality");
    }
    if (!qr_topic.empty()) {
      if (qr_topic == topic) {throw std::invalid_argument("QR and preview topics must differ");}
      qr_publisher_ = create_publisher<sensor_msgs::msg::CompressedImage>(qr_topic,
        rclcpp::SensorDataQoS().keep_last(1));
    }
    if (declare_parameter("stop_on_qr", false)) {
      complete_sub_ = create_subscription<std_msgs::msg::Bool>(
        declare_parameter("complete_topic", "/vision/qr/session_complete"),
        rclcpp::QoS(1).reliable().transient_local(),
        [this](std_msgs::msg::Bool::ConstSharedPtr message) {
          if (message->data && !stop_.exchange(true)) {
            RCLCPP_INFO(get_logger(), "Confirmed QR received: camera capture stopped");
            preview_wake_.notify_all();
          }
        });
    }
    RCLCPP_INFO(get_logger(), "Native CSI: %s JPEG %dx%d Q=%d, at most %d fps -> %s",
      monochrome_ ? "monochrome" : "color",
      options.width, options.height, options.quality, options.fps,
      qr_publisher_ ? qr_topic.c_str() : topic.c_str());
    if (qr_publisher_) {
      RCLCPP_INFO(get_logger(), "Independent preview: 640x480 Q=%d, at most %d fps -> %s",
        preview_quality_, preview_fps_, topic.c_str());
      preview_worker_ = std::thread([this] {preview();});
    }
    worker_ = std::thread([this, options] {
        bool first = true;
        vision_cpp::run_capture(options, stop_, [this, &first](vision_cpp::Bytes && jpeg) {
            if (stop_.load() || !rclcpp::ok()) {return;}
            auto message = std::make_shared<sensor_msgs::msg::CompressedImage>();
            message->header.stamp = now();
            message->header.frame_id = frame_id_;
            message->format = "jpeg";
            message->data = std::move(jpeg);
            if (qr_publisher_) {
              qr_publisher_->publish(*message);
              // QR and preview have independent consumers, each with one pending frame.
              // A slow encoder or Wi-Fi subscriber cannot queue frames in capture.
              if (publisher_->get_subscription_count() > 0) {
                std::lock_guard<std::mutex> guard(preview_mutex_);
                preview_pending_ = message;
                preview_wake_.notify_one();
              }
            } else {publisher_->publish(*message);}
            if (first) {
              RCLCPP_INFO(get_logger(), "Camera stream active: first JPEG published");
              first = false;
            }
          }, [this](const std::string & error) {RCLCPP_ERROR(get_logger(), "%s", error.c_str());});
      });
  }
  ~CameraNode() override {
    stop_.store(true);
    preview_wake_.notify_all();
    if (worker_.joinable()) {worker_.join();}
    if (preview_worker_.joinable()) {preview_worker_.join();}
  }
private:
  void preview() {
    auto next = vision_cpp::Clock::now();
    while (!stop_.load()) {
      sensor_msgs::msg::CompressedImage::ConstSharedPtr source;
      {
        std::unique_lock<std::mutex> guard(preview_mutex_);
        preview_wake_.wait(guard, [this] {return stop_.load() || preview_pending_;});
        preview_wake_.wait_until(guard, next, [this] {return stop_.load();});
        if (stop_.load()) {return;}
        source = std::move(preview_pending_);
      }
      next = vision_cpp::Clock::now() + std::chrono::nanoseconds(1000000000 / preview_fps_);
      try {
        auto full = cv::imdecode(source->data,
          monochrome_ ? cv::IMREAD_GRAYSCALE : cv::IMREAD_COLOR);
        if (full.empty()) {continue;}
        // Preview alone is resized. Recognition receives the untouched full-resolution JPEG.
        const double scale = std::min(640.0 / full.cols, 480.0 / full.rows);
        cv::Mat reduced, canvas(480, 640, monochrome_ ? CV_8UC1 : CV_8UC3,
          cv::Scalar(0, 0, 0));
        cv::resize(full, reduced, {}, scale, scale, cv::INTER_AREA);
        reduced.copyTo(canvas(cv::Rect((640 - reduced.cols) / 2, (480 - reduced.rows) / 2,
          reduced.cols, reduced.rows)));
        sensor_msgs::msg::CompressedImage message;
        message.header = source->header;
        message.format = "jpeg";
        if (!cv::imencode(".jpg", canvas, message.data,
          {cv::IMWRITE_JPEG_QUALITY, preview_quality_, cv::IMWRITE_JPEG_OPTIMIZE, 1}))
        {throw std::runtime_error("Preview JPEG encoding failed");}
        if (!stop_.load()) {publisher_->publish(message);}
      } catch (const std::exception & error) {
        RCLCPP_WARN(get_logger(), "Preview: %s", error.what());
      }
    }
  }
  std::atomic_bool stop_{false};
  std::thread worker_, preview_worker_;
  std::mutex preview_mutex_;
  std::condition_variable preview_wake_;
  sensor_msgs::msg::CompressedImage::ConstSharedPtr preview_pending_;
  int preview_fps_, preview_quality_;
  bool monochrome_ = false;
  std::string frame_id_;
  rclcpp::Publisher<sensor_msgs::msg::CompressedImage>::SharedPtr publisher_;
  rclcpp::Publisher<sensor_msgs::msg::CompressedImage>::SharedPtr qr_publisher_;
  rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr complete_sub_;
};
int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  cv::setNumThreads(1);
  int result = 0;
  try {rclcpp::spin(std::make_shared<CameraNode>());} catch (const std::exception & error) {
    RCLCPP_ERROR(rclcpp::get_logger("rpi_camera_node"), "%s", error.what());
    result = 1;
  }
  rclcpp::shutdown();
  return result;
}
