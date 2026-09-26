#!/usr/bin/env bash
# ==============================================================================
# start_nav2_pi.sh — Запуск навигационного стека Nav2 на Raspberry Pi по SSH.
#
# Запускает:
# 1. Map Server (статическая карта полигона 4x4 м)
# 2. Статический TF map -> odom (чистая одометрия) или AMCL
# 3. Controller Server (Regulated Pure Pursuit) + Smoother + Planner + BT Navigator
# 4. Twist Mux (арбитраж скоростей: аварийный 100, телеоп 50, навигация 10)
#
# Обрабатывает Ctrl+C с гарантированной остановкой нод Nav2 на Pi.
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

PRIMARY_HOST="172.22.35.154"
DEFAULT_BACKUP="192.168.1.10"
PI_HOST="${PI_HOST:-${ROBOT_IP:-${PRIMARY_HOST}}}"
if [[ "${PI_HOST}" == "${DEFAULT_BACKUP}" ]]; then
    BACKUP_HOST="${PRIMARY_HOST}"
else
    BACKUP_HOST="${DEFAULT_BACKUP}"
fi
PI_USER="${PI_USER:-${ROBOT_USER:-otmorozki}}"
REMOTE_WS="/home/${PI_USER}/IJKbot"
FORCE_START="false"
RUN_LOCAL="false"
HOST_SPECIFIED="false"
SSH_PID=""

# Параметры навигации
INITIAL_X="0.4"
INITIAL_Y="0.4"
INITIAL_YAW="0.0"
USE_AMCL="false"
MAP_FILE=""
EXTRA_NAV2_ARGS=""

print_help() {
    echo -e "${BOLD}Использование:${NC} $0 [ПАРАМЕТРЫ]"
    echo ""
    echo "Параметры:"
    echo "  --host <IP>          IP-адрес Raspberry Pi (по умолчанию: ${PI_HOST})"
    echo "  --user <USER>        SSH-пользователь на роботе (по умолчанию: ${PI_USER})"
    echo "  --initial-x <X>      Начальная координата X на карте (по умолчанию: 0.4)"
    echo "  --initial-y <Y>      Начальная координата Y на карте (по умолчанию: 0.4)"
    echo "  --initial-yaw <YAW>  Начальный угол Yaw на карте в радианах (по умолчанию: 0.0)"
    echo "  --map <YAML_FILE>    Путь к пользовательской карте полигона"
    echo "  --use-amcl           Использовать AMCL локализацию (по умолчанию: одометрия)"
    echo "  --local              Запустить Nav2 локально на этом ноутбуке (через Pixi)"
    echo "  --ws <DIR>           Путь к репозиторию на Pi (по умолчанию: ${REMOTE_WS})"
    echo "  --force              Игнорировать ошибки проверки ping и продолжать запуск"
    echo "  --extra <ARGS>       Дополнительные аргументы для navigation.launch.py"
    echo "  -h, --help           Показать эту справку"
    echo ""
    echo "Переменные окружения:"
    echo "  PI_HOST / ROBOT_IP   IP-адрес Raspberry Pi (дефолт: ${PRIMARY_HOST})"
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
        --initial-x)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует значения координаты X (м)${NC}" >&2
                print_help
                exit 1
            fi
            INITIAL_X="$2"
            shift 2
            ;;
        --initial-y)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует значения координаты Y (м)${NC}" >&2
                print_help
                exit 1
            fi
            INITIAL_Y="$2"
            shift 2
            ;;
        --initial-yaw)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует значения угла Yaw (рад)${NC}" >&2
                print_help
                exit 1
            fi
            INITIAL_YAW="$2"
            shift 2
            ;;
        --map)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует пути к файлу карты (.yaml)${NC}" >&2
                print_help
                exit 1
            fi
            MAP_FILE="$2"
            shift 2
            ;;
        --use-amcl)
            USE_AMCL="true"
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
            EXTRA_NAV2_ARGS="$2"
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
echo -e "${CYAN}${BOLD}     IJKbot — Запуск навигации Nav2 ($([[ "${RUN_LOCAL}" == "true" ]] && echo "Локально на Ноутбуке 2" || echo "Удаленно на Raspberry Pi"))   ${NC}"
echo -e "${CYAN}${BOLD}================================================================${NC}"
echo -e "${BLUE}Хост запуска:${NC}      ${BOLD}$([[ "${RUN_LOCAL}" == "true" ]] && echo "Локальный (Ноутбук 2)" || echo "${PI_USER}@${PI_HOST}")${NC}"
echo -e "${BLUE}ROS_DOMAIN_ID:${NC}     ${BOLD}${ROS_DOMAIN_ID}${NC}"
echo -e "${BLUE}Стартовая поза:${NC}    X=${INITIAL_X} м, Y=${INITIAL_Y} м, Yaw=${INITIAL_YAW} рад"
echo -e "${BLUE}Локализация:${NC}       $([[ "${USE_AMCL}" == "true" ]] && echo "AMCL" || echo "Чистая одометрия + static TF map->odom")"
if [[ -n "${MAP_FILE}" ]]; then
    echo -e "${BLUE}Карта:${NC}             ${MAP_FILE}"
fi
echo -e "${CYAN}----------------------------------------------------------------${NC}"

# Если выбран локальный запуск через Pixi
if [[ "${RUN_LOCAL}" == "true" ]]; then
    PIXI_MANIFEST="${PIXI_PROJECT_MANIFEST:-/home/lev/ros2_jazzy/pixi.toml}"
    LOCAL_SETUP="${REPO_DIR}/install/setup.bash"
    if [[ ! -f "${LOCAL_SETUP}" ]]; then
        echo -e "${RED}[ERROR] Файл окружения ${LOCAL_SETUP} не найден. Соберите пакеты: colcon build${NC}" >&2
        exit 1
    fi

    echo -e "${GREEN}[OK] Запуск Nav2 локально через Pixi...${NC}"
    export PIXI_PROJECT_MANIFEST="${PIXI_MANIFEST}"
    MAP_PARAM=()
    if [[ -n "${MAP_FILE}" ]]; then
        MAP_PARAM+=("map:=${MAP_FILE}")
    fi

    LOCAL_PID=""
    cleanup_local() {
        trap - SIGINT SIGTERM EXIT
        echo -e "\n${YELLOW}[INFO] Остановка локальных процессов Nav2...${NC}"
        if [[ -n "${LOCAL_PID}" ]] && kill -0 "${LOCAL_PID}" 2>/dev/null; then
            kill -INT "${LOCAL_PID}" 2>/dev/null || true
        fi
        sleep 0.5
        pkill -2 -f 'controller_server' 2>/dev/null || true
        pkill -2 -f 'planner_server' 2>/dev/null || true
        pkill -2 -f 'bt_navigator' 2>/dev/null || true
        pkill -2 -f 'twist_mux' 2>/dev/null || true
        pkill -2 -f 'map_server' 2>/dev/null || true
        sleep 0.3
        pkill -9 -f 'controller_server' 2>/dev/null || true
        pkill -9 -f 'smoother_server' 2>/dev/null || true
        pkill -9 -f 'planner_server' 2>/dev/null || true
        pkill -9 -f 'behavior_server' 2>/dev/null || true
        pkill -9 -f 'bt_navigator' 2>/dev/null || true
        pkill -9 -f 'static_transform_publisher' 2>/dev/null || true
        pkill -9 -f 'twist_mux' 2>/dev/null || true
        pkill -9 -f 'map_server' 2>/dev/null || true
        pkill -9 -f 'nav2_' 2>/dev/null || true
        if [[ -n "${LOCAL_PID}" ]] && kill -0 "${LOCAL_PID}" 2>/dev/null; then
            kill -9 "${LOCAL_PID}" 2>/dev/null || true
        fi
        echo -e "${GREEN}[OK] Локальные ноды навигации Nav2 остановлены.${NC}"
        exit 0
    }
    trap cleanup_local SIGINT SIGTERM EXIT

    pixi run bash -c "source '${LOCAL_SETUP}' && ros2 launch nav2 navigation.launch.py \
        initial_x:='${INITIAL_X}' \
        initial_y:='${INITIAL_Y}' \
        initial_yaw:='${INITIAL_YAW}' \
        use_amcl:='${USE_AMCL}' \
        ${MAP_PARAM[*]} \
        ${EXTRA_NAV2_ARGS}" &
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
    # Если хост не был задан явно через --host, пробуем резервный
    if [[ "${HOST_SPECIFIED}" != "true" && -n "${BACKUP_HOST:-}" && "${PI_HOST}" != "${BACKUP_HOST}" ]]; then
        SSH_PROBE_BACKUP=$(ssh -o BatchMode=yes -o ConnectTimeout=2 -o StrictHostKeyChecking=no "${PI_USER}@${BACKUP_HOST}" "true" 2>&1)
        SSH_BACKUP_EXIT=$?
        if [[ ${SSH_BACKUP_EXIT} -eq 0 ]] || echo "${SSH_PROBE_BACKUP}" | grep -q "Permission denied"; then
            echo -e "${YELLOW}[WARN] Хост ${PI_HOST} не отвечает. Автоматическое переключение на ${BACKUP_HOST}...${NC}"
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
    echo -e "${RED}[FAIL] Робот ${PI_HOST} не отвечает по сети (SSH/Ping недоступен)!${NC}"
    if [[ "${FORCE_START}" != "true" ]]; then
        echo -e "${YELLOW}Подсказка:${NC}"
        echo -e "  - Проверьте подключение к точке доступа Wi-Fi (сети телефона 172.22.35.0/24)."
        echo -e "  - Проверьте IP: возможно робот на арене соревнований (192.168.1.10)?"
        echo -e "  - Для запуска с альтернативным IP используйте: $0 --host 192.168.1.10"
        echo -e "  - Для локального прогона используйте: $0 --local"
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

MAP_REMOTE=""
if [[ -n "${MAP_FILE}" ]]; then
    MAP_REMOTE="map:=${MAP_FILE}"
fi

REMOTE_CMD="${REMOTE_SETUP}
    echo '[REMOTE] Запуск navigation.launch.py...';
    exec ros2 launch nav2 navigation.launch.py \
        initial_x:=${INITIAL_X} \
        initial_y:=${INITIAL_Y} \
        initial_yaw:=${INITIAL_YAW} \
        use_amcl:=${USE_AMCL} \
        ${MAP_REMOTE} \
        ${EXTRA_NAV2_ARGS}
"

CLEANUP_CALLED=false
# Функция безопасного завершения при получении сигналов
cleanup() {
    CLEANUP_CALLED=true
    echo -e "\n${YELLOW}[INFO] Получен сигнал остановки (Ctrl+C). Остановка Nav2 на Raspberry Pi...${NC}"
    if [[ -n "${SSH_PID}" ]] && kill -0 "${SSH_PID}" 2>/dev/null; then
        kill -INT "${SSH_PID}" 2>/dev/null || true
    fi

    # Удаленная отправка сигналов остановки на Pi (мягко SIGINT, затем гарантированно SIGKILL всем Nav2 компонентам)
    ssh -o BatchMode=yes -o ConnectTimeout=3 -o StrictHostKeyChecking=no "${PI_USER}@${PI_HOST}" "
        pkill -2 -f 'navigation.launch.py' 2>/dev/null || true;
        sleep 0.5;
        pkill -9 -f 'navigation.launch.py' 2>/dev/null || true;
        pkill -9 -f 'controller_server' 2>/dev/null || true;
        pkill -9 -f 'smoother_server' 2>/dev/null || true;
        pkill -9 -f 'planner_server' 2>/dev/null || true;
        pkill -9 -f 'behavior_server' 2>/dev/null || true;
        pkill -9 -f 'bt_navigator' 2>/dev/null || true;
        pkill -9 -f 'static_transform_publisher' 2>/dev/null || true;
        pkill -9 -f 'twist_mux' 2>/dev/null || true;
        pkill -9 -f 'map_server' 2>/dev/null || true;
        pkill -9 -f 'nav2_' 2>/dev/null || true;
    " >/dev/null 2>&1 || true

    echo -e "${GREEN}[OK] Ноды навигации Nav2 на Pi остановлены.${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM

echo -e "${GREEN}${BOLD}[2/2] Подключение по SSH и запуск navigation.launch.py...${NC}"
echo -e "${YELLOW}Для штатной остановки нажмите Ctrl+C${NC}"
echo -e "${CYAN}----------------------------------------------------------------${NC}"

ssh -tt -o ConnectTimeout=5 -o StrictHostKeyChecking=no "${PI_USER}@${PI_HOST}" "bash -c \"${REMOTE_CMD}\"" &
SSH_PID=$!

wait "${SSH_PID}"
SSH_EXIT=$?
SSH_PID=""

if [[ ${SSH_EXIT} -ne 0 && "${CLEANUP_CALLED}" != "true" ]]; then
    echo -e "${RED}[ERROR] Ошибка запуска navigation.launch.py по SSH (код выхода: ${SSH_EXIT}).${NC}" >&2
    exit ${SSH_EXIT}
fi

echo -e "${GREEN}[OK] Сессия Nav2 на Raspberry Pi завершена.${NC}"
