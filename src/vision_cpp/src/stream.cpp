#include "vision_cpp/camera.hpp"
#include <csignal>
#include <fcntl.h>
#include <iostream>
#include <stdexcept>
#include <unistd.h>

namespace {
std::atomic_bool stopped{false};
void stop(int) {stopped.store(true);}
}
int main(int argc, char ** argv) {
  signal(SIGINT, stop);
  signal(SIGTERM, stop);
  signal(SIGPIPE, SIG_IGN);
  try {
    vision_cpp::Options options;
    bool stdin_raw = false;
    for (int i = 1; i < argc; ++i) {
      const std::string argument = argv[i];
      if (argument == "--raw-stdin") {stdin_raw = true;}
      else if (argument == "--mock") {options.mock = true;}
      else if (argument == "--monochrome") {options.monochrome = true;}
      else if (argument == "--help") {
        std::cerr << "csi_jpeg_stream [--fps 10] [--quality 85] [--device /dev/video0] "
          "[--width 640] [--height 480] [--exposure 2500] [--gain 320] "
          "[--mock] [--monochrome] [--raw-stdin]\n";
        return 0;
      } else {
        if (i + 1 >= argc) {throw std::invalid_argument("Missing option value");}
        const std::string value = argv[++i];
        if (argument == "--fps") {options.fps = std::stoi(value);}
        else if (argument == "--quality") {options.quality = std::stoi(value);}
        else if (argument == "--width") {options.width = std::stoi(value);}
        else if (argument == "--height") {options.height = std::stoi(value);}
        else if (argument == "--device") {options.device = value;}
        else if (argument == "--subdevice") {options.subdevice = value;}
        else if (argument == "--exposure") {options.exposure = std::stoi(value);}
        else if (argument == "--gain") {options.gain = std::stoi(value);}
        else if (argument == "--backend") {options.backend = value;}
        else {throw std::invalid_argument("Unknown option: " + argument);}
      }
    }
    options.validate();
    cv::setNumThreads(1);
    fcntl(STDOUT_FILENO, F_SETFL, fcntl(STDOUT_FILENO, F_GETFL) | O_NONBLOCK);
    auto sink = [](vision_cpp::Bytes && jpeg) {
        vision_cpp::write_jpeg(STDOUT_FILENO, jpeg, stopped);
      };
    if (stdin_raw) {
      // Deterministic offline conversion for regression tests; no camera required.
      vision_cpp::Encoder encoder(options.quality, options.width, options.height,
        options.monochrome);
      vision_cpp::Bytes raw(static_cast<size_t>(options.width) * options.height * 5 / 4);
      while (!stopped.load()) {
        std::cin.read(reinterpret_cast<char *>(raw.data()), raw.size());
        if (std::cin.gcount() == 0 && std::cin.eof()) {break;}
        if (static_cast<size_t>(std::cin.gcount()) != raw.size()) {
          throw std::runtime_error("Incomplete RAW frame on stdin");
        }
        sink(encoder.encode(raw.data(), raw.size()));
      }
    } else {
      // Exit on transport errors: a partially written JPEG cannot be restarted in place.
      vision_cpp::capture(options, stopped, sink);
    }
    return 0;
  } catch (const std::exception & error) {
    std::cerr << "CSI stream: " << error.what() << '\n';
    return stopped.load() ? 0 : 1;
  }
}
