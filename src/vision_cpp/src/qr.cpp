#include "vision_cpp/qr.hpp"
#include <algorithm>
#include <cmath>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

namespace vision_cpp {
namespace {
// Dense QR payloads can defeat QRCodeDetector's geometric grouping. Their three
// nested finder squares are still visible; locate those with ordinary OpenCV
// contours, retaining original pixels (including quiet-zone padding) for decoding.
std::optional<cv::Rect> finder_region(const cv::Mat & gray) {
  for (bool adaptive : {false, true}) {
    cv::Mat binary;
    if (adaptive) {
      cv::adaptiveThreshold(gray, binary, 255, cv::ADAPTIVE_THRESH_GAUSSIAN_C,
        cv::THRESH_BINARY_INV, 31, 7);
    } else {cv::threshold(gray, binary, 0, 255, cv::THRESH_BINARY_INV | cv::THRESH_OTSU);}
    std::vector<std::vector<cv::Point>> contours;
    std::vector<cv::Vec4i> hierarchy;
    cv::findContours(binary, contours, hierarchy, cv::RETR_TREE, cv::CHAIN_APPROX_SIMPLE);
    std::vector<cv::Rect> finders;
    for (size_t i = 0; i < contours.size(); ++i) {
      const int child = hierarchy[i][2];
      if (child < 0 || hierarchy[child][2] < 0) {continue;}
      const auto outer = cv::boundingRect(contours[i]);
      if (outer.width < 7 || outer.height < 7 || outer.width > outer.height * 1.6 ||
        outer.height > outer.width * 1.6) {continue;}
      std::vector<cv::Point> polygon;
      cv::approxPolyDP(contours[i], polygon, cv::arcLength(contours[i], true) * 0.04, true);
      if (polygon.size() != 4 || !cv::isContourConvex(polygon)) {continue;}
      const auto inner = cv::boundingRect(contours[hierarchy[child][2]]);
      const double ratio = static_cast<double>(inner.area()) / outer.area();
      if (ratio < 0.08 || ratio > 0.4 ||
        std::abs((inner.x + inner.width / 2.0) - (outer.x + outer.width / 2.0)) > outer.width * 0.2 ||
        std::abs((inner.y + inner.height / 2.0) - (outer.y + outer.height / 2.0)) > outer.height * 0.2)
      {continue;}
      finders.push_back(outer);
    }
    // Bound candidate combinations even in heavily textured scenes.
    std::sort(finders.begin(), finders.end(), [](const auto & a, const auto & b) {return a.area() > b.area();});
    if (finders.size() > 32) {finders.resize(32);}
    auto center = [](const cv::Rect & r) {return cv::Point2f(r.x + r.width / 2.0F, r.y + r.height / 2.0F);};
    for (size_t i = 0; i < finders.size(); ++i) {
      for (size_t j = 0; j < finders.size(); ++j) {
        if (j == i) {continue;}
        for (size_t k = j + 1; k < finders.size(); ++k) {
          if (k == i) {continue;}
          const auto a = center(finders[i]), b = center(finders[j]), c = center(finders[k]);
          const auto u = b - a, v = c - a;
          const double lu = cv::norm(u), lv = cv::norm(v);
          const int largest = std::max({finders[i].width, finders[j].width, finders[k].width});
          const int smallest = std::min({finders[i].width, finders[j].width, finders[k].width});
          if (largest > smallest * 1.8 || lu < largest * 2 || lv < largest * 2 ||
            lu > lv * 1.8 || lv > lu * 1.8 || std::abs(u.dot(v)) > lu * lv * 0.25) {continue;}
          const std::vector<cv::Point2f> corners{a, b, c, b + c - a};
          const auto box = cv::boundingRect(corners);
          const int margin = std::max(12, static_cast<int>(largest * 1.2));
          return cv::Rect(box.x - margin, box.y - margin, box.width + 2 * margin,
            box.height + 2 * margin) & cv::Rect(0, 0, gray.cols, gray.rows);
        }
      }
    }
  }
  return std::nullopt;
}
}  // namespace
std::optional<std::string> Confirmation::observe(const std::string & text) {
  if (text.empty()) {reset(); return std::nullopt;}
  if (text != candidate_) {candidate_ = text; count_ = 1;}
  else if (count_ < required_) {++count_;}
  if (count_ >= required_ && published_ != text) {published_ = text; return text;}
  return std::nullopt;
}
std::optional<Detection> QrDecoder::decode(const Bytes & jpeg, bool exhaustive) {
  if (jpeg.empty()) {return std::nullopt;}
  auto original = cv::imdecode(jpeg, cv::IMREAD_COLOR);
  if (original.empty()) {return std::nullopt;}
  auto image = original;
  cv::Point origin;
  // Model-free WeChat spends tens of seconds scanning a large, noisy scene.
  // Locate a candidate cheaply, then crop ORIGINAL pixels for all text decoding.
  // The smaller image is used only for geometry, never to decode the payload.
  if (std::max(original.cols, original.rows) > 800) {
    cv::Mat gray_full, locator, candidate;
    cv::cvtColor(original, gray_full, cv::COLOR_BGR2GRAY);
    auto region = finder_region(gray_full);
    if (!region) {
      const double ratio = 640.0 / std::max(original.cols, original.rows);
      cv::resize(gray_full, locator, {}, ratio, ratio, cv::INTER_AREA);
      bool found = fallback_.detect(locator, candidate);
      if (found) {candidate /= ratio;}
      // Periodic full-resolution geometry search retains small finder patterns
      // that the cheap locator could miss, without doing it on every empty frame.
      if (!found && (exhaustive || search_frame_++ % 4 == 0)) {
        found = fallback_.detect(gray_full, candidate);
      }
      if (!found) {return std::nullopt;}
      const auto box = cv::boundingRect(candidate);
      const int margin = std::max(12, std::max(box.width, box.height) / 8);
      region = cv::Rect(box.x - margin, box.y - margin,
        box.width + 2 * margin, box.height + 2 * margin) & cv::Rect(0, 0, original.cols, original.rows);
    }
    if (region->empty()) {return std::nullopt;}
    origin = region->tl();
    image = original(*region);
  }
  std::string text;
  cv::Mat points;
  int selected_scale = 1;
  cv::Mat gray;
  cv::cvtColor(image, gray, cv::COLOR_BGR2GRAY);
  const std::vector<std::string> methods{"gray", "otsu", "adaptive", "clahe", "nearest2", "nearest4"};
  std::vector<int> attempts{preferred_};
  if (preferred_ != 0) {attempts.push_back(0);}
  if (exhaustive) {
    for (int method = 1; method < 6; ++method) {
      if (method != preferred_) {attempts.push_back(method);}
    }
  } else {
    const int method = 1 + static_cast<int>(retry_++ % 5);
    if (method != preferred_) {attempts.push_back(method);}
  }
  int selected_method = 0;
  // Preserve WeChat first and the 2x/4x nearest-neighbour small-code fallbacks.
  // Never downsample the recognition input. Binary variants supplement the original.
  for (int method : attempts) {
    int scale = method == 4 ? 2 : (method == 5 ? 4 : 1);
    if (scale > 1 && image.total() * scale * scale > 6000000U) {continue;}
    cv::Mat input;
    if (method == 0) {input = gray;}
    if (method == 1) {cv::threshold(gray, input, 0, 255, cv::THRESH_BINARY | cv::THRESH_OTSU);}
    if (method == 2) {
      cv::adaptiveThreshold(gray, input, 255, cv::ADAPTIVE_THRESH_GAUSSIAN_C, cv::THRESH_BINARY, 31, 7);
    }
    if (method == 3) {cv::createCLAHE(2.0, {8, 8})->apply(gray, input);}
    if (scale > 1) {cv::resize(gray, input, {}, scale, scale, cv::INTER_NEAREST);}
    for (int detector = 0; detector < 2 && text.empty(); ++detector) {
      points.release();
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
      if (!text.empty()) {selected_scale = scale; selected_method = method; break;}
    }
    if (!text.empty()) {break;}
  }
  if (text.empty()) {return std::nullopt;}
  preferred_ = selected_method;
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
  Detection result{text, {}, original, methods[selected_method]};
  if (!points.empty()) {
    cv::Mat coordinates;
    points.reshape(1, static_cast<int>(points.total() * points.channels() / 2)).convertTo(coordinates, CV_32F);
    for (int i = 0; i < coordinates.rows; ++i) {
      result.corners.emplace_back(
        origin.x + static_cast<int>(std::nearbyint(coordinates.at<float>(i, 0) / selected_scale)),
        origin.y + static_cast<int>(std::nearbyint(coordinates.at<float>(i, 1) / selected_scale)));
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
