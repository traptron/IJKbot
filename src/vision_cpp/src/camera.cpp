#include "vision_cpp/camera.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <cmath>
#include <cstring>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <linux/v4l2-subdev.h>
#include <linux/media-bus-format.h>
#include <poll.h>
#include <spawn.h>
#include <stdexcept>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

extern char ** environ;
namespace vision_cpp {
namespace {
void fail(const std::string & operation) {
  throw std::runtime_error(operation + ": " + std::strerror(errno));
}
int control(int fd, unsigned long request, void * arg) {
  int result;
  do {result = ioctl(fd, request, arg);} while (result < 0 && errno == EINTR);
  return result;
}
void checked(int fd, unsigned long request, void * arg, const char * label) {
  if (control(fd, request, arg) < 0) {fail(label);}
}
bool ready(int fd, short events, const std::atomic_bool & stop) {
  pollfd descriptor{fd, events, 0};
  while (!stop.load()) {
    const int result = poll(&descriptor, 1, 100);
    if (result < 0 && errno == EINTR) {continue;}
    if (result < 0) {fail("poll");}
    if (result == 0) {return false;}
    if (descriptor.revents & (POLLERR | POLLNVAL)) {
      throw std::runtime_error("Camera/transport closed");
    }
    if (descriptor.revents & events) {return true;}
    if (descriptor.revents & POLLHUP) {throw std::runtime_error("Camera/transport closed");}
  }
  return false;
}
class V4l2 {
public:
  explicit V4l2(const Options & options) : height_(options.height) {
    try {
      fd_ = open(options.device.c_str(), O_RDWR | O_NONBLOCK | O_CLOEXEC);
      if (fd_ < 0) {fail("Open camera");}
      v4l2_capability caps{};
      checked(fd_, VIDIOC_QUERYCAP, &caps, "QUERYCAP");
      const auto flags = caps.capabilities & V4L2_CAP_DEVICE_CAPS ?
        caps.device_caps : caps.capabilities;
      if (!(flags & V4L2_CAP_VIDEO_CAPTURE) || !(flags & V4L2_CAP_STREAMING)) {
        throw std::runtime_error("Camera does not support single-plane mmap capture");
      }
      v4l2_format format{};
      format.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
      format.fmt.pix.width = options.width;
      format.fmt.pix.height = options.height;
      format.fmt.pix.pixelformat = V4L2_PIX_FMT_SGBRG10P;
      format.fmt.pix.field = V4L2_FIELD_NONE;
      // These are the same sensor settings as the original Python publisher.
      const int subfd = open(options.subdevice.c_str(), O_RDWR | O_CLOEXEC);
      if (subfd < 0) {fail("Open camera controls");}
      v4l2_subdev_format sensor{};
      sensor.which = V4L2_SUBDEV_FORMAT_ACTIVE;
      sensor.pad = 0;
      sensor.format.width = options.width;
      sensor.format.height = options.height;
      sensor.format.code = MEDIA_BUS_FMT_SGBRG10_1X10;
      const bool format_ok = control(subfd, VIDIOC_SUBDEV_S_FMT, &sensor) == 0;
      if (!format_ok || sensor.format.width != static_cast<unsigned>(options.width) ||
        sensor.format.height != static_cast<unsigned>(options.height))
      {
        close(subfd);
        throw std::runtime_error("Sensor rejected requested capture resolution");
      }
      v4l2_control exposure{V4L2_CID_EXPOSURE, options.exposure};
      v4l2_control gain{V4L2_CID_ANALOGUE_GAIN, options.gain};
      const bool controls_ok = control(subfd, VIDIOC_S_CTRL, &exposure) == 0 &&
        control(subfd, VIDIOC_S_CTRL, &gain) == 0;
      const int saved_errno = errno;
      close(subfd);
      if (!controls_ok) {errno = saved_errno; fail("Set camera exposure/gain");}
      checked(fd_, VIDIOC_S_FMT, &format, "S_FMT");
      if (format.fmt.pix.width != static_cast<unsigned>(options.width) ||
        format.fmt.pix.height != static_cast<unsigned>(options.height) ||
        format.fmt.pix.pixelformat != V4L2_PIX_FMT_SGBRG10P ||
        format.fmt.pix.bytesperline < static_cast<unsigned>(options.width * 5 / 4))
      {
        throw std::runtime_error("Capture resolution/packed GBRG10 format mismatch");
      }
      stride_ = format.fmt.pix.bytesperline;
      v4l2_requestbuffers request{};
      request.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
      request.memory = V4L2_MEMORY_MMAP;
      request.count = 4;
      checked(fd_, VIDIOC_REQBUFS, &request, "REQBUFS");
      if (request.count < 2 || request.count > 32) {
        throw std::runtime_error("Invalid camera buffer count");
      }
      for (unsigned i = 0; i < request.count; ++i) {
        auto buffer = descriptor(i);
        checked(fd_, VIDIOC_QUERYBUF, &buffer, "QUERYBUF");
        void * address = mmap(nullptr, buffer.length, PROT_READ | PROT_WRITE,
          MAP_SHARED, fd_, buffer.m.offset);
        if (address == MAP_FAILED) {fail("mmap camera");}
        buffers_.push_back({address, buffer.length});
        checked(fd_, VIDIOC_QBUF, &buffer, "QBUF");
      }
      auto type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
      checked(fd_, VIDIOC_STREAMON, &type, "STREAMON");
      streaming_ = true;
    } catch (...) {cleanup(); throw;}
  }
  ~V4l2() {cleanup();}
  V4l2(const V4l2 &) = delete;
  V4l2 & operator=(const V4l2 &) = delete;
  bool latest(Bytes & raw, const std::atomic_bool & stop) {
    if (!ready(fd_, POLLIN, stop)) {return false;}
    // Hold dequeued buffers until the current queue is drained; requeuing inside
    // the drain could otherwise consume an endless stream on a slow computer.
    std::vector<v4l2_buffer> completed;
    completed.reserve(buffers_.size());
    while (completed.size() < buffers_.size()) {
      auto buffer = descriptor(0);
      if (control(fd_, VIDIOC_DQBUF, &buffer) < 0) {
        if (errno == EAGAIN) {break;}
        fail("DQBUF");
      }
      if (buffer.index >= buffers_.size() || buffer.bytesused > buffers_[buffer.index].size) {
        throw std::runtime_error("Invalid camera buffer");
      }
      completed.push_back(buffer);
    }
    bool found = false;
    for (auto it = completed.rbegin(); it != completed.rend(); ++it) {
      if (!(it->flags & V4L2_BUF_FLAG_ERROR) && it->bytesused >= stride_ * height_) {
        const auto * data = static_cast<const uint8_t *>(buffers_[it->index].address);
        raw.assign(data, data + stride_ * height_);
        found = true;
        break;
      }
    }
    for (auto & buffer : completed) {checked(fd_, VIDIOC_QBUF, &buffer, "QBUF");}
    return found;
  }
  size_t stride() const {return stride_;}
private:
  struct Mapping {void * address; size_t size;};
  static v4l2_buffer descriptor(unsigned index) {
    v4l2_buffer buffer{};
    buffer.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    buffer.memory = V4L2_MEMORY_MMAP;
    buffer.index = index;
    return buffer;
  }
  void cleanup() {
    if (streaming_) {
      auto type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
      control(fd_, VIDIOC_STREAMOFF, &type);
    }
    for (auto & buffer : buffers_) {munmap(buffer.address, buffer.size);}
    buffers_.clear();
    if (fd_ >= 0) {close(fd_); fd_ = -1;}
  }
  int fd_ = -1;
  bool streaming_ = false;
  size_t stride_ = 800;
  int height_;
  std::vector<Mapping> buffers_;
};
}  // namespace

void Options::validate() const {
  if (width < 64 || width > 2592 || width % 4 || height < 64 || height > 1944 || height % 2) {
    throw std::invalid_argument("Capture width must be 64..2592, multiple of 4; height 64..1944, even");
  }
  if (fps < 1 || fps > 15 || quality < 1 || quality > 100) {
    throw std::invalid_argument("fps must be 1..15; jpeg_quality must be 1..100");
  }
  if (backend != "v4l2_raw" && backend != "libcamera") {
    throw std::invalid_argument("backend must be v4l2_raw or libcamera");
  }
  if (exposure < 4 || exposure > 3145 || gain < 16 || gain > 1023) {
    throw std::invalid_argument("OV5647 exposure/analogue_gain out of range");
  }
  if (camera_name.find_first_of("\r\n") != std::string::npos ||
    camera_name.find('\0') != std::string::npos)
  {throw std::invalid_argument("Invalid camera_name");}
}

Encoder::Encoder(int quality, int width, int height) : quality_(quality), width_(width), height_(height),
  lookup_(1, 256, CV_8UC3)
{
  if (quality < 1 || quality > 100) {throw std::invalid_argument("Invalid JPEG quality");}
  Options options;
  options.width = width; options.height = height;
  options.validate();
  bayer_.create(height, width, CV_8U);
}
cv::Mat Encoder::correct_color(const cv::Mat & bgr) {
  const auto means = cv::mean(bgr);
  const double reference = (means[0] + means[1] + means[2]) / 3;
  // Preserve NumPy's gain multiplication and uint8 truncation using tiny LUTs.
  for (int value = 0; value < 256; ++value) {
    auto & mapped = lookup_.at<cv::Vec3b>(0, value);
    for (int channel = 0; channel < 3; ++channel) {
      const double gain = std::clamp(reference / std::max(means[channel], 1.0), 0.75, 1.35);
      mapped[channel] = static_cast<uint8_t>(std::min(255.0, value * gain));
    }
  }
  cv::LUT(bgr, lookup_, balanced_);
  cv::cvtColor(balanced_, gray_, cv::COLOR_BGR2GRAY);
  const double luminance = cv::mean(gray_)[0];
  if (luminance < 110) {
    const double gamma = std::clamp(std::log(0.5) /
      std::log(std::max(luminance / 255, 1.0 / 255)), 0.42, 0.88);
    for (int value = 0; value < 256; ++value) {
      const auto mapped = static_cast<uint8_t>(std::nearbyint(std::pow(value / 255.0, gamma) * 255));
      lookup_.at<cv::Vec3b>(0, value) = cv::Vec3b(mapped, mapped, mapped);
    }
    cv::LUT(balanced_, lookup_, balanced_);
  }
  cv::cvtColor(balanced_, hsv_, cv::COLOR_BGR2HSV);
  for (int row = 0; row < hsv_.rows; ++row) {
    auto * pixels = hsv_.ptr<cv::Vec3b>(row);
    for (int column = 0; column < hsv_.cols; ++column) {
      pixels[column][1] = static_cast<uint8_t>(std::min(255.0F, pixels[column][1] * 2.5F));
    }
  }
  cv::cvtColor(hsv_, balanced_, cv::COLOR_HSV2BGR);
  return balanced_;
}
Bytes Encoder::encode(const uint8_t * raw, size_t bytes, size_t stride) {
  if (stride == 0) {stride = static_cast<size_t>(width_) * 5 / 4;}
  if (!raw || stride < static_cast<size_t>(width_) * 5 / 4 || bytes != stride * height_) {
    throw std::invalid_argument("Incomplete packed GBRG10 frame");
  }
  for (int row = 0; row < height_; ++row) {
    auto * target = bayer_.ptr<uint8_t>(row);
    const auto * source = raw + row * stride;
    // The legacy path uses the high eight bits of each RAW10 sample; preserve it.
    for (int group = 0; group < width_ / 4; ++group) {
      std::memcpy(target + group * 4, source + group * 5, 4);
    }
  }
  cv::cvtColor(bayer_, bgr_, cv::COLOR_BayerGBRG2BGR);
  Bytes jpeg;
  // Huffman optimisation shrinks the stream without changing decoded pixels.
  if (!cv::imencode(".jpg", correct_color(bgr_), jpeg,
    {cv::IMWRITE_JPEG_QUALITY, quality_, cv::IMWRITE_JPEG_OPTIMIZE, 1}))
  {
    throw std::runtime_error("Camera JPEG encoding failed");
  }
  return jpeg;
}

std::vector<Bytes> MjpegFramer::feed(const uint8_t * data, size_t size) {
  std::vector<Bytes> frames;
  // Append in bounded pieces even if a caller passes an arbitrarily large chunk.
  for (size_t offset = 0; offset < size;) {
    const size_t count = std::min<size_t>(65536, size - offset);
    buffer_.insert(buffer_.end(), data + offset, data + offset + count);
    offset += count;
    while (!buffer_.empty()) {
      const std::array<uint8_t, 2> start_marker{0xff, 0xd8}, end_marker{0xff, 0xd9};
      auto start = std::search(buffer_.begin(), buffer_.end(), start_marker.begin(), start_marker.end());
      if (start == buffer_.end()) {
        const bool trailing_ff = buffer_.back() == 0xff;
        buffer_.clear();
        if (trailing_ff) {buffer_.push_back(0xff);}
        break;
      }
      buffer_.erase(buffer_.begin(), start);
      auto end = std::search(buffer_.begin() + 2, buffer_.end(), end_marker.begin(), end_marker.end());
      const size_t frame_size = end == buffer_.end() ? buffer_.size() :
        static_cast<size_t>(end - buffer_.begin()) + 2;
      if (frame_size > limit_) {
        buffer_.clear();
        throw std::runtime_error("JPEG exceeds bounded capture buffer");
      }
      if (end == buffer_.end()) {break;}
      frames.emplace_back(buffer_.begin(), end + 2);
      buffer_.erase(buffer_.begin(), end + 2);
    }
  }
  return frames;
}

ChildPipe::ChildPipe(const std::vector<std::string> & arguments) {
  if (arguments.empty()) {throw std::invalid_argument("Empty capture command");}
  int pipefd[2];
  if (pipe2(pipefd, O_CLOEXEC) < 0) {fail("pipe2");}
  posix_spawn_file_actions_t actions;
  posix_spawn_file_actions_init(&actions);
  posix_spawn_file_actions_adddup2(&actions, pipefd[1], STDOUT_FILENO);
  posix_spawn_file_actions_addclose(&actions, pipefd[0]);
  posix_spawn_file_actions_addclose(&actions, pipefd[1]);
  std::vector<char *> argv;
  for (const auto & argument : arguments) {argv.push_back(const_cast<char *>(argument.c_str()));}
  argv.push_back(nullptr);
  const int error = posix_spawnp(&pid_, argv[0], &actions, nullptr, argv.data(), environ);
  posix_spawn_file_actions_destroy(&actions);
  close(pipefd[1]);
  if (error) {close(pipefd[0]); pid_ = -1; errno = error; fail("Spawn capture");}
  fd_ = pipefd[0];
  fcntl(fd_, F_SETFL, fcntl(fd_, F_GETFL) | O_NONBLOCK);
}
ChildPipe::~ChildPipe() {
  if (fd_ >= 0) {close(fd_);}
  if (pid_ < 0) {return;}
  kill(pid_, SIGTERM);
  for (int attempt = 0; attempt < 20; ++attempt) {
    const int result = waitpid(pid_, nullptr, WNOHANG);
    if (result == pid_ || (result < 0 && errno == ECHILD)) {return;}
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
  }
  kill(pid_, SIGKILL);
  while (waitpid(pid_, nullptr, 0) < 0 && errno == EINTR) {}
}

void read_mjpeg(int fd, const std::atomic_bool & stop, const Sink & sink, int fps) {
  if (fps < 1 || fps > 15) {throw std::invalid_argument("Invalid fps");}
  MjpegFramer parser;
  std::array<uint8_t, 65536> chunk{};
  auto last_frame = Clock::now();
  auto next = Clock::time_point::min();
  while (!stop.load()) {
    if (Clock::now() - last_frame > std::chrono::seconds(5)) {
      throw std::runtime_error("No camera JPEG frames for 5 seconds");
    }
    if (!ready(fd, POLLIN, stop)) {continue;}
    const auto size = read(fd, chunk.data(), chunk.size());
    if (size < 0 && (errno == EAGAIN || errno == EINTR)) {continue;}
    if (size <= 0) {throw std::runtime_error("Camera JPEG output closed");}
    auto frames = parser.feed(chunk.data(), static_cast<size_t>(size));
    if (frames.empty()) {continue;}
    last_frame = Clock::now();
    if (last_frame >= next) {
      const auto period = std::chrono::nanoseconds(1000000000 / fps);
      next = next == Clock::time_point::min() ? last_frame + period : next + period;
      if (next <= last_frame) {next = last_frame + period;}
      sink(std::move(frames.back()));
    }
  }
}
void capture(const Options & options, const std::atomic_bool & stop, const Sink & sink) {
  options.validate();
  if (options.mock || options.backend == "libcamera") {
    std::vector<std::string> command{"gst-launch-1.0", "-q",
      options.mock ? "videotestsrc" : "libcamerasrc"};
    if (options.mock) {command.push_back("is-live=true");}
    if (!options.mock && !options.camera_name.empty()) {
      command.push_back("camera-name=" + options.camera_name);
    }
    const std::vector<std::string> tail{"!", "video/x-raw,width=" + std::to_string(options.width) +
      ",height=" + std::to_string(options.height) + ",framerate=" +
      std::to_string(options.fps) + "/1", "!", "videoconvert", "!", "video/x-raw,format=I420",
      "!", "jpegenc", "quality=" + std::to_string(options.quality), "!", "fdsink", "fd=1"};
    command.insert(command.end(), tail.begin(), tail.end());
    ChildPipe child(command);
    read_mjpeg(child.fd(), stop, sink, options.fps);
    return;
  }
  V4l2 camera(options);
  Encoder encoder(options.quality, options.width, options.height);
  Bytes raw;
  auto last_frame = Clock::now();
  auto next = Clock::time_point::min();
  while (!stop.load()) {
    if (Clock::now() - last_frame > std::chrono::seconds(5)) {
      throw std::runtime_error("No camera RAW frames for 5 seconds");
    }
    if (!camera.latest(raw, stop)) {continue;}
    last_frame = Clock::now();
    if (last_frame < next) {continue;}
    // Rate-limit BEFORE expensive demosaic and encoding, never accumulate frames.
    const auto period = std::chrono::nanoseconds(1000000000 / options.fps);
    next = next == Clock::time_point::min() ? last_frame + period : next + period;
    if (next <= last_frame) {next = last_frame + period;}
    sink(encoder.encode(raw.data(), raw.size(), camera.stride()));
  }
}
void write_jpeg(int fd, const Bytes & jpeg, const std::atomic_bool & stop) {
  auto deadline = Clock::now() + std::chrono::seconds(2);
  size_t offset = 0;
  while (offset < jpeg.size() && !stop.load()) {
    if (Clock::now() > deadline) {
      throw std::runtime_error("JPEG output stalled for 2 seconds");
    }
    if (!ready(fd, POLLOUT, stop)) {continue;}
    const auto count = write(fd, jpeg.data() + offset, jpeg.size() - offset);
    if (count < 0 && (errno == EAGAIN || errno == EINTR)) {continue;}
    if (count <= 0) {fail("Write JPEG");}
    offset += static_cast<size_t>(count);
  }
}
void run_capture(const Options & options, const std::atomic_bool & stop,
  const Sink & sink, const Log & log)
{
  while (!stop.load()) {
    try {capture(options, stop, sink);} catch (const std::exception & error) {
      if (!stop.load()) {log(std::string(error.what()) + "; retry in 2 seconds");}
    }
    for (int i = 0; i < 20 && !stop.load(); ++i) {
      std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
  }
}
}  // namespace vision_cpp
