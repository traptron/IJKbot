#!/usr/bin/env bash
# Inspect the Jetson and its ROS workspace without launching nodes or opening UART.
set -euo pipefail

usage() {
  echo 'Usage: jetson_preflight.sh [--workspace DIR] [--lidar-port PATH] [--motor-port PATH]'
  echo 'Exit 1 when the Jetson, Jazzy or CycloneDDS prerequisites are missing.'
  echo 'Sensor ports, camera tools, GPU libraries and the project overlay are reported separately.'
}

workspace=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
lidar_port=/dev/ttyUSB0
motor_port=/dev/ttySTS
while (($#)); do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --workspace|--lidar-port|--motor-port)
      if (($# < 2)) || [[ -z $2 || $2 == --* ]]; then
        echo "Missing value for $1" >&2
        exit 2
      fi
      case "$1" in
        --workspace) workspace=$2 ;;
        --lidar-port) lidar_port=$2 ;;
        --motor-port) motor_port=$2 ;;
      esac
      shift 2
      ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

status=0
if [[ -r /proc/device-tree/model && -r /etc/nv_tegra_release && $(uname -m) == aarch64 ]]; then
  printf 'Board: %s\n' "$(tr -d '\000' </proc/device-tree/model)"
  head -n 1 /etc/nv_tegra_release
else
  echo '[MISSING] aarch64 Jetson device tree or L4T release information'
  status=1
fi
if [[ -r /etc/os-release ]]; then
  awk -F= '$1 == "PRETTY_NAME" {print "OS: " $2}' /etc/os-release
fi
uname -rm
awk '/^(MemTotal|MemAvailable|SwapTotal):/ {print}' /proc/meminfo
if [[ -d $workspace ]]; then
  df -h -- "$workspace"
else
  printf '[MISSING] Workspace directory: %s\n' "$workspace"
  df -h /
fi

ros_prefix=/opt/ros/jazzy
if [[ -r $ros_prefix/setup.bash && -x $ros_prefix/bin/ros2 ]]; then
  printf '[OK] ROS 2 Jazzy: %s\n' "$ros_prefix"
else
  printf '[MISSING] ROS 2 Jazzy: %s\n' "$ros_prefix"
  status=1
fi
if [[ -f $ros_prefix/share/ament_index/resource_index/packages/rmw_cyclonedds_cpp ]]; then
  echo '[OK] CycloneDDS package in Jazzy underlay'
else
  echo '[MISSING] CycloneDDS package in Jazzy underlay'
  status=1
fi
if [[ -r $workspace/install/setup.bash ]]; then
  printf '[OK] Project overlay: %s/install/setup.bash\n' "$workspace"
else
  printf '[PENDING] Build project overlay: %s/install/setup.bash\n' "$workspace"
fi

if ! command -v lsusb >/dev/null; then
  echo '[SKIP] USB topology: lsusb not installed'
elif ! lsusb -t; then
  echo '[SKIP] USB topology: lsusb failed'
fi

check_uart() {
  local label=$1 port=$2
  if [[ -c $port && -r $port && -w $port ]]; then
    printf '[OK] %s: %s -> %s (read/write permissions)\n' "$label" "$port" "$(readlink -f -- "$port")"
  elif [[ -c $port ]]; then
    printf '[MISSING] %s: no read/write access to %s\n' "$label" "$port"
  else
    printf '[PENDING] %s: no character device at %s\n' "$label" "$port"
  fi
}
check_uart Lidar "$lidar_port"
check_uart Motors "$motor_port"
if [[ -c $lidar_port && -c $motor_port && $lidar_port -ef $motor_port ]]; then
  echo '[ERROR] Lidar and motor paths refer to the same device'
  status=1
fi

if command -v dpkg-query >/dev/null; then
  for family in 'nvidia-jetpack*' 'librealsense*' 'ros-jazzy-*realsense*' \
                'libopencv-core*' 'libopencv-contrib*' 'cuda-cudart*' 'libnvinfer*'; do
    packages=$(dpkg-query -W -f='${db:Status-Abbrev}\t${binary:Package}\t${Version}\n' "$family" 2>/dev/null || true)
    installed=$(awk '$1 ~ /^.i/ {print $2, $3}' <<<"$packages")
    if [[ -n $installed ]]; then
      printf '%s\n' "$installed"
    else
      printf '[SKIP] No installed dpkg package matching %s\n' "$family"
    fi
  done
fi

for tool in tegrastats trtexec rs-enumerate-devices; do
  if path=$(command -v "$tool"); then
    printf '[OK] %s: %s\n' "$tool" "$path"
  elif [[ $tool == trtexec && -x /usr/src/tensorrt/bin/trtexec ]]; then
    echo '[OK] trtexec: /usr/src/tensorrt/bin/trtexec'
  else
    printf '[SKIP] %s not found\n' "$tool"
  fi
done

exit "$status"
