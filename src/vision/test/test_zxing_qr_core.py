import numpy as np
import pytest

from vision.core.qr import QrConfirmation, QrDecoder, image_to_gray


def test_confirms_only_consecutive_identical_reads():
    confirmation = QrConfirmation(confirm_frames=2, reset_timeout_sec=1.2)

    assert confirmation.observe('A', 0.0) is None
    assert confirmation.observe('B', 0.1) is None
    assert confirmation.observe(None, 0.2) is None
    assert confirmation.observe('B', 0.3) is None
    assert confirmation.observe('B', 0.4) == 'B'
    assert confirmation.observe('B', 0.5) is None


def test_visibility_timeout_clears_candidate_and_allows_same_code_again():
    confirmation = QrConfirmation(confirm_frames=2, reset_timeout_sec=1.2)

    assert confirmation.observe('same', 0.0) is None
    assert confirmation.observe('same', 1.3) is None
    assert confirmation.observe('same', 1.4) == 'same'
    assert confirmation.observe(None, 1.5) is None
    assert confirmation.observe('same', 2.0) is None
    assert confirmation.observe('same', 2.1) is None
    confirmation.expire(3.4)
    assert confirmation.observe('same', 3.5) is None
    assert confirmation.observe('same', 3.6) == 'same'


def test_explicit_reset_allows_two_approaches_to_same_code():
    confirmation = QrConfirmation(confirm_frames=2, reset_timeout_sec=1.2)

    for start in (0.0, 0.2):
        confirmation.reset()
        assert confirmation.observe('same', start) is None
        assert confirmation.observe('same', start + 0.1) == 'same'


@pytest.mark.parametrize(('encoding', 'pixels', 'expected'), [
    ('rgb8', [[255, 0, 0, 0, 255, 0], [0, 0, 255, 255, 255, 255]], [[77, 149], [29, 255]]),
    ('bgr8', [[0, 0, 255, 0, 255, 0], [255, 0, 0, 0, 0, 0]], [[77, 149], [29, 0]]),
    ('mono8', [[12, 34], [56, 78]], [[12, 34], [56, 78]]),
])
def test_converts_images_with_padded_rows(encoding, pixels, expected):
    data = bytes(value for row in pixels for value in (*row, 13, 247))
    gray = image_to_gray(data, width=2, height=2, step=len(pixels[0]) + 2, encoding=encoding)

    assert gray.dtype == np.uint8
    np.testing.assert_array_equal(gray, expected)


@pytest.mark.parametrize(('length', 'step', 'encoding'), [(15, 8, 'rgb8'), (10, 5, 'bgr8'), (4, 2, 'yuyv')])
def test_rejects_invalid_stride_buffer_or_encoding(length, step, encoding):
    with pytest.raises(ValueError):
        image_to_gray(bytes(length), width=2, height=2, step=step, encoding=encoding)


def test_zxing_preserves_text_and_falls_back_to_full_frame():
    zxing = pytest.importorskip('zxingcpp')
    text = 'Пострадавший\nСостояние: стабильное'
    barcode = zxing.create_barcode(text, zxing.BarcodeFormat.QRCode)
    tile = np.asarray(zxing.write_barcode_to_image(barcode, scale=4))
    height, width = tile.shape
    gray = np.full((height * 3, width * 3), 255, dtype=np.uint8)
    gray[:height, :width] = tile

    decoder = QrDecoder(try_harder=True, use_center_crop=True, center_crop_ratio=0.5)
    assert decoder.decode(gray) == text
    assert decoder.decode(np.full_like(gray, 255)) is None


def test_zxing_prefers_largest_candidate():
    zxing = pytest.importorskip('zxingcpp')
    small = np.asarray(zxing.write_barcode_to_image(
        zxing.create_barcode('other', zxing.BarcodeFormat.QRCode), scale=3))
    large = np.asarray(zxing.write_barcode_to_image(
        zxing.create_barcode('target', zxing.BarcodeFormat.QRCode), scale=6))
    gray = np.full((large.shape[0], small.shape[1] + large.shape[1] + 20), 255, dtype=np.uint8)
    gray[:small.shape[0], :small.shape[1]] = small
    gray[:, -large.shape[1]:] = large

    assert QrDecoder().decode(gray) == 'target'
