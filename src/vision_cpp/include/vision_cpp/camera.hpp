#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <string>
#include <vector>
#include <opencv2/core.hpp>

namespace vision_cpp {
using Bytes = std::vector<uint8_t>;
using Clock = std::chrono::steady_clock;
constexpr int kWidth = 640;
constexpr int kHeight = 480;
constexpr size_t kRawBytes = kWidth * kHeight * 5 / 4;

struct Options {
  int fps = 10;
  int quality = 85;
  int exposure = 2500;
  int gain = 320;
  int width = kWidth;
  int height = kHeight;
  std::string device = "/dev/video0";
  std::string subdevice = "/dev/v4l-subdev0";
  std::string backend = "v4l2_raw";
  std::string camera_name;
  bool mock = false;
  void validate() const;
};

// Preserve the legacy demosaic, white balance, gamma and saturation processing.
class Encoder {
public:
  explicit Encoder(int quality = 85, int width = kWidth, int height = kHeight);
  Bytes encode(const uint8_t * raw, size_t bytes, size_t stride = 0);
  cv::Mat correct_color(const cv::Mat & bgr);
private:
  int quality_, width_, height_;
  cv::Mat bayer_, bgr_, balanced_, gray_, hsv_, lookup_;
};

class MjpegFramer {
public:
  explicit MjpegFramer(size_t limit = 2000000) : limit_(limit) {}
  std::vector<Bytes> feed(const uint8_t * data, size_t size);
  size_t buffered() const {return buffer_.size();}
private:
  size_t limit_;
  Bytes buffer_;
};

// No shell, bounded shutdown, stderr never contaminates the JPEG pipe.
class ChildPipe {
public:
  explicit ChildPipe(const std::vector<std::string> & argv);
  ~ChildPipe();
  ChildPipe(const ChildPipe &) = delete;
  ChildPipe & operator=(const ChildPipe &) = delete;
  int fd() const {return fd_;}
private:
  int fd_ = -1;
  int pid_ = -1;
};

using Sink = std::function<void(Bytes &&)>;
using Log = std::function<void(const std::string &)>;
void capture(const Options & options, const std::atomic_bool & stop, const Sink & sink);
void read_mjpeg(int fd, const std::atomic_bool & stop, const Sink & sink, int fps);
void write_jpeg(int fd, const Bytes & jpeg, const std::atomic_bool & stop);
void run_capture(const Options & options, const std::atomic_bool & stop,
  const Sink & sink, const Log & log);
}  // namespace vision_cpp
