# Native CSI video and QR

C++17 replacements for camera capture, JPEG streaming, the SSH bridge and QR
reading. Public ROS topics and QR parameters remain compatible with `vision`.
Python nodes remain available through `implementation:=vision` for rollback.
See [the operator guide](../vision/README.md) for build/run commands.

The RAW10 route uses V4L2 mmap, drains old buffers, rate-limits **before**
demosaicing/encoding, reuses OpenCV storage and replaces full-image floating-point
colour correction with equivalent lookup tables. JPEG stays 640×480, Q=85,
with optimised Huffman tables. No raw frames travel over Wi-Fi. Sensor settings
remain exposure=2500, analogue_gain=320. The camera timestamp is host publication
time, not hardware exposure time.

QR detection preserves WeChatQRCode, QRCodeDetector and 2×/4× small-code retries.
Only the latest pending frame is kept. Recognition runs outside the ROS executor;
confirmation, mission filtering, triggered snapshots, evidence topics and disk
snapshot deduplication remain supported. An evidence JPEG is encoded only once a
result is confirmed, using the already decoded image.

## Measurements on tokmachka, 2026-09-28

The deployed native nodes run in Pi tmux session `ijkbot-vision-native`.
The motor/lidar launch and its driver PIDs were preserved during the switch.
CPU figures are 5-second `pidstat` averages; 100% means one core.

| Metric | Python | C++ |
|---|---:|---:|
| Camera CPU | 115.2% | 37.6% |
| QR CPU | 105.4% | 100.4% |
| Received camera FPS, 10-second sample | 9.43 | 9.90 |
| Camera RSS | 178 MiB | 78 MiB |
| JPEG dimensions / quality | 640×480 / 85 | 640×480 / 85 |

Live JPEG payload was 5.29 Mbit/s before and 6.82 Mbit/s after, with different
captured images and different frame rates. This observation does **not** prove
lower live network traffic. For an identical seven-frame RAW10 fixture, payload
decreased from 326,762 to 297,387 bytes (9.0%) and the decoded JPEG pixels were
identical, on both the laptop and Pi. A real QR at competition distance and
lighting still needs a physical reading check; no such check is claimed here.

Eight native unit/ROS checks pass on both platforms. They cover packed/padded
RAW10, malformed/fragmented MJPEG, broken pipes, small/dark QR text and evidence,
confirmation, duplicate timestamps, state gating, triggered snapshots and mock
camera publication/shutdown. The 32 existing Python tests also pass locally.
The fixture comparison checks six QR conditions against the old implementation:
four decode successfully in both, while two fail in both; there is no regression.
Reducing QR CPU further without changing its search behaviour would require
additional work; the native QR node still uses approximately one core in this
scene.
