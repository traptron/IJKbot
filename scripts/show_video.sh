#!/usr/bin/env bash
# Preview existing Pi JPEGs; never opens the camera or starts motors.
set -euo pipefail
robot_host="${1:-otmorozki@10.34.243.154}"
preview_fps="${2:-4}"
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
socket="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/ijkbot-preview-ssh.sock"
viewer="$project_root/install/vision_cpp/lib/vision_cpp/video_viewer"
if [[ ! -x "$viewer" ]]; then
  echo 'Build vision_cpp first: colcon build --symlink-install --packages-select vision_cpp' >&2
  exit 1
fi
if ! ssh -S "$socket" -O check "$robot_host" 2>/dev/null; then
  ssh -f -M -N -S "$socket" -o ConnectTimeout=5 \
    -o ServerAliveInterval=5 -o ServerAliveCountMax=2 "$robot_host"
fi
# ROS setup scripts may reference unset variables.
set +u
source /opt/ros/jazzy/setup.bash
set -u
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
exec env -u GTK_PATH -u GTK_MODULES -u GIO_MODULE_DIR -u QT_PLUGIN_PATH -u LD_PRELOAD \
  QT_QPA_PLATFORM=xcb "$viewer" --ros-args \
  -p "ssh_host:=$robot_host" -p "ssh_socket:=$socket" -p "preview_fps:=$preview_fps"
