#!/usr/bin/env bash
# ==============================================================================
# start_robot_pi.sh — Запуск базового стека робота на Raspberry Pi по SSH.
#
# Запускает на бортовом компьютере:
# 1. Robot State Publisher (URDF, статические TF)
# 2. Сенсоры: Intel RealSense D435 + depthimage_to_laserscan (/scan)
# 3. Драйвер приводов Feetech STS3215 (diff_drive_node, одометрия 50 Гц)
#
# Обрабатывает Ctrl+C с гарантированной остановкой удаленных процессов на Pi.
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

PI_HOST="${PI_HOST:-${ROBOT_IP:-172.22.35.154}}"
PI_USER="${PI_USER:-${ROBOT_USER:-otmorozki}}"
REMOTE_WS="/home/${PI_USER}/IJKbot"
MOCK_HARDWARE="false"
FORCE_START="false"
RUN_LOCAL="false"
SSH_PID=""
EXTRA_LAUNCH_ARGS=""

print_help() {
    echo -e "${BOLD}Использование:${NC} $0 [ПАРАМЕТРЫ]"
    echo ""
    echo "Параметры:"
    echo "  --host <IP>          IP-адрес Raspberry Pi (по умолчанию: ${PI_HOST})"
    echo "  --user <USER>        SSH-пользователь на роботе (по умолчанию: ${PI_USER})"
    echo "  --mock               Запуск с имитацией моторов (mock_hardware:=true)"
    echo "  --local              Запуск robot.launch.py локально на этом ноутбуке (через Pixi)"
    echo "  --ws <DIR>           Путь к репозиторию на Pi (по умолчанию: ${REMOTE_WS})"
    echo "  --force              Игнорировать ошибки проверки ping и продолжать запуск"
    echo "  --extra <ARGS>       Дополнительные аргументы для robot.launch.py"
    echo "  -h, --help           Показать эту справку"
    echo ""
    echo "Переменные окружения:"
    echo "  PI_HOST / ROBOT_IP   IP-адрес Raspberry Pi (дефолт: 172.22.35.154)"
    echo "  PI_USER / ROBOT_USER SSH-пользователь (дефолт: otmorozki)"
    echo "  ROS_DOMAIN_ID        ID ROS-домена (дефолт: 42)"
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
        --mock)
            MOCK_HARDWARE="true"
            shift
            ;;
        --local)
            RUN_LOCAL="true"
            shift
            ;;
        --ws)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует пути к рабочей директории${NC}" >&2
                print_help
                exit 1
            fi
            REMOTE_WS="$2"
            shift 2
            ;;
        --force)
            FORCE_START="true"
            shift
            ;;
        --extra)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует дополнительных аргументов${NC}" >&2
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
            echo -e "${RED}[ERROR] Неизвестный аргумент: $1${NC}" >&2
            print_help
            exit 1
            ;;
    esac
done

echo -e "${CYAN}${BOLD}================================================================${NC}"
echo -e "${CYAN}${BOLD}    IJKbot — Запуск базового стека ($([[ "${RUN_LOCAL}" == "true" ]] && echo "Локально на Ноутбуке 2" || echo "На Raspberry Pi по SSH"))   ${NC}"
echo -e "${CYAN}${BOLD}================================================================${NC}"
echo -e "${BLUE}Хост запуска:${NC}      ${BOLD}$([[ "${RUN_LOCAL}" == "true" ]] && echo "Локальный (Ноутбук 2)" || echo "${PI_USER}@${PI_HOST}")${NC}"
echo -e "${BLUE}ROS_DOMAIN_ID:${NC}     ${BOLD}${ROS_DOMAIN_ID}${NC}"
echo -e "${BLUE}Режим моторов:${NC}     ${BOLD}$([[ "${MOCK_HARDWARE}" == "true" ]] && echo "MOCK (симуляция)" || echo "РЕАЛЬНЫЕ (UART STS3215)")${NC}"
echo -e "${BLUE}Рабочая папка:${NC}     $([[ "${RUN_LOCAL}" == "true" ]] && echo "${REPO_DIR}" || echo "${REMOTE_WS}")"
echo -e "${CYAN}----------------------------------------------------------------${NC}"

# Если выбран локальный запуск через Pixi
if [[ "${RUN_LOCAL}" == "true" ]]; then
    PIXI_MANIFEST="${PIXI_PROJECT_MANIFEST:-/home/lev/ros2_jazzy/pixi.toml}"
    LOCAL_SETUP="${REPO_DIR}/install/setup.bash"
    if [[ ! -f "${LOCAL_SETUP}" ]]; then
        echo -e "${RED}[ERROR] Файл окружения ${LOCAL_SETUP} не найден. Соберите пакеты: colcon build${NC}" >&2
        exit 1
    fi

    echo -e "${GREEN}[OK] Запуск robot.launch.py локально через Pixi (mock_hardware:=${MOCK_HARDWARE})...${NC}"
    export PIXI_PROJECT_MANIFEST="${PIXI_MANIFEST}"

    LOCAL_PID=""
    cleanup_local() {
        trap - SIGINT SIGTERM EXIT
        echo -e "\n${YELLOW}[INFO] Остановка локальных процессов robot.launch.py...${NC}"
        if [[ -n "${LOCAL_PID}" ]] && kill -0 "${LOCAL_PID}" 2>/dev/null; then
            kill -INT "${LOCAL_PID}" 2>/dev/null || true
        fi
        sleep 0.5
        pkill -2 -f 'diff_drive_node' 2>/dev/null || true
        pkill -2 -f 'realsense2_camera_node' 2>/dev/null || true
        pkill -2 -f 'robot_state_publisher' 2>/dev/null || true
        sleep 0.3
        pkill -9 -f 'diff_drive_node' 2>/dev/null || true
        pkill -9 -f 'realsense2_camera_node' 2>/dev/null || true
        pkill -9 -f 'depthimage_to_laserscan' 2>/dev/null || true
        pkill -9 -f 'robot_state_publisher' 2>/dev/null || true
        if [[ -n "${LOCAL_PID}" ]] && kill -0 "${LOCAL_PID}" 2>/dev/null; then
            kill -9 "${LOCAL_PID}" 2>/dev/null || true
        fi
        echo -e "${GREEN}[OK] Локальные процессы базового стека остановлены.${NC}"
        exit 0
    }
    trap cleanup_local SIGINT SIGTERM EXIT

    pixi run bash -c "source '${LOCAL_SETUP}' && ros2 launch bringup robot.launch.py \
        mock_hardware:='${MOCK_HARDWARE}' \
        ${EXTRA_LAUNCH_ARGS}" &
    LOCAL_PID=$!
    wait "${LOCAL_PID}" || true
    cleanup_local
    exit 0
fi

# 1. Проверка доступности робота по сети
echo -ne "${BLUE}[1/2] Проверка связи с роботом (${PI_HOST})... ${NC}"
SSH_PROBE_OUT=$(ssh -o BatchMode=yes -o ConnectTimeout=2 -o StrictHostKeyChecking=no "${PI_USER}@${PI_HOST}" "true" 2>&1)
SSH_PROBE_EXIT=$?
HOST_UNREACHABLE=false

if [[ ${SSH_PROBE_EXIT} -eq 0 ]] || echo "${SSH_PROBE_OUT}" | grep -q "Permission denied"; then
    HOST_UNREACHABLE=false
else
    HOST_UNREACHABLE=true
fi

if [[ "${HOST_UNREACHABLE}" == "true" ]]; then
    echo -e "${RED}[FAIL] Робот ${PI_HOST} не отвечает по сети (SSH/Ping недоступен)!${NC}"
    if [[ "${FORCE_START}" != "true" ]]; then
        echo -e "${YELLOW}Подсказка:${NC}"
        echo -e "  - Проверьте подключение к точке доступа Wi-Fi (сети телефона 172.22.35.0/24)."
        echo -e "  - Проверьте IP: возможно робот на арене соревнований (192.168.1.10)?"
        echo -e "  - Для запуска с альтернативным IP используйте: $0 --host 192.168.1.10"
        echo -e "  - Для локального прогона без робота используйте: $0 --mock --local"
        echo -e "  - Для принудительного продолжения используйте флаг --force"
        exit 1
    else
        echo -e "${YELLOW}[WARN] Флаг --force активен: продолжаем попытку SSH подключения...${NC}"
    fi
else
    echo -e "${GREEN}[OK] Связь с ${PI_HOST} установлена.${NC}"
fi

# 2. Формирование удаленной команды запуска
REMOTE_SETUP="
    export ROS_DOMAIN_ID=${ROS_DOMAIN_ID};
    export RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION};
    source /opt/ros/jazzy/setup.bash 2>/dev/null || true;
    if [[ -f '${REMOTE_WS}/install/setup.bash' ]]; then
        source '${REMOTE_WS}/install/setup.bash';
    fi
"

REMOTE_CMD="${REMOTE_SETUP}
    echo '[REMOTE] Запуск robot.launch.py (mock_hardware:=${MOCK_HARDWARE})...';
    exec ros2 launch bringup robot.launch.py mock_hardware:=${MOCK_HARDWARE} ${EXTRA_LAUNCH_ARGS}
"

CLEANUP_CALLED=false
# Функция безопасного завершения при получении сигналов
cleanup() {
    CLEANUP_CALLED=true
    echo -e "\n${YELLOW}[INFO] Получен сигнал остановки (Ctrl+C). Остановка процессов на Raspberry Pi...${NC}"
    if [[ -n "${SSH_PID}" ]] && kill -0 "${SSH_PID}" 2>/dev/null; then
        kill -INT "${SSH_PID}" 2>/dev/null || true
    fi

    # Удаленная отправка сигналов остановки на Pi (мягко SIGINT, затем SIGKILL драйверам и сенсорам)
    ssh -o BatchMode=yes -o ConnectTimeout=3 -o StrictHostKeyChecking=no "${PI_USER}@${PI_HOST}" "
        pkill -2 -f 'robot.launch.py' 2>/dev/null || true;
        pkill -2 -f 'diff_drive_node' 2>/dev/null || true;
        pkill -2 -f 'realsense2_camera_node' 2>/dev/null || true;
        sleep 0.5;
        pkill -9 -f 'robot.launch.py' 2>/dev/null || true;
        pkill -9 -f 'diff_drive_node' 2>/dev/null || true;
        pkill -9 -f 'realsense2_camera_node' 2>/dev/null || true;
        pkill -9 -f 'depthimage_to_laserscan' 2>/dev/null || true;
        pkill -9 -f 'robot_state_publisher' 2>/dev/null || true;
    " >/dev/null 2>&1 || true

    echo -e "${GREEN}[OK] Удаленные процессы базового стека на Pi остановлены.${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM

echo -e "${GREEN}${BOLD}[2/2] Подключение по SSH и запуск robot.launch.py...${NC}"
echo -e "${YELLOW}Для штатной остановки нажмите Ctrl+C${NC}"
echo -e "${CYAN}----------------------------------------------------------------${NC}"

# Запуск по SSH с выделением псевдо-терминала (-tt) для корректной передачи сигналов
ssh -tt -o ConnectTimeout=5 -o StrictHostKeyChecking=no "${PI_USER}@${PI_HOST}" "bash -c \"${REMOTE_CMD}\"" &
SSH_PID=$!

wait "${SSH_PID}"
SSH_EXIT=$?
SSH_PID=""

if [[ ${SSH_EXIT} -ne 0 && "${CLEANUP_CALLED}" != "true" ]]; then
    echo -e "${RED}[ERROR] Ошибка запуска robot.launch.py по SSH (код выхода: ${SSH_EXIT}).${NC}" >&2
    exit ${SSH_EXIT}
fi

echo -e "${GREEN}[OK] Сессия robot.launch.py на Raspberry Pi завершена.${NC}"
