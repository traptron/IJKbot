#!/usr/bin/env bash
# Separate City hackathon profile. Run once on each laptop with the matching role.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ROLE="vision"
PI_HOST="${PI_HOST:-${ROBOT_IP:-10.34.243.154}}"
PI_USER="${PI_USER:-${ROBOT_USER:-otmorozki}}"
IMAGE_TOPIC="/camera/color/image_raw/compressed"
SHOW_VIDEO="auto"
MAP_FILE=""
MOCK="false"
CAMERA="true"
RVIZ="true"
SKIP_SYNC="false"
MINIMUM_SCORE="0.68"
CONFIRM_FRAMES="3"

usage() {
    cat <<'EOF'
Использование: ./scripts/start_gorod.sh [--role vision|operator] [параметры]

  --role vision       Ноутбук 1: распознавание знаков и размеченное видео (по умолчанию)
  --role operator     Ноутбук 2: Raspberry Pi, Nav2 и RViz; камера включена
  --pi-host HOST      Адрес Raspberry Pi (PI_HOST/ROBOT_IP также поддерживаются)
  --user USER         SSH-пользователь Raspberry Pi (для --role operator)
  --image-topic TOPIC Сжатый JPEG поток камеры (для --role vision)
  --no-video          Не открывать окно с размеченными знаками
  --map FILE          Использовать готовую карту и AMCL; иначе запускается SLAM
  --mock              Симуляция приводов (для --role operator)
  --no-camera         Внешняя камера уже запущена на Pi (для --role operator)
  --no-rviz           Не запускать RViz (для --role operator)
  --skip-sync         Пропустить проверку Chrony (для --role operator)
  --minimum-score N   Минимальное сходство знака, по умолчанию 0.68
  --confirm-frames N  Подтверждение по N кадрам, по умолчанию 3
  -h, --help          Показать справку

ROS_DOMAIN_ID по умолчанию 42. Детектор публикует распознанные знаки, но не
отправляет команды движения; маршрут и остановки задаются отдельно.
EOF
}

need_value() {
    if [[ $# -lt 2 || -z "$2" ]]; then
        echo "Не задано значение для $1" >&2
        exit 2
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --role) need_value "$@"; ROLE="$2"; shift 2 ;;
        --pi-host) need_value "$@"; PI_HOST="$2"; shift 2 ;;
        --user) need_value "$@"; PI_USER="$2"; shift 2 ;;
        --image-topic) need_value "$@"; IMAGE_TOPIC="$2"; shift 2 ;;
        --map) need_value "$@"; MAP_FILE="$2"; shift 2 ;;
        --minimum-score) need_value "$@"; MINIMUM_SCORE="$2"; shift 2 ;;
        --confirm-frames) need_value "$@"; CONFIRM_FRAMES="$2"; shift 2 ;;
        --no-video) SHOW_VIDEO="false"; shift ;;
        --mock) MOCK="true"; shift ;;
        --no-camera) CAMERA="false"; shift ;;
        --no-rviz) RVIZ="false"; shift ;;
        --skip-sync) SKIP_SYNC="true"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Неизвестный параметр: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ "$ROLE" != "vision" && "$ROLE" != "operator" ]]; then
    echo "Роль должна быть vision или operator" >&2
    exit 2
fi
if [[ ! "$PI_HOST" =~ ^[[:alnum:]._-]+$ ]]; then
    echo "Некорректный адрес Raspberry Pi" >&2
    exit 2
fi
if [[ ! "$MINIMUM_SCORE" =~ ^0\.[0-9]+$|^1(\.0+)?$ ]] ||
   [[ ! "$CONFIRM_FRAMES" =~ ^[1-9][0-9]*$ ]]; then
    echo "Некорректные параметры распознавания" >&2
    exit 2
fi

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"

if [[ "$ROLE" == "operator" ]]; then
    args=(--batch --host "$PI_HOST" --user "$PI_USER")
    if [[ -n "$MAP_FILE" ]]; then
        args+=(--map "$MAP_FILE" --use-amcl)
    else
        args+=(--slam)
    fi
    if [[ "$CAMERA" == "true" ]]; then args+=(--with-camera); else args+=(--no-camera); fi
    if [[ "$MOCK" == "true" ]]; then args+=(--mock); fi
    if [[ "$RVIZ" == "false" ]]; then args+=(--no-rviz); fi
    if [[ "$SKIP_SYNC" == "true" ]]; then args+=(--skip-sync); fi
    echo "Город: запускаю Pi и Nav2; камера ${CAMERA}; ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"
    exec "${SCRIPT_DIR}/start_all_laptop2.sh" "${args[@]}"
fi

if [[ ! -f "${REPO_DIR}/install/setup.bash" ]]; then
    echo "Нет install/setup.bash; сначала выполните colcon build --symlink-install --packages-select vision vision_cpp bringup" >&2
    exit 1
fi
if [[ ! -f /opt/ros/jazzy/setup.bash ]]; then
    echo "ROS 2 Jazzy не найден в /opt/ros/jazzy" >&2
    exit 1
fi
set +u
source /opt/ros/jazzy/setup.bash
source "${REPO_DIR}/install/setup.bash"
set -u

CYCLONE_CONFIG_FILE=""
cleanup() {
    if [[ -n "$CYCLONE_CONFIG_FILE" ]]; then
        rm -f "$CYCLONE_CONFIG_FILE"
    fi
}
trap cleanup EXIT
if [[ -z "${CYCLONEDDS_URI:-}" ]]; then
    PI_ADDR="$(getent ahostsv4 "$PI_HOST" 2>/dev/null | awk 'NR == 1 { print $1 }')"
    if [[ -n "$PI_ADDR" ]]; then
        SRC_IP="$(ip -4 route get "$PI_ADDR" 2>/dev/null | awk '{ for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit } }')"
        CYCLONE_CONFIG_FILE="$(mktemp "${TMPDIR:-/tmp}/ijkbot-city-dds.XXXXXX.xml")"
        cat > "$CYCLONE_CONFIG_FILE" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<CycloneDDS xmlns="https://cdds.io/config">
  <Domain id="any">
    <General><AllowMulticast>true</AllowMulticast>
$(if [[ -n "$SRC_IP" ]]; then printf '      <Interfaces><NetworkInterface address="%s"/></Interfaces>\n' "$SRC_IP"; fi)
    </General>
    <Discovery><Peers><Peer address="$PI_ADDR"/></Peers></Discovery>
  </Domain>
</CycloneDDS>
EOF
        export CYCLONEDDS_URI="file://${CYCLONE_CONFIG_FILE}"
    else
        echo "Город: $PI_HOST пока не разрешается, DDS будет искать робота через multicast" >&2
    fi
fi

if [[ "$SHOW_VIDEO" == "auto" ]]; then
    if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
        SHOW_VIDEO="true"
    else
        SHOW_VIDEO="false"
    fi
fi

echo "Город: камера $IMAGE_TOPIC; размеченное видео: $SHOW_VIDEO"
echo 'Город: знаки /vision/traffic_sign/confirmed; остановка Ctrl+C'
ros2 launch bringup city.launch.py \
    "image_topic:=${IMAGE_TOPIC}" \
    "show_video:=${SHOW_VIDEO}" \
    "minimum_score:=${MINIMUM_SCORE}" \
    "confirm_frames:=${CONFIRM_FRAMES}"
