#!/usr/bin/env bash
# Native JPEG-only SSH bridge and standalone QR reader; does not start motors.
# Source ROS 2 and install/setup.bash before running this script.
set -euo pipefail
PI_TARGET="${1:-${PI_USER:-otmorozki}@${PI_HOST:-172.22.35.154}}"
SSH_SOCKET="${2:-/tmp/ijkbot-camera-new.sock}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
BRIDGE_PID=""
READER_PID=""
cleanup() {
    if [[ -n "${BRIDGE_PID}" ]]; then kill -INT "${BRIDGE_PID}" 2>/dev/null || true; fi
    if [[ -n "${READER_PID}" ]]; then kill -INT "${READER_PID}" 2>/dev/null || true; fi
    wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 0' INT TERM
ros2 run vision_cpp qr_ssh_bridge --ros-args -p "host:=${PI_TARGET}" -p "socket:=${SSH_SOCKET}" &
BRIDGE_PID=$!
ros2 run vision_cpp qr_reader_node --ros-args -p state_filter_enabled:=false \
    -p save_snapshot:=false -p confirm_frames:=3 &
READER_PID=$!
wait -n "${BRIDGE_PID}" "${READER_PID}"
