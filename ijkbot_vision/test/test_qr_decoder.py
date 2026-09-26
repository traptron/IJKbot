"""Unit tests for QR decoder and confirmation helpers."""

import unittest
from unittest.mock import patch

from ijkbot_vision.qr_decoder import (
    QrConfirmation,
    annotate_qr_image,
    annotate_qr_jpeg,
    decode_jpeg,
    draw_qr_border,
)


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
        self.assertIsNotNone(result.annotated_jpeg)
        self.assertIsNotNone(result.corners)

    def test_decodes_tilted_qr_with_wechat_d07(self):
        """Defect D07: WeChatQRCode decodes QR tilted >5 deg where QRCodeDetector fails."""
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest('OpenCV is not installed')

        frame = np.full((480, 640, 3), 128, dtype=np.uint8)
        qr = cv2.QRCodeEncoder_create().encode('Tilted QR 15deg')
        qr = cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)
        qr = cv2.resize(qr, (80, 80), interpolation=cv2.INTER_NEAREST)
        # Apply 15 degree rotation
        matrix = cv2.getRotationMatrix2D((40, 40), 15, 1.0)
        qr_rot = cv2.warpAffine(qr, matrix, (80, 80), borderValue=(128, 128, 128))
        frame[200:280, 280:360] = qr_rot
        ok, jpeg = cv2.imencode('.jpg', frame)
        self.assertTrue(ok)

        result = decode_jpeg(bytes(jpeg))
        self.assertIsNotNone(result)
        self.assertEqual('Tilted QR 15deg', result.text)
        self.assertIsNotNone(result.corners)
        self.assertGreaterEqual(len(result.corners), 4)
        self.assertIsNotNone(result.annotated_jpeg)

    def test_fallback_to_standard_qr_detector(self):
        """Fallback to standard OpenCV QRCodeDetector when WeChatQRCode is unavailable."""
        try:
            import cv2
        except ImportError:
            self.skipTest('OpenCV is not installed')

        image = cv2.QRCodeEncoder_create().encode('Fallback Detector Test')
        ok, jpeg = cv2.imencode('.jpg', image)
        self.assertTrue(ok)

        with patch('ijkbot_vision.qr_decoder.get_wechat_detector', return_value=None):
            result = decode_jpeg(bytes(jpeg))
            self.assertIsNotNone(result)
            self.assertEqual('Fallback Detector Test', result.text)

    def test_scaling_small_qr_d12(self):
        """Defect D12: scaling condition handles small QR codes on 640x480 frame."""
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest('OpenCV is not installed')

        frame = np.full((480, 640, 3), 255, dtype=np.uint8)
        qr = cv2.QRCodeEncoder_create().encode('Small QR Code')
        qr = cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)
        qr = cv2.resize(qr, (35, 35), interpolation=cv2.INTER_NEAREST)
        frame[100:135, 100:135] = qr
        ok, jpeg = cv2.imencode('.jpg', frame)
        self.assertTrue(ok)

        result = decode_jpeg(bytes(jpeg))
        self.assertIsNotNone(result)
        self.assertEqual('Small QR Code', result.text)

    def test_annotate_qr_image_and_jpeg(self):
        """Ensure green border (0, 255, 0) of thickness 3 is drawn along corners."""
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest('OpenCV is not installed')

        blank = np.zeros((100, 100, 3), dtype=np.uint8)
        corners = ((10, 10), (50, 10), (50, 50), (10, 50))
        annotated = annotate_qr_image(blank, corners, color=(0, 255, 0), thickness=3)
        self.assertIsNotNone(annotated)
        # Check green pixels exist in annotated image
        green_mask = (annotated[:, :, 1] == 255) & (annotated[:, :, 0] == 0) & (annotated[:, :, 2] == 0)
        self.assertGreater(green_mask.sum(), 0)

        # Alias draw_qr_border works identically
        alias_annotated = draw_qr_border(blank, corners)
        self.assertTrue(np.array_equal(annotated, alias_annotated))

        # Check annotate_qr_jpeg
        ok, jpeg = cv2.imencode('.jpg', blank)
        self.assertTrue(ok)
        ann_jpeg = annotate_qr_jpeg(bytes(jpeg), corners)
        self.assertIsNotNone(ann_jpeg)
        decoded = cv2.imdecode(np.frombuffer(ann_jpeg, np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(decoded)

    def test_annotate_edge_cases(self):
        """Check empty/None corner inputs gracefully return original or None."""
        try:
            import numpy as np
        except ImportError:
            self.skipTest('NumPy is not installed')

        blank = np.zeros((50, 50, 3), dtype=np.uint8)
        self.assertIsNone(annotate_qr_image(None, None))
        res_no_corners = annotate_qr_image(blank, None)
        self.assertTrue(np.array_equal(blank, res_no_corners))
        self.assertIsNone(annotate_qr_jpeg(b'', None))

    def test_wechat_multi_candidate_with_empty_first(self):
        """WeChat returns multiple candidates where the first one has empty text."""
        from unittest.mock import Mock
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest('OpenCV is not installed')

        blank = np.zeros((100, 100, 3), dtype=np.uint8)
        ok, jpeg = cv2.imencode('.jpg', blank)
        self.assertTrue(ok)

        pts1 = np.array([(0, 0), (10, 0), (10, 10), (0, 10)], dtype=np.float32)
        pts2 = np.array([(20, 20), (30, 20), (30, 30), (20, 30)], dtype=np.float32)

        mock_wechat = Mock()
        mock_wechat.detectAndDecode.return_value = (('', 'MULTI_CANDIDATE_VICTIM'), (pts1, pts2))

        with patch('ijkbot_vision.qr_decoder.get_wechat_detector', return_value=mock_wechat), \
             patch('ijkbot_vision.qr_decoder.get_fallback_detector', return_value=None):
            result = decode_jpeg(bytes(jpeg))
            self.assertIsNotNone(result)
            self.assertEqual('MULTI_CANDIDATE_VICTIM', result.text)
            self.assertEqual(((20, 20), (30, 20), (30, 30), (20, 30)), result.corners)

    def test_annotate_grayscale_image_produces_bgr_green(self):
        """Grayscale image is converted to 3-channel BGR with green border."""
        try:
            import numpy as np
        except ImportError:
            self.skipTest('NumPy is not installed')

        gray = np.zeros((100, 100), dtype=np.uint8)
        corners = ((10, 10), (50, 10), (50, 50), (10, 50))
        ann = annotate_qr_image(gray, corners)
        self.assertIsNotNone(ann)
        self.assertEqual(3, ann.ndim)
        self.assertEqual(3, ann.shape[2])
        # Green channel has 255, Blue and Red have 0
        green_mask = (ann[:, :, 1] == 255) & (ann[:, :, 0] == 0) & (ann[:, :, 2] == 0)
        self.assertTrue(green_mask.any())

    def test_annotate_malformed_corners_safe(self):
        """Malformed corners do not crash and return image copy."""
        try:
            import numpy as np
        except ImportError:
            self.skipTest('NumPy is not installed')

        blank = np.zeros((50, 50, 3), dtype=np.uint8)
        malformed = [(10, None), (20, 'bad')]
        res = annotate_qr_image(blank, malformed)
        self.assertIsNotNone(res)
        self.assertTrue(np.array_equal(blank, res))


if __name__ == '__main__':
    unittest.main()
