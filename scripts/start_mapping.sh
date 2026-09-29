#!/usr/bin/env bash
# ==============================================================================
# start_mapping.sh — Запуск картографирования полигона (SLAM) с ноутбука.
#
# Запускает:
# 1. На Raspberry Pi (по SSH):
#    - RPLIDAR A2M8 (/scan или /scan_raw)
#    - Драйвер моторов Feetech STS3215 (diff_drive_node)
#    - Robot State Publisher и TF дерево (base_footprint -> lidar_link)
#    - slam_toolbox (async_slam_toolbox_node) для построения /map
# 2. На Ноутбуке:
#    - RViz2 (отображение сетки, робота, лучей лидара и строящейся карты /map)
#    - Опционально: окно телеуправления с клавиатуры (teleop.sh)
#
# Корректно завершает удаленные и локальные процессы по Ctrl+C.
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
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"

PRIMARY_HOST="10.34.243.154"
DEFAULT_BACKUP="192.168.1.10"
PI_HOST="${PI_HOST:-${ROBOT_IP:-${PRIMARY_HOST}}}"
if [[ "${PI_HOST}" == "${DEFAULT_BACKUP}" ]]; then
    BACKUP_HOST="${PRIMARY_HOST}"
else
    BACKUP_HOST="${DEFAULT_BACKUP}"
fi
PI_USER="${PI_USER:-${ROBOT_USER:-otmorozki}}"
REMOTE_WS="/home/${PI_USER}/IJKbot"

LIDAR_PORT="/dev/ttyUSB0"
LIDAR_BAUD="115200"
SCAN_TOPIC="/scan"
MOCK_HARDWARE="false"
RUN_LOCAL="false"
HOST_SPECIFIED="false"
FORCE_START="false"
LAUNCH_RVIZ="true"
LAUNCH_TELEOP="false"
EXTRA_LAUNCH_ARGS=""

SSH_PID=""
RVIZ_PID=""
TELEOP_PID=""

print_help() {
    echo -e "${BOLD}Использование:${NC} $0 [ПАРАМЕТРЫ]"
    echo ""
    echo "Скрипт для картографирования полигона (SLAM) на базе slam_toolbox."
    echo ""
    echo "Параметры:"
    echo "  --host <IP>          IP-адрес Raspberry Pi (по умолчанию: ${PI_HOST})"
    echo "  --user <USER>        SSH-пользователь (по умолчанию: ${PI_USER})"
    echo "  --lidar-port <PORT>  Последовательный порт RPLIDAR A2M8 (по умолчанию: ${LIDAR_PORT})"
    echo "  --scan-topic <TOPIC> Топик сканов лидара (по умолчанию: ${SCAN_TOPIC}, можно /scan_raw)"
    echo "  --no-rviz            Не запускать окно RViz2 на ноутбуке"
    echo "  --teleop             Открыть телеуправление с клавиатуры в отдельном терминале"
    echo "  --mock               Режим симуляции моторов (mock_hardware:=true)"
    echo "  --local              Запуск всего стека локально на ноутбуке (через Pixi)"
    echo "  --force              Игнорировать ошибки проверки связи (ping/SSH) и продолжать"
    echo "  --extra <ARGS>       Дополнительные аргументы для mapping.launch.py"
    echo "  -h, --help           Показать эту справку"
    echo ""
    echo "Примеры:"
    echo "  $0                   Стандартный запуск картографирования с робота по SSH + RViz2"
    echo "  $0 --teleop          Запуск со встроенным вызовом телеуправления"
    echo "  $0 --scan-topic /scan_raw  Использовать сырой топик лидара в обход фильтра"
    echo ""
    echo "Сохранение карты после завершения:"
    echo "  bash scripts/save_map.sh [имя_карты]"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует IP-адреса${NC}" >&2
                print_help
                exit 1
            fi
            PI_HOST="$2"
            HOST_SPECIFIED="true"
            shift 2
            ;;
        --user)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует имени пользователя${NC}" >&2
                print_help
                exit 1
            fi
            PI_USER="$2"
            shift 2
            ;;
        --lidar-port)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует пути к порту${NC}" >&2
                print_help
                exit 1
            fi
            LIDAR_PORT="$2"
            shift 2
            ;;
        --scan-topic)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует имени топика${NC}" >&2
                print_help
                exit 1
            fi
            SCAN_TOPIC="$2"
            shift 2
            ;;
        --no-rviz)
            LAUNCH_RVIZ="false"
            shift
            ;;
        --teleop)
            LAUNCH_TELEOP="true"
            shift
            ;;
        --mock)
            MOCK_HARDWARE="true"
            shift
            ;;
        --local)
            RUN_LOCAL="true"
            shift
            ;;
        --force)
            FORCE_START="true"
            shift
            ;;
        --extra)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует строки аргументов${NC}" >&2
                print_help
                exit 1
            fi
            EXTRA_LAUNCH_ARGS="$2"
            shift 2
            ;;
        -h|--help)
            print_help
            exit 0
            ;;
        *)
            echo -e "${RED}[ERROR] Неизвестный параметр: $1${NC}" >&2
            print_help
            exit 1
            ;;
    esac
done

echo -e "${CYAN}${BOLD}================================================================${NC}"
echo -e "${CYAN}${BOLD}     IJKbot — Картографирование полигона (SLAM Toolbox)        ${NC}"
echo -e "${CYAN}${BOLD}================================================================${NC}"
echo -e "${BLUE}Хост запуска:${NC}      ${BOLD}$([[ "${RUN_LOCAL}" == "true" ]] && echo "Локальный (Ноутбук)" || echo "${PI_USER}@${PI_HOST}")${NC}"
echo -e "${BLUE}ROS_DOMAIN_ID:${NC}     ${BOLD}${ROS_DOMAIN_ID}${NC}"
echo -e "${BLUE}RMW:${NC}               ${BOLD}${RMW_IMPLEMENTATION}${NC}"
echo -e "${BLUE}Порт лидара:${NC}       ${LIDAR_PORT}"
echo -e "${BLUE}Топик сканов:${NC}      ${SCAN_TOPIC}"
echo -e "${BLUE}Моторы:${NC}            $([[ "${MOCK_HARDWARE}" == "true" ]] && echo "MOCK" || echo "STS3215 (реальные)")"
echo -e "${CYAN}----------------------------------------------------------------${NC}"

# Проверка сетевой доступности Pi (если запуск не локальный)
if [[ "${RUN_LOCAL}" != "true" ]]; then
    echo -ne "${BLUE}[1/3] Проверка связи с роботом (${PI_HOST})... ${NC}"
    SSH_PROBE_OUT=$(ssh -o BatchMode=yes -o ConnectTimeout=2 -o StrictHostKeyChecking=no "${PI_USER}@${PI_HOST}" "true" 2>&1)
    SSH_PROBE_EXIT=$?
    HOST_UNREACHABLE=false

    if [[ ${SSH_PROBE_EXIT} -eq 0 ]] || echo "${SSH_PROBE_OUT}" | grep -q "Permission denied"; then
        HOST_UNREACHABLE=false
    else
        if [[ "${HOST_SPECIFIED}" != "true" && -n "${BACKUP_HOST:-}" && "${PI_HOST}" != "${BACKUP_HOST}" ]]; then
            SSH_PROBE_BACKUP=$(ssh -o BatchMode=yes -o ConnectTimeout=2 -o StrictHostKeyChecking=no "${PI_USER}@${BACKUP_HOST}" "true" 2>&1)
            SSH_BACKUP_EXIT=$?
            if [[ ${SSH_BACKUP_EXIT} -eq 0 ]] || echo "${SSH_PROBE_BACKUP}" | grep -q "Permission denied"; then
                echo -e "${YELLOW}[WARN] Хост ${PI_HOST} недоступен. Переключение на ${BACKUP_HOST}...${NC}"
                PI_HOST="${BACKUP_HOST}"
                HOST_UNREACHABLE=false
            else
                HOST_UNREACHABLE=true
            fi
        else
            HOST_UNREACHABLE=true
        fi
    fi

    if [[ "${HOST_UNREACHABLE}" == "true" ]]; then
        echo -e "${RED}[FAIL] Робот ${PI_HOST} не отвечает по сети!${NC}"
        if [[ "${FORCE_START}" != "true" ]]; then
            echo -e "${YELLOW}Подсказка:${NC}"
            echo -e "  - Проверьте Wi-Fi (точка доступа 172.22.35.0/24 или роутер 192.168.1.0/24)."
            echo -e "  - Укажите IP явно: $0 --host <IP>"
            echo -e "  - Для симуляции без робота: $0 --mock --local"
            exit 1
        fi
    else
        echo -e "${GREEN}[OK] Связь с ${PI_HOST} установлена.${NC}"
    fi
fi

# Подготовка локального Pixi / PATH
if ! command -v pixi &>/dev/null; then
    if [[ -x "${HOME}/.pixi/bin/pixi" ]]; then
        export PATH="${HOME}/.pixi/bin:${PATH}"
    fi
fi

# Запуск RViz2 на ноутбуке (если включен)
if [[ "${LAUNCH_RVIZ}" == "true" ]]; then
    if pgrep -f "rviz2" >/dev/null 2>&1; then
        echo -e "${YELLOW}[2/3] Окно RViz2 уже запущено на ноутбуке.${NC}"
    else
        echo -e "${BLUE}[2/3] Запуск RViz2 на ноутбуке...${NC}"
        bash "${SCRIPT_DIR}/start_rviz.sh" >/dev/null 2>&1 &
        RVIZ_PID=$!
        sleep 1
    fi
else
    echo -e "${YELLOW}[2/3] Запуск RViz2 пропущен (--no-rviz).${NC}"
fi

# Опциональный запуск телеуправления в отдельном окне
if [[ "${LAUNCH_TELEOP}" == "true" ]]; then
    if command -v gnome-terminal &>/dev/null; then
        gnome-terminal --title="IJKbot Teleop" -- bash "${SCRIPT_DIR}/teleop.sh" &
        TELEOP_PID=$!
    elif command -v xterm &>/dev/null; then
        xterm -title "IJKbot Teleop" -e bash "${SCRIPT_DIR}/teleop.sh" &
        TELEOP_PID=$!
    else
        echo -e "${YELLOW}[WARN] Графический эмулятор терминала не найден. Запустите teleop.sh вручную в соседней вкладке.${NC}"
    fi
fi

# Обработчик корректного завершения по Ctrl+C
cleanup() {
    trap - SIGINT SIGTERM EXIT
    echo -e "\n${YELLOW}[INFO] Получен сигнал остановки (Ctrl+C). Завершение картографирования...${NC}"

    if [[ -n "${SSH_PID}" ]] && kill -0 "${SSH_PID}" 2>/dev/null; then
        kill -INT "${SSH_PID}" 2>/dev/null || true
    fi

    if [[ "${RUN_LOCAL}" != "true" ]]; then
        echo -e "${BLUE}Остановка нод SLAM и сенсоров на Raspberry Pi...${NC}"
        ssh -o BatchMode=yes -o ConnectTimeout=3 -o StrictHostKeyChecking=no "${PI_USER}@${PI_HOST}" "
            pkill -2 -f 'mapping.launch.py' 2>/dev/null || true;
            pkill -2 -f 'async_slam_toolbox_node' 2>/dev/null || true;
            pkill -2 -f 'sllidar_node' 2>/dev/null || true;
            pkill -2 -f 'diff_drive_node' 2>/dev/null || true;
            sleep 0.5;
            pkill -9 -f 'async_slam_toolbox_node' 2>/dev/null || true;
            pkill -9 -f 'sllidar_node' 2>/dev/null || true;
            pkill -9 -f 'diff_drive_node' 2>/dev/null || true;
            pkill -9 -f 'scan_to_scan_filter_chain' 2>/dev/null || true;
            pkill -9 -f 'robot_state_publisher' 2>/dev/null || true;
        " >/dev/null 2>&1 || true
    fi

    if [[ -n "${RVIZ_PID}" ]] && kill -0 "${RVIZ_PID}" 2>/dev/null; then
        kill -INT "${RVIZ_PID}" 2>/dev/null || true
    fi

    echo -e "${GREEN}[OK] Все процессы картографирования остановлены.${NC}"
    echo -e "${CYAN}----------------------------------------------------------------${NC}"
    echo -e "${BOLD}Не забудьте сохранить карту, если ещё не сделали этого:${NC}"
    echo -e "  ${GREEN}bash scripts/save_map.sh [имя_карты]${NC}"
    echo -e "${CYAN}================================================================${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

echo -e "${CYAN}----------------------------------------------------------------${NC}"
echo -e "${GREEN}${BOLD}[3/3] Запуск картографирования...${NC}"
echo -e "${YELLOW}  1. Для управления движением робота откройте отдельный терминал:${NC}"
echo -e "     ${BOLD}bash scripts/teleop.sh${NC}"
echo -e "${YELLOW}  2. Для сохранения карты в процессе или по завершении выполните:${NC}"
echo -e "     ${BOLD}bash scripts/save_map.sh [имя_карты]${NC}"
echo -e "${YELLOW}  3. Для остановки картографирования нажмите Ctrl+C${NC}"
echo -e "${CYAN}----------------------------------------------------------------${NC}"

if [[ "${RUN_LOCAL}" == "true" ]]; then
    PIXI_MANIFEST="${PIXI_PROJECT_MANIFEST:-/home/lev/ros2_jazzy/pixi.toml}"
    LOCAL_SETUP="${REPO_DIR}/install/setup.bash"
    if [[ ! -f "${LOCAL_SETUP}" ]]; then
        echo -e "${RED}[ERROR] Файл ${LOCAL_SETUP} не найден. Соберите пакеты: colcon build${NC}" >&2
        exit 1
    fi
    export PIXI_PROJECT_MANIFEST="${PIXI_MANIFEST}"
    pixi run bash -c "source '${LOCAL_SETUP}' && ros2 launch bringup mapping.launch.py \
        lidar_serial_port:='${LIDAR_PORT}' \
        scan_topic:='${SCAN_TOPIC}' \
        mock_hardware:='${MOCK_HARDWARE}' \
        ${EXTRA_LAUNCH_ARGS}" &
    SSH_PID=$!
    wait "${SSH_PID}" || true
else
    REMOTE_SETUP="
        export ROS_DOMAIN_ID=${ROS_DOMAIN_ID};
        export RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION};
        source /opt/ros/jazzy/setup.bash 2>/dev/null || true;
        if [[ -f '${REMOTE_WS}/install/setup.bash' ]]; then
            source '${REMOTE_WS}/install/setup.bash';
        fi
    "
    REMOTE_CMD="${REMOTE_SETUP}
        echo '[REMOTE] Запуск mapping.launch.py...';
        exec ros2 launch bringup mapping.launch.py \
            lidar_serial_port:='${LIDAR_PORT}' \
            scan_topic:='${SCAN_TOPIC}' \
            mock_hardware:='${MOCK_HARDWARE}' \
            ${EXTRA_LAUNCH_ARGS}
    "
    ssh -tt -o ConnectTimeout=5 -o StrictHostKeyChecking=no "${PI_USER}@${PI_HOST}" "bash -c \"${REMOTE_CMD}\"" &
    SSH_PID=$!
    wait "${SSH_PID}" || true
fi
