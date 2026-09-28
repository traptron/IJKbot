#include "vision_cpp/qr.hpp"
#include <cmath>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

namespace vision_cpp {
std::optional<std::string> Confirmation::observe(const std::string & text) {
  if (text.empty()) {reset(); return std::nullopt;}
  if (text != candidate_) {candidate_ = text; count_ = 1;}
  else if (count_ < required_) {++count_;}
  if (count_ >= required_ && published_ != text) {published_ = text; return text;}
  return std::nullopt;
}
std::optional<Detection> QrDecoder::decode(const Bytes & jpeg) {
  if (jpeg.empty()) {return std::nullopt;}
  auto image = cv::imdecode(jpeg, cv::IMREAD_COLOR);
  if (image.empty()) {return std::nullopt;}
  std::string text;
  cv::Mat points;
  int selected_scale = 1;
  // Preserve WeChat first and the 2x/4x nearest-neighbour small-code fallbacks.
  for (int detector = 0; detector < 2 && text.empty(); ++detector) {
    for (const int scale : {1, 2, 4}) {
      if (scale != 1 && image.rows > 640 && image.cols > 640) {break;}
      cv::Mat input = image;
      if (scale != 1) {cv::resize(image, input, {}, scale, scale, cv::INTER_NEAREST);}
      try {
        if (detector == 0) {
          std::vector<cv::Mat> bounds;
          auto texts = wechat_.detectAndDecode(input, bounds);
          for (size_t i = 0; i < texts.size(); ++i) {
            if (!texts[i].empty()) {
              text = texts[i];
              if (i < bounds.size()) {points = bounds[i];}
              break;
            }
          }
        } else {text = fallback_.detectAndDecode(input, points);}
      } catch (const cv::Exception &) {text.clear(); points.release();}
      if (!text.empty()) {selected_scale = scale; break;}
    }
  }
  if (text.empty()) {return std::nullopt;}
  // Model-free WeChat can report the full input as its bounds. Refine the
  // evidence polygon with OpenCV's geometric detector without decoding twice.
  if (!points.empty()) {
    cv::Mat flattened;
    points.reshape(1, static_cast<int>(points.total() * points.channels() / 2)).convertTo(flattened, CV_32F);
    const auto last_x = (image.cols * selected_scale) - 1;
    const auto last_y = (image.rows * selected_scale) - 1;
    if (flattened.rows == 4 && flattened.at<float>(0, 0) == 0 &&
      flattened.at<float>(0, 1) == 0 && flattened.at<float>(2, 0) == last_x &&
      flattened.at<float>(2, 1) == last_y)
    {
      cv::Mat refined;
      try {
        if (fallback_.detect(image, refined)) {points = refined; selected_scale = 1;}
      } catch (const cv::Exception &) { /* Keep WeChat bounds if refinement fails. */ }
    }
  }
  Detection result{text, {}, image};
  if (!points.empty()) {
    cv::Mat coordinates;
    points.reshape(1, static_cast<int>(points.total() * points.channels() / 2)).convertTo(coordinates, CV_32F);
    for (int i = 0; i < coordinates.rows; ++i) {
      result.corners.emplace_back(
        static_cast<int>(std::nearbyint(coordinates.at<float>(i, 0) / selected_scale)),
        static_cast<int>(std::nearbyint(coordinates.at<float>(i, 1) / selected_scale)));
    }
  }
  return result;
}
Bytes QrDecoder::annotate(const Detection & detection) {
  auto image = detection.image.clone();
  if (detection.corners.size() >= 3) {
    cv::polylines(image, std::vector<std::vector<cv::Point>>{detection.corners}, true, {0, 255, 0}, 3);
  }
  Bytes jpeg;
  if (!cv::imencode(".jpg", image, jpeg)) {throw std::runtime_error("QR evidence JPEG encoding failed");}
  return jpeg;
}
}  // namespace vision_cpp
