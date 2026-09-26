#!/usr/bin/env bash
# ==============================================================================
# start_all_laptop1.sh — Единый командный центр / Судейский ИИ & Дашборд (Ноутбук 1)
#
# Сценарий соревнований («Кубок РТК Высшая Лига / Хакатон Эвакуация»):
# - Машина 1 (Ноутбук 1, этот компьютер): Ollama LLM + NiceGUI Web Dashboard (судейский экран) + QR Vision
# - Машина 2 (Ноутбук 2): Рабочее место оператора, SSH-управление Pi, Nav2, RViz2
# - Машина 3 (Raspberry Pi 4B): Бортовые сенсоры, RealSense, STS3215, одометрия
#
# Последовательность запуска:
# 1. Проверка окружения ROS 2 Jazzy (Pixi или нативный ROS 2) и собранных пакетов.
# 2. Проверка доступности сервера Ollama LLM и наличия целевой модели (Qwen 2.5 7B).
# 3. Проверка доступности сетевого порта Web Dashboard (по умолчанию: 8080).
# 4. Запуск laptop.launch.py (NiceGUI Dashboard + QR reader + LLM State Machine).
# 5. Автоматическое открытие интерфейса в веб-браузере (http://localhost:8080).
# 6. Перехват Ctrl+C и гарантированная остановка всех процессов.
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
LLM_HOST="${LLM_HOST:-http://localhost:11434}"
LLM_MODEL="${LLM_MODEL:-qwen2.5:7b-instruct-q4_K_M}"
PORT="${PORT:-8080}"
HOST="${HOST:-0.0.0.0}"
MOCK="false"
ENABLE_VISION="true"
OPEN_BROWSER="true"
SKIP_OLLAMA="false"

LAUNCH_PID=""
CLEANUP_DONE=false

print_help() {
    echo -e "${BOLD}Использование:${NC} $0 [ПАРАМЕТРЫ]"
    echo ""
    echo "Параметры запуска:"
    echo "  --llm-host <URL>     Адрес сервера Ollama (по умолчанию: ${LLM_HOST})"
    echo "  --model <NAME>       Имя модели для проверки в Ollama (по умолчанию: ${LLM_MODEL})"
    echo "  --port <PORT>        Порт веб-интерфейса NiceGUI (по умолчанию: ${PORT})"
    echo "  --host <IP>          IP-адрес для привязки веб-сервера (по умолчанию: ${HOST})"
    echo "  --mock               Режим симуляции (mock:=true, без подключения к реальным сенсорам)"
    echo "  --no-vision          Не запускать ноду распознавания QR-кодов (qr_reader_node)"
    echo "  --no-browser         Не открывать автоматически веб-браузер после старта"
    echo "  --skip-ollama        Пропустить проверку доступности Ollama"
    echo "  -h, --help           Показать эту справку"
    echo ""
    echo "Переменные окружения:"
    echo "  LLM_HOST             Адрес сервиса Ollama (дефолт: http://localhost:11434)"
    echo "  LLM_MODEL            Имя модели Ollama (дефолт: qwen2.5:7b-instruct-q4_K_M)"
    echo "  ROS_DOMAIN_ID        ID ROS-домена (дефолт: 42)"
    echo ""
    echo "Примеры:"
    echo "  $0                   Стандартный запуск на Ноутбуке 1 (судейский дашборд)"
    echo "  $0 --mock            Запуск в режиме симуляции без реального робота"
    echo "  $0 --no-browser      Запуск сервера без автоматического открытия вкладки браузера"
}

# Разбор аргументов командной строки
while [[ $# -gt 0 ]]; do
    case "$1" in
        --llm-host)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует URL-адреса${NC}" >&2
                print_help
                exit 1
            fi
            LLM_HOST="$2"
            shift 2
            ;;
        --model)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует имени модели${NC}" >&2
                print_help
                exit 1
            fi
            LLM_MODEL="$2"
            shift 2
            ;;
        --port)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует номера порта${NC}" >&2
                print_help
                exit 1
            fi
            PORT="$2"
            shift 2
            ;;
        --host)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует IP-адреса хоста${NC}" >&2
                print_help
                exit 1
            fi
            HOST="$2"
            shift 2
            ;;
        --mock)
            MOCK="true"
            shift
            ;;
        --no-vision)
            ENABLE_VISION="false"
            shift
            ;;
        --no-browser)
            OPEN_BROWSER="false"
            shift
            ;;
        --skip-ollama)
            SKIP_OLLAMA="true"
            shift
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

cleanup() {
    if [[ "${CLEANUP_DONE}" == "true" ]]; then
        return
    fi
    CLEANUP_DONE=true
    trap - SIGINT SIGTERM EXIT

    echo -e "\n${YELLOW}${BOLD}[ЗАВЕРШЕНИЕ] Остановка компонентов Ноутбука 1...${NC}"

    if [[ -n "${LAUNCH_PID}" ]] && kill -0 "${LAUNCH_PID}" 2>/dev/null; then
        echo -e "${BLUE}Посылаем SIGINT процессу запуска (PID ${LAUNCH_PID})...${NC}"
        kill -INT "${LAUNCH_PID}" 2>/dev/null || true
        for _ in {1..10}; do
            if ! kill -0 "${LAUNCH_PID}" 2>/dev/null; then
                break
            fi
            sleep 0.2
        done
        if kill -0 "${LAUNCH_PID}" 2>/dev/null; then
            kill -9 "${LAUNCH_PID}" 2>/dev/null || true
        fi
    fi

    # Завершение дочерних нод
    pkill -2 -f 'dashboard_app' 2>/dev/null || true
    pkill -2 -f 'qr_reader_node' 2>/dev/null || true
    sleep 0.3
    pkill -9 -f 'dashboard_app' 2>/dev/null || true
    pkill -9 -f 'qr_reader_node' 2>/dev/null || true

    echo -e "${GREEN}[OK] Все процессы Ноутбука 1 корректно остановлены.${NC}"
}
trap cleanup SIGINT SIGTERM EXIT

echo -e "${CYAN}${BOLD}================================================================${NC}"
echo -e "${CYAN}${BOLD}       IJKbot — Запуск судейского ИИ & дашборда (Ноутбук 1)     ${NC}"
echo -e "${CYAN}${BOLD}================================================================${NC}"
echo -e "${BLUE}ROS_DOMAIN_ID:${NC}     ${BOLD}${ROS_DOMAIN_ID}${NC}"
echo -e "${BLUE}RMW:${NC}               ${RMW_IMPLEMENTATION}"
echo -e "${BLUE}Ollama LLM:${NC}        ${BOLD}${LLM_HOST}${NC} (модель: ${LLM_MODEL})"
echo -e "${BLUE}NiceGUI Dashboard:${NC} http://${HOST}:${PORT}"
echo -e "${BLUE}Режим симуляции:${NC}   $([[ "${MOCK}" == "true" ]] && echo "${YELLOW}ВКЛЮЧЕН (MOCK)${NC}" || echo "${GREEN}ВЫКЛЮЧЕН (реальный робот)${NC}")"
echo -e "${BLUE}QR-распознавание:${NC}  $([[ "${ENABLE_VISION}" == "true" ]] && echo "${GREEN}ВКЛЮЧЕНО${NC}" || echo "${YELLOW}ОТКЛЮЧЕНО${NC}")"
echo -e "${CYAN}----------------------------------------------------------------${NC}"

# ==============================================================================
# ШАГ 1: Проверка собранного окружения ROS 2
# ==============================================================================
echo -e "\n${BLUE}${BOLD}[ШАГ 1/4] Проверка сборки пакетов ROS 2...${NC}"
SETUP_BASH="${REPO_DIR}/install/setup.bash"
if [[ ! -f "${SETUP_BASH}" ]]; then
    echo -e "${RED}[ERROR] Файл ${SETUP_BASH} не найден!${NC}" >&2
    echo -e "${YELLOW}Соберите пакеты репозитория командой:${NC}" >&2
    echo -e "  colcon build --symlink-install" >&2
    exit 1
fi
echo -e "${GREEN}[OK] Окружение пакетов найдено (${SETUP_BASH}).${NC}"

# ==============================================================================
# ШАГ 2: Проверка доступности Ollama LLM
# ==============================================================================
echo -e "\n${BLUE}${BOLD}[ШАГ 2/4] Проверка подключения к Ollama LLM (${LLM_HOST})...${NC}"
if [[ "${SKIP_OLLAMA}" == "true" ]]; then
    echo -e "${YELLOW}[SKIP] Проверка Ollama пропущена по флагу --skip-ollama.${NC}"
else
    TAGS_JSON=""
    if TAGS_JSON=$(curl -s --connect-timeout 2 --max-time 3 "${LLM_HOST}/api/tags" 2>/dev/null); then
        echo -e "${GREEN}[OK] Сервер Ollama доступен.${NC}"
        
        # Проверка наличия целевой модели
        CLEAN_MODEL_NAME="${LLM_MODEL%%:*}"
        if echo "${TAGS_JSON}" | grep -q "${CLEAN_MODEL_NAME}"; then
            echo -e "${GREEN}[OK] Найдена совместимая модель семейства '${CLEAN_MODEL_NAME}'.${NC}"
        else
            echo -e "${YELLOW}[WARN] Модель '${LLM_MODEL}' не обнаружена в ответе /api/tags!${NC}"
            echo -e "${YELLOW}[HINT] Чтобы скачать модель, выполните в терминале:${NC}"
            echo -e "  ollama pull ${LLM_MODEL}"
        fi
    else
        echo -e "${RED}[FAIL] Ollama не отвечает по адресу ${LLM_HOST}!${NC}" >&2
        echo -e "${YELLOW}Для запуска Ollama выполните:${NC}" >&2
        echo -e "  ollama serve" >&2
        echo -e "или" >&2
        echo -e "  ollama run ${LLM_MODEL}" >&2
        echo -e "${YELLOW}Если вы хотите продолжить без локальной Ollama, используйте флаг --skip-ollama${NC}" >&2
        exit 1
    fi
fi

# ==============================================================================
# ШАГ 3: Проверка доступности сетевого порта дашборда
# ==============================================================================
echo -e "\n${BLUE}${BOLD}[ШАГ 3/4] Проверка порта ${PORT}...${NC}"
PORT_OCCUPIED=false
if command -v ss &>/dev/null; then
    if ss -tulpn 2>/dev/null | grep -q ":${PORT} "; then
        PORT_OCCUPIED=true
    fi
elif command -v lsof &>/dev/null; then
    if lsof -i ":${PORT}" &>/dev/null; then
        PORT_OCCUPIED=true
    fi
fi

if [[ "${PORT_OCCUPIED}" == "true" ]]; then
    echo -e "${RED}[FAIL] Порт ${PORT} уже занят другим процессом!${NC}" >&2
    echo -e "${YELLOW}Освободите порт или укажите другой через флаг --port <PORT>.${NC}" >&2
    exit 1
fi
echo -e "${GREEN}[OK] Порт ${PORT} свободен.${NC}"

# ==============================================================================
# ШАГ 4: Запуск laptop.launch.py и веб-браузера
# ==============================================================================
echo -e "\n${BLUE}${BOLD}[ШАГ 4/4] Запуск стека Ноутбука 1 (laptop.launch.py)...${NC}"
PIXI_MANIFEST="${PIXI_PROJECT_MANIFEST:-/home/lev/ros2_jazzy/pixi.toml}"

LAUNCH_CMD="source '${SETUP_BASH}' && ros2 launch bringup laptop.launch.py \
    llm_host:='${LLM_HOST}' \
    port:='${PORT}' \
    host:='${HOST}' \
    mock:='${MOCK}' \
    enable_vision:='${ENABLE_VISION}'"

# Фоновый вотчер для автоматического открытия браузера
if [[ "${OPEN_BROWSER}" == "true" ]]; then
    (
        TARGET_URL="http://localhost:${PORT}"
        echo -e "${BLUE}[BROWSER] Ожидание запуска веб-сервера NiceGUI (${TARGET_URL})...${NC}"
        for _ in {1..40}; do
            if python3 -c "import socket; s = socket.socket(); s.settimeout(0.5); res = s.connect_ex(('127.0.0.1', int('${PORT}'))); s.close(); exit(0 if res == 0 else 1)" 2>/dev/null; then
                echo -e "\n${GREEN}${BOLD}[BROWSER] Веб-сервер готов! Открываем ${TARGET_URL}...${NC}"
                if command -v xdg-open &>/dev/null && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
                    xdg-open "${TARGET_URL}" >/dev/null 2>&1 || true
                elif python3 -c "import webbrowser; webbrowser.open('${TARGET_URL}')" 2>/dev/null; then
                    :
                fi
                break
            fi
            sleep 0.5
        done
    ) &
fi

echo -e "${GREEN}${BOLD}Запуск нод... (Для остановки нажмите Ctrl+C)${NC}"
echo -e "${CYAN}----------------------------------------------------------------${NC}"

if command -v pixi &>/dev/null && [[ -f "${PIXI_MANIFEST}" ]]; then
    export PIXI_PROJECT_MANIFEST="${PIXI_MANIFEST}"
    pixi run bash -c "${LAUNCH_CMD}" &
    LAUNCH_PID=$!
else
    # Нативный ROS 2
    if [[ -f "/opt/ros/jazzy/setup.bash" ]]; then
        source "/opt/ros/jazzy/setup.bash"
    fi
    bash -c "${LAUNCH_CMD}" &
    LAUNCH_PID=$!
fi

# Ожидание завершения процесса
wait "${LAUNCH_PID}" || true
cleanup
