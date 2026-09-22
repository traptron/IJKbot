"""Unit tests that do not require ROS, OpenCV, or a camera."""

import unittest

from ijkbot_vision.qr_decoder import QrConfirmation, decode_jpeg


class TestQrConfirmation(unittest.TestCase):
    def test_preserves_text_and_rearms(self):
        confirmation = QrConfirmation(2)
        text = '  Пострадавший\nСостояние: стабильно\n'
        self.assertIsNone(confirmation.observe(text))
        self.assertEqual(text, confirmation.observe(text))
        confirmation.observe(None)
        self.assertIsNone(confirmation.observe(text))
        self.assertEqual(text, confirmation.observe(text))

    def test_empty_and_corrupt_jpeg(self):
        self.assertIsNone(decode_jpeg(b''))
        self.assertIsNone(decode_jpeg(b'not a jpeg'))

    def test_confirms_only_after_required_identical_frames(self):
        confirmation = QrConfirmation(required_frames=3)
        self.assertIsNone(confirmation.observe('status=stable'))
        self.assertIsNone(confirmation.observe('status=stable'))
        self.assertEqual('status=stable', confirmation.observe('status=stable'))
        self.assertIsNone(confirmation.observe('status=stable'))

    def test_different_text_restarts_confirmation(self):
        confirmation = QrConfirmation(required_frames=2)
        self.assertIsNone(confirmation.observe('first'))
        self.assertIsNone(confirmation.observe('second'))
        self.assertEqual('second', confirmation.observe('second'))

    def test_empty_frame_resets_candidate(self):
        confirmation = QrConfirmation(required_frames=2)
        self.assertIsNone(confirmation.observe('text'))
        self.assertIsNone(confirmation.observe(None))
        self.assertIsNone(confirmation.observe('text'))
        self.assertEqual('text', confirmation.observe('text'))

    def test_decodes_jpeg_generated_by_opencv(self):
        try:
            import cv2
        except ImportError:
            self.skipTest('OpenCV is not installed')

        image = cv2.QRCodeEncoder_create().encode('IJKbot QR test')
        ok, jpeg = cv2.imencode('.jpg', image)
        self.assertTrue(ok)

        result = decode_jpeg(bytes(jpeg))
        self.assertIsNotNone(result)
        self.assertEqual('IJKbot QR test', result.text)


if __name__ == '__main__':
    unittest.main()
