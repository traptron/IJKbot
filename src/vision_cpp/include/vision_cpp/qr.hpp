#pragma once
#include "vision_cpp/camera.hpp"
#include <optional>
#include <opencv2/objdetect.hpp>
#include <opencv2/wechat_qrcode.hpp>

namespace vision_cpp {
struct Detection {
  std::string text;
  std::vector<cv::Point> corners;
  cv::Mat image;
};
class QrDecoder {
public:
  std::optional<Detection> decode(const Bytes & jpeg);
  Bytes annotate(const Detection & detection);
private:
  cv::wechat_qrcode::WeChatQRCode wechat_;
  cv::QRCodeDetector fallback_;
};
class Confirmation {
public:
  explicit Confirmation(int required) : required_(required) {
    if (required < 1) {throw std::invalid_argument("confirm_frames must be >= 1");}
  }
  std::optional<std::string> observe(const std::string & text);
  void reset() {candidate_.clear(); published_.clear(); count_ = 0;}
private:
  int required_, count_ = 0;
  std::string candidate_, published_;
};
}  // namespace vision_cpp
