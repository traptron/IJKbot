#!/usr/bin/env bash
# ==============================================================================
# start_all_laptop2.sh — Единый командный центр / оркестратор запуска (Ноутбук 2)
#
# Сценарий соревнований:
# - Машина 1 (Ноутбук 1): Ollama LLM + NiceGUI Web Dashboard (судейский экран)
# - Машина 2 (Ноутбук 2, этот компьютер): Оператор, SSH-управление Pi, Nav2, RViz2
# - Машина 3 (Raspberry Pi 4B): Бортовые сенсоры, RealSense, STS3215, одометрия
#
# Последовательность запуска:
# 1. Проверка доступности робота по сети (ping) и автопереключение на резервный IP.
# 2. Проверка синхронизации часов Chrony (|Δt| < 5.0 мс по регламенту).
# 3. Запуск базового стека на Pi по SSH (robot.launch.py).
# 4. Запуск навигации Nav2 на Pi по SSH (navigation.launch.py).
# 5. Запуск RViz2 локально через Pixi (ROS 2 Jazzy).
# 6. Перехват Ctrl+C и гарантированная остановка всех систем (stop_all.sh).
# ==============================================================================
set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${REPO_DIR}/log"
mkdir -p "${LOG_DIR}"

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"

# Параметры по умолчанию
PI_HOST="${PI_HOST:-${ROBOT_IP:-192.168.1.10}}"
BACKUP_HOST="172.22.35.154"
PI_USER="${PI_USER:-${ROBOT_USER:-otmorozki}}"
MOCK_HARDWARE="false"
RUN_LOCAL="false"
SKIP_SYNC="false"
START_RVIZ="true"
THRESHOLD_MS="5.0"
LAUNCH_MODE="bg" # 'bg', 'tabs', 'windows', 'tmux'
INITIAL_X="0.4"
INITIAL_Y="0.4"
INITIAL_YAW="0.0"
USE_AMCL="false"
MAP_FILE=""
FORCE_START="false"
NO_CAMERA="false"

ROBOT_PID=""
NAV2_PID=""
RVIZ_PID=""
CLEANUP_DONE=false

print_help() {
    echo -e "${BOLD}Использование:${NC} $0 [ПАРАМЕТРЫ]"
    echo ""
    echo "Параметры запуска:"
    echo "  --host <IP>          IP-адрес Raspberry Pi (по умолчанию: ${PI_HOST})"
    echo "  --user <USER>        SSH-пользователь на роботе (по умолчанию: ${PI_USER})"
    echo "  --mock               Режим симуляции моторов (mock_hardware:=true, без реального UART)"
    echo "  --local              Запуск всех компонентов локально на Ноутбуке 2 (через Pixi)"
    echo "  --force              Игнорировать сбои сетевых проверок и продолжать запуск"
    echo "  --mode <MODE>        Режим запуска интерфейсов: 'bg' (по умолчанию), 'tabs', 'windows', 'tmux'"
    echo "  --no-rviz            Не запускать RViz2 (фоновый режим)"
    echo "  --no-camera          Не запускать камеру RealSense (только моторы и одометрия)"
    echo "  --skip-sync          Пропустить предстартовую проверку Chrony (или игнорировать ошибку Δt)"
    echo "  --threshold-ms <MS>  Максимально допустимое расхождение времени в мс (по умолчанию: 5.0)"
    echo "  --initial-x <X>      Начальная координата X на карте (по умолчанию: 0.4)"
    echo "  --initial-y <Y>      Начальная координата Y на карте (по умолчанию: 0.4)"
    echo "  --initial-yaw <YAW>  Начальный угол Yaw на карте (по умолчанию: 0.0)"
    echo "  --map <YAML_FILE>    Путь к пользовательской карте полигона (.yaml)"
    echo "  --use-amcl           Использовать AMCL локализацию (по умолчанию: одометрия)"
    echo "  -h, --help           Показать эту справку"
    echo ""
    echo "Переменные окружения:"
    echo "  PI_HOST / ROBOT_IP   IP-адрес Raspberry Pi (дефолт: 192.168.1.10)"
    echo "  PI_USER / ROBOT_USER SSH-пользователь (дефолт: otmorozki)"
    echo "  ROS_DOMAIN_ID        ID ROS-домена (дефолт: 42)"
    echo ""
    echo "Примеры:"
    echo "  $0                   Обычный соревновательный запуск (Wi-Fi 192.168.1.10)"
    echo "  $0 --mock --local    Полностью автономный тестовый прогон на ноутбуке без робота"
    echo "  $0 --mode tabs       Запуск компонентов в отдельных вкладках терминала"
}

# Разбор флагов
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
        --mode)
            LAUNCH_MODE="$2"
            shift 2
            ;;
        --no-rviz)
            START_RVIZ="false"
            shift
            ;;
        --no-camera)
            NO_CAMERA="true"
            shift
            ;;
        --skip-sync)
            SKIP_SYNC="true"
            shift
            ;;
        --threshold-ms)
            THRESHOLD_MS="$2"
            shift 2
            ;;
        --initial-x)
            INITIAL_X="$2"
            shift 2
            ;;
        --initial-y)
            INITIAL_Y="$2"
            shift 2
            ;;
        --initial-yaw)
            INITIAL_YAW="$2"
            shift 2
            ;;
        --map)
            MAP_FILE="$2"
            shift 2
            ;;
        --use-amcl)
            USE_AMCL="true"
            shift
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
echo -e "${CYAN}${BOLD}     IJKbot — Единый командный центр (Ноутбук 2 / Оператор)     ${NC}"
echo -e "${CYAN}${BOLD}================================================================${NC}"
echo -e "${BLUE}Хост робота:${NC}       ${BOLD}$([[ "${RUN_LOCAL}" == "true" ]] && echo "Локальный (Ноутбук 2)" || echo "${PI_USER}@${PI_HOST}")${NC}"
echo -e "${BLUE}ROS_DOMAIN_ID:${NC}     ${BOLD}${ROS_DOMAIN_ID}${NC}"
echo -e "${BLUE}Режим аппаратуры:${NC}  $([[ "${MOCK_HARDWARE}" == "true" ]] && echo -e "${YELLOW}MOCK (симуляция)${NC}" || echo -e "${GREEN}ФИЗИЧЕСКИЙ РОБОТ (UART STS3215)${NC}")"
echo -e "${BLUE}Режим запуска:${NC}     ${BOLD}${LAUNCH_MODE}${NC} (логи в ${LOG_DIR}/)"
echo -e "${BLUE}Запуск RViz2:${NC}      ${START_RVIZ}"
echo -e "${CYAN}----------------------------------------------------------------${NC}"

# Функция гарантированной остановки при завершении
cleanup_all() {
    if [[ "${CLEANUP_DONE}" == "true" ]]; then
        return
    fi
    CLEANUP_DONE=true
    echo -e "\n${RED}${BOLD}[STOP] Получен сигнал завершения. Остановка всех систем IJKbot...${NC}"

    # Остановка локального RViz, если был запущен в фоне
    if [[ -n "${RVIZ_PID}" ]] && kill -0 "${RVIZ_PID}" 2>/dev/null; then
        kill -INT "${RVIZ_PID}" 2>/dev/null || true
    fi

    # Вызов штатного стоп-скрипта (передаем caller-pid, чтобы стоп-скрипт не убил нас)
    if [[ -f "${SCRIPT_DIR}/stop_all.sh" ]]; then
        "${SCRIPT_DIR}/stop_all.sh" --host "${PI_HOST}" --user "${PI_USER}" --caller-pid $$ || true
    fi

    # Завершение фоновых процессов
    if [[ -n "${ROBOT_PID}" ]] && kill -0 "${ROBOT_PID}" 2>/dev/null; then
        kill -9 "${ROBOT_PID}" 2>/dev/null || true
    fi
    if [[ -n "${NAV2_PID}" ]] && kill -0 "${NAV2_PID}" 2>/dev/null; then
        kill -9 "${NAV2_PID}" 2>/dev/null || true
    fi

    echo -e "${GREEN}[OK] Работа оркестратора Ноутбука 2 завершена.${NC}"
}
trap cleanup_all EXIT INT TERM

# ==============================================================================
# ШАГ 1: Проверка доступности робота по сети
# ==============================================================================
echo -e "${BLUE}${BOLD}[ШАГ 1/5] Проверка сетевого подключения к роботу...${NC}"
check_host_reachability() {
    local target="$1"
    local probe
    probe=$(ssh -o BatchMode=yes -o ConnectTimeout=2 -o StrictHostKeyChecking=no "${PI_USER}@${target}" "true" 2>&1 || true)
    if echo "${probe}" | grep -qE "timed out|No route to host|Connection refused|Connection timed out during banner exchange"; then
        return 1
    elif ! ping -c 1 -W 1 "${target}" &>/dev/null && [[ -n "${probe}" ]] && ! echo "${probe}" | grep -qE "Permission denied"; then
        return 1
    fi
    return 0
}

if [[ "${RUN_LOCAL}" == "true" ]]; then
    echo -e "${YELLOW}[SKIP] Локальный режим (--local): проверка сетевого подключения пропущена.${NC}"
elif [[ "${MOCK_HARDWARE}" == "true" && "${FORCE_START}" == "true" ]]; then
    echo -e "${YELLOW}[SKIP] Режим симуляции с флагом --force: проверка физического подключения пропущена.${NC}"
else
    if check_host_reachability "${PI_HOST}"; then
        echo -e "${GREEN}[OK] Робот ${PI_HOST} доступен.${NC}"
    else
        echo -e "${YELLOW}[WARN] Хост ${PI_HOST} не отвечает по сети.${NC}"
        # Проверяем резервный IP (мобильная точка)
        if [[ "${PI_HOST}" != "${BACKUP_HOST}" ]] && check_host_reachability "${BACKUP_HOST}"; then
            echo -e "${GREEN}[INFO] Резервный хост ${BACKUP_HOST} доступен! Переключение на ${BACKUP_HOST}...${NC}"
            PI_HOST="${BACKUP_HOST}"
        else
            echo -e "${RED}[ERROR] Не удалось связаться с Raspberry Pi ни по ${PI_HOST}, ни по ${BACKUP_HOST}!${NC}"
            if [[ "${MOCK_HARDWARE}" == "true" ]]; then
                echo -e "${YELLOW}[AUTO-SWITCH] Включен режим --mock: автоматически переключаемся в локальный режим (--local)...${NC}"
                RUN_LOCAL="true"
            elif [[ "${FORCE_START}" == "true" ]]; then
                echo -e "${YELLOW}[WARN] Флаг --force активен: продолжаем запуск вопреки ошибкам сети...${NC}"
            else
                echo -e "${YELLOW}Подсказка:${NC}"
                echo -e "  - Проверьте Wi-Fi роутер (5 ГГц) и питание робота."
                echo -e "  - Для запуска без робота на этом ноутбуке используйте: $0 --mock --local"
                echo -e "  - Для принудительного продолжения используйте: $0 --force"
                exit 1
            fi
        fi
    fi
fi

# ==============================================================================
# ШАГ 2: Проверка синхронизации часов Chrony
# ==============================================================================
echo -e "\n${BLUE}${BOLD}[ШАГ 2/5] Проверка синхронизации часов Chrony (|Δt| < ${THRESHOLD_MS} мс)...${NC}"
if [[ "${SKIP_SYNC}" == "true" ]]; then
    echo -e "${YELLOW}[SKIP] Предстартовая проверка времени пропущена флагом --skip-sync.${NC}"
else
    CHECK_CMD=(python3 "${SCRIPT_DIR}/check_clock_sync.py" --host "${PI_HOST}" --user "${PI_USER}" --threshold-ms "${THRESHOLD_MS}")
    if [[ "${MOCK_HARDWARE}" == "true" || "${RUN_LOCAL}" == "true" ]]; then
        CHECK_CMD+=(--mock)
    fi

    if "${CHECK_CMD[@]}"; then
        echo -e "${GREEN}[OK] Синхронизация времени в норме (регламент соблюден).${NC}"
    else
        echo -e "${RED}[FAIL] Ошибка синхронизации времени с Raspberry Pi!${NC}"
        echo -e "${YELLOW}Регламент соревнований требует |Δt| < 5.0 мс для корректной работы TF-дерева и Nav2.${NC}"
        echo -e "${YELLOW}Для настройки выполните: ./scripts/setup_chrony.sh deploy-pi${NC}"
        echo -e "Хотите продолжить запуск несмотря на рассинхронизацию? [y/N]: "
        read -r -t 10 response || response="N"
        if [[ ! "${response}" =~ ^[yYдД]$ ]]; then
            echo -e "${RED}[ABORT] Запуск отменен оператором из-за рассинхронизации часов.${NC}"
            exit 1
        fi
        echo -e "${YELLOW}[WARN] Продолжение запуска с риском рассинхронизации TF!${NC}"
    fi
fi

# ==============================================================================
# ШАГ 3: Запуск базового стека робота (robot.launch.py)
# ==============================================================================
echo -e "\n${BLUE}${BOLD}[ШАГ 3/5] Запуск базового стека ($([[ "${RUN_LOCAL}" == "true" ]] && echo "локально через Pixi" || echo "на Raspberry Pi по SSH"))...${NC}"
ROBOT_LOG="${LOG_DIR}/robot_pi.log"

START_ROBOT_CMD="${SCRIPT_DIR}/start_robot_pi.sh --host ${PI_HOST} --user ${PI_USER}"
if [[ "${MOCK_HARDWARE}" == "true" ]]; then
    START_ROBOT_CMD="${START_ROBOT_CMD} --mock"
fi
if [[ "${RUN_LOCAL}" == "true" ]]; then
    START_ROBOT_CMD="${START_ROBOT_CMD} --local --extra enable_camera:=false"
elif [[ "${FORCE_START}" == "true" ]]; then
    START_ROBOT_CMD="${START_ROBOT_CMD} --force"
fi
if [[ "${NO_CAMERA}" == "true" && "${RUN_LOCAL}" != "true" ]]; then
    START_ROBOT_CMD="${START_ROBOT_CMD} --extra enable_camera:=false"
fi

case "${LAUNCH_MODE}" in
    tmux)
        if command -v tmux &>/dev/null; then
            tmux new-session -d -s ijkbot -n "robot" "${START_ROBOT_CMD}"
            echo -e "${GREEN}[OK] robot.launch.py запущен в tmux окне 'ijkbot:robot'${NC}"
        else
            echo -e "${YELLOW}[WARN] tmux не установлен. Переключение в режим фоновых логов (bg)...${NC}"
            LAUNCH_MODE="bg"
        fi
        ;;
    tabs|windows)
        TERMINAL_BIN=""
        if command -v ptyxis &>/dev/null; then
            TERMINAL_BIN="ptyxis"
        elif command -v gnome-terminal &>/dev/null; then
            TERMINAL_BIN="gnome-terminal"
        fi

        if [[ -n "${TERMINAL_BIN}" ]]; then
            if [[ "${LAUNCH_MODE}" == "tabs" && "${TERMINAL_BIN}" == "ptyxis" ]]; then
                ptyxis --tab -d "${REPO_DIR}" -T "IJKbot Robot" -- bash -c "${START_ROBOT_CMD}; exec bash" &
            elif [[ "${LAUNCH_MODE}" == "tabs" && "${TERMINAL_BIN}" == "gnome-terminal" ]]; then
                gnome-terminal --tab --title="IJKbot Robot" -- bash -c "${START_ROBOT_CMD}; exec bash" &
            else
                "${TERMINAL_BIN}" --title="IJKbot Robot" -- bash -c "${START_ROBOT_CMD}; exec bash" &
            fi
            echo -e "${GREEN}[OK] robot.launch.py запущен в отдельном окне/вкладке терминала.${NC}"
        else
            echo -e "${YELLOW}[WARN] Эмулятор терминала не найден. Переключение в фоновый режим (bg)...${NC}"
            LAUNCH_MODE="bg"
        fi
        ;;
esac

if [[ "${LAUNCH_MODE}" == "bg" ]]; then
    echo -e "${BLUE}Лог пишется в:${NC} ${ROBOT_LOG}"
    ${START_ROBOT_CMD} > "${ROBOT_LOG}" 2>&1 &
    ROBOT_PID=$!
    echo -e "${GREEN}[OK] robot.launch.py запущен в фоне (PID ${ROBOT_PID}).${NC}"
fi

echo -ne "${BLUE}Ожидание инициализации драйвера и сенсоров (4 сек)... ${NC}"
sleep 4
if [[ "${LAUNCH_MODE}" == "bg" ]]; then
    if ! kill -0 "${ROBOT_PID}" 2>/dev/null; then
        echo -e "${RED}[FAIL] robot.launch.py завершился с ошибкой сразу после старта!${NC}" >&2
        echo -e "${YELLOW}Последние строки лога (${ROBOT_LOG}):${NC}" >&2
        tail -n 20 "${ROBOT_LOG}" >&2 || true
        cleanup_all
        exit 1
    fi
fi
echo -e "${GREEN}Готово.${NC}"

# ==============================================================================
# ШАГ 4: Запуск навигационного стека Nav2 (navigation.launch.py)
# ==============================================================================
echo -e "\n${BLUE}${BOLD}[ШАГ 4/5] Запуск навигации Nav2 ($([[ "${RUN_LOCAL}" == "true" ]] && echo "локально через Pixi" || echo "на Raspberry Pi по SSH"))...${NC}"
NAV2_LOG="${LOG_DIR}/nav2_pi.log"

START_NAV2_CMD="${SCRIPT_DIR}/start_nav2_pi.sh --host ${PI_HOST} --user ${PI_USER} --initial-x ${INITIAL_X} --initial-y ${INITIAL_Y} --initial-yaw ${INITIAL_YAW}"
if [[ "${USE_AMCL}" == "true" ]]; then
    START_NAV2_CMD="${START_NAV2_CMD} --use-amcl"
fi
if [[ -n "${MAP_FILE}" ]]; then
    START_NAV2_CMD="${START_NAV2_CMD} --map ${MAP_FILE}"
fi
if [[ "${RUN_LOCAL}" == "true" ]]; then
    START_NAV2_CMD="${START_NAV2_CMD} --local"
elif [[ "${FORCE_START}" == "true" ]]; then
    START_NAV2_CMD="${START_NAV2_CMD} --force"
fi

case "${LAUNCH_MODE}" in
    tmux)
        tmux new-window -t ijkbot -n "nav2" "${START_NAV2_CMD}"
        echo -e "${GREEN}[OK] navigation.launch.py запущен в tmux окне 'ijkbot:nav2'${NC}"
        ;;
    tabs|windows)
        if [[ -n "${TERMINAL_BIN:-}" ]]; then
            if [[ "${LAUNCH_MODE}" == "tabs" && "${TERMINAL_BIN}" == "ptyxis" ]]; then
                ptyxis --tab -d "${REPO_DIR}" -T "IJKbot Nav2" -- bash -c "${START_NAV2_CMD}; exec bash" &
            elif [[ "${LAUNCH_MODE}" == "tabs" && "${TERMINAL_BIN}" == "gnome-terminal" ]]; then
                gnome-terminal --tab --title="IJKbot Nav2" -- bash -c "${START_NAV2_CMD}; exec bash" &
            else
                "${TERMINAL_BIN}" --title="IJKbot Nav2" -- bash -c "${START_NAV2_CMD}; exec bash" &
            fi
            echo -e "${GREEN}[OK] navigation.launch.py запущен в отдельном окне/вкладке терминала.${NC}"
        fi
        ;;
    bg)
        echo -e "${BLUE}Лог пишется в:${NC} ${NAV2_LOG}"
        ${START_NAV2_CMD} > "${NAV2_LOG}" 2>&1 &
        NAV2_PID=$!
        echo -e "${GREEN}[OK] navigation.launch.py запущен в фоне (PID ${NAV2_PID}).${NC}"
        ;;
esac

echo -ne "${BLUE}Ожидание конфигурации Lifecycle нод Nav2 (3 сек)... ${NC}"
sleep 3
if [[ "${LAUNCH_MODE}" == "bg" ]]; then
    if ! kill -0 "${NAV2_PID}" 2>/dev/null; then
        echo -e "${RED}[FAIL] navigation.launch.py завершился с ошибкой сразу после старта!${NC}" >&2
        echo -e "${YELLOW}Последние строки лога (${NAV2_LOG}):${NC}" >&2
        tail -n 20 "${NAV2_LOG}" >&2 || true
        cleanup_all
        exit 1
    fi
fi
echo -e "${GREEN}Готово.${NC}"

# ==============================================================================
# ШАГ 5: Запуск RViz2 на Ноутбуке 2
# ==============================================================================
echo -e "\n${BLUE}${BOLD}[ШАГ 5/5] Запуск RViz2 (ROS 2 Jazzy Pixi)...${NC}"

if [[ "${START_RVIZ}" != "true" ]]; then
    echo -e "${YELLOW}[INFO] Запуск RViz2 пропущен (--no-rviz).${NC}"
    echo -e "${GREEN}${BOLD}Все системы запущены и работают в фоне!${NC}"
    echo -e "${YELLOW}Для аварийной остановки нажмите Ctrl+C или выполните: ./scripts/stop_all.sh${NC}"
    # Ожидание и мониторинг фоновых процессов до нажатия Ctrl+C
    while true; do
        if [[ -n "${ROBOT_PID}" ]] && ! kill -0 "${ROBOT_PID}" 2>/dev/null; then
            echo -e "${RED}[ERROR] Процесс robot.launch.py неожиданно завершился!${NC}" >&2
            tail -n 10 "${ROBOT_LOG}" >&2 || true
            cleanup_all
            exit 1
        fi
        if [[ -n "${NAV2_PID}" ]] && ! kill -0 "${NAV2_PID}" 2>/dev/null; then
            echo -e "${RED}[ERROR] Процесс navigation.launch.py неожиданно завершился!${NC}" >&2
            tail -n 10 "${NAV2_LOG}" >&2 || true
            cleanup_all
            exit 1
        fi
        sleep 2
    done
else
    START_RVIZ_CMD="${SCRIPT_DIR}/start_rviz.sh"

    case "${LAUNCH_MODE}" in
        tmux)
            tmux new-window -t ijkbot -n "rviz" "${START_RVIZ_CMD}"
            echo -e "${GREEN}[OK] RViz2 запущен в tmux окне 'ijkbot:rviz'${NC}"
            echo -e "${CYAN}Для просмотра подключитесь к сессии: tmux attach -t ijkbot${NC}"
            tmux attach -t ijkbot
            ;;
        tabs|windows)
            if [[ -n "${TERMINAL_BIN:-}" ]]; then
                "${START_RVIZ_CMD}"
            fi
            ;;
        bg)
            echo -e "${GREEN}${BOLD}Запуск RViz2 в основном окне...${NC}"
            echo -e "${YELLOW}Закрытие окна RViz2 или Ctrl+C штатно остановит все системы робота.${NC}"
            "${START_RVIZ_CMD}" || true
            ;;
    esac
fi

# При нормальном выходе из RViz штатно выполняем остановку
cleanup_all
