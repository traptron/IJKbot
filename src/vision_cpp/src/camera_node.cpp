#include "vision_cpp/camera.hpp"
#include <memory>
#include <thread>
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
    options.mock = declare_parameter("mock_hardware", false);
    options.backend = declare_parameter("backend", "v4l2_raw");
    options.device = declare_parameter("device", "/dev/video0");
    options.subdevice = declare_parameter("subdevice", "/dev/v4l-subdev0");
    options.camera_name = declare_parameter("camera_name", "");
    options.validate();
    frame_id_ = declare_parameter("frame_id", "camera_optical_frame");
    const auto topic = declare_parameter("image_topic", "/camera/color/image_raw/compressed");
    publisher_ = create_publisher<sensor_msgs::msg::CompressedImage>(topic,
      rclcpp::SensorDataQoS().keep_last(1));
    if (declare_parameter("stop_on_qr", false)) {
      complete_sub_ = create_subscription<std_msgs::msg::Bool>(
        declare_parameter("complete_topic", "/vision/qr/session_complete"),
        rclcpp::QoS(1).reliable().transient_local(),
        [this](std_msgs::msg::Bool::ConstSharedPtr message) {
          if (message->data && !stop_.exchange(true)) {
            RCLCPP_INFO(get_logger(), "Confirmed QR received: camera capture stopped");
          }
        });
    }
    RCLCPP_INFO(get_logger(), "Native CSI: JPEG 640x480 Q=%d, at most %d fps -> %s",
      options.quality, options.fps, topic.c_str());
    worker_ = std::thread([this, options] {
        bool first = true;
        vision_cpp::run_capture(options, stop_, [this, &first](vision_cpp::Bytes && jpeg) {
            if (stop_.load() || !rclcpp::ok()) {return;}
            auto message = std::make_unique<sensor_msgs::msg::CompressedImage>();
            message->header.stamp = now();
            message->header.frame_id = frame_id_;
            message->format = "jpeg";
            message->data = std::move(jpeg);
            publisher_->publish(std::move(message));
            if (first) {
              RCLCPP_INFO(get_logger(), "Camera stream active: first JPEG published");
              first = false;
            }
          }, [this](const std::string & error) {RCLCPP_ERROR(get_logger(), "%s", error.c_str());});
      });
  }
  ~CameraNode() override {stop_.store(true); if (worker_.joinable()) {worker_.join();}}
private:
  std::atomic_bool stop_{false};
  std::thread worker_;
  std::string frame_id_;
  rclcpp::Publisher<sensor_msgs::msg::CompressedImage>::SharedPtr publisher_;
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
