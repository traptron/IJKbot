#include "vision_cpp/camera.hpp"
#include <memory>
#include <thread>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>

class Bridge : public rclcpp::Node {
public:
  Bridge() : Node("qr_ssh_bridge") {
    const auto host = declare_parameter("host", "otmorozki@192.168.0.191");
    const auto socket = declare_parameter("socket", "/tmp/ijkbot-camera-new.sock");
    const auto remote = declare_parameter("remote_executable",
      "/home/otmorozki/IJKbot/install/vision_cpp/lib/vision_cpp/csi_jpeg_stream");
    const int fps = declare_parameter("fps", 10);
    const int quality = declare_parameter("jpeg_quality", 85);
    vision_cpp::Options options;
    options.fps = fps;
    options.quality = quality;
    options.validate();
    // SSH joins remote argv into shell text; restrict these configurable fields.
    if (host.empty() || host[0] == '-' ||
      host.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@._-:") != std::string::npos ||
      remote.empty() || remote[0] != '/' ||
      remote.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/._-") != std::string::npos)
    {throw std::invalid_argument("Invalid SSH host/remote executable");}
    const auto topic = declare_parameter("image_topic", "/camera/color/image_raw/compressed");
    frame_id_ = declare_parameter("frame_id", "camera_optical_frame");
    publisher_ = create_publisher<sensor_msgs::msg::CompressedImage>(topic,
      rclcpp::SensorDataQoS().keep_last(1));
    RCLCPP_INFO(get_logger(), "JPEG-only SSH bridge: %s -> %s", host.c_str(), topic.c_str());
    worker_ = std::thread([this, host, socket, remote, fps, quality] {
        while (!stop_.load()) {
          try {
            vision_cpp::ChildPipe child({"ssh", "-S", socket, "-o", "BatchMode=yes",
              "-o", "ConnectTimeout=5", host, remote, "--fps", std::to_string(fps),
              "--quality", std::to_string(quality)});
            vision_cpp::read_mjpeg(child.fd(), stop_, [this](vision_cpp::Bytes && jpeg) {
                if (stop_.load() || !rclcpp::ok()) {return;}
                auto message = std::make_unique<sensor_msgs::msg::CompressedImage>();
                message->header.stamp = now();
                message->header.frame_id = frame_id_;
                message->format = "jpeg";
                message->data = std::move(jpeg);
                publisher_->publish(std::move(message));
              }, fps);
          } catch (const std::exception & error) {
            if (!stop_.load()) {RCLCPP_ERROR(get_logger(), "%s; retry in 2 seconds", error.what());}
          }
          for (int i = 0; i < 20 && !stop_.load(); ++i) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
          }
        }
      });
  }
  ~Bridge() override {stop_.store(true); if (worker_.joinable()) {worker_.join();}}
private:
  std::atomic_bool stop_{false};
  std::thread worker_;
  std::string frame_id_;
  rclcpp::Publisher<sensor_msgs::msg::CompressedImage>::SharedPtr publisher_;
};
int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  int result = 0;
  try {rclcpp::spin(std::make_shared<Bridge>());} catch (const std::exception & error) {
    RCLCPP_ERROR(rclcpp::get_logger("qr_ssh_bridge"), "%s", error.what());
    result = 1;
  }
  rclcpp::shutdown();
  return result;
}
