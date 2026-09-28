#include "vision_cpp/camera.hpp"
#include "vision_cpp/qr.hpp"
#include <gtest/gtest.h>
#include <fcntl.h>
#include <unistd.h>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

TEST(Mjpeg, FragmentedMarkersMultipleFramesAndRecovery) {
  vision_cpp::MjpegFramer parser(20);
  auto feed = [&parser](const vision_cpp::Bytes & bytes) {return parser.feed(bytes.data(), bytes.size());};
  EXPECT_TRUE(feed({'x', 0xff}).empty());
  EXPECT_TRUE(feed({0xd8, 'a', 0xff}).empty());
  auto frames = feed({0xd9, 0xff, 0xd8, 'b', 0xff, 0xd9});
  ASSERT_EQ(frames.size(), 2U);
  EXPECT_EQ(frames[0], (vision_cpp::Bytes{0xff, 0xd8, 'a', 0xff, 0xd9}));
  EXPECT_EQ(frames[1], (vision_cpp::Bytes{0xff, 0xd8, 'b', 0xff, 0xd9}));
  vision_cpp::Bytes corrupt(40, 'x');
  corrupt[0] = 0xff; corrupt[1] = 0xd8;
  EXPECT_THROW(feed(corrupt), std::runtime_error);
  EXPECT_EQ(parser.buffered(), 0U);
  EXPECT_EQ(feed({0xff, 0xd8, 'c', 0xff, 0xd9}).size(), 1U);
  EXPECT_TRUE(feed(vision_cpp::Bytes(100000, 'x')).empty());
  EXPECT_LE(parser.buffered(), 1U);
}
TEST(Camera, ValidationAndPaddedStride) {
  vision_cpp::Options options;
  options.fps = 0;
  EXPECT_THROW(options.validate(), std::invalid_argument);
  vision_cpp::Encoder encoder;
  vision_cpp::Bytes raw(vision_cpp::kRawBytes, 100);
  EXPECT_THROW(encoder.encode(raw.data(), raw.size() - 1), std::invalid_argument);
  auto contiguous = encoder.encode(raw.data(), raw.size());
  vision_cpp::Bytes padded(816 * 480, 42);
  for (int row = 0; row < 480; ++row) {std::copy_n(raw.data() + row * 800, 800, padded.data() + row * 816);}
  EXPECT_EQ(contiguous, encoder.encode(padded.data(), padded.size(), 816));
  auto image = cv::imdecode(contiguous, cv::IMREAD_COLOR);
  EXPECT_EQ(image.cols, 640); EXPECT_EQ(image.rows, 480);
}
TEST(Camera, FullResolutionPackedAndPaddedStride) {
  vision_cpp::Options options;
  options.width = 1297;
  EXPECT_THROW(options.validate(), std::invalid_argument);
  constexpr int width = 1296, height = 972, packed_stride = width * 5 / 4;
  vision_cpp::Encoder encoder(95, width, height);
  vision_cpp::Bytes raw(packed_stride * height, 100);
  auto contiguous = encoder.encode(raw.data(), raw.size());
  vision_cpp::Bytes padded((packed_stride + 16) * height, 42);
  for (int row = 0; row < height; ++row) {
    std::copy_n(raw.data() + row * packed_stride, packed_stride,
      padded.data() + row * (packed_stride + 16));
  }
  EXPECT_EQ(contiguous, encoder.encode(padded.data(), padded.size(), packed_stride + 16));
  const auto image = cv::imdecode(contiguous, cv::IMREAD_COLOR);
  EXPECT_EQ(image.cols, width); EXPECT_EQ(image.rows, height);
  vision_cpp::Encoder monochrome(95, width, height, true);
  const auto gray = cv::imdecode(monochrome.encode(raw.data(), raw.size()), cv::IMREAD_UNCHANGED);
  EXPECT_EQ(gray.type(), CV_8UC1);
  EXPECT_EQ(gray.cols, width); EXPECT_EQ(gray.rows, height);
}
TEST(Transport, ClosedPipeAndMissingChildFailCleanly) {
  EXPECT_THROW(vision_cpp::ChildPipe({"/ijkbot/nonexistent/camera"}), std::runtime_error);
  int descriptors[2];
  ASSERT_EQ(pipe2(descriptors, O_NONBLOCK), 0);
  close(descriptors[0]);
  std::atomic_bool stopped{false};
  // poll reports the broken reader before write, so no SIGPIPE is raised.
  EXPECT_THROW(vision_cpp::write_jpeg(descriptors[1], {0xff, 0xd8, 0xff, 0xd9}, stopped), std::runtime_error);
  close(descriptors[1]);
}
TEST(Qr, ConfirmationRequiresDistinctObservationsAndResetsOnGap) {
  vision_cpp::Confirmation confirmation(3);
  EXPECT_FALSE(confirmation.observe("patient"));
  EXPECT_FALSE(confirmation.observe("patient"));
  EXPECT_EQ(confirmation.observe("patient"), std::optional<std::string>("patient"));
  EXPECT_FALSE(confirmation.observe("patient"));
  confirmation.observe("");
  EXPECT_FALSE(confirmation.observe("patient"));
  EXPECT_FALSE(confirmation.observe("patient"));
  EXPECT_TRUE(confirmation.observe("patient"));
}
TEST(Qr, TextCoordinatesAndEvidenceForSmallAndDarkCodes) {
  vision_cpp::QrDecoder decoder;
  EXPECT_FALSE(decoder.decode({}));
  EXPECT_FALSE(decoder.decode({'b', 'a', 'd'}));
  cv::Mat code;
  const std::string text = "IJKbot patient stable";
  cv::QRCodeEncoder::create()->encode(text, code);
  cv::copyMakeBorder(code, code, 4, 4, 4, 4, cv::BORDER_CONSTANT, 255);
  for (int side : {80, 150, 350}) {
    for (int white : {80, 255}) {
      cv::Mat frame(480, 640, CV_8UC1, cv::Scalar(white));
      cv::Mat scaled;
      cv::resize(code, scaled, {side, side}, 0, 0, cv::INTER_NEAREST);
      scaled.convertTo(scaled, CV_8U, (white - 10) / 255.0, 10);
      scaled.copyTo(frame(cv::Rect(40, 40, side, side)));
      vision_cpp::Bytes jpeg;
      ASSERT_TRUE(cv::imencode(".jpg", frame, jpeg, {cv::IMWRITE_JPEG_QUALITY, 85}));
      auto detection = decoder.decode(jpeg);
      ASSERT_TRUE(detection) << "side=" << side << ", white=" << white;
      EXPECT_EQ(detection->text, text);
      EXPECT_EQ(detection->corners.size(), 4U);
      for (const auto & corner : detection->corners) {
        // Model-free WeChat returns full-frame bounds for some tiny QR codes,
        // as in the legacy decoder. The text must still decode correctly.
        EXPECT_GE(corner.x, 0); EXPECT_LT(corner.x, 640);
        EXPECT_GE(corner.y, 0); EXPECT_LT(corner.y, 480);
        if (side >= 150) {
          EXPECT_GE(corner.x, 35); EXPECT_LE(corner.x, 45 + side);
          EXPECT_GE(corner.y, 35); EXPECT_LE(corner.y, 45 + side);
        }
      }
      auto evidence = cv::imdecode(decoder.annotate(*detection), cv::IMREAD_COLOR);
      EXPECT_EQ(evidence.cols, 640); EXPECT_EQ(evidence.rows, 480);
    }
  }
}
TEST(Qr, DenseUtf8PayloadAtFullResolution) {
  std::string text = "Пациент: Иван; состояние: стабилен; ";
  for (int i = 0; i < 24; ++i) {
    text += "field_" + std::to_string(i) + "=abcdefghijklmnopqrstuvwxyz0123456789;";
  }
  ASSERT_GT(text.size(), 1000U);
  cv::QRCodeEncoder::Params params;
  params.mode = cv::QRCodeEncoder::MODE_BYTE;
  params.correction_level = cv::QRCodeEncoder::CORRECT_LEVEL_M;
  cv::Mat code;
  cv::QRCodeEncoder::create(params)->encode(text, code);
  cv::copyMakeBorder(code, code, 4, 4, 4, 4, cv::BORDER_CONSTANT, 255);
  const int side = code.rows * 4;
  ASSERT_LT(side, 900);
  cv::resize(code, code, {side, side}, 0, 0, cv::INTER_NEAREST);
  for (int scene : {0, 1, 2}) {
    const bool shadow = scene == 1;
    cv::Mat frame(972, 1296, CV_8UC1, cv::Scalar(240));
    code.copyTo(frame(cv::Rect(180, 80, side, side)));
    if (shadow) {
      for (int y = 0; y < frame.rows; ++y) {
        auto * row = frame.ptr<uint8_t>(y);
        for (int x = 0; x < frame.cols; ++x) {
          row[x] = cv::saturate_cast<uint8_t>(row[x] * (0.35 + 0.6 * x / frame.cols) + 15);
        }
      }
    }
    if (scene == 2) {
      const auto transform = cv::getRotationMatrix2D({180 + side / 2.0F, 80 + side / 2.0F}, 12, 1);
      cv::warpAffine(frame, frame, transform, frame.size(), cv::INTER_LINEAR, cv::BORDER_CONSTANT, 240);
    }
    vision_cpp::Bytes jpeg;
    ASSERT_TRUE(cv::imencode(".jpg", frame, jpeg, {cv::IMWRITE_JPEG_QUALITY, 95}));
    vision_cpp::QrDecoder decoder;
    std::optional<vision_cpp::Detection> detection;
    const auto started = vision_cpp::Clock::now();
    for (int attempt = 0; attempt < 6 && !detection; ++attempt) {detection = decoder.decode(jpeg, false);}
    ASSERT_TRUE(detection) << "scene=" << scene;
    EXPECT_EQ(detection->text, text);
    EXPECT_EQ(detection->image.cols, 1296); EXPECT_EQ(detection->image.rows, 972);
    const auto evidence = cv::imdecode(decoder.annotate(*detection), cv::IMREAD_COLOR);
    EXPECT_EQ(evidence.cols, 1296); EXPECT_EQ(evidence.rows, 972);
    std::cout << "Dense QR " << text.size() << " bytes, scene=" << scene << ", "
      << std::chrono::duration<double, std::milli>(vision_cpp::Clock::now() - started).count()
      << " ms, method=" << detection->method << '\n';
  }
}
TEST(Qr, TexturedFullResolutionSceneDoesNotProduceText) {
  cv::Mat noise(972, 1296, CV_8UC1);
  cv::RNG random(42);
  random.fill(noise, cv::RNG::UNIFORM, 0, 256);
  vision_cpp::Bytes jpeg;
  ASSERT_TRUE(cv::imencode(".jpg", noise, jpeg, {cv::IMWRITE_JPEG_QUALITY, 95}));
  vision_cpp::QrDecoder decoder;
  for (int i = 0; i < 4; ++i) {EXPECT_FALSE(decoder.decode(jpeg, false));}
}
TEST(Qr, FullResolutionQrSurvivesLargerFinderLikeDecoy) {
  cv::Mat frame(972, 1296, CV_8UC1, cv::Scalar(255));
  cv::Mat code;
  const std::string text = "patient behind a finder-shaped decoy";
  cv::QRCodeEncoder::create()->encode(text, code);
  cv::copyMakeBorder(code, code, 4, 4, 4, 4, cv::BORDER_CONSTANT, 255);
  cv::resize(code, code, {400, 400}, 0, 0, cv::INTER_NEAREST);
  code.copyTo(frame(cv::Rect(700, 250, 400, 400)));
  for (const auto & origin : {cv::Point(70, 70), cv::Point(280, 70), cv::Point(70, 280)}) {
    cv::rectangle(frame, cv::Rect(origin.x, origin.y, 80, 80), cv::Scalar(0), cv::FILLED);
    cv::rectangle(frame, cv::Rect(origin.x + 12, origin.y + 12, 56, 56), cv::Scalar(255), cv::FILLED);
    cv::rectangle(frame, cv::Rect(origin.x + 25, origin.y + 25, 30, 30), cv::Scalar(0), cv::FILLED);
  }
  vision_cpp::Bytes jpeg;
  ASSERT_TRUE(cv::imencode(".jpg", frame, jpeg, {cv::IMWRITE_JPEG_QUALITY, 95}));
  vision_cpp::QrDecoder decoder;
  std::optional<vision_cpp::Detection> detection;
  for (int attempt = 0; attempt < 6 && !detection; ++attempt) {
    detection = decoder.decode(jpeg, false);
  }
  ASSERT_TRUE(detection);
  EXPECT_EQ(detection->text, text);
  for (const auto & corner : detection->corners) {
    EXPECT_GE(corner.x, 690); EXPECT_LE(corner.x, 1110);
    EXPECT_GE(corner.y, 240); EXPECT_LE(corner.y, 660);
  }
}
