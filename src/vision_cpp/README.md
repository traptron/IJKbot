# Native CSI video and QR

C++17 replacements for camera capture, JPEG streaming, the SSH bridge and QR
reading. Public ROS topics and QR parameters remain compatible with `vision`.
Python nodes remain available through `implementation:=vision` for rollback.
See [the operator guide](../vision/README.md) for build/run commands.

## Dense QR capture and independent preview

The native standalone launch now defaults to a real **1296×972** sensor mode,
JPEG quality 95 and up to 6 capture FPS. This is not an enlarged VGA image.
V4L2 configures both the sensor and capture device and rejects a mismatched
resolution. The general camera executable retains its legacy 640×480 defaults.

```bash
# On the robot (ROS_DOMAIN_ID=42), no motor launch:
ros2 launch vision_cpp rpi_qr.launch.py one_shot:=true
# On the laptop, using the robot's current IP:
bash scripts/show_video.sh otmorozki@10.18.233.154 4
```

Capture publishes the full-resolution JPEG to `/camera/qr/image/compressed`,
which the on-robot QR reader consumes. A separate preview worker keeps only the
latest frame, prepares a letterboxed 640×480 JPEG at quality 85 and publishes
`/camera/color/image_raw/compressed` at up to 4 FPS. Preview encoding is skipped
when nobody subscribes. Only subscribe to the full-resolution topic on the Pi;
use the existing preview topic/SSH relay on Wi-Fi. No raw images are transmitted.
QR evidence also preserves the full capture dimensions.

Recognition uses OpenCV C++ WeChatQRCode and QRCodeDetector. It tries the original
grayscale image, supplemented by Otsu, adaptive thresholding and CLAHE, plus the
existing 2×/4× nearest-neighbour retries for small inputs. It never downsamples
the recognition input. Expansions above six million pixels are skipped to bound
memory usage. The successful variant is tried first on following frames.
Streaming rotates costly fallback variants over fresh frames; a photo trigger
tries all variants on the requested photograph. Thresholding never replaces the
original capture or colour evidence. See the
[OpenCV thresholding documentation](https://docs.opencv.org/4.6.0/d7/d4d/tutorial_py_thresholding.html).

Before high-resolution decoding, OpenCV contours locate the three nested finder
squares. A geometric QR locator is used as a fallback, with periodic native-size
searches for small patterns. A reduced image may be used for **location only**;
the candidate is cropped from the original image with quiet-zone padding and
all payload decoding operates on those original pixels. Evidence coordinates
are translated back into the original full frame. This avoids passing an entire
high-resolution textured scene into model-free WeChat, which took 27–71 seconds
per failed attempt in the first live measurement. Candidates still need three
successful distinct-frame decodes; a finder pattern alone is not a result.

`max_decode_fps:=3.0` limits the background worker's start rate independently of
capture and preview. An in-progress decode and at most one pending frame are
retained; newer frames replace the pending one. Actual recognition FPS depends
on scene complexity. `decode_duty_cycle:=0.7` adds a proportional cooldown after
expensive attempts so the worker yields CPU even when decoding is slower than
the target period. This is a scheduling target, not a hard CPU quota; photo
triggers bypass the cooldown. `confirmation_timeout_sec:=5.0` allows slow dense-code
observations to accumulate without the previous one-second reset. Confirmation
still requires three distinct frame timestamps; lost capture or a disallowed
mission state resets it. Status, detected, evidence, snapshot triggers, disk
deduplication, state filtering and one-shot completion retain their contracts.

Other native launch controls: `width`, `height`, `fps`, `jpeg_quality`,
`preview_fps`, `preview_quality`, `confirm_frames`, `qr_image_topic`.
For the previous sensor resolution use `width:=640 height:=480 fps:=10
jpeg_quality:=85`. The `vision` compatibility launch still has its legacy VGA
defaults. `csi_jpeg_stream` also accepts `--width` and `--height`.

Validation includes a 1158-byte UTF-8 QR (including Cyrillic), even lighting and
a simulated shadow, unchanged full-resolution evidence, padded RAW10 at both
resolutions, and ROS tests for the split streams, slow confirmations, snapshots,
state gating, duplicate timestamps, retained results and stopping both streams.
Synthetic fixtures do not establish readability of a particular printed code:
focus, motion and pixels per QR module still require a physical test. JPEG Q95
is lossy; additional pixels do not recover detail lost to focus or motion blur.

Read-only on-robot stream measurements:

```bash
python3 src/vision_cpp/test/measure_streams.py --seconds 10
```

The measurements below describe the earlier VGA implementation, not a benchmark
of the new high-resolution capture path.

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

## One QR per capture session

The standalone C++ `rpi_qr.launch.py` now defaults to `one_shot:=true`:
the first QR confirmed in three distinct frames is published once, with one
evidence image. `/vision/qr/session_complete` then stops camera capture,
the JPEG relay and the desktop preview. Further frames, photo triggers and
mission-state changes cannot publish another result during that session.
Camera quality and QR confirmation rules are unchanged.

Deployed on the Pi on 2026-09-28 after a successful `vision_cpp`/`vision`
build and all eight native unit/ROS checks. The capture session runs in tmux
`ijkbot-vision-native`; its output is `/tmp/ijkbot-qr-once.log` on the Pi.

The reader stays alive without decoding to retain the result for a laptop
that reconnects after the Wi-Fi outage. Reliable/transient-local subscriptions
can fetch the cached text after streaming has stopped:

```bash
ROS_DOMAIN_ID=42 ros2 topic echo --once --qos-reliability reliable \
  --qos-durability transient_local /victim_status std_msgs/msg/String
```

Restart the standalone launch to begin a new session. Use `one_shot:=false`
for continuous C++ capture. General-purpose reader/camera nodes remain
continuous by default; the Python rollback implementation does not implement
the new one-shot controls.

## Low-backlog desktop preview

Build `vision_cpp` on both computers. On the Pi, disable the optional desktop
target with `--cmake-args -DBUILD_VIDEO_VIEWER=OFF`. Leave the camera and QR reader
running: the new `jpeg_topic_stream` subscribes to their existing compressed
topic, rather than opening the camera again.

On the laptop, run:

```bash
bash scripts/show_video.sh otmorozki@10.18.233.154 4
```

The host argument is the robot's current address, not a guaranteed static IP.
SSH asks for credentials interactively; no password is stored. The window is
`IJKbot - live camera`; Q/Escape closes it. An SSH control connection remains
available for subsequent launches (close with `ssh -S
"$XDG_RUNTIME_DIR/ijkbot-preview-ssh.sock" -O exit <host>` when finished).

Preview is limited to four FPS by default; the Pi camera and QR reader keep
their original ten FPS. Every displayed JPEG uses the original compressed bytes,
without resizing or re-encoding. Only one frame may be in flight: the receiver
acknowledges complete JPEGs, and the sender then selects the newest pending
frame. Stalls do not create a growing application backlog. The viewer marks
missing frames after 0.5 seconds and retries failed SSH channels. Direct DDS
preview remains available by running `video_viewer` without `ssh_host`.

This does not guarantee real-time delivery through a failing Wi-Fi link. During
diagnosis on 2026-09-28, both SSH and DDS stalled through the Pixel_1765 hotspot
on 2.4 GHz. Pi Wi-Fi power saving was found enabled and disabled for the current
boot only. This is a reversible runtime change, not a persistent network
configuration; no router, SSID, channel or motor settings were changed.

The added ROS relay regression test checks byte-for-byte JPEG preservation,
absence of output before acknowledgement, and newest-frame selection after it.
At the relay-only stage, both platforms passed seven native unit/ROS checks. After switching
preview transport, the laptop briefly displayed 2.2–3.8 FPS, then the underlying
SSH connection failed again. A six-packet ping sample showed 16.7% loss and
151–935 ms RTT (with one duplicate). Thus the recurring long freeze is **not
resolved** by this code change. A healthy network link is still required.
If the SSH master itself dies, rerun the preview script to authenticate again;
channel retries cannot recover password authentication without interaction.
