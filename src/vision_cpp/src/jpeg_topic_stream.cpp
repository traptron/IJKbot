#include "vision_cpp/camera.hpp"
#include <condition_variable>
#include <fcntl.h>
#include <iostream>
#include <mutex>
#include <poll.h>
#include <signal.h>
#include <thread>
#include <unistd.h>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>
#include <std_msgs/msg/bool.hpp>

int main(int argc, char ** argv) {
  int fps = 4;
  std::string topic = "/camera/color/image_raw/compressed";
  try {
    for (int i = 1; i < argc; ++i) {
      const std::string option = argv[i];
      if (i + 1 == argc) {throw std::invalid_argument("Missing option value");}
      const std::string value = argv[++i];
      if (option == "--fps") {fps = std::stoi(value);}
      else if (option == "--topic") {topic = value;}
      else {throw std::invalid_argument("Unknown option: " + option);}
    }
    if (fps < 1 || fps > 15) {throw std::invalid_argument("fps must be 1..15");}
  } catch (const std::exception & error) {std::cerr << error.what() << '\n'; return 1;}
  rclcpp::init(0, nullptr);
  signal(SIGPIPE, SIG_IGN);
  auto node = std::make_shared<rclcpp::Node>("jpeg_topic_stream");
  using Image = sensor_msgs::msg::CompressedImage;
  std::atomic_bool stop{false};
  std::mutex mutex;
  std::condition_variable available;
  Image::ConstSharedPtr latest;
  auto completion = node->create_subscription<std_msgs::msg::Bool>(
    "/vision/qr/session_complete", rclcpp::QoS(1).reliable().transient_local(),
    [&](std_msgs::msg::Bool::ConstSharedPtr message) {
      if (message->data) {stop.store(true); available.notify_all();}
    });
  auto subscription = node->create_subscription<Image>(topic,
    rclcpp::SensorDataQoS().keep_last(1), [&](Image::ConstSharedPtr message) {
      std::lock_guard<std::mutex> guard(mutex);
      latest = std::move(message);
      available.notify_one();
    });
  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(node);
  std::thread receiver([&] {executor.spin(); stop.store(true); available.notify_all();});
  fcntl(STDOUT_FILENO, F_SETFL, fcntl(STDOUT_FILENO, F_GETFL) | O_NONBLOCK);
  int result = 0;
  try {
    RCLCPP_INFO(node->get_logger(), "JPEG relay: original bytes, at most %d fps, one frame in flight", fps);
    auto next = vision_cpp::Clock::now();
    auto last_frame = next;
    while (!stop.load()) {
      Image::ConstSharedPtr frame;
      {
        std::unique_lock<std::mutex> guard(mutex);
        available.wait_for(guard, std::chrono::milliseconds(20), [&] {
            return stop.load() || (latest && vision_cpp::Clock::now() >= next);
          });
        if (stop.load()) {break;}
        if (vision_cpp::Clock::now() < next || !latest) {
          if (vision_cpp::Clock::now() - last_frame > std::chrono::seconds(5)) {
            throw std::runtime_error("No camera JPEG for 5 seconds");
          }
          continue;
        }
        frame = std::move(latest);
      }
      last_frame = vision_cpp::Clock::now();
      next = last_frame + std::chrono::nanoseconds(1000000000 / fps);
      if (frame->data.size() < 4 || frame->data[0] != 0xff || frame->data[1] != 0xd8) {
        throw std::runtime_error("Camera topic did not contain JPEG");
      }
      // Never re-encode; QR sees exactly the original camera image on the Pi.
      vision_cpp::write_jpeg(STDOUT_FILENO, frame->data, stop);
      const auto deadline = vision_cpp::Clock::now() + std::chrono::seconds(5);
      bool acknowledged = false;
      while (!stop.load() && vision_cpp::Clock::now() < deadline) {
        pollfd descriptor{STDIN_FILENO, POLLIN, 0};
        const int status = poll(&descriptor, 1, 100);
        if (status < 0 && errno == EINTR) {continue;}
        if (status < 0) {throw std::runtime_error("ACK poll failed");}
        if (descriptor.revents & POLLIN) {
          char ack;
          if (read(STDIN_FILENO, &ack, 1) != 1 || ack != 'A') {
            throw std::runtime_error("Invalid/closed JPEG acknowledgement");
          }
          acknowledged = true;
          break;
        }
        if (descriptor.revents & (POLLERR | POLLHUP | POLLNVAL)) {
          throw std::runtime_error("JPEG receiver disconnected");
        }
      }
      if (!acknowledged && !stop.load()) {throw std::runtime_error("JPEG acknowledgement timed out");}
    }
  } catch (const std::exception & error) {
    if (!stop.load()) {RCLCPP_ERROR(node->get_logger(), "%s", error.what()); result = 1;}
  }
  stop.store(true);
  executor.cancel(); receiver.join(); rclcpp::shutdown();
  return result;
}
