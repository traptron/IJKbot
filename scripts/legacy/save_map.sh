#!/usr/bin/env bash
# ==============================================================================
# save_map.sh — Сохранение текущей карты из SLAM (slam_toolbox) в nav2/maps.
#
# Запускается на ноутбуке во время или после картографирования полигона.
# Сохраняет файлы <map_name>.yaml и <map_name>.pgm и делает путь к изображению
# относительным для переносимости между ноутбуком и Raspberry Pi.
# ==============================================================================
set -euo pipefail

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

MAP_NAME="polygon_real"
OUTPUT_DIR="${REPO_DIR}/src/nav2/maps"
MAP_TOPIC="/map"
TIMEOUT_SEC=15

print_help() {
    echo -e "${BOLD}Использование:${NC} $0 [ИМЯ_КАРТЫ] [ПАРАМЕТРЫ]"
    echo ""
    echo "Параметры:"
    echo "  ИМЯ_КАРТЫ            Имя файла карты без расширения (по умолчанию: ${MAP_NAME})"
    echo "  -d, --dir <DIR>      Директория для сохранения (по умолчанию: ${OUTPUT_DIR})"
    echo "  -t, --topic <TOPIC>  Топик карты (по умолчанию: ${MAP_TOPIC})"
    echo "  --timeout <SEC>      Таймаут ожидания сервиса карты (по умолчанию: ${TIMEOUT_SEC}с)"
    echo "  -h, --help           Показать эту справку"
    echo ""
    echo "Примеры:"
    echo "  $0                   Сохранить карту как polygon_real.yaml/.pgm"
    echo "  $0 arena_round1      Сохранить карту как arena_round1.yaml/.pgm"
}

# Разбор первого позиционного аргумента, если это не флаг
if [[ $# -gt 0 && ! "$1" =~ ^- ]]; then
    MAP_NAME="$1"
    shift
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        -d|--dir)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует пути к каталогу${NC}" >&2
                exit 1
            fi
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -t|--topic)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует имени топика${NC}" >&2
                exit 1
            fi
            MAP_TOPIC="$2"
            shift 2
            ;;
        --timeout)
            if [[ $# -lt 2 ]]; then
                echo -e "${RED}[ERROR] Опция $1 требует количества секунд${NC}" >&2
                exit 1
            fi
            TIMEOUT_SEC="$2"
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

mkdir -p "${OUTPUT_DIR}"
TARGET_BASE="${OUTPUT_DIR}/${MAP_NAME}"

echo -e "${CYAN}${BOLD}================================================================${NC}"
echo -e "${CYAN}${BOLD}          IJKbot — Сохранение карты полигона (SLAM)            ${NC}"
echo -e "${CYAN}${BOLD}================================================================${NC}"
echo -e "${BLUE}Топик карты:${NC}       ${BOLD}${MAP_TOPIC}${NC}"
echo -e "${BLUE}Имя карты:${NC}         ${BOLD}${MAP_NAME}${NC}"
echo -e "${BLUE}Каталог:${NC}           ${OUTPUT_DIR}"
echo -e "${BLUE}ROS_DOMAIN_ID:${NC}     ${BOLD}${ROS_DOMAIN_ID}${NC}"
echo -e "${CYAN}----------------------------------------------------------------${NC}"

# Проверка наличия pixi / ros2
if ! command -v ros2 &>/dev/null; then
    if [[ -x "${HOME}/.pixi/bin/pixi" ]]; then
        export PATH="${HOME}/.pixi/bin:${PATH}"
    fi
fi

echo -e "${YELLOW}[1/3] Запрос карты из топика ${MAP_TOPIC}...${NC}"
if ! ros2 run nav2_map_server map_saver_cli \
    -t "${MAP_TOPIC}" \
    -f "${TARGET_BASE}" \
    --occ 0.65 \
    --free 0.15; then
    echo -e "${RED}[FAIL] Не удалось сохранить карту! Убедитесь, что картографирование запущено.${NC}" >&2
    exit 1
fi

YAML_FILE="${TARGET_BASE}.yaml"
PGM_FILE="${TARGET_BASE}.pgm"

if [[ ! -f "${YAML_FILE}" || ! -f "${PGM_FILE}" ]]; then
    echo -e "${RED}[FAIL] Файлы карты не найдены после map_saver_cli!${NC}" >&2
    exit 1
fi

echo -e "${YELLOW}[2/3] Нормализация путей в ${YAML_FILE}...${NC}"
# Делаем путь к PGM относительно YAML файла (только имя файла), чтобы карта открывалась и на роботе, и на ноутбуке
PGM_BASENAME="$(basename "${PGM_FILE}")"
sed -i "s|^image:.*|image: ${PGM_BASENAME}|" "${YAML_FILE}"

echo -e "${GREEN}${BOLD}[3/3] [УСПЕХ] Карта успешно сохранена!${NC}"
echo -e "  - YAML: ${GREEN}${YAML_FILE}${NC}"
echo -e "  - PGM:  ${GREEN}${PGM_FILE}${NC}"
echo -e "${CYAN}----------------------------------------------------------------${NC}"
echo -e "${BOLD}Для использования этой карты в навигации с AMCL:${NC}"
echo -e "  ros2 launch nav2 navigation.launch.py \\"
echo -e "    use_amcl:=true \\"
echo -e "    map:='${YAML_FILE}' \\"
echo -e "    initial_x:=0.4 initial_y:=0.4 initial_yaw:=0.0"
echo -e "${CYAN}================================================================${NC}"
