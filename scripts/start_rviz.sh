#!/usr/bin/env bash
# ==============================================================================
# start_rviz.sh — Запуск RViz2 на Ноутбуке 2 через окружение Pixi (ROS 2 Jazzy).
#
# Отображает:
# - RobotModel (/robot_description)
# - TF дерево
# - LaserScan (/scan)
# - Карта (/map) и Costmaps (/global_costmap/costmap, /local_costmap/costmap)
# - Footprint робота (/local_costmap/published_footprint)
# - Пути (/plan, /local_plan)
# - Камера с детекцией QR (/vision/qr/image/compressed)
# ==============================================================================
set -euo pipefail

# Цветовой вывод в терминал
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Окружение ROS 2
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"

PIXI_MANIFEST="${PIXI_PROJECT_MANIFEST:-/home/lev/ros2_jazzy/pixi.toml}"
DEFAULT_RVIZ_CONFIG="${REPO_DIR}/ijkbot_nav2/rviz/nav2_default_view.rviz"
FALLBACK_RVIZ_CONFIG="${REPO_DIR}/ijkbot_nav2/rviz/nav2_view.rviz"

RVIZ_CONFIG="${DEFAULT_RVIZ_CONFIG}"
EXTRA_ARGS=()

# Разбор аргументов командной строки
while [[ $# -gt 0 ]]; do
    case "$1" in
        -d|--config)
            RVIZ_CONFIG="$2"
            shift 2
            ;;
        -h|--help)
            echo -e "${BOLD}Использование:${NC} $0 [ПАРАМЕТРЫ] [-- RViz2_ARGS]"
            echo ""
            echo "Параметры:"
            echo "  -d, --config <FILE>    Путь к .rviz файлу конфигурации (по умолчанию: nav2_default_view.rviz)"
            echo "  -f, --fixed-frame <F>  Задать фиксированный фрейм (по умолчанию: map)"
            echo "  -h, --help             Показать эту справку"
            echo ""
            echo "Переменные окружения:"
            echo "  ROS_DOMAIN_ID          Идентификатор домена ROS 2 (по умолчанию: 42)"
            echo "  PIXI_PROJECT_MANIFEST  Путь к pixi.toml (по умолчанию: /home/lev/ros2_jazzy/pixi.toml)"
            exit 0
            ;;
        -f|--fixed-frame)
            EXTRA_ARGS+=("-f" "$2")
            shift 2
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

echo -e "${CYAN}${BOLD}================================================================${NC}"
echo -e "${CYAN}${BOLD}       IJKbot — Запуск RViz2 (Ноутбук 2 / Pixi ROS 2 Jazzy)     ${NC}"
echo -e "${CYAN}${BOLD}================================================================${NC}"
echo -e "${BLUE}ROS_DOMAIN_ID:${NC} ${BOLD}${ROS_DOMAIN_ID}${NC}"
echo -e "${BLUE}Pixi Manifest:${NC} ${PIXI_MANIFEST}"

# Проверка наличия Pixi
if ! command -v pixi &>/dev/null; then
    echo -e "${RED}[ERROR] Утилита 'pixi' не найдена в PATH! Убедитесь, что pixi установлен.${NC}" >&2
    exit 1
fi

if [[ ! -f "${PIXI_MANIFEST}" ]]; then
    echo -e "${RED}[ERROR] Файл манифеста Pixi не найден: ${PIXI_MANIFEST}${NC}" >&2
    exit 1
fi

# Проверка и восстановление файла конфигурации RViz
if [[ ! -f "${RVIZ_CONFIG}" ]]; then
    echo -e "${YELLOW}[WARN] Конфигурационный файл ${RVIZ_CONFIG} не найден.${NC}"
    if [[ -f "${FALLBACK_RVIZ_CONFIG}" ]]; then
        echo -e "${YELLOW}[INFO] Копирование базового конфига из ${FALLBACK_RVIZ_CONFIG}...${NC}"
        mkdir -p "$(dirname "${RVIZ_CONFIG}")"
        cp "${FALLBACK_RVIZ_CONFIG}" "${RVIZ_CONFIG}"
        echo -e "${GREEN}[OK] Конфиг создан: ${RVIZ_CONFIG}${NC}"
    else
        echo -e "${RED}[ERROR] Ни один файл конфигурации RViz не найден!${NC}" >&2
        exit 1
    fi
fi

echo -e "${BLUE}RViz2 Config:${NC}  ${RVIZ_CONFIG}"
echo -e "${GREEN}${BOLD}Запуск RViz2... (Для выхода закройте окно или нажмите Ctrl+C)${NC}"
echo -e "${CYAN}----------------------------------------------------------------${NC}"

# Перехват сигналов завершения
CLEANUP_DONE=false
cleanup() {
    if [[ "${CLEANUP_DONE}" == "true" ]]; then
        return
    fi
    CLEANUP_DONE=true
    trap - SIGINT SIGTERM EXIT
    echo -e "\n${YELLOW}[INFO] Завершение работы RViz2...${NC}"
}
trap cleanup SIGINT SIGTERM EXIT

export PIXI_PROJECT_MANIFEST="${PIXI_MANIFEST}"
pixi run rviz2 -d "${RVIZ_CONFIG}" "${EXTRA_ARGS[@]}"
cleanup
