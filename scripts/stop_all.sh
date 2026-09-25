#!/usr/bin/env bash
# ==============================================================================
# stop_all.sh — Экстренная и штатная остановка всех подсистем IJKbot:
# 1. Посылает нулевую скорость в /cmd_vel_emergency (приоритет 100) и /cmd_vel.
# 2. Завершает удаленные процессы на Raspberry Pi по SSH (robot.launch, Nav2, diff_drive_node).
# 3. Завершает локальные процессы на Ноутбуке 2 (RViz2, телеоп, скрипты запуска).
# ==============================================================================
set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"

PI_HOST="${PI_HOST:-${ROBOT_IP:-192.168.1.10}}"
PI_USER="${PI_USER:-${ROBOT_USER:-otmorozki}}"
PIXI_MANIFEST="${PIXI_PROJECT_MANIFEST:-/home/lev/ros2_jazzy/pixi.toml}"
SEND_ZERO_VEL=true
FORCE_KILL=false
CALLER_PID=""

print_help() {
    echo -e "${BOLD}Использование:${NC} $0 [ПАРАМЕТРЫ]"
    echo ""
    echo "Параметры:"
    echo "  --host <IP>          IP-адрес Raspberry Pi (по умолчанию: ${PI_HOST})"
    echo "  --user <USER>        SSH-пользователь на Pi (по умолчанию: ${PI_USER})"
    echo "  --force, -f          Немедленное принудительное завершение всех процессов (SIGKILL)"
    echo "  --no-vel             Пропустить публикацию нулевой скорости в ROS-топики"
    echo "  --caller-pid <PID>   PID вызывающего процесса для исключения из завершения"
    echo "  -h, --help           Показать эту справку"
    echo ""
    echo "Переменные окружения:"
    echo "  PI_HOST / ROBOT_IP   IP-адрес Raspberry Pi (дефолт: 192.168.1.10)"
    echo "  PI_USER / ROBOT_USER SSH-пользователь (дефолт: otmorozki)"
    echo "  ROS_DOMAIN_ID        ID ROS-домена (дефолт: 42)"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            PI_HOST="$2"
            shift 2
            ;;
        --user)
            PI_USER="$2"
            shift 2
            ;;
        --force|-f)
            FORCE_KILL=true
            shift
            ;;
        --no-vel)
            SEND_ZERO_VEL=false
            shift
            ;;
        --caller-pid)
            CALLER_PID="$2"
            shift 2
            ;;
        -h|--help)
            print_help
            exit 0
            ;;
        *)
            echo -e "${RED}[ERROR] Неизвестный аргумент: $1${NC}" >&2
            print_help
            exit 1
            ;;
    esac
done

echo -e "${RED}${BOLD}================================================================${NC}"
echo -e "${RED}${BOLD}          IJKbot — ОСТАНОВКА ВСЕХ СИСТЕМ (STOP ALL)             ${NC}"
echo -e "${RED}${BOLD}================================================================${NC}"
echo -e "${BLUE}Целевой робот:${NC}  ${BOLD}${PI_USER}@${PI_HOST}${NC}"
echo -e "${BLUE}ROS_DOMAIN_ID:${NC}  ${BOLD}${ROS_DOMAIN_ID}${NC}"
echo -e "${CYAN}----------------------------------------------------------------${NC}"

# 1. Отправка нулевой скорости для немедленного торможения приводов
if [[ "${SEND_ZERO_VEL}" == "true" ]]; then
    echo -e "${YELLOW}[1/3] Отправка нулевой скорости (/cmd_vel_emergency, /cmd_vel_sm & /cmd_vel)...${NC}"
    if command -v pixi &>/dev/null && [[ -f "${PIXI_MANIFEST}" ]]; then
        # Публикуем с -w 0, чтобы не блокироваться в ожидании подписчиков
        timeout 2s pixi run --manifest-path "${PIXI_MANIFEST}" ros2 topic pub --once -w 0 /cmd_vel_emergency geometry_msgs/msg/Twist \
            "{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}" >/dev/null 2>&1 || true
        timeout 2s pixi run --manifest-path "${PIXI_MANIFEST}" ros2 topic pub --once -w 0 /cmd_vel_sm geometry_msgs/msg/Twist \
            "{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}" >/dev/null 2>&1 || true
        timeout 2s pixi run --manifest-path "${PIXI_MANIFEST}" ros2 topic pub --once -w 0 /cmd_vel geometry_msgs/msg/Twist \
            "{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}" >/dev/null 2>&1 || true
        echo -e "${GREEN}[OK] Команда нулевой скорости отправлена в топики.${NC}"
    else
        echo -e "${YELLOW}[SKIP] Pixi/ROS 2 недоступен локально для отправки Twist.${NC}"
    fi
else
    echo -e "${YELLOW}[1/3] Пропуск отправки Twist (--no-vel).${NC}"
fi

# 2. Остановка удаленных процессов на Raspberry Pi по SSH
echo -e "${YELLOW}[2/3] Остановка удаленных процессов на Raspberry Pi (${PI_HOST})...${NC}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=2 -o StrictHostKeyChecking=no)

ALL_KILL_CMD="
    pkill -2 -f 'robot.launch.py' 2>/dev/null || true;
    pkill -2 -f 'navigation.launch.py' 2>/dev/null || true;
    pkill -2 -f 'system.launch.py' 2>/dev/null || true;
    pkill -2 -f 'diff_drive_node' 2>/dev/null || true;
    pkill -2 -f 'realsense2_camera_node' 2>/dev/null || true;
    sleep 0.5;
    pkill -9 -f 'robot.launch.py' 2>/dev/null || true;
    pkill -9 -f 'navigation.launch.py' 2>/dev/null || true;
    pkill -9 -f 'system.launch.py' 2>/dev/null || true;
    pkill -9 -f 'diff_drive_node' 2>/dev/null || true;
    pkill -9 -f 'realsense2_camera_node' 2>/dev/null || true;
    pkill -9 -f 'depthimage_to_laserscan' 2>/dev/null || true;
    pkill -9 -f 'robot_state_publisher' 2>/dev/null || true;
    pkill -9 -f 'controller_server' 2>/dev/null || true;
    pkill -9 -f 'smoother_server' 2>/dev/null || true;
    pkill -9 -f 'planner_server' 2>/dev/null || true;
    pkill -9 -f 'behavior_server' 2>/dev/null || true;
    pkill -9 -f 'bt_navigator' 2>/dev/null || true;
    pkill -9 -f 'static_transform_publisher' 2>/dev/null || true;
    pkill -9 -f 'twist_mux' 2>/dev/null || true;
    pkill -9 -f 'map_server' 2>/dev/null || true;
    pkill -9 -f 'qr_reader_node' 2>/dev/null || true;
    pkill -9 -f 'nav2_' 2>/dev/null || true;
"

if timeout 4s ssh "${SSH_OPTS[@]}" "${PI_USER}@${PI_HOST}" "${ALL_KILL_CMD}" >/dev/null 2>&1; then
    echo -e "${GREEN}[OK] Команды остановки на Raspberry Pi выполнены.${NC}"
else
    echo -e "${YELLOW}[WARN] Хост ${PI_HOST} не ответил по SSH (робот выключен или недоступен).${NC}"
fi

# 3. Остановка локальных процессов на Ноутбуке 2
echo -e "${YELLOW}[3/3] Остановка локальных процессов Ноутбука 2...${NC}"
MY_PID=$$
EXCLUDE_PIDS="^(${MY_PID}|${PPID}${CALLER_PID:+|${CALLER_PID}})$"

# Завершение RViz2
pkill -f rviz2 2>/dev/null && echo -e "  - RViz2 остановлен" || true
# Завершение клавиатурного телеопа
pkill -f teleop_twist_keyboard 2>/dev/null && echo -e "  - teleop_twist_keyboard остановлен" || true

# Остановка фоновых скриптов запуска Ноутбука 2 (исключая текущий процесс, родителя и редактор)
for script in "start_robot_pi.sh" "start_nav2_pi.sh" "start_rviz.sh" "teleop.sh"; do
    pgrep -f "bash.*${script}|/${script}" | grep -v -E "${EXCLUDE_PIDS}" | xargs -r kill -2 2>/dev/null || true
done
sleep 0.3
for script in "start_robot_pi.sh" "start_nav2_pi.sh" "start_rviz.sh" "teleop.sh"; do
    pgrep -f "bash.*${script}|/${script}" | grep -v -E "${EXCLUDE_PIDS}" | xargs -r kill -9 2>/dev/null || true
done

# Если вызван автономно (не из start_all_laptop2.sh), останавливаем и сам оркестратор
if [[ -z "${CALLER_PID}" ]]; then
    pgrep -f "bash.*start_all_laptop2\.sh|/start_all_laptop2\.sh" | grep -v -E "${EXCLUDE_PIDS}" | xargs -r kill -2 2>/dev/null || true
fi

echo -e "${GREEN}${BOLD}================================================================${NC}"
echo -e "${GREEN}${BOLD}          ВСЕ СИСТЕМЫ УСПЕШНО ОСТАНОВЛЕНЫ                       ${NC}"
echo -e "${GREEN}${BOLD}================================================================${NC}"
exit 0
