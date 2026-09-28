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
