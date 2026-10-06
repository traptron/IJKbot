#include <chrono>
#include <memory>
#include <mutex>
#include <thread>
#include <signal.h>
#include <poll.h>
#include <unistd.h>
#include "vision_cpp/camera.hpp"
#include "vision_cpp/duplex_pipe.hpp"
#include <opencv2/highgui.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>
#include <std_msgs/msg/bool.hpp>

int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  cv::setNumThreads(1);
  auto node = std::make_shared<rclcpp::Node>("video_viewer");
  using Image = sensor_msgs::msg::CompressedImage;
  using Clock = std::chrono::steady_clock;
  const auto topic = node->declare_parameter("image_topic", "/camera/color/image_raw/compressed");
  const auto title = node->declare_parameter("window_title", "IJKbot - live camera");
  const auto host = node->declare_parameter("ssh_host", "");
  const auto socket = node->declare_parameter("ssh_socket", "/tmp/ijkbot-preview-ssh.sock");
  const auto remote = node->declare_parameter("remote_executable",
    "/home/otmorozki/IJKbot/install/vision_cpp/lib/vision_cpp/jpeg_topic_stream");
  const int preview_fps = node->declare_parameter("preview_fps", 4);
  if (preview_fps < 1 || preview_fps > 15 || (!host.empty() && (host[0] == '-' ||
    host.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@._-:") != std::string::npos)) ||
    remote.empty() || remote[0] != '/' ||
    remote.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/._-") != std::string::npos)
  {
    RCLCPP_ERROR(node->get_logger(), "Invalid SSH preview parameters");
    rclcpp::shutdown(); return 1;
  }
  std::mutex mutex;
  Image::ConstSharedPtr latest;
  auto received = Clock::now();
  auto receive = [&](Image::ConstSharedPtr message) {
      std::lock_guard<std::mutex> guard(mutex);
      latest = std::move(message);
      received = Clock::now();
    };
  rclcpp::Subscription<Image>::SharedPtr subscription;
  if (host.empty()) {
    subscription = node->create_subscription<Image>(topic, rclcpp::SensorDataQoS().keep_last(1), receive);
  }
  std::atomic_bool stop{false};
  std::atomic_bool completed{false};
  auto completion = node->create_subscription<std_msgs::msg::Bool>(
    node->declare_parameter("complete_topic", "/vision/qr/session_complete"),
    rclcpp::QoS(1).reliable().transient_local(),
    [&](std_msgs::msg::Bool::ConstSharedPtr message) {
      if (message->data) {completed.store(true); stop.store(true);}
    });
  std::thread stream;
  signal(SIGPIPE, SIG_IGN);
  if (!host.empty()) {
    const auto domain = node->get_node_base_interface()->get_context()->get_domain_id();
    stream = std::thread([&, domain] {
        while (!stop.load()) {
          try {
            const auto command = "source /opt/ros/jazzy/setup.bash; export ROS_DOMAIN_ID=" +
              std::to_string(domain) + "; exec " + remote + " --fps " + std::to_string(preview_fps);
            vision_cpp::DuplexPipe child({"ssh", "-S", socket, "-o", "BatchMode=yes", "-o",
              "ConnectTimeout=5", host, "bash", "-lc", "'" + command + "'"});
            vision_cpp::MjpegFramer parser;
            auto last_data = Clock::now();
            bool received_frame = false;
            uint8_t buffer[65536];
            while (!stop.load()) {
              pollfd descriptor{child.output(), POLLIN, 0};
              const int status = poll(&descriptor, 1, 100);
              if (status < 0 && errno == EINTR) {continue;}
              if (status < 0) {throw std::runtime_error("SSH preview poll failed");}
              if (descriptor.revents & POLLIN) {
                const auto count = read(child.output(), buffer, sizeof(buffer));
                if (count < 0 && (errno == EAGAIN || errno == EINTR)) {continue;}
                if (count <= 0) {throw std::runtime_error("SSH preview closed");}
                last_data = Clock::now();
                for (auto & jpeg : parser.feed(buffer, static_cast<size_t>(count))) {
                  auto message = std::make_shared<Image>();
                  message->format = "jpeg";
                  message->data = std::move(jpeg);
                  received_frame = true;
                  receive(message);
                  child.acknowledge();
                }
              } else if (descriptor.revents & (POLLERR | POLLHUP | POLLNVAL)) {
                throw std::runtime_error("SSH preview disconnected");
              }
              // Allow process startup and DDS discovery before the first frame.
              // A running stream still reconnects quickly after a network stall.
              const auto timeout = std::chrono::seconds(received_frame ? 5 : 15);
              if (Clock::now() - last_data > timeout) {
                throw std::runtime_error(received_frame ? "No SSH frame for 5 seconds" :
                  "Camera/DDS startup timed out after 15 seconds");
              }
            }
          } catch (const std::exception & error) {
            if (!stop.load()) {RCLCPP_WARN(node->get_logger(), "SSH preview: %s", error.what());}
          }
          for (int i = 0; i < 20 && !stop.load(); ++i) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
          }
        }
      });
  }
  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(node);
  std::thread receiver([&] {executor.spin();});
  int result = 0;
  try {
    cv::namedWindow(title, cv::WINDOW_NORMAL);
    cv::resizeWindow(title, 960, 720);
    cv::Mat frame(480, 640, CV_8UC3, cv::Scalar(0, 0, 0));
    bool have_frame = false;
    auto last_received = Clock::now();
    auto last_log = Clock::now();
    unsigned frames = 0;
    RCLCPP_INFO(node->get_logger(), "Latest-frame viewer: %s; queue=1; Escape/Q closes window",
      host.empty() ? topic.c_str() : host.c_str());
    while (rclcpp::ok() && !completed.load()) {
      Image::ConstSharedPtr message;
      {
        std::lock_guard<std::mutex> guard(mutex);
        message = std::move(latest);
        if (message) {last_received = received;}
      }
      if (message) {
        auto decoded = cv::imdecode(message->data, cv::IMREAD_COLOR);
        if (!decoded.empty()) {frame = std::move(decoded); have_frame = true; ++frames;}
      }
      const double gap = std::chrono::duration<double>(Clock::now() - last_received).count();
      auto display = frame.clone();
      if (!have_frame || gap > 0.5) {
        const std::string status = have_frame ? "STREAM PAUSED - " + std::to_string(gap).substr(0, 4) + " s" :
          "WAITING FOR CAMERA";
        cv::rectangle(display, {0, 0}, {display.cols, 35}, {0, 0, 0}, cv::FILLED);
        cv::putText(display, status, {10, 24}, cv::FONT_HERSHEY_SIMPLEX, 0.65, {0, 180, 255}, 2);
      }
      cv::imshow(title, display);
      const int key = cv::waitKey(10);
      if (key == 27 || key == 'q' || cv::getWindowProperty(title, cv::WND_PROP_VISIBLE) < 1) {break;}
      const double interval = std::chrono::duration<double>(Clock::now() - last_log).count();
      if (interval >= 5) {
        RCLCPP_INFO(node->get_logger(), "Displayed %.1f fps; last receive %.2f seconds ago", frames / interval, gap);
        frames = 0;
        last_log = Clock::now();
      }
    }
    cv::destroyAllWindows();
    if (completed.load()) {RCLCPP_INFO(node->get_logger(), "QR session complete: preview closed");}
  } catch (const std::exception & error) {
    RCLCPP_ERROR(node->get_logger(), "Video viewer: %s", error.what());
    result = 1;
  }
  executor.cancel();
  receiver.join();
  stop.store(true);
  if (stream.joinable()) {stream.join();}
  rclcpp::shutdown();
  return result;
}
