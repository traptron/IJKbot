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
PRIMARY_HOST="172.22.35.154"
DEFAULT_BACKUP="192.168.1.10"
PI_HOST="${PI_HOST:-${ROBOT_IP:-${PRIMARY_HOST}}}"
if [[ "${PI_HOST}" == "${DEFAULT_BACKUP}" ]]; then
    BACKUP_HOST="${PRIMARY_HOST}"
else
    BACKUP_HOST="${DEFAULT_BACKUP}"
fi
HOST_SPECIFIED="false"
PI_USER="${PI_USER:-${ROBOT_USER:-otmorozki}}"
REMOTE_WS="${REMOTE_WS:-/home/${PI_USER}/IJKbot}"
MOCK_HARDWARE="false"
RUN_LOCAL="false"
SKIP_SYNC="false"
START_RVIZ="true"
THRESHOLD_MS="5.0"
LAUNCH_MODE="bg" # 'bg', 'tabs', 'windows', 'tmux'
INITIAL_X="0.4"
INITIAL_Y="0.4"
INITIAL_YAW="0.0"
LOC_METHOD=""
USE_AMCL="false"
MAP_FILE=""
MAP_INPUT=""
INTERACTIVE_MODE="auto" # 'auto', 'true', 'false'
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
    echo "  --map <YAML_FILE>    Путь к карте или имя файла в src/nav2/maps/ (например: polygon_real)"
    echo "  --loc <MODE>         Способ локализации: 'amcl' (по лидару и карте), 'odom', 'slam'"
    echo "  --use-amcl           Использовать AMCL локализацию (shortcut для --loc amcl)"
    echo "  --use-odom           Использовать чистую одометрию (shortcut для --loc odom)"
    echo "  --slam               Использовать SLAM картографирование на лету (shortcut для --loc slam)"
    echo "  -i, --interactive    Принудительно показать интерактивное меню выбора карты и локализации"
    echo "  -y, --batch          Пропустить интерактивное меню (использовать дефолты или флаги CLI)"
    echo "  -h, --help           Показать эту справку"
    echo ""
    echo "Переменные окружения:"
    echo "  PI_HOST / ROBOT_IP   IP-адрес Raspberry Pi (дефолт: ${PRIMARY_HOST})"
    echo "  PI_USER / ROBOT_USER SSH-пользователь (дефолт: otmorozki)"
    echo "  ROS_DOMAIN_ID        ID ROS-домена (дефолт: 42)"
    echo ""
    echo "Примеры:"
    echo "  $0                   Интерактивный запуск с выбором карты и способа локализации"
    echo "  $0 --map polygon_real --loc amcl  Запуск с реальной картой и AMCL локализацией"
    echo "  $0 --mock --local    Полностью автономный тестовый прогон на ноутбуке без робота"
    echo "  $0 --mode tabs       Запуск компонентов в отдельных вкладках терминала"
}

# Разбор флагов
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
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует указания режима ('bg', 'tabs', 'windows', 'tmux')${NC}" >&2
                print_help
                exit 1
            fi
            if [[ ! "$2" =~ ^(bg|tabs|windows|tmux)$ ]]; then
                echo -e "${RED}[ERROR] Неизвестный режим запуска: ${2:-<не указан>}${NC}" >&2
                print_help
                exit 1
            fi
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
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует значения в мс${NC}" >&2
                print_help
                exit 1
            fi
            THRESHOLD_MS="$2"
            shift 2
            ;;
        --initial-x)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует значения X (м)${NC}" >&2
                print_help
                exit 1
            fi
            INITIAL_X="$2"
            shift 2
            ;;
        --initial-y)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует значения Y (м)${NC}" >&2
                print_help
                exit 1
            fi
            INITIAL_Y="$2"
            shift 2
            ;;
        --initial-yaw)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует значения Yaw (рад)${NC}" >&2
                print_help
                exit 1
            fi
            INITIAL_YAW="$2"
            shift 2
            ;;
        --map)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует пути или имени карты${NC}" >&2
                print_help
                exit 1
            fi
            MAP_INPUT="$2"
            shift 2
            ;;
        --loc|--localization)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует способа локализации (amcl, odom, slam)${NC}" >&2
                print_help
                exit 1
            fi
            case "$2" in
                amcl|AMCL) LOC_METHOD="amcl" ;;
                odom|ODOM|static|STATIC) LOC_METHOD="odom" ;;
                slam|SLAM) LOC_METHOD="slam" ;;
                *)
                    echo -e "${RED}[ERROR] Неизвестный способ локализации: $2 (допустимо: amcl, odom, slam)${NC}" >&2
                    exit 1
                    ;;
            esac
            shift 2
            ;;
        --use-amcl)
            LOC_METHOD="amcl"
            shift
            ;;
        --use-odom)
            LOC_METHOD="odom"
            shift
            ;;
        --slam)
            LOC_METHOD="slam"
            shift
            ;;
        -i|--interactive)
            INTERACTIVE_MODE="true"
            shift
            ;;
        -y|--non-interactive|--batch)
            INTERACTIVE_MODE="false"
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

MAPS_DIR="${REPO_DIR}/src/nav2/maps"

# 1. Сбор всех доступных карт из src/nav2/maps/
AVAILABLE_MAPS=()
if [[ -d "${MAPS_DIR}" ]]; then
    # Приоритет polygon_real.yaml, затем polygon_empty_4x4.yaml, затем остальные
    if [[ -f "${MAPS_DIR}/polygon_real.yaml" ]]; then
        AVAILABLE_MAPS+=("${MAPS_DIR}/polygon_real.yaml")
    fi
    if [[ -f "${MAPS_DIR}/polygon_empty_4x4.yaml" ]]; then
        AVAILABLE_MAPS+=("${MAPS_DIR}/polygon_empty_4x4.yaml")
    fi
    for m in "${MAPS_DIR}"/*.yaml; do
        [[ -f "$m" ]] || continue
        if [[ "$m" != "${MAPS_DIR}/polygon_real.yaml" && "$m" != "${MAPS_DIR}/polygon_empty_4x4.yaml" ]]; then
            AVAILABLE_MAPS+=("$m")
        fi
    done
fi

# 2. Если карта передана через аргумент командной строки
if [[ -n "${MAP_INPUT}" ]]; then
    if [[ -f "${MAP_INPUT}" ]]; then
        MAP_FILE="$(realpath "${MAP_INPUT}")"
    elif [[ -f "${MAPS_DIR}/${MAP_INPUT}" ]]; then
        MAP_FILE="${MAPS_DIR}/${MAP_INPUT}"
    elif [[ -f "${MAPS_DIR}/${MAP_INPUT}.yaml" ]]; then
        MAP_FILE="${MAPS_DIR}/${MAP_INPUT}.yaml"
    else
        echo -e "${RED}[ERROR] Карта '${MAP_INPUT}' не найдена!${NC}" >&2
        echo -e "${YELLOW}Доступные карты в ${MAPS_DIR}:${NC}" >&2
        for m in "${AVAILABLE_MAPS[@]}"; do
            echo -e "  - $(basename "$m")" >&2
        done
        exit 1
    fi
fi

# 3. Интерактивный режим выбора (если терминал интерактивный и не все параметры переданы)
SHOULD_PROMPT="false"
if [[ "${INTERACTIVE_MODE}" == "true" ]]; then
    SHOULD_PROMPT="true"
elif [[ "${INTERACTIVE_MODE}" == "auto" && -t 0 ]]; then
    if [[ -z "${MAP_FILE}" || -z "${LOC_METHOD}" ]]; then
        SHOULD_PROMPT="true"
    fi
fi

if [[ "${SHOULD_PROMPT}" == "true" ]]; then
    # Меню выбора карты (если не была задана через флаг)
    if [[ -z "${MAP_FILE}" ]]; then
        echo -e "\n${CYAN}${BOLD}----------------------------------------------------------------${NC}"
        echo -e "${CYAN}${BOLD}                 [ВЫБОР КАРТЫ ПОЛИГОНА]                         ${NC}"
        echo -e "${CYAN}${BOLD}----------------------------------------------------------------${NC}"
        echo -e "Доступные карты в ${BLUE}src/nav2/maps/${NC}:"

        idx=1
        for m in "${AVAILABLE_MAPS[@]}"; do
            m_name="$(basename "$m")"
            m_desc=""
            if [[ "${m_name}" == "polygon_real.yaml" ]]; then
                m_desc="${GREEN}(РЕКОМЕНДУЕТСЯ — актуальная карта полигона)${NC}"
            elif [[ "${m_name}" == "polygon_empty_4x4.yaml" ]]; then
                m_desc="${YELLOW}(пустой квадрат 4x4 м)${NC}"
            else
                m_desc="${BLUE}(пользовательская копия)${NC}"
            fi
            echo -e "  ${BOLD}[${idx}]${NC} ${m_name} ${m_desc}"
            ((idx++))
        done
        echo -e "  ${BOLD}[C]${NC} Указать свой путь к .yaml файлу вручную"
        echo -e "${CYAN}----------------------------------------------------------------${NC}"

        DEFAULT_MAP_NAME=""
        if [[ ${#AVAILABLE_MAPS[@]} -gt 0 ]]; then
            DEFAULT_MAP_NAME="$(basename "${AVAILABLE_MAPS[0]}")"
        fi

        echo -ne "${YELLOW}Выберите карту [1-$((idx-1)), C] (Enter = [1] ${DEFAULT_MAP_NAME}, таймаут 10с): ${NC}"
        MAP_CHOICE=""
        read -t 10 -r MAP_CHOICE || true
        echo ""

        MAP_CHOICE="$(echo -e "${MAP_CHOICE}" | tr -d '[:space:]')"

        if [[ -z "${MAP_CHOICE}" || "${MAP_CHOICE}" == "1" ]]; then
            if [[ ${#AVAILABLE_MAPS[@]} -gt 0 ]]; then
                MAP_FILE="${AVAILABLE_MAPS[0]}"
            fi
        elif [[ "${MAP_CHOICE}" =~ ^[0-9]+$ ]] && [[ "${MAP_CHOICE}" -le ${#AVAILABLE_MAPS[@]} && "${MAP_CHOICE}" -ge 1 ]]; then
            MAP_FILE="${AVAILABLE_MAPS[$((MAP_CHOICE-1))]}"
        elif [[ "${MAP_CHOICE}" =~ ^[cC]$ ]]; then
            echo -ne "${BLUE}Введите путь к файлу карты (.yaml): ${NC}"
            read -r CUSTOM_MAP_PATH
            if [[ -f "${CUSTOM_MAP_PATH}" ]]; then
                MAP_FILE="$(realpath "${CUSTOM_MAP_PATH}")"
            else
                echo -e "${RED}[ERROR] Файл '${CUSTOM_MAP_PATH}' не найден! Откат к [1] ${DEFAULT_MAP_NAME}${NC}"
                MAP_FILE="${AVAILABLE_MAPS[0]}"
            fi
        else
            echo -e "${YELLOW}[WARN] Некорректный ввод '${MAP_CHOICE}', выбран вариант [1] ${DEFAULT_MAP_NAME}.${NC}"
            MAP_FILE="${AVAILABLE_MAPS[0]}"
        fi
    fi

    # Меню выбора локализации (если не была задана)
    if [[ -z "${LOC_METHOD}" ]]; then
        echo -e "\n${CYAN}${BOLD}----------------------------------------------------------------${NC}"
        echo -e "${CYAN}${BOLD}             [ВЫБОР СПОСОБА ЛОКАЛИЗАЦИИ]                        ${NC}"
        echo -e "${CYAN}${BOLD}----------------------------------------------------------------${NC}"
        echo -e "  ${BOLD}[1]${NC} ${GREEN}AMCL${NC}        — Адаптивная локализация по лидару и карте ${GREEN}(РЕКОМЕНДУЕТСЯ)${NC}"
        echo -e "  ${BOLD}[2]${NC} ${YELLOW}Одометрия${NC}   — Чистая одометрия колес + статический TF map->odom"
        echo -e "  ${BOLD}[3]${NC} ${MAGENTA}SLAM${NC}        — Онлайн построение карты и навигация (slam_toolbox)"
        echo -e "${CYAN}----------------------------------------------------------------${NC}"

        echo -ne "${YELLOW}Выберите способ [1-3] (Enter = [1] AMCL, таймаут 10с): ${NC}"
        LOC_CHOICE=""
        read -t 10 -r LOC_CHOICE || true
        echo ""

        LOC_CHOICE="$(echo -e "${LOC_CHOICE}" | tr -d '[:space:]')"

        case "${LOC_CHOICE}" in
            ""|"1")
                LOC_METHOD="amcl"
                ;;
            "2")
                LOC_METHOD="odom"
                ;;
            "3")
                LOC_METHOD="slam"
                ;;
            *)
                echo -e "${YELLOW}[WARN] Некорректный выбор '${LOC_CHOICE}', выбран [1] AMCL.${NC}"
                LOC_METHOD="amcl"
                ;;
        esac
    fi
fi

# 4. Значения по умолчанию, если параметры не были заданы
if [[ -z "${MAP_FILE}" ]]; then
    if [[ ${#AVAILABLE_MAPS[@]} -gt 0 ]]; then
        MAP_FILE="${AVAILABLE_MAPS[0]}"
    else
        MAP_FILE="${MAPS_DIR}/polygon_empty_4x4.yaml"
    fi
fi

if [[ -z "${LOC_METHOD}" ]]; then
    LOC_METHOD="amcl"
fi

if [[ "${LOC_METHOD}" == "amcl" ]]; then
    USE_AMCL="true"
else
    USE_AMCL="false"
fi

# 5. Автоматическая проверка и синхронизация карты на Raspberry Pi
if [[ "${RUN_LOCAL}" != "true" && -f "${MAP_FILE}" && "${LOC_METHOD}" != "slam" ]]; then
    MAP_BASENAME="$(basename "${MAP_FILE}")"
    if ! ssh -o BatchMode=yes -o ConnectTimeout=2 -o StrictHostKeyChecking=no "${PI_USER}@${PI_HOST}" "test -f '${REMOTE_WS}/src/nav2/maps/${MAP_BASENAME}'" 2>/dev/null; then
        echo -e "${YELLOW}[SYNC] Карта ${MAP_BASENAME} отсутствует на Raspberry Pi. Копирование по SCP...${NC}"
        MAP_DIR="$(dirname "${MAP_FILE}")"
        PGM_NAME="$(grep -E "^image:" "${MAP_FILE}" | awk '{print $2}' || true)"
        PGM_PATH="${MAP_DIR}/${PGM_NAME}"

        FILES_TO_SYNC=("${MAP_FILE}")
        if [[ -n "${PGM_NAME}" && -f "${PGM_PATH}" ]]; then
            FILES_TO_SYNC+=("${PGM_PATH}")
        fi

        if scp -o BatchMode=yes -o ConnectTimeout=3 -o StrictHostKeyChecking=no "${FILES_TO_SYNC[@]}" "${PI_USER}@${PI_HOST}:${REMOTE_WS}/src/nav2/maps/" 2>/dev/null; then
            echo -e "${GREEN}[OK] Карта ${MAP_BASENAME} успешно синхронизирована с Raspberry Pi.${NC}"
        else
            echo -e "${YELLOW}[WARN] Не удалось выполнить автокопирование карты на Pi (возможно, хост пока недоступен).${NC}"
        fi
    fi
if [[ "${RUN_LOCAL}" != "true" ]]; then
    SRC_IP=$(ip route get "${PI_HOST}" 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1); exit}')
    if [[ -n "${SRC_IP}" ]]; then
        CYCLONE_XML="/tmp/cyclonedds_ijkbot.xml"
        cat <<EOF > "${CYCLONE_XML}"
<?xml version="1.0" encoding="UTF-8" ?>
<CycloneDDS xmlns="https://cdds.io/config">
    <Domain id="any">
        <General>
            <NetworkInterfaceAddress>${SRC_IP}</NetworkInterfaceAddress>
            <AllowMulticast>true</AllowMulticast>
        </General>
        <Discovery>
            <Peers>
                <Peer address="${PI_HOST}"/>
            </Peers>
        </Discovery>
    </Domain>
</CycloneDDS>
EOF
        export CYCLONEDDS_URI="file://${CYCLONE_XML}"
    fi
fi

echo -e "${CYAN}${BOLD}================================================================${NC}"
echo -e "${CYAN}${BOLD}     IJKbot — Единый командный центр (Ноутбук 2 / Оператор)     ${NC}"
echo -e "${CYAN}${BOLD}================================================================${NC}"
echo -e "${BLUE}Хост робота:${NC}       ${BOLD}$([[ "${RUN_LOCAL}" == "true" ]] && echo "Локальный (Ноутбук 2)" || echo "${PI_USER}@${PI_HOST}")${NC}"
echo -e "${BLUE}ROS_DOMAIN_ID:${NC}     ${BOLD}${ROS_DOMAIN_ID}${NC}"
echo -e "${BLUE}Режим аппаратуры:${NC}  $([[ "${MOCK_HARDWARE}" == "true" ]] && echo -e "${YELLOW}MOCK (симуляция)${NC}" || echo -e "${GREEN}ФИЗИЧЕСКИЙ РОБОТ (UART STS3215)${NC}")"
echo -e "${BLUE}Режим запуска:${NC}     ${BOLD}${LAUNCH_MODE}${NC} (логи в ${LOG_DIR}/)"
echo -e "${BLUE}Запуск RViz2:${NC}      ${START_RVIZ}"
echo -e "${CYAN}----------------------------------------------------------------${NC}"
if [[ "${LOC_METHOD}" != "slam" ]]; then
    echo -e "${BLUE}Карта полигона:${NC}    ${BOLD}$(basename "${MAP_FILE}")${NC} (${MAP_FILE})"
fi
case "${LOC_METHOD}" in
    amcl) echo -e "${BLUE}Локализация:${NC}       ${GREEN}${BOLD}AMCL (адаптивная по лидару и карте)${NC}" ;;
    odom) echo -e "${BLUE}Локализация:${NC}       ${YELLOW}${BOLD}Одометрия (чистая одометрия + static TF map->odom)${NC}" ;;
    slam) echo -e "${BLUE}Локализация:${NC}       ${MAGENTA}${BOLD}SLAM (онлайн картографирование slam_toolbox)${NC}" ;;
esac
echo -e "${BLUE}Стартовая поза:${NC}    X=${INITIAL_X} м, Y=${INITIAL_Y} м, Yaw=${INITIAL_YAW} рад"
echo -e "${CYAN}----------------------------------------------------------------${NC}"

WATCHDOG_PID=""

# Функция гарантированной остановки при завершении
cleanup_all() {
    if [[ "${CLEANUP_DONE}" == "true" ]]; then
        return
    fi
    CLEANUP_DONE=true
    echo -e "\n${RED}${BOLD}[STOP] Получен сигнал завершения. Остановка всех систем IJKbot...${NC}"

    # Остановка фонового watchdog
    if [[ -n "${WATCHDOG_PID}" ]] && kill -0 "${WATCHDOG_PID}" 2>/dev/null; then
        kill -9 "${WATCHDOG_PID}" 2>/dev/null || true
    fi

    # Остановка локального RViz, если был запущен в фоне
    if [[ -n "${RVIZ_PID}" ]] && kill -0 "${RVIZ_PID}" 2>/dev/null; then
        kill -INT "${RVIZ_PID}" 2>/dev/null || true
    fi

    # Вызов штатного стоп-скрипта (передаем caller-pid, чтобы стоп-скрипт не убил нас)
    STOP_OPTS=(--host "${PI_HOST}" --user "${PI_USER}" --caller-pid $$)
    if [[ "${RUN_LOCAL}" == "true" ]]; then
        STOP_OPTS+=(--local)
    fi
    if [[ -f "${SCRIPT_DIR}/stop_all.sh" ]]; then
        "${SCRIPT_DIR}/stop_all.sh" "${STOP_OPTS[@]}" || true
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
    probe=$(ssh -o BatchMode=yes -o ConnectTimeout=2 -o StrictHostKeyChecking=no "${PI_USER}@${target}" "true" 2>&1)
    local probe_exit=$?
    if [[ ${probe_exit} -eq 0 ]] || echo "${probe}" | grep -q "Permission denied"; then
        return 0
    fi
    return 1
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
        # Проверяем резервный IP
        if [[ "${HOST_SPECIFIED}" != "true" && "${PI_HOST}" != "${BACKUP_HOST}" ]] && check_host_reachability "${BACKUP_HOST}"; then
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
        if [[ "${FORCE_START}" == "true" ]]; then
            echo -e "${YELLOW}[WARN] Флаг --force активен: продолжение запуска вопреки рассинхронизации часов.${NC}"
        else
            echo -e "Хотите продолжить запуск несмотря на рассинхронизацию? [y/N]: "
            read -r -t 10 response || response="N"
            if [[ ! "${response}" =~ ^[yYдД]$ ]]; then
                echo -e "${RED}[ABORT] Запуск отменен оператором из-за рассинхронизации часов.${NC}"
                exit 1
            fi
            echo -e "${YELLOW}[WARN] Продолжение запуска с риском рассинхронизации TF!${NC}"
        fi
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

START_NAV2_CMD="${SCRIPT_DIR}/start_nav2_pi.sh --host ${PI_HOST} --user ${PI_USER} --initial-x ${INITIAL_X} --initial-y ${INITIAL_Y} --initial-yaw ${INITIAL_YAW} --loc ${LOC_METHOD}"
if [[ "${LOC_METHOD}" != "slam" && -n "${MAP_FILE}" ]]; then
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
            # Фоновый watchdog для мониторинга liveness процессов robot и nav2 во время работы RViz2
            (
                while kill -0 $$ 2>/dev/null; do
                    if [[ -n "${ROBOT_PID}" ]] && ! kill -0 "${ROBOT_PID}" 2>/dev/null; then
                        echo -e "\n${RED}[ERROR] Процесс robot.launch.py неожиданно завершился!${NC}" >&2
                        tail -n 10 "${ROBOT_LOG}" >&2 || true
                        kill -INT $$ 2>/dev/null || true
                        break
                    fi
                    if [[ -n "${NAV2_PID}" ]] && ! kill -0 "${NAV2_PID}" 2>/dev/null; then
                        echo -e "\n${RED}[ERROR] Процесс navigation.launch.py неожиданно завершился!${NC}" >&2
                        tail -n 10 "${NAV2_LOG}" >&2 || true
                        kill -INT $$ 2>/dev/null || true
                        break
                    fi
                    sleep 2
                done
            ) &
            WATCHDOG_PID=$!
            "${START_RVIZ_CMD}" || true
            if [[ -n "${WATCHDOG_PID}" ]] && kill -0 "${WATCHDOG_PID}" 2>/dev/null; then
                kill -9 "${WATCHDOG_PID}" 2>/dev/null || true
                WATCHDOG_PID=""
            fi
            ;;
    esac
fi

# При нормальном выходе из RViz штатно выполняем остановку
cleanup_all
