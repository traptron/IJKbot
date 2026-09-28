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
